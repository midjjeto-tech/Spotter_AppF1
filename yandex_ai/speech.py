"""Yandex SpeechKit TTS: text → LPCM 48kHz mono → numpy float32.

Supports both v1 (legacy REST form) and v3 (modern REST JSON) synthesis.
Version is selected via set_tts_version("v1"|"v3"). Default is "v1" to preserve
existing behaviour. v3 falls back gracefully to v1 on any error.

asynthesize() — async, пробрасывает исключения. synthesize() — sync-обёртка для
voice/tts.py; исключения глотает и возвращает (None, sr) → Piper-фолбэк.
"""
from __future__ import annotations

import base64
import concurrent.futures
import json
import logging
import queue
import threading
import time

import numpy as np

import config
from core.pronunciation import apply_yandex
from yandex_ai import voices

_log = logging.getLogger(__name__)

# SpeechKit v1 (legacy REST) rejects the premium neuro voices with HTTP 400
# (live probe 2026-07-01) — only v3 supports them. Whenever _try_once dispatches
# to v1, remap each premium voice to its nearest legacy equivalent so the v1
# attempt can actually succeed. Gender-matched: alexander/anton/kirill (male) ->
# filipp/ermil/zahar; marina (female) -> alena. Legacy emotions were never tuned
# for the premium personas, so emotion is forced to "neutral" on remap.
_V1_VOICE_FALLBACK: dict[str, str] = {
    "alexander": "filipp",
    "anton": "ermil",
    "marina": "alena",
    "kirill": "zahar",
}


class YandexSpeech:
    def __init__(self, client, persona_overrides: dict | None = None):
        self._client = client
        self._overrides = persona_overrides or {}
        self._version: str = "v1"   # "v1" or "v3"; set by engine via set_tts_version()
        # Предохранитель v3 (см. config.YANDEX_TTS_V3_FAILURE_THRESHOLD).
        # Лок нужен: synthesize() зовут из воркера очереди озвучки, а он не один.
        self._v3_lock = threading.Lock()
        self._v3_failures = 0
        self._v3_blocked_until = 0.0

    def set_overrides(self, overrides: dict | None) -> None:
        self._overrides = overrides or {}

    # ── Предохранитель v3 ────────────────────────────────────────────────────

    def _v3_blocked(self) -> bool:
        """Открыт ли предохранитель — то есть стоит ли вообще пробовать v3.

        Монотонные часы, а не wall clock: перевод системного времени не должен
        ни продлевать остывание, ни обнулять его."""
        with self._v3_lock:
            return time.monotonic() < self._v3_blocked_until

    def _note_v3_result(self, ok: bool) -> None:
        """Учесть исход попытки v3 и при необходимости разомкнуть цепь."""
        with self._v3_lock:
            if ok:
                if self._v3_blocked_until or self._v3_failures:
                    _log.info("YandexSpeech: v3 снова отвечает — предохранитель сброшен")
                self._v3_failures = 0
                self._v3_blocked_until = 0.0
                return
            self._v3_failures += 1
            if self._v3_failures < config.YANDEX_TTS_V3_FAILURE_THRESHOLD:
                return
            self._v3_blocked_until = (time.monotonic()
                                      + config.YANDEX_TTS_V3_BREAKER_COOLDOWN)
            self._v3_failures = 0
            _log.warning(
                "YandexSpeech: %d неудачи v3 подряд — уходим на v1 на %.0f с "
                "(перестаём платить таймаут каждой фразой)",
                config.YANDEX_TTS_V3_FAILURE_THRESHOLD,
                config.YANDEX_TTS_V3_BREAKER_COOLDOWN)

    def reset_v3_breaker(self) -> None:
        """Снять блокировку принудительно — смена настроек озвучки и новая
        сессия не должны наследовать остывание прошлой."""
        self._note_v3_result(True)

    def set_tts_version(self, version: str) -> None:
        """Select active TTS backend version. Ignored if value not in
        ("v1", "v3", "v3-grpc")."""
        if version in ("v1", "v3", "v3-grpc"):
            prev = self._version
            self._version = version
            if version != prev:
                _log.info("YandexSpeech TTS version changed: %s → %s", prev, version)

    @property
    def tts_version(self) -> str:
        return self._version

    # ------------------------------------------------------------------
    # v1 (legacy form-POST, LPCM raw bytes)
    # ------------------------------------------------------------------

    async def asynthesize(self, text: str, voice: str, emotion: str,
                          speed: float, sr: int | None = None) -> np.ndarray | None:
        """Public alias for v1 synthesis (backward-compatible with existing callers)."""
        import config as _config
        return await self._asynthesize_v1(text, voice, emotion, speed,
                                          sr or _config.YANDEX_TTS_SAMPLE_RATE)

    async def _asynthesize_v1(self, text: str, voice: str, emotion: str,
                               speed: float, sr: int) -> np.ndarray | None:
        data = {
            "text": text,
            "voice": voice,
            "emotion": emotion,
            "speed": str(speed),
            "lang": "ru-RU",
            "format": "lpcm",
            "sampleRateHertz": str(sr),
            "folderId": self._client.folder_id,
        }
        raw = await self._client.post_form(
            config.YANDEX_TTS_URL, data,
            connect=config.YANDEX_TTS_CONNECT_TIMEOUT,
            total=config.YANDEX_TTS_TOTAL_TIMEOUT,
        )
        if not raw:
            return None
        return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0

    # ------------------------------------------------------------------
    # v3 (JSON POST, response = newline-delimited JSON with base64 audio)
    # ------------------------------------------------------------------

    async def _asynthesize_v3(self, text: str, voice: str, speed: float,
                               sr: int, emotion: str = "neutral") -> np.ndarray | None:
        """Synthesize using SpeechKit v3 utteranceSynthesis REST endpoint.

        Response is a stream of newline-delimited JSON objects; each has
        ``audioChunk.data`` (base64 LPCM s16le).
        """
        hints: list[dict] = [
            {"voice": voice},
            {"speed": speed},
        ]
        # v3 передаёт эмоцию как role-хинт; neutral не шлём (дефолт голоса).
        # Неподдерживаемая роль → ошибка v3 → штатный per-phrase фолбэк на v1.
        if emotion and emotion != "neutral":
            hints.append({"role": emotion})
        payload = {
            "text": text,
            "outputAudioSpec": {
                "rawAudio": {
                    "audioEncoding": "LINEAR16_PCM",
                    "sampleRateHertz": sr,
                }
            },
            "hints": hints,
            "loudnessNormalizationType": "LUFS",
        }
        # v3 utteranceSynthesis returns a newline-delimited JSON STREAM, so we must
        # read raw bytes — post_json() (resp.json()) would fail on the multi-object
        # body and, worse, return a dict that the parsing below cannot decode.
        # The service account folder is derived from the Api-Key; v3 has no folderId
        # body field (sending one triggers HTTP 400 "unknown field").
        raw = await self._client.post_json_raw(
            config.YANDEX_TTS_V3_URL, payload,
            connect=config.YANDEX_TTS_V3_CONNECT_TIMEOUT,
            total=config.YANDEX_TTS_V3_TOTAL_TIMEOUT,
        )
        if not raw:
            return None
        # raw is bytes of newline-delimited JSON (or a single JSON object)
        try:
            text_body = raw.decode("utf-8")
        except Exception:
            return None
        chunks: list[bytes] = []
        for line in text_body.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            # unwrap { "result": { "audioChunk": { "data": "<b64>" } } }
            result = obj.get("result") or obj
            chunk_b64 = (result.get("audioChunk") or {}).get("data")
            if chunk_b64:
                chunks.append(base64.b64decode(chunk_b64))
        if not chunks:
            return None
        raw_pcm = b"".join(chunks)
        return np.frombuffer(raw_pcm, dtype="<i2").astype(np.float32) / 32768.0

    # ------------------------------------------------------------------
    # v3-grpc (SpeechKit v3 Synthesizer.UtteranceSynthesis, server-streaming gRPC)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_utterance_request(text: str, voice: str, speed: float, sr: int,
                                  emotion: str = "neutral"):
        """Shared request builder for the buffered and streaming v3-grpc calls
        (Этап A / Этап B) — avoids duplicating the Hints/AudioFormatOptions
        construction between them."""
        from yandex.cloud.ai.tts.v3 import tts_pb2
        hints = [tts_pb2.Hints(voice=voice), tts_pb2.Hints(speed=speed)]
        if emotion and emotion != "neutral":
            hints.append(tts_pb2.Hints(role=emotion))
        return tts_pb2.UtteranceSynthesisRequest(
            text=text,
            hints=hints,
            output_audio_spec=tts_pb2.AudioFormatOptions(
                raw_audio=tts_pb2.RawAudio(
                    audio_encoding=tts_pb2.RawAudio.LINEAR16_PCM,
                    sample_rate_hertz=sr,
                )
            ),
            loudness_normalization_type=tts_pb2.UtteranceSynthesisRequest.LUFS,
        )

    async def _stream_utterance_chunks(self, text: str, voice: str, speed: float,
                                        sr: int, emotion: str = "neutral"):
        """Shared async generator over Synthesizer.UtteranceSynthesis chunks —
        request construction, auth metadata, stub, gRPC timeout, and per-chunk
        PCM decode live HERE only, so the buffered (_asynthesize_v3_grpc) and
        streaming (synthesize_streaming) call sites can't drift apart on
        transport-level details (a past risk when both duplicated this body)."""
        request = self._build_utterance_request(text, voice, speed, sr, emotion)
        metadata = await self._client.grpc_metadata()
        stub = self._client.tts_synthesizer_stub()
        call = stub.UtteranceSynthesis(request, metadata=metadata,
                                       timeout=config.YANDEX_TTS_GRPC_TIMEOUT)
        async for response in call:
            yield np.frombuffer(response.audio_chunk.data,
                                dtype="<i2").astype(np.float32) / 32768.0

    async def _asynthesize_v3_grpc(self, text: str, voice: str, speed: float,
                                    sr: int, emotion: str = "neutral") -> np.ndarray | None:
        """Synthesize using SpeechKit v3 Synthesizer.UtteranceSynthesis (gRPC,
        server-streaming). Этап A: собираем ВСЕ чанки, потом декодируем — то же
        поведение, что _asynthesize_v3 (REST/NDJSON), другой транспорт. Настоящее
        потоковое воспроизведение по мере поступления чанков — synthesize_streaming()
        ниже (Этап B, voice/tts.py)."""
        parts = [chunk async for chunk in
                 self._stream_utterance_chunks(text, voice, speed, sr, emotion)]
        if not parts:
            return None
        return np.concatenate(parts).astype(np.float32)

    def synthesize_streaming(self, text: str, persona: str,
                             speed_scale: float = 1.0):
        """Этап B: yields (audio float32 mono, sample_rate) per gRPC chunk, as
        they arrive — for low-latency playback (voice/tts.py::_play_streaming).

        Same (audio, sr) generator contract as
        new_tts.piper_tts.PiperVoiceEngine.synthesize_streaming(). Only
        available for tts_version == "v3-grpc" — v1/REST-v3 have no true
        incremental transport (empty generator otherwise, caller falls back).

        The gRPC call must run on YandexClient's dedicated event-loop thread;
        this method is a SYNC generator called from the TTSQueue worker
        thread. A queue.Queue bridges the two: an async producer task
        (submitted via self._client.submit) pushes decoded chunks (or the
        raised exception, or a sentinel on completion) onto the queue; this
        generator just blocks on queue.get() and yields.
        """
        if self._version != "v3-grpc":
            return
        text = apply_yandex(text)
        sr = config.YANDEX_TTS_SAMPLE_RATE
        spec = voices.resolve(persona, self._overrides)
        # Множитель срочности — тот же, что в synthesize(): потоковый и обычный
        # путь обязаны звучать одинаково, иначе одна и та же реплика меняла бы
        # темп в зависимости от того, успел ли включиться стриминг.
        speed = float(spec["speed"]) * float(speed_scale)
        voice, emotion = spec["voice"], spec["emotion"]

        q: "queue.Queue" = queue.Queue()
        _DONE = object()

        async def _produce() -> None:
            try:
                async for pcm in self._stream_utterance_chunks(text, voice, speed, sr, emotion):
                    q.put(pcm)
            except Exception as exc:  # noqa: BLE001 — propagated to the consumer thread
                q.put(exc)
            finally:
                q.put(_DONE)

        self._client.submit(_produce())
        # Watchdog per q.get() call, not one deadline for the whole stream —
        # a long multi-chunk phrase keeps resetting it on every chunk. Without
        # this, a loop that stops or dies between submit() and _produce()
        # actually running (e.g. YandexClient.stop() racing this call) would
        # leave the queue empty forever with nothing to ever wake this up —
        # the sole TTSQueue playback worker thread would hang permanently.
        # gRPC's own per-call timeout (config.YANDEX_TTS_GRPC_TIMEOUT) already
        # bounds a live call; this margin only covers the loop-dead case. Also
        # budgets for a possible IAM token exchange inside _produce() before
        # the gRPC call even starts (see _try_once's iam_margin for the same
        # reasoning on the buffered path).
        iam_margin = (config.YANDEX_IAM_TOTAL_TIMEOUT
                     if self._client.iam_refresh_active else 0.0)
        watchdog = config.YANDEX_TTS_GRPC_TIMEOUT + 5.0 + iam_margin
        while True:
            try:
                item = q.get(timeout=watchdog)
            except queue.Empty:
                raise TimeoutError(
                    f"synthesize_streaming: no response within {watchdog:.0f}s "
                    "(event loop may have stopped)")
            if item is _DONE:
                return
            if isinstance(item, Exception):
                raise item
            yield item, sr

    # ------------------------------------------------------------------
    # Unified internal call (dispatches to v1, v3, or v3-grpc)
    # ------------------------------------------------------------------

    def _try_once(self, text: str, voice: str, emotion: str, speed: float,
                  sr: int, version: str) -> np.ndarray | None:
        """Single synthesis attempt. Returns None on any failure (logs at WARNING).

        Classifies the failure reason so the caller can log a specific fallback message:
        timeout | HTTP <code> | NDJSON parse error | <exc type>: <msg>
        """
        if version == "v1":
            mapped = _V1_VOICE_FALLBACK.get(voice)
            if mapped:
                _log.debug(
                    "YandexSpeech v1: premium voice '%s' unsupported on v1 — using '%s' (neutral)",
                    voice, mapped,
                )
                voice, emotion = mapped, "neutral"
        # auth_mode="iam": headers()/grpc_metadata() may transparently exchange
        # the OAuth token for a fresh IAM token INSIDE the coroutine below
        # (up to YANDEX_IAM_TOTAL_TIMEOUT) before the request itself even
        # starts. Without this margin, the first synthesis after each hourly
        # cache expiry (YANDEX_IAM_REFRESH_INTERVAL_SEC) on a slow network
        # could spuriously time out here while the coroutine keeps running
        # to completion in the background (a paid synthesis whose result
        # gets discarded).
        iam_margin = (config.YANDEX_IAM_TOTAL_TIMEOUT
                     if self._client.iam_refresh_active else 0.0)
        try:
            if version == "v3":
                coro = self._asynthesize_v3(text, voice, speed, sr, emotion=emotion)
                timeout = config.YANDEX_TTS_V3_TOTAL_TIMEOUT + 1.0 + iam_margin
            elif version == "v3-grpc":
                coro = self._asynthesize_v3_grpc(text, voice, speed, sr, emotion=emotion)
                timeout = config.YANDEX_TTS_GRPC_TIMEOUT + 1.0 + iam_margin
            else:
                coro = self._asynthesize_v1(text, voice, emotion, speed, sr)
                timeout = config.YANDEX_TTS_TOTAL_TIMEOUT + 1.0 + iam_margin
            fut = self._client.submit(coro)
            return fut.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            reason = f"future timeout ({timeout:.0f}s)"
        except Exception as exc:  # noqa: BLE001
            etype = type(exc).__name__
            msg = str(exc)
            if "Timeout" in etype or "timeout" in msg.lower():
                reason = f"timeout: {msg}"
            elif hasattr(exc, "status"):          # aiohttp.ClientResponseError
                reason = f"HTTP {exc.status}: {msg}"
            elif hasattr(exc, "code") and callable(getattr(exc, "code", None)):
                reason = f"gRPC {exc.code()}: {exc.details()}"   # grpc.aio.AioRpcError
            elif "JSONDecodeError" in etype:
                reason = f"NDJSON parse error: {msg}"
            else:
                reason = f"{etype}: {msg}"
        _log.warning("YandexSpeech v%s failed (%s/%s): %s", version, voice, emotion, reason)
        return None

    def synthesize(self, text: str, persona: str,
                   speed_scale: float = 1.0) -> tuple[np.ndarray | None, int]:
        """`speed_scale` — множитель темпа по срочности реплики
        (`core/radio/voice_cast.py::speed_scale`). Ложится ПОВЕРХ скорости
        персоны/слота: базовый темп остаётся выбором пользователя, срочность
        лишь смещает его. 1.0 — нейтрально, и это же значение сохраняет
        совместимость с уже накопленным кэшем (см. voice/tts.py::_voice_key)."""
        text = apply_yandex(text)   # ударения для проблемных имён (см. core/pronunciation.py)
        sr = config.YANDEX_TTS_SAMPLE_RATE
        spec = voices.resolve(persona, self._overrides)
        speed = float(spec["speed"]) * float(speed_scale)
        version = self._version

        # Предохранитель разомкнут — v3 не трогаем вовсе и не платим её таймаут.
        # Это же держит тембр: пока цепь открыта, все реплики идут одним
        # маршрутом, а не через раз премиальным голосом и легаси-подменой.
        if version in ("v3", "v3-grpc") and self._v3_blocked():
            _log.info(
                "YandexSpeech synthesize: v3 на остывании — сразу v1 "
                "(persona=%s voice=%s)", persona, spec["voice"])
            version = "v1"

        _log.info(
            "YandexSpeech synthesize: version=%s persona=%s voice=%s emotion=%s",
            version, persona, spec["voice"], spec["emotion"],
        )

        audio = self._try_once(text, spec["voice"], spec["emotion"], speed, sr, version)
        if version in ("v3", "v3-grpc"):
            self._note_v3_result(audio is not None and len(audio) > 0)

        if audio is not None and len(audio) > 0:
            _log.info("YandexSpeech OK: version=%s persona=%s voice=%s (%d samples)",
                      version, persona, spec["voice"], len(audio))
            return (audio, sr)

        # v3/v3-grpc graceful fallback to v1
        if audio is None and version in ("v3", "v3-grpc"):
            _log.warning(
                "YandexSpeech fallback: %s failed for persona=%s voice=%s — trying v1 "
                "(reason logged above)",
                version, persona, spec["voice"],
            )
            audio = self._try_once(text, spec["voice"], spec["emotion"], speed, sr, "v1")
            if audio is not None and len(audio) > 0:
                _log.info("YandexSpeech OK via v1 fallback: persona=%s voice=%s (%d samples)",
                          persona, spec["voice"], len(audio))
                return (audio, sr)

        # Defence: unsupported voice+emotion combo → retry with neutral (v1 only)
        if version == "v1" and spec["emotion"] != "neutral":
            audio = self._try_once(text, spec["voice"], "neutral", speed, sr, "v1")
            if audio is not None and len(audio) > 0:
                _log.warning(
                    "Yandex: emotion '%s' rejected by voice '%s' — used neutral",
                    spec["emotion"], spec["voice"],
                )
                return (audio, sr)

        return (None, sr)
