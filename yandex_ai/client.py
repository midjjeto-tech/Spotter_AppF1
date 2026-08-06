"""Общий клиент Yandex Cloud: asyncio-loop в выделенном потоке + aiohttp-сессия.

Потоковые вызыватели подают корутины через submit() и ждут future.result(timeout=...).
Блокируется только их собственный поток — поток телеметрии/UI не затрагивается.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading

import aiohttp
import grpc

import config
from yandex_ai import credentials as creds_mod
from yandex_ai.credentials import Credentials
from yandex_ai.iam_token import IamTokenManager

_log = logging.getLogger(__name__)


class YandexClient:
    def __init__(self, creds: Credentials):
        self._creds = creds
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: aiohttp.ClientSession | None = None
        self._grpc_channel: "grpc.aio.Channel | None" = None
        self._ready = threading.Event()
        self._stopped = False
        # auth_mode="iam": api_key хранит OAuth-токен, IamTokenManager обменивает
        # его на короткоживущий IAM-токен и авто-рефрешит. Иначе — обычный Api-Key.
        self._iam = IamTokenManager() if creds.auth_mode == "iam" else None

    # ------------------------------ lifecycle ----------------------------- #
    def start(self) -> None:
        if self._stopped:
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True,
                                        name="yandex-loop")
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            _log.error("YandexClient loop did not start in time")
        elif self._session is None or self._grpc_channel is None:
            _log.error("YandexClient session/grpc channel failed to initialize")

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        async def _init_session() -> None:
            # aiohttp 3.14: ClientSession must be constructed inside a running
            # event loop (it calls asyncio.get_running_loop()).
            self._session = aiohttp.ClientSession()
            # grpc.aio channel — long-lived, multiplexed, same lifecycle as
            # the aiohttp session above (created once, reused for every call).
            self._grpc_channel = grpc.aio.secure_channel(
                config.YANDEX_TTS_GRPC_ENDPOINT, grpc.ssl_channel_credentials())

        # Гарантируем _ready.set() даже при сбое инициализации, чтобы start()
        # не висел весь таймаут; при провале сессии loop не запускаем.
        try:
            self._loop.run_until_complete(_init_session())
        except Exception:  # noqa: BLE001
            _log.exception("YandexClient session init failed")
        finally:
            self._ready.set()
        if self._session is None or self._grpc_channel is None:
            self._loop.close()
            return
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def stop(self, timeout: float = 3.0) -> None:
        if self._stopped:
            return
        self._stopped = True
        loop = self._loop
        if loop is None:
            return
        async def _close():
            if self._session:
                await self._session.close()
            if self._grpc_channel:
                await self._grpc_channel.close()
        try:
            asyncio.run_coroutine_threadsafe(_close(), loop).result(
                timeout=max(0.0, timeout))
        except Exception:  # noqa: BLE001
            pass
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:  # noqa: BLE001 — loop уже закрыт (поток умер аномально)
            pass
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))

    def submit(self, coro) -> concurrent.futures.Future:
        if self._loop is None:
            raise RuntimeError("YandexClient not started")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    # ------------------------------- helpers ------------------------------ #
    @property
    def folder_id(self) -> str:
        return self._creds.folder_id

    @property
    def iam_refresh_active(self) -> bool:
        """True if headers()/grpc_metadata() may need to exchange an OAuth
        token for a fresh IAM token before a request can proceed — callers
        that impose their own timeout on the whole call (yandex_ai/speech.py's
        _try_once) should budget extra time for that possible network round
        trip, on top of the request's own timeout."""
        return self._iam is not None

    async def _auth_header(self) -> dict:
        if self._iam is not None:
            token = await self._iam.get_token(self._session, self._creds.api_key)
            return {"Authorization": f"Bearer {token}"}
        return creds_mod.auth_header(self._creds)

    async def headers(self, extra: dict | None = None) -> dict:
        h = await self._auth_header()
        if extra:
            h.update(extra)
        return h

    async def grpc_metadata(self) -> list[tuple[str, str]]:
        if self._iam is not None:
            token = await self._iam.get_token(self._session, self._creds.api_key)
            return [("authorization", f"Bearer {token}")]
        return creds_mod.grpc_auth_metadata(self._creds)

    def tts_synthesizer_stub(self):
        from yandex.cloud.ai.tts.v3 import tts_service_pb2_grpc
        return tts_service_pb2_grpc.SynthesizerStub(self._grpc_channel)

    async def post_json(self, url: str, payload: dict, *, connect: float, total: float,
                        extra_headers: dict | None = None) -> dict:
        timeout = aiohttp.ClientTimeout(total=total, connect=connect)
        headers = await self.headers({"Content-Type": "application/json", **(extra_headers or {})})
        async with self._session.post(url, json=payload, headers=headers,
                                      timeout=timeout) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def post_json_raw(self, url: str, payload: dict, *, connect: float, total: float,
                            extra_headers: dict | None = None) -> bytes:
        """POST JSON, return the RAW response body (bytes).

        Needed for streaming endpoints (e.g. SpeechKit v3 utteranceSynthesis)
        whose response is newline-delimited JSON, NOT a single JSON object —
        post_json()'s resp.json() would choke on the multi-object stream.
        """
        timeout = aiohttp.ClientTimeout(total=total, connect=connect)
        headers = await self.headers({"Content-Type": "application/json", **(extra_headers or {})})
        async with self._session.post(url, json=payload, headers=headers,
                                      timeout=timeout) as resp:
            resp.raise_for_status()
            return await resp.read()

    async def post_form(self, url: str, data: dict, *, connect: float, total: float) -> bytes:
        timeout = aiohttp.ClientTimeout(total=total, connect=connect)
        headers = await self.headers()
        async with self._session.post(url, data=data, headers=headers,
                                      timeout=timeout) as resp:
            resp.raise_for_status()
            return await resp.read()

    async def post_audio(self, url: str, audio: bytes, params: dict, *, connect: float,
                         total: float) -> bytes:
        """POST raw audio bytes как тело запроса + query-параметры (Yandex STT
        recognize: LPCM в теле, folderId/lang/format/sampleRateHertz в query-строке)."""
        timeout = aiohttp.ClientTimeout(total=total, connect=connect)
        headers = await self.headers()
        async with self._session.post(url, params=params, data=audio, headers=headers,
                                      timeout=timeout) as resp:
            resp.raise_for_status()
            return await resp.read()

    # ------------------------------ validate ------------------------------ #
    async def validate(self) -> tuple[bool, str, str]:
        """(ok, code, message). Дешёвые пробы GPT и TTS."""
        from yandex_ai.gpt import YandexGPT
        from yandex_ai.speech import YandexSpeech
        # --- GPT ---
        try:
            gpt = YandexGPT(self)
            txt = await gpt.acomplete("Ты тестовый ассистент.", "пинг", max_tokens=1)
            if not txt:
                return (False, "YANDEX_CRED_INVALID", "GPT не вернул ответ")
        except aiohttp.ClientResponseError as e:
            if e.status in (401, 403):
                return (False, "YANDEX_CRED_INVALID", "Ключ или Folder ID неверны")
            if e.status == 429:
                return (False, "YANDEX_RATE_LIMIT", "Превышен лимит запросов")
            return (False, "YANDEX_NETWORK_ERROR", f"HTTP {e.status}")
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return (False, "YANDEX_NETWORK_ERROR", "Нет связи с Yandex Cloud")
        # --- TTS ---
        try:
            sp = YandexSpeech(self)
            pcm = await sp.asynthesize("тест", "filipp", "neutral", 1.0)
            if pcm is None or len(pcm) == 0:
                return (False, "YANDEX_TTS_ERROR", "SpeechKit не вернул аудио")
        except Exception:  # noqa: BLE001
            return (False, "YANDEX_TTS_ERROR", "SpeechKit недоступен")
        return (True, "OK", "Yandex подключён")

    async def validate_quick(self, timeout: float = 2.5) -> bool:
        """Лёгкая проба «жив ли ключ» для фонового health-monitor.

        Один GPT-пинг на 1 токен с общим таймаутом — дешевле full validate()
        (не дёргает платный TTS на каждой пробе). True = Yandex ответил вовремя.
        Любой сбой/таймаут = False (детали классифицирует startup-validate()).
        """
        from yandex_ai.gpt import YandexGPT
        try:
            gpt = YandexGPT(self)
            txt = await asyncio.wait_for(
                gpt.acomplete("Ты тестовый ассистент.", "пинг", max_tokens=1),
                timeout=timeout,
            )
            return bool(txt)
        except Exception:  # noqa: BLE001 — таймаут/сеть/HTTP → недоступен
            return False
