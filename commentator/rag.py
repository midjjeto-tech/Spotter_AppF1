"""
commentator/rag.py
==================
Retrieval-Augmented Generation: поиск релевантных фактов из базы знаний F1
для обогащения контекста LLM (commentator/brain.py).

Единственная внешняя зависимость — sentence-transformers (numpy уже есть).
FAISS не используется: для базы в 60–100 фактов numpy cosine similarity
мгновенно, а дополнительный .dll не нужен.

Инициализация выполняется в фоновом потоке: не блокирует старт приложения.
Эмбеддинги кэшируются на диске по SHA1-хешу содержимого JSON-файла.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path

import numpy as np

_log = logging.getLogger(__name__)

_FACTS_PATH = Path(__file__).parent / "knowledge_base" / "f1_facts.json"
_CACHE_DIR  = Path(__file__).parent / "knowledge_base" / ".cache"
_MODEL_NAME = "intfloat/multilingual-e5-small"


class F1RAG:
    """Векторный поиск по базе знаний F1.

    Создаётся в Commentator.__init__, инициализируется в фоне — первые
    запросы до готовности возвращают пустую строку без блокировки.
    """

    def __init__(self, facts_path: Path | None = None, model_name: str = _MODEL_NAME):
        self._available = False
        self._facts: list[str] = []
        self._embeddings: np.ndarray | None = None  # [N, dim] float32, L2-норма = 1
        self._model = None
        self._ready = threading.Event()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False
        self._stopped = False

        self._facts_path = facts_path or _FACTS_PATH
        self._model_name = model_name

    def start(self) -> None:
        if self._started or self._stopped:
            return
        self._started = True
        self._thread = threading.Thread(
            target=self._init, daemon=True, name="rag-init")
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._stop_event.set()
        self._ready.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))

    # ------------------------------------------------------------------ #
    # Инициализация (фоновый поток)
    # ------------------------------------------------------------------ #

    def _init(self) -> None:
        if self._stop_event.is_set():
            return
        try:
            from sentence_transformers import SentenceTransformer  # noqa: F401
        except ImportError as exc:
            _log.warning(
                "F1RAG disabled (sentence-transformers not installed: %s). "
                "Run: pip install sentence-transformers", exc,
            )
            self._ready.set()
            return

        if not self._facts_path.exists():
            _log.warning("F1RAG: knowledge base not found: %s", self._facts_path)
            self._ready.set()
            return

        try:
            from sentence_transformers import SentenceTransformer

            raw = json.loads(self._facts_path.read_text(encoding="utf-8"))
            # Поддержка обоих форматов: плоская строка или {"text": ..., "tags": [], "priority": N}
            self._facts = [
                entry["text"] if isinstance(entry, dict) else entry
                for entry in raw
            ]
            if not self._facts:
                self._ready.set()
                return

            self._model = SentenceTransformer(self._model_name)
            if self._stop_event.is_set():
                return
            self._embeddings = self._build_or_load_embeddings()
            if self._stop_event.is_set():
                return
            self._available = True
            _log.info("F1RAG ready: %d facts, dim=%d",
                      len(self._facts), self._embeddings.shape[1])
        except Exception as exc:
            _log.warning("F1RAG init failed: %s", exc)
        finally:
            self._ready.set()

    def _build_or_load_embeddings(self) -> np.ndarray:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        content_hash = hashlib.sha1(self._facts_path.read_bytes()).hexdigest()[:12]
        cache_file = _CACHE_DIR / f"emb_{content_hash}.npy"

        if cache_file.exists():
            _log.debug("F1RAG: loading cached embeddings (%s)", cache_file.name)
            emb = np.load(str(cache_file))
        else:
            _log.info("F1RAG: encoding %d facts (first run)...", len(self._facts))
            prefixed = [f"passage: {f}" for f in self._facts]
            emb = self._model.encode(
                prefixed,
                convert_to_numpy=True,
                show_progress_bar=False,
                batch_size=32,
            ).astype(np.float32)
            np.save(str(cache_file), emb)
            _log.info("F1RAG: embeddings cached → %s", cache_file.name)

        # L2-нормализация для косинусного сходства через dot-product
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return emb / norms

    # ------------------------------------------------------------------ #
    # Запрос
    # ------------------------------------------------------------------ #

    def get_relevant_context(self, query: str, k: int = 3) -> str:
        """Вернуть k наиболее релевантных фактов через \\n.

        Возвращает пустую строку если RAG ещё не готов или запрос пустой.
        """
        if not self._ready.is_set() or not self._available or not query.strip():
            return ""
        try:
            query_emb = self._model.encode(
                [f"query: {query}"],
                convert_to_numpy=True,
            ).astype(np.float32)
            # нормализация
            norm = np.linalg.norm(query_emb)
            if norm > 0:
                query_emb /= norm

            # cosine similarity: scores[i] = dot(emb[i], query)
            scores = self._embeddings @ query_emb.ravel()   # [N]
            top_k = int(min(k, len(self._facts)))
            top_indices = np.argsort(scores)[::-1][:top_k]
            results = [self._facts[i] for i in top_indices]
            return "\n".join(f"- {r}" for r in results)
        except Exception as exc:
            _log.debug("F1RAG search failed: %s", exc)
            return ""
