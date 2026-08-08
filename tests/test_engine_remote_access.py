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
    info = engine.get_remote_access_info()

    assert info["enabled"] is True
    assert info["token"] == engine.settings["remote_access_token"]
    assert info["url"].startswith("http://")
    assert info["token"] in info["url"]
    assert "127.0.0.1" not in info["url"], "адрес loopback бесполезен на телефоне"


def test_remote_info_is_empty_while_disabled(engine):
    info = engine.get_remote_access_info()
    assert info["enabled"] is False
    assert info["url"] == ""
