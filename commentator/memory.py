"""
commentator/memory.py
======================
Long-term phrase memory с дисковой персистентностью.

Хранит последние фразы комментатора (timestamp + текст + код события)
в DATA_DIR/commentator_memory.json. На старте загружает записи из последних
2 часов — после перезапуска приложения посреди гонки LLM продолжает с того же
места и не повторяет уже сказанное.

Записи старше MAX_AGE_SEC автоматически отбрасываются при загрузке и сохранении.
Максимальный объём на диске — MAX_ENTRIES записей (~20).
Thread-safe.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

import config

_log = logging.getLogger(__name__)

_MAX_ENTRIES = 20
_MAX_AGE_SEC = 7200    # 2 часа — покрывает полный заезд F1
_CONTEXT_WINDOW = 5    # шире окно: модель меняет не только строку, но и ритм/заход


class PhraseMemory:
    """Персистентная память последних фраз для анти-повтора.

    Используется в Commentator._compose() вместо короткой памяти в процессе:
    при перезапуске приложения LLM видит фразы из предыдущего сеанса
    (если гонка ещё не закончилась — записи не устарели).
    """

    def __init__(
        self,
        path: Path | None = None,
        context_window: int = _CONTEXT_WINDOW,
        max_entries: int = _MAX_ENTRIES,
    ):
        self._path = path or (Path(config.DATA_DIR) / "commentator_memory.json")
        self._context_window = context_window
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._entries: list[dict] = []  # [{"ts": float, "phrase": str, "code": str}]
        self._load()

    # ------------------------------------------------------------------ #
    # Публичный API
    # ------------------------------------------------------------------ #

    def append(self, phrase: str, event_code: str = "") -> None:
        """Добавить фразу и сохранить на диск."""
        with self._lock:
            self._entries.append({
                "ts": time.time(),
                "phrase": phrase,
                "code": event_code,
            })
            if len(self._entries) > self._max_entries:
                self._entries = self._entries[-self._max_entries:]
            self._save()

    def recent(self, n: int | None = None) -> list[str]:
        """Вернуть последние n фраз (по умолчанию context_window)."""
        n = n if n is not None else self._context_window
        with self._lock:
            return [e["phrase"] for e in self._entries[-n:]]

    def clear(self) -> None:
        """Очистить память (вызывать при старте новой сессии/гонки)."""
        with self._lock:
            self._entries = []
            self._save()

    def __bool__(self) -> bool:
        return bool(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    # ------------------------------------------------------------------ #
    # Персистентность
    # ------------------------------------------------------------------ #

    def _load(self) -> None:
        try:
            if not self._path.exists():
                return
            data = json.loads(self._path.read_text(encoding="utf-8"))
            cutoff = time.time() - _MAX_AGE_SEC
            self._entries = [
                e for e in data
                if isinstance(e, dict) and e.get("ts", 0) >= cutoff
            ]
            if self._entries:
                _log.info(
                    "PhraseMemory: loaded %d phrase(s) from last session (≤2 h)",
                    len(self._entries),
                )
        except Exception as exc:
            _log.warning("PhraseMemory: load failed: %s", exc)
            self._entries = []

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._entries, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self._path)
        except Exception as exc:
            _log.debug("PhraseMemory: save failed (non-fatal): %s", exc)
