"""Политика доступа к локальному API извне (core/remote_access.py).

Сервер отдаёт не только состояние гонки: через него МЕНЯЮТ настройки и ЗАПИСЫВАЮТ
ключи Yandex и GigaChat. Поэтому «второй экран на телефоне» — это не смена
адреса привязки, а отдельная политика, и почти все тесты ниже про то, что
именно она обязана НЕ пускать.
"""
import pytest

from core import remote_access
from core.remote_access import CREDENTIAL_PATHS, RemoteAccessPolicy, is_loopback


def _policy(enabled=True, token="secret123"):
    return RemoteAccessPolicy(enabled=enabled, token=token)


# ── Локальный клиент: ничего не должно сломаться ─────────────────────────────

@pytest.mark.parametrize("addr", ["127.0.0.1", "::1", "localhost"])
def test_loopback_is_always_allowed(addr):
    """Само приложение ходит в своё же API. Любая политика, которая его
    ломает, ломает продукт."""
    p = _policy(enabled=False, token="")
    assert p.allows(addr, "/api/settings", "POST", token=None) is True


def test_loopback_may_write_credentials():
    p = _policy(enabled=False, token="")
    assert p.allows("127.0.0.1", "/api/yandex/credentials", "POST", None) is True


@pytest.mark.parametrize("addr,expected", [
    ("127.0.0.1", True), ("127.0.0.5", True), ("::1", True),
    ("192.168.1.10", False), ("10.0.0.2", False), ("", False), (None, False),
])
def test_is_loopback(addr, expected):
    assert is_loopback(addr) is expected


# ── Удалённый клиент ─────────────────────────────────────────────────────────

def test_remote_is_denied_while_the_feature_is_off():
    p = _policy(enabled=False)
    assert p.allows("192.168.1.10", "/api/state", "GET", "secret123") is False


def test_remote_with_valid_token_is_allowed():
    assert _policy().allows("192.168.1.10", "/api/state", "GET", "secret123") is True


def test_remote_without_token_is_denied():
    assert _policy().allows("192.168.1.10", "/api/state", "GET", None) is False


def test_remote_with_wrong_token_is_denied():
    assert _policy().allows("192.168.1.10", "/api/state", "GET", "nope") is False


def test_empty_token_never_authorises_even_when_enabled():
    """Пустой токен в настройках — это не «доступ всем», это сломанная
    конфигурация."""
    p = _policy(enabled=True, token="")
    assert p.allows("192.168.1.10", "/api/state", "GET", "") is False
    assert p.allows("192.168.1.10", "/api/state", "GET", None) is False


@pytest.mark.parametrize("path", sorted(CREDENTIAL_PATHS))
def test_credentials_are_loopback_only_even_with_a_valid_token(path):
    """Единственное, чья утечка стоит реальных денег. Телефону незачем
    записывать ключи API — запрещаем независимо от токена."""
    assert _policy().allows("192.168.1.10", path, "POST", "secret123") is False


def test_token_comparison_does_not_short_circuit_on_length():
    """Сравнение постоянного времени: длина токена не должна утекать через
    время ответа."""
    p = _policy(token="a" * 32)
    assert p.allows("192.168.1.10", "/api/state", "GET", "a") is False
    assert p.allows("192.168.1.10", "/api/state", "GET", "a" * 32) is True


# ── Статика ──────────────────────────────────────────────────────────────────

def test_remote_may_load_the_ui_itself_with_a_token():
    p = _policy()
    assert p.allows("192.168.1.10", "/", "GET", "secret123") is True
    assert p.allows("192.168.1.10", "/_next/static/chunks/x.js", "GET", "secret123") is True


def test_remote_cannot_load_the_ui_without_a_token():
    p = _policy()
    assert p.allows("192.168.1.10", "/", "GET", None) is False


# ── Токен ────────────────────────────────────────────────────────────────────

def test_generated_token_is_long_and_unique():
    from core.remote_access import generate_token

    a, b = generate_token(), generate_token()
    assert len(a) >= 24
    assert a != b


def test_bind_host_follows_the_setting():
    from core.remote_access import bind_host

    assert bind_host(False) == "127.0.0.1"
    assert bind_host(True) == "0.0.0.0"


# ── Выбор адреса для телефона ────────────────────────────────────────────────
# Найдено живой проверкой: на машине с VPN приложение показывало адрес туннеля
# (172.18.0.1, адаптер happ-tun), и телефон не достучался. Прежний способ —
# UDP-сокет к внешнему адресу — давал туннель для ЛЮБОЙ цели, включая 8.8.8.8
# и 192.168.1.1: полный VPN забирает маршрут по умолчанию.

def test_real_lan_wins_over_a_vpn_tunnel(monkeypatch):
    """Ровно та машина, на которой это нашли."""
    monkeypatch.setattr(remote_access, "lan_candidates", lambda: [
        ("192.168.31.214", "Ethernet"),
        ("172.18.0.1", "happ-tun"),
    ])
    assert remote_access.lan_address() == "192.168.31.214"


@pytest.mark.parametrize("adapter", [
    "happ-tun", "vEthernet (WSL)", "Docker Desktop", "VirtualBox Host-Only",
    "TAP-Windows Adapter V9", "Tailscale", "WireGuard Tunnel",
])
def test_virtual_adapters_rank_below_a_real_one(adapter):
    """Отличать приходится по ИМЕНИ: Docker живёт в 172.17–172.18, то есть в том
    же приватном диапазоне, что и роутеры."""
    real = remote_access._rank("192.168.1.5", "Ethernet")
    virtual = remote_access._rank("192.168.1.6", adapter)
    assert real < virtual


def test_home_router_range_is_preferred_over_the_docker_one():
    assert (remote_access._rank("192.168.0.10", "Ethernet")
            < remote_access._rank("172.20.0.10", "Ethernet 2"))


@pytest.mark.parametrize("address,private", [
    ("192.168.1.1", True), ("10.0.0.5", True), ("172.16.0.1", True),
    ("172.31.255.1", True), ("172.15.0.1", False), ("172.32.0.1", False),
    ("127.0.0.1", False), ("169.254.10.1", False), ("8.8.8.8", False),
    ("", False),
])
def test_only_private_addresses_are_offered(address, private):
    assert remote_access._is_private(address) is private


def test_candidates_survive_a_missing_psutil(monkeypatch):
    """Список адресов — удобство, а не обязанность: без psutil остаётся
    запасной способ, а не падение на старте."""
    import builtins
    real_import = builtins.__import__

    def _no_psutil(name, *a, **kw):
        if name == "psutil":
            raise ImportError("no psutil")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _no_psutil)
    assert remote_access.lan_candidates() == []


def test_address_family_is_compared_by_value_not_by_name():
    """Регрессия на молчаливую поломку: сравнение шло со СТРОКОЙ имени семейства,
    а в Python 3.11 у IntEnum сменился __str__ — str(socket.AF_INET) стал "2"
    вместо "AddressFamily.AF_INET". Перебор не находил НИ ОДНОГО адреса, список
    выходил пустым, и всё тихо откатывалось на тот же VPN."""
    import socket
    assert str(socket.AF_INET) != "AddressFamily.AF_INET"
    hosts = [address for address, _ in remote_access.lan_candidates()]
    assert all(remote_access._is_private(h) for h in hosts)
