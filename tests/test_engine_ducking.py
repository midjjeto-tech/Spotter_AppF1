"""Подключение приглушения игры к движку.

Проверяется, что тумблер реально управляет звуком, а не только пишется в
настройки: голос про настройки ничего не знает, ducker ему ставит движок.
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


def test_ducker_is_absent_while_the_setting_is_off(engine):
    engine.apply_settings({"game_ducking_enabled": False})
    assert engine.voice.game_ducker is None


def test_enabling_the_setting_attaches_a_ducker(engine):
    engine.apply_settings({"game_ducking_enabled": True})
    assert engine.voice.game_ducker is not None


def test_disabling_releases_a_held_duck(engine):
    """Выключить тумблер посреди реплики нельзя так, чтобы игра осталась
    тихой."""
    engine.apply_settings({"game_ducking_enabled": True})
    ducker = engine.voice.game_ducker

    class _S:
        process_name = "F1_25.exe"
        volume = 1.0

    session = _S()
    ducker._backend = type("B", (), {"sessions": staticmethod(lambda: [session])})()
    ducker.set_busy(True)
    assert session.volume < 1.0

    engine.apply_settings({"game_ducking_enabled": False})

    assert session.volume == pytest.approx(1.0)
    assert engine.voice.game_ducker is None


def test_level_change_is_applied_to_the_live_ducker(engine):
    engine.apply_settings({"game_ducking_enabled": True, "game_ducking_level": 20})
    assert engine.voice.game_ducker._level == pytest.approx(0.20)

    engine.apply_settings({"game_ducking_level": 50})
    assert engine.voice.game_ducker._level == pytest.approx(0.50)


def test_ducker_is_attached_at_boot_when_the_setting_is_on():
    """Включённый тумблер обязан работать сразу после запуска, а не после
    первого захода в настройки."""
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        engine = F1Engine({"game_ducking_enabled": True})
        assert engine.voice.game_ducker is not None
    finally:
        eng_mod.yc.load = orig
