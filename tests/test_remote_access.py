"""Политика доступа к локальному API извне (core/remote_access.py).

Сервер отдаёт не только состояние гонки: через него МЕНЯЮТ настройки и ЗАПИСЫВАЮТ
ключи Yandex и GigaChat. Поэтому «второй экран на телефоне» — это не смена
адреса привязки, а отдельная политика, и почти все тесты ниже про то, что
именно она обязана НЕ пускать.
"""
import pytest

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
