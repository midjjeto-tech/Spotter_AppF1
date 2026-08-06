"""
yandex_ai/stt.py
=================
Yandex SpeechKit STT (v1, короткое аудио): LPCM bytes -> распознанный текст.

Мирроит yandex_ai/speech.py: recognize() — синхронная обёртка, глотает
исключения -> None (вызывающий код деградирует в safe-фолбэк, см. commentator/query.py).
"""
from __future__ import annotations

import json
import logging

import config

_log = logging.getLogger(__name__)


class YandexSTT:
    def __init__(self, client):
        self._client = client

    async def _arecognize(self, audio: bytes, sr: int) -> str | None:
        params = {
            "folderId": self._client.folder_id,
            "lang": "ru-RU",
            "format": "lpcm",
            "sampleRateHertz": str(sr),
        }
        raw = await self._client.post_audio(
            config.YANDEX_STT_URL, audio, params,
            connect=config.YANDEX_STT_CONNECT_TIMEOUT,
            total=config.YANDEX_STT_TOTAL_TIMEOUT,
        )
        if not raw:
            return None
        data = json.loads(raw.decode("utf-8"))
        text = (data.get("result") or "").strip()
        return text or None

    def recognize(self, audio: bytes, sr: int = 48000) -> str | None:
        """Распознать речь из LPCM int16 mono bytes. None — недоступно/сбой/тишина."""
        if not audio:
            return None
        try:
            fut = self._client.submit(self._arecognize(audio, sr))
            return fut.result(timeout=config.YANDEX_STT_TOTAL_TIMEOUT + 1.0)
        except Exception as exc:  # noqa: BLE001
            _log.warning("YandexSTT recognize failed: %s", exc)
            return None
