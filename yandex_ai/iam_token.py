"""yandex_ai/iam_token.py
=========================
Обмен долгоживущего Yandex OAuth-токена на короткоживущий (~12ч) IAM-токен,
с авто-рефрешем. Используется, когда Credentials.auth_mode == "iam" —
Credentials.api_key в этом режиме хранит OAuth-токен, не сырой IAM-токен.

Кэш держит консервативный TTL (config.YANDEX_IAM_REFRESH_INTERVAL_SEC),
заметно короче реального времени жизни IAM-токена — см. комментарий в
config.py о том, почему expiresAt из ответа Yandex не парсится.
"""
from __future__ import annotations

import asyncio
import time

import aiohttp

import config


class IamTokenManager:
    def __init__(self) -> None:
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_token(self, session: aiohttp.ClientSession, oauth_token: str) -> str:
        """Вернуть валидный IAM-токен, обменяв OAuth-токен заново при необходимости."""
        async with self._lock:
            if self._token is not None and time.monotonic() < self._expires_at:
                return self._token
            token = await self._exchange(session, oauth_token)
            self._token = token
            self._expires_at = time.monotonic() + config.YANDEX_IAM_REFRESH_INTERVAL_SEC
            return token

    async def _exchange(self, session: aiohttp.ClientSession, oauth_token: str) -> str:
        timeout = aiohttp.ClientTimeout(total=config.YANDEX_IAM_TOTAL_TIMEOUT,
                                        connect=config.YANDEX_IAM_CONNECT_TIMEOUT)
        async with session.post(
            config.YANDEX_IAM_URL,
            json={"yandexPassportOauthToken": oauth_token},
            timeout=timeout,
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
        return data["iamToken"]
