"""
voice/tts.py
============
Озвучка через Piper (ONNX, CPU, нативный русский). Резерв — pyttsx3.
Streaming: синтез по предложениям, первый звук играет, пока генерится остальное.
Кэш фраз на диск (voice/cache.py) — повтор без синтеза. Кэш хранит «сухой»
звук; радио-эффект (voice/radio_fx.py) накладывается при воспроизведении.
Queue: события не перебивают и не накладываются.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time

import config
from voice.cache import TTSCache
from voice import radio_fx
from commentator.templates import SIMPLE
from new_tts.piper_tts import PiperVoiceEngine, PERSONA_VOICE
from new_tts.queue_handler import TTSQueue

_log = logging.getLogger(__name__)


class Voice:
    def __init__(self, *_args, **_kwargs):
        self._engine = PiperVoiceEngine()
        self.pyttsx3_engine = None
        self.status_message = "Загрузка Piper..."
        # version tag invalidates stale cache. Bump on engine/voice/normalizer change.
        # v2: Ruslan default + расширенный ru_textnorm (англ.→кириллица, год→порядковое)
        self._cache = TTSCache(os.path.join(config.DATA_DIR, "tts_cache"), version="piper-22k-v2")
        self._queue: TTSQueue | None = None
        self._current_persona = "tv"
        self._radio_enabled = True
        self._configure_stdout()
        removed = self._cache.cleanup_tmp()
        if removed:
            _log.info("Removed %d stale .tmp files from TTS cache", removed)
        threading.Thread(target=self._wait_and_setup, daemon=True, name="tts-setup").start()

    def _configure_stdout(self) -> None:
        stdout = getattr(sys, "stdout", None)
        encoding = getattr(stdout, "encoding", None)
        if encoding is None or encoding.lower() != "utf-8":
            try:
                if stdout is not None:
                    stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass

    def _wait_and_setup(self) -> None:
        """Ждёт загрузки Piper, затем создаёт Queue и прогревает кэш."""
        self._engine.wait_until_ready(timeout=120.0)

        if self._engine.is_ready:
            self._queue = TTSQueue(speak_fn=self._play_blocking)
            self.status_message = self._engine.status
            threading.Thread(target=self._prewarm_cache, daemon=True, name="tts-prewarm").start()
        else:
            engine_err = self._engine.status
            self._init_pyttsx3()
            if self.pyttsx3_engine is not None:
                self._queue = TTSQueue(speak_fn=self._say_pyttsx3_blocking)
            else:
                self.status_message = engine_err

    def _init_pyttsx3(self) -> None:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", 180)
            for voice in engine.getProperty("voices"):
                name = (voice.name or "").lower()
                vid = (voice.id or "").lower()
                if "russian" in name or "ru" in vid:
                    engine.setProperty("voice", voice.id)
                    break
            self.pyttsx3_engine = engine
            self.status_message = "pyttsx3 активирован (резерв)"
        except Exception as exc:
            self.status_message = f"pyttsx3: {exc}"

    def _prewarm_cache(self) -> None:
        """Кэширует статичные фразы для всех персон в фоне.
        Уступает движок, если очередь воспроизведения не пуста."""
        try:
            for phrases in SIMPLE.values():
                for phrase in phrases:
                    if "{" in phrase or not self._engine.is_ready:
                        continue
                    if self._queue is not None and not self._queue._queue.empty():
                        time.sleep(0.2)
                        continue
                    for persona in PERSONA_VOICE:
                        cache_path = self._cache.path_for(phrase.strip(), persona)
                        if not os.path.exists(cache_path):
                            self._generate_and_cache(phrase.strip(), persona)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Публичный интерфейс (engine.py зависит от этих полей и методов)     #
    # ------------------------------------------------------------------ #

    @property
    def is_available(self) -> bool:
        return self._engine.is_ready or self.pyttsx3_engine is not None

    @property
    def engine_name(self) -> str:
        if self._engine.is_ready:
            return "Piper (RU)"
        if self.pyttsx3_engine is not None:
            return "pyttsx3"
        return "Нет"

    def set_persona(self, persona: str) -> None:
        self._current_persona = persona if persona in PERSONA_VOICE else "tv"

    def set_radio_fx(self, enabled: bool) -> None:
        self._radio_enabled = bool(enabled)

    def say(self, text: str) -> bool:
        """Ставит фразу в очередь воспроизведения. Возвращает True сразу."""
        if not text or not text.strip() or not self.is_available:
            return False
        if self._queue is not None:
            self._queue.enqueue(text.strip())
            return True
        return False

    def test_say(self, text: str) -> bool:
        """Тестовое воспроизведение: очищает очередь, ставит фразу первой."""
        if self._queue is not None:
            self._queue.clear()
        t0 = time.monotonic()
        ok = self.say(text)
        _log.debug("test_say enqueued in %.1f ms", (time.monotonic() - t0) * 1000)
        return ok

    # ------------------------------------------------------------------ #
    # Воспроизведение (вызывается из TTSQueue._worker в фоновом потоке)   #
    # ------------------------------------------------------------------ #

    def _play_blocking(self, text: str) -> None:
        self.status_message = self._engine.status
        persona = self._current_persona
        cache_path = self._cache.path_for(text, persona)
        if os.path.exists(cache_path):
            t0 = time.monotonic()
            self._play_wav(cache_path)
            _log.debug("playback from cache: %.0f ms", (time.monotonic() - t0) * 1000)
            return

        t0 = time.monotonic()
        self._play_streaming(text, cache_path, persona)
        _log.debug("playback synthesized+streamed: %.0f ms", (time.monotonic() - t0) * 1000)

    def _play_streaming(self, text: str, cache_path: str, persona: str = "tv") -> None:
        """Streaming: воспроизводит по сегментам, кэширует «сухую» полную запись.
        Радио-эффект накладывается на лету, в кэш не пишется."""
        try:
            import sounddevice as sd
            import numpy as np

            sr = self._engine.sample_rate
            dry_parts: list[np.ndarray] = []
            radio = self._radio_enabled

            with sd.OutputStream(
                samplerate=sr,
                channels=1,
                dtype="float32",
                latency="low",
            ) as stream:
                if radio:
                    stream.write(radio_fx.squelch(sr).reshape(-1, 1))
                for seg, seg_sr in self._engine.synthesize_streaming(text, persona):
                    dry_parts.append(seg)
                    out = radio_fx.bandpass(seg, seg_sr) if radio else seg
                    stream.write(np.ascontiguousarray(out.reshape(-1, 1), dtype="float32"))
                if radio:
                    stream.write(radio_fx.squelch(sr).reshape(-1, 1))

            if dry_parts:
                full = np.concatenate(dry_parts).astype(np.float32)
                self._save_wav(full, sr, cache_path)
                self._cache.evict_if_needed()

        except ImportError:
            audio, sr = self._engine.synthesize(text, persona)
            if audio is not None:
                self._save_wav(audio, sr, cache_path)
                self._play_wav(cache_path)
        except Exception as exc:
            self.status_message = f"Воспроизведение: {exc}"

    def _generate_and_cache(self, text: str, persona: str) -> str | None:
        """Генерирует и кэширует «сухой» звук без воспроизведения."""
        cache_path = self._cache.path_for(text, persona)
        if os.path.exists(cache_path):
            return cache_path
        audio, sr = self._engine.synthesize(text, persona)
        if audio is not None:
            self._save_wav(audio, sr, cache_path)
            return cache_path
        return None

    def _save_wav(self, audio, sample_rate: int, path: str) -> None:
        """Save mono float32 as 16-bit WAV using soundfile (dry, no radio fx)."""
        try:
            import numpy as np
            import soundfile as sf
            pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
            tmp = path + ".tmp"
            # format='WAV' must be explicit — soundfile can't infer it from .tmp
            sf.write(tmp, pcm, sample_rate, format="WAV", subtype="PCM_16")
            os.replace(tmp, path)
        except Exception as exc:
            self.status_message = f"Кэш TTS: {exc}"

    def _play_wav(self, path: str) -> None:
        """Play a cached dry WAV, applying the radio effect on the fly if enabled."""
        try:
            import sounddevice as sd
            import soundfile as sf
            import numpy as np
            data, sr = sf.read(path, dtype="float32")
            if data.ndim > 1:
                data = data[:, 0]  # cache is mono, but be safe
            if self._radio_enabled:
                data = np.concatenate([
                    radio_fx.squelch(sr),
                    radio_fx.bandpass(data, sr),
                    radio_fx.squelch(sr),
                ]).astype(np.float32)
            sd.play(data, sr)
            sd.wait()
        except ImportError:
            if sys.platform == "win32":
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
        except Exception as exc:
            self.status_message = f"WAV play: {exc}"

    # ------------------------------------------------------------------ #
    # pyttsx3 (резерв, если Piper не загрузился)                          #
    # ------------------------------------------------------------------ #

    def _say_pyttsx3_blocking(self, text: str) -> None:
        try:
            self.pyttsx3_engine.say(text)
            self.pyttsx3_engine.runAndWait()
        except Exception as exc:
            self.status_message = f"pyttsx3: {exc}"
