"""
core/remote_access.py
======================
Политика доступа к локальному API снаружи — «второй экран»: таймингборд и лента
на телефоне рядом с рулём, без Alt-Tab.

**Это не смена адреса привязки.** Через то же API МЕНЯЮТ настройки и ЗАПИСЫВАЮТ
ключи Yandex и GigaChat. Открыть его в сеть без политики означало бы отдать
любому в квартире (и любому гостю Wi-Fi) право переписать чужие платные ключи.

Правила, по убыванию важности:

1. Локальный клиент разрешён ВСЕГДА. Само приложение ходит в своё же API, и
   политика, которая ломает это, ломает продукт.
2. Пока `remote_access_enabled` выключен, снаружи не пускаем никого — это
   поведение по умолчанию и оно совпадает с прежним (привязка к 127.0.0.1).
3. Снаружи нужен верный токен. Пустой токен в настройках — это сломанная
   конфигурация, а не «доступ всем».
4. Запись ключей API доступна ТОЛЬКО локально, даже с верным токеном. Телефону
   незачем задавать ключи, а их утечка стоит реальных денег.

Модуль чистый: ни Bottle, ни сокетов. Решение — функция от адреса, пути, метода
и токена, поэтому его можно проверить целиком без поднятого сервера.
"""
from __future__ import annotations

import hmac
import secrets

#: Ручки, доступные только с самой машины — независимо от токена.
#: Ключи Yandex/GigaChat: их утечка стоит реальных денег, а телефону незачем
#: их задавать. `/api/remote-access` отдаёт сам токен — его место тоже только
#: на той машине, где приложение запущено.
LOCAL_ONLY_PATHS: frozenset[str] = frozenset({
    "/api/yandex/credentials",
    "/api/gigachat/credentials",
    "/api/remote-access",
})

#: Прежнее имя — оставлено, чтобы не ломать читателей политики.
CREDENTIAL_PATHS = LOCAL_ONLY_PATHS

_LOOPBACK_NAMES = frozenset({"localhost", "::1", "::ffff:127.0.0.1"})

TOKEN_BYTES = 24


def generate_token() -> str:
    """Токен для второго экрана. Одноразовая генерация при включении фичи."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def bind_host(remote_enabled: bool) -> str:
    """Адрес привязки HTTP-сервера.

    Без удалённого доступа остаётся ровно прежний 127.0.0.1: включение фичи —
    единственное, что открывает порт наружу."""
    return "0.0.0.0" if remote_enabled else "127.0.0.1"


def lan_address() -> str:
    """Адрес этой машины в локальной сети — тот, который надо набрать на
    телефоне.

    UDP-сокет к внешнему адресу НИЧЕГО не отправляет: он нужен только чтобы
    спросить у ОС, какой интерфейс она выбрала бы для выхода наружу. Это
    надёжнее, чем `gethostbyname(gethostname())`, который на машинах с
    несколькими адаптерами (Hyper-V, VPN, WSL) часто отдаёт не тот адрес."""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def is_loopback(addr: str | None) -> bool:
    if not addr:
        return False
    if addr in _LOOPBACK_NAMES:
        return True
    return addr.startswith("127.")


class RemoteAccessPolicy:
    """Один экземпляр на приложение; пересоздаётся при смене настроек."""

    def __init__(self, enabled: bool, token: str) -> None:
        self.enabled = bool(enabled)
        self.token = token or ""

    def allows(self, client_addr: str | None, path: str, method: str,
               token: str | None) -> bool:
        if is_loopback(client_addr):
            return True
        if not self.enabled or not self.token:
            return False
        if path in LOCAL_ONLY_PATHS:
            # Не «забыли добавить токен», а сознательный отказ: ключи задаются
            # только с той машины, где запущено приложение.
            return False
        # Постоянное время: длина и содержимое токена не должны утекать через
        # время ответа.
        return hmac.compare_digest(self.token, token or "")
