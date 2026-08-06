"""
new_tts/piper_tts.py
====================
PiperVoiceEngine — Russian CPU TTS via Piper (ONNX). Replaces MOSS-TTS-Nano.

- 4 native Russian voices (one per persona), 22050 Hz mono.
- Low first-audio latency: text is split into sentences and synthesized one at a
  time, so the first phrase plays while the rest is still being generated.
- Russian text normalization (Latin -> Cyrillic) before synthesis.
- Model warmup on load to eliminate the one-time ONNX first-inference lag.

Public interface mirrors the old MossTTS so voice/tts.py stays thin:
  is_ready, status, sample_rate, channels, wait_until_ready(),
  synthesize(text, persona), synthesize_streaming(text, persona)
"""
from __future__ import annotations

import logging
import re
import threading
import traceback
from pathlib import Path

import numpy as np

import config
from new_tts import ru_textnorm

_log = logging.getLogger(__name__)

_PIPER_DIR = Path(config.BASE_DIR) / "models" / "piper"

# persona -> (voice name, length_scale).  length_scale < 1 = faster, > 1 = slower
# Ruslan = лучший по качеству, поэтому он на основной (дефолтной) персоне tv.
PERSONA_VOICE: dict[str, tuple[str, float]] = {
    "tv":    ("ruslan", 1.0),
    "hype":  ("denis",  0.92),
    "calm":  ("irina",  1.08),
    "toxic": ("dmitri", 1.0),
    # Слоты ролей (см. yandex_ai/voices.py). Гарантия здесь СЛАБЕЕ, чем у
    # Yandex, и это осознанно: в models/piper/ лежат ровно четыре модели, и
    # все четыре уже розданы персонам выше — свободной под роль просто нет.
    # Динамически уступить голос, как это делает voice_cast.resolve(), путь
    # Piper тоже не может: PERSONA_VOICE.get(persona) статичен, механизма
    # оверрайдов у него нет.
    # Поэтому: инженер и споттер гарантированно отличаются ДРУГ ОТ ДРУГА и по
    # голосу, и по темпу, но могут совпасть с комментатором — при persona=toxic
    # с инженером, при persona=hype со споттером. Это аварийный фолбэк на
    # случай отказа сети, а не режим работы: качество голоса в проекте держится
    # на Yandex, и Piper намеренно не развивается.
    "engineer": ("dmitri", 1.0),
    "spotter":  ("denis",  1.12),
}
_DEFAULT_VOICE = "ruslan"

_SENT_SPLIT = re.compile(r'(?<=[.!?…])\s+')
_CLAUSE_SPLIT = re.compile(r'(?<=[,;:—–])\s+')
_MAX_SEGMENT_CHARS = 90  # split longer sentences at clause boundaries for latency


def _voice_path(name: str) -> Path:
    return _PIPER_DIR / f"ru_RU-{name}-medium.onnx"


def _split_segments(text: str) -> list[str]:
    """Split text into short speakable segments for low-latency streaming."""
    out: list[str] = []
    for sentence in _SENT_SPLIT.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= _MAX_SEGMENT_CHARS:
            out.append(sentence)
            continue
        buf = ""
        for clause in _CLAUSE_SPLIT.split(sentence):
            clause = clause.strip()
            if not clause:
                continue
            if len(buf) + len(clause) + 1 <= _MAX_SEGMENT_CHARS:
                buf = (buf + " " + clause).strip()
            else:
                if buf:
                    out.append(buf)
                buf = clause
        if buf:
            out.append(buf)
    return out


class PiperVoiceEngine:
    def __init__(self) -> None:
        self._voices: dict[str, object] = {}   # name -> PiperVoice
        self._lock = threading.RLock()         # serialize inference; reentrant for lazy load
        self._loaded = threading.Event()       # set on success or failure
        self.sample_rate = 22050
        self.channels = 1
        self.is_ready = False
        self.status = "Piper не запущен"
        self._PiperVoice = None
        self._SynthesisConfig = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False
        self._stopped = False

    def start(self) -> None:
        """Start model loading explicitly; construction itself is passive."""
        if self._started or self._stopped:
            return
        self._started = True
        self.status = "Загрузка Piper..."
        self._thread = threading.Thread(
            target=self._load, daemon=True, name="piper-load")
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        """Request cancellation and wait a bounded time for model loading."""
        if self._stopped:
            return
        self._stopped = True
        self._stop_event.set()
        # Unblock Voice._wait_and_setup even when ONNX loading cannot be
        # interrupted immediately inside third-party code.
        self._loaded.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
        if not self.is_ready:
            self.status = "Piper остановлен"

    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        try:
            if self._stop_event.is_set():
                return
            from piper import PiperVoice, SynthesisConfig
            self._PiperVoice = PiperVoice
            self._SynthesisConfig = SynthesisConfig
            voice = self._ensure_voice(_DEFAULT_VOICE)  # load + warmup default
            if self._stop_event.is_set():
                return
            self.sample_rate = int(voice.config.sample_rate)
            self.is_ready = True
            self.status = "Piper готов (CPU, русский)"
            _log.info("Piper loaded: %d Hz, default voice '%s'", self.sample_rate, _DEFAULT_VOICE)
        except Exception as exc:
            self.status = f"Piper: {exc}"
            _log.error("Piper load failed:\n%s", traceback.format_exc())
        finally:
            self._loaded.set()

    def _ensure_voice(self, name: str):
        """Load a voice on first use (and warm it up). Caches by name."""
        with self._lock:
            if name in self._voices:
                return self._voices[name]
            path = _voice_path(name)
            if not path.exists():
                raise FileNotFoundError(f"Piper voice not found: {path}")
            voice = self._PiperVoice.load(str(path))
            self._voices[name] = voice
            try:
                for _ in voice.synthesize("Готов."):  # warmup pass
                    pass
            except Exception:
                pass
            return voice

    def _config_for(self, persona: str):
        _, length_scale = PERSONA_VOICE.get(persona, (_DEFAULT_VOICE, 1.0))
        return self._SynthesisConfig(length_scale=length_scale)

    # ------------------------------------------------------------------ #
    def synthesize(self, text: str, persona: str = "tv") -> tuple[np.ndarray | None, int]:
        """Full synthesis. Returns (audio float32 mono [-1,1], sample_rate)."""
        if not self.is_ready or not text.strip():
            return None, 0
        parts = list(self._stream_arrays(text, persona))
        if not parts:
            return None, 0
        return np.concatenate(parts).astype(np.float32), self.sample_rate

    def synthesize_streaming(self, text: str, persona: str = "tv"):
        """Yields (audio float32 mono, sample_rate) per segment for low latency."""
        if not self.is_ready:
            return
        for audio in self._stream_arrays(text, persona):
            yield audio, self.sample_rate

    def _stream_arrays(self, text: str, persona: str):
        norm = ru_textnorm.normalize(text)
        if not norm.strip():
            return
        name, _ = PERSONA_VOICE.get(persona, (_DEFAULT_VOICE, 1.0))
        for segment in _split_segments(norm):
            if self._stop_event.is_set():
                return
            # lock only around inference of one segment, released during playback
            with self._lock:
                try:
                    voice = self._ensure_voice(name)
                    cfg = self._config_for(persona)
                    chunks = [ch.audio_int16_array for ch in voice.synthesize(segment, cfg)]
                except Exception as exc:
                    self.status = f"Синтез: {exc}"
                    _log.error("Piper synth error: %s", exc)
                    continue
            if chunks:
                audio = np.concatenate(chunks).astype(np.float32) / 32768.0
                if len(audio):
                    yield audio

    def wait_until_ready(self, timeout: float = 120.0) -> bool:
        self._loaded.wait(timeout=timeout)
        return self.is_ready
