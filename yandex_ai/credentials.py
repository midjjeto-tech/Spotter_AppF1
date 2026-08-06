"""Хранение и валидация Yandex-ключа.

Шифрование — Windows DPAPI через ctypes (crypt32.dll), без зависимости от pywin32.
Привязано к Windows-аккаунту: файл бесполезен на другой машине/юзере. Если DPAPI
недоступен — плейнтекст-фолбэк с предупреждением в лог.
"""
from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
from ctypes import wintypes
from dataclasses import dataclass

import config

_log = logging.getLogger(__name__)


@dataclass
class Credentials:
    api_key: str
    folder_id: str
    auth_mode: str = "api_key"   # "api_key" | "iam"


# ----------------------------- DPAPI (ctypes) ----------------------------- #

class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob_in(data: bytes) -> _DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _blob_bytes(blob: _DATA_BLOB) -> bytes:
    return ctypes.string_at(blob.pbData, int(blob.cbData))


def dpapi_encrypt(plaintext: str) -> str | None:
    """DPAPI-шифр строки -> base64. None, если DPAPI недоступен."""
    try:
        blob_in = _blob_in(plaintext.encode("utf-8"))
        blob_out = _DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
        if not ok:
            return None
        try:
            enc = _blob_bytes(blob_out)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return base64.b64encode(enc).decode("ascii")
    except Exception as exc:  # noqa: BLE001 — DPAPI может отсутствовать (не Windows и т.п.)
        _log.warning("DPAPI encrypt unavailable: %s", exc)
        return None


def dpapi_decrypt(b64: str) -> str | None:
    try:
        blob_in = _blob_in(base64.b64decode(b64.encode("ascii")))
        blob_out = _DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
        if not ok:
            return None
        try:
            dec = _blob_bytes(blob_out)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return dec.decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        _log.warning("DPAPI decrypt failed: %s", exc)
        return None


# ----------------------------- persistence -------------------------------- #

def save(creds: Credentials) -> None:
    enc = dpapi_encrypt(creds.api_key)
    payload: dict = {"folder_id": creds.folder_id, "auth_mode": creds.auth_mode}
    if enc is not None:
        payload["api_key_enc"] = enc
        payload["encrypted"] = True
    else:
        payload["api_key"] = creds.api_key
        payload["encrypted"] = False
        _log.warning("Yandex creds saved WITHOUT encryption (DPAPI unavailable)")
    path = config.YANDEX_CREDS_FILE
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)


def load() -> Credentials | None:
    path = config.YANDEX_CREDS_FILE
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:  # noqa: BLE001
        return None
    if payload.get("encrypted"):
        api_key = dpapi_decrypt(payload.get("api_key_enc", ""))
    else:
        api_key = payload.get("api_key", "")
    if not api_key or not payload.get("folder_id"):
        return None
    return Credentials(api_key=api_key,
                       folder_id=payload["folder_id"],
                       auth_mode=payload.get("auth_mode", "api_key"))


def clear() -> None:
    try:
        os.remove(config.YANDEX_CREDS_FILE)
    except FileNotFoundError:
        pass


# ------------------------------- helpers ---------------------------------- #

def auth_header(creds: Credentials) -> dict:
    """Низкоуровневый форматтер: собрать Authorization из УЖЕ ГОТОВОГО токена.

    ВАЖНО про auth_mode="iam": здесь `creds.api_key` трактуется как готовый к
    использованию IAM-токен (Bearer как есть, без обмена). Но
    `yandex_ai/client.py::YandexClient` в режиме "iam" хранит в `api_key`
    OAuth-токен и сам обменивает его на IAM через `IamTokenManager` (см.
    `YandexClient._auth_header()`/`grpc_metadata()`) — эта функция напрямую
    не вызывается для живого IAM-пути (единственные вызовы —
    `YandexClient`'s api_key-ветка, `self._iam is None`). Не звать эту функцию
    напрямую с IAM-режимными `Credentials` из нового кода — она отправит
    долгоживущий OAuth-секрет как Bearer-токен."""
    if creds.auth_mode == "iam":
        return {"Authorization": f"Bearer {creds.api_key}"}
    return {"Authorization": f"Api-Key {creds.api_key}"}


def grpc_auth_metadata(creds: Credentials) -> list[tuple[str, str]]:
    """То же значение Authorization, что и auth_header(), но как gRPC-metadata
    (нижний регистр ключа — требование gRPC), не HTTP-заголовок. Переиспользует
    auth_header() — ветка iam/api_key не дублируется в двух местах. Те же
    оговорки про auth_mode="iam", что и в auth_header(), применимы и здесь."""
    value = auth_header(creds)["Authorization"]
    return [("authorization", value)]


def mask(secret: str) -> str:
    if not secret:
        return ""
    return ("•" * max(0, len(secret) - 4)) + secret[-4:]
