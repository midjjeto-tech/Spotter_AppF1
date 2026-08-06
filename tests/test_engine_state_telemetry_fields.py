"""/api/state должен сам сообщать источник телеметрии и адрес UDP.

Экран «Настройки» рисовал 127.0.0.1 и 20777 литералами в разметке: при правке
config.py панель показывала старые значения, а про telemetry_source="iracing"
(режим без UDP F1 вообще) UI не знал ничего.
"""
import pytest

import config
import core.engine as eng_mod


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None      # без сети
    try:
        yield eng_mod.F1Engine({})
    finally:
        eng_mod.yc.load = orig


def test_state_reports_udp_endpoint_from_config(engine):
    state = engine.get_state()
    assert state["udp_ip"] == config.UDP_IP
    assert state["udp_port"] == config.UDP_PORT


def test_state_follows_config_change(engine, monkeypatch):
    """Значение читается на каждый снимок, а не запоминается при старте."""
    monkeypatch.setattr(config, "UDP_PORT", 20999)
    assert engine.get_state()["udp_port"] == 20999


def test_state_reports_telemetry_source(engine):
    assert engine.get_state()["telemetry_source"] == engine._telemetry_source


def test_iracing_source_is_visible_in_state():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        engine = eng_mod.F1Engine({"telemetry_source": "iracing"})
    finally:
        eng_mod.yc.load = orig
    state = engine.get_state()
    assert state["telemetry_source"] == "iracing"
    # Тот же режим уже выключает справочник пилотов F1 — оба поля должны быть
    # согласованы, иначе UI покажет «источник iRacing» и «метаданные загружены».
    assert state["metadata_loaded"] is False
