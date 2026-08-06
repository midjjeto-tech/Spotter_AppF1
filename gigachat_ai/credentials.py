"""Хранение Authorization-ключа GigaChat.

Шифрование — тот же Windows DPAPI, что и у Yandex (переиспользуем
yandex_ai/credentials.py, без дублирования крипто-кода). Файл привязан к
Windows-аккаунту: бесполезен на другой машине/юзере. Если DPAPI недоступен —
плейнтекст-фолбэк с предупреждением в лог.

В отличие от Yandex, GigaChat не требует folder_id — нужен только Authorization
key (base64 client_id:client_secret) и scope (физлица: GIGACHAT_API_PERS).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

import config
from yandex_ai.credentials import dpapi_decrypt, dpapi_encrypt

_log = logging.getLogger(__name__)


@dataclass
class GigaChatCredentials:
    authorization_key: str
    scope: str = "GIGACHAT_API_PERS"


def save(creds: GigaChatCredentials) -> None:
    enc = dpapi_encrypt(creds.authorization_key)
    payload: dict = {"scope": creds.scope}
    if enc is not None:
        payload["authorization_key_enc"] = enc
        payload["encrypted"] = True
    else:
        payload["authorization_key"] = creds.authorization_key
        payload["encrypted"] = False
        _log.warning("GigaChat creds saved WITHOUT encryption (DPAPI unavailable)")
    path = config.GIGACHAT_CREDS_FILE
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)


def load() -> GigaChatCredentials | None:
    path = config.GIGACHAT_CREDS_FILE
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:  # noqa: BLE001
        return None
    if payload.get("encrypted"):
        key = dpapi_decrypt(payload.get("authorization_key_enc", ""))
    else:
        key = payload.get("authorization_key", "")
    if not key:
        return None
    return GigaChatCredentials(authorization_key=key,
                               scope=payload.get("scope", config.GIGACHAT_SCOPE))


def clear() -> None:
    try:
        os.remove(config.GIGACHAT_CREDS_FILE)
    except FileNotFoundError:
        pass
