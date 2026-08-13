"""Включение второго экрана в движке: генерация токена и адрес доступа.

Токен обязан появляться при включении и НЕ меняться при последующих правках —
иначе адрес на телефоне протухал бы после каждого касания настроек.
"""
import pytest

import core.engine as eng_mod
from core.engine import F1Engine


@pytest.fixture
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def test_enabling_generates_a_token(engine):
    engine.apply_settings({"remote_access_enabled": True})
    assert len(engine.settings["remote_access_token"]) >= 24


def test_token_is_stable_across_further_changes(engine):
    engine.apply_settings({"remote_access_enabled": True})
    token = engine.settings["remote_access_token"]

    engine.apply_settings({"volume": 70})
    engine.apply_settings({"remote_access_enabled": True})

    assert engine.settings["remote_access_token"] == token


def test_disabling_keeps_the_token_for_next_time(engine):
    """Выключение — это не отзыв доступа навсегда: включив снова, пользователь
    ждёт тот же адрес."""
    engine.apply_settings({"remote_access_enabled": True})
    token = engine.settings["remote_access_token"]

    engine.apply_settings({"remote_access_enabled": False})

    assert engine.settings["remote_access_token"] == token


def test_no_token_is_generated_while_the_feature_is_off(engine):
    engine.apply_settings({"volume": 70})
    assert engine.settings.get("remote_access_token", "") == ""


def test_remote_url_contains_a_lan_address_and_the_token(engine):
    engine.apply_settings({"remote_access_enabled": True})
    engine.set_bound_host("0.0.0.0")   # сокет реально открыт наружу
    info = engine.get_remote_access_info()

    assert info["enabled"] is True
    assert info["restart_required"] is False
    assert info["token"] == engine.settings["remote_access_token"]
    assert info["url"].startswith("http://")
    assert info["token"] in info["url"]
    assert "127.0.0.1" not in info["url"], "адрес loopback бесполезен на телефоне"


def test_remote_url_leads_to_the_phone_screen(engine):
    """Ссылка ведёт на телефонный экран, а не на десктопный корень.

    Десктопная вёрстка на телефоне непригодна замеряно: сайдбар `w-60` не
    сжимается, и при 375px на контент остаётся 87 пикселей. Отправить туда
    пользователя — вернуть ровно ту жалобу, из-за которой экран и появился."""
    engine.apply_settings({"remote_access_enabled": True})
    engine.set_bound_host("0.0.0.0")

    assert "/phone.html?token=" in engine.get_remote_access_info()["url"]


def test_no_url_until_the_socket_is_actually_open_to_the_network(engine):
    """Случай из живой проверки: настройку включили на РАБОТАЮЩЕМ приложении.

    Привязка выбирается один раз на старте, поэтому порт остался на 127.0.0.1 —
    а панель показывала бодрую ссылку, которая давала ERR_CONNECTION_REFUSED и с
    телефона, и с самого ПК. Пустой url — сигнал для UI: он на него показывает
    «адрес появится после перезапуска» (эта ветка в settings.tsx уже была, просто
    движок никогда её не включал)."""
    engine.apply_settings({"remote_access_enabled": True})
    engine.set_bound_host("127.0.0.1")

    info = engine.get_remote_access_info()

    assert info["enabled"] is True
    assert info["restart_required"] is True
    assert info["url"] == ""
    assert info["token"], "токен остаётся: он не протухает от перезапуска"


def test_a_never_started_server_is_treated_as_not_open(engine):
    """Про привязку ещё ничего не известно — обещать работающий адрес авансом мы
    уже пробовали."""
    engine.apply_settings({"remote_access_enabled": True})

    assert engine.get_remote_access_info()["restart_required"] is True


def test_all_machine_addresses_are_offered(engine):
    """Один адрес — это гадание. На машине с VPN их несколько, и какой из них
    видит телефон, приложение знать не может: пусть выбирает пользователь."""
    engine.apply_settings({"remote_access_enabled": True})
    engine.set_bound_host("0.0.0.0")

    candidates = engine.get_remote_access_info()["candidates"]

    assert isinstance(candidates, list)
    for item in candidates:
        assert set(item) == {"host", "adapter"}


def test_remote_info_is_empty_while_disabled(engine):
    info = engine.get_remote_access_info()
    assert info["enabled"] is False
    assert info["url"] == ""
