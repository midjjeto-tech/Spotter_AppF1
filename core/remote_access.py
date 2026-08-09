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


#: Куски имён адаптеров, которые почти никогда не являются домашней сетью.
#: Список именно по ИМЕНАМ, потому что по адресу их не отличить: Docker живёт в
#: 172.17–172.18, а это тот же приватный диапазон, что и у роутеров.
_VIRTUAL_HINTS = (
    "loopback", "vethernet", "hyper-v", "wsl", "docker", "vmware", "virtualbox",
    "vbox", "tap", "tun", "tailscale", "zerotier", "wireguard", "openvpn",
    "hamachi", "radmin", "bluetooth", "npcap", "teredo", "isatap",
)


def _rank(address: str, adapter: str) -> tuple:
    """Ключ сортировки кандидатов: меньше — лучше."""
    name = adapter.lower()
    virtual = any(hint in name for hint in _VIRTUAL_HINTS)
    # 192.168/16 — то, что раздаёт почти любой домашний роутер; 10/8 — второй по
    # распространённости; 172.16/12 идёт последним ОСОЗНАННО: в нём же сидят
    # Docker и WSL, поэтому реальная сеть в этом диапазоне встречается реже, чем
    # виртуальная.
    if address.startswith("192.168."):
        family = 0
    elif address.startswith("10."):
        family = 1
    else:
        family = 2
    return (int(virtual), family, address)


def lan_candidates() -> list[tuple[str, str]]:
    """Все адреса этой машины в приватных сетях: [(адрес, адаптер)], лучший
    первым.

    Отдаём СПИСОК, а не одно значение, потому что честно угадать нельзя.
    Найдено живой проверкой: на машине с VPN прежний способ (UDP-сокет к внешнему
    адресу — «спроси у ОС, каким интерфейсом она пойдёт наружу») возвращал адрес
    туннеля для ЛЮБОЙ цели, включая 8.8.8.8 и 192.168.1.1, потому что VPN
    забирает маршрут по умолчанию. Телефон по такому адресу не достучится
    никогда, а пользователь видит правдоподобную ссылку и ищет причину в
    брандмауэре.

    Поэтому лучший кандидат — только предположение, а UI обязан показать
    остальные."""
    try:
        import socket

        import psutil
    except ImportError:
        return []

    found: list[tuple[str, str]] = []
    try:
        stats = psutil.net_if_stats()
        for adapter, addresses in psutil.net_if_addrs().items():
            link = stats.get(adapter)
            if link is not None and not link.isup:
                continue
            for entry in addresses:
                # Сравнение с самой константой, а НЕ со строкой её имени: в
                # Python 3.11 у IntEnum сменился __str__, и str(socket.AF_INET)
                # стал "2" вместо "AddressFamily.AF_INET". Проверка по имени
                # молча не находила ни одного адреса — список кандидатов
                # получался пустым, и всё откатывалось на тот же VPN.
                if entry.family != socket.AF_INET:
                    continue
                address = getattr(entry, "address", "") or ""
                if _is_private(address):
                    found.append((address, adapter))
    except Exception:  # noqa: BLE001 — адрес не повод падать на старте
        return []
    return sorted(found, key=lambda item: _rank(*item))


def _is_private(address: str) -> bool:
    if not address or address.startswith("127.") or address.startswith("169.254."):
        return False
    if address.startswith("192.168.") or address.startswith("10."):
        return True
    if address.startswith("172."):
        try:
            second = int(address.split(".")[1])
        except (IndexError, ValueError):
            return False
        return 16 <= second <= 31
    return False


def lan_address() -> str:
    """Лучший кандидат на адрес для телефона. Только предположение — полный
    список отдаёт `lan_candidates()`."""
    candidates = lan_candidates()
    if candidates:
        return candidates[0][0]
    return _address_by_route()


def _address_by_route() -> str:
    """Запасной способ: спросить у ОС, каким интерфейсом она пойдёт наружу.

    UDP-сокет НИЧЕГО не отправляет — `connect` на датаграммном сокете только
    выбирает маршрут. Оставлен на случай, когда перебор интерфейсов недоступен
    (нет psutil); самостоятельно он ненадёжен — см. `lan_candidates`."""
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
