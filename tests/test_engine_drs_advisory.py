"""Проводка DRSAdvisoryTracker в F1Engine: обе ветки _update_telemetry
(LapData и CarStatus) вызывают update() с последними известными значениями.
См. docs/superpowers/specs/2026-07-13-engineer-phase-a-cheap-calls-design.md.
"""
import struct

import pytest

import core.engine as eng_mod
from core.engine import F1Engine, SPEAKER_ENGINEER
from core.packets import HEADER_SIZE, CAR_STATUS_SIZE, LAP_DATA_SIZE, PACKET_CAR_STATUS, PACKET_LAP_DATA
from tests.telemetry import consume_f1_packet


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _drain(engine):
    drained = []
    while not engine._commentary_events.empty():
        drained.append(engine._commentary_events.get_nowait())
    return drained


def _reset_drs_state(engine):
    """engine — module-scoped fixture, общая для всех тестов файла.
    _drs_advisory.reset() чистит только внутреннее состояние трекера, не
    сырые атрибуты движка, которые трекер читает на следующем тике — без
    явного сброса и этих атрибутов тесты неявно зависели бы от порядка
    выполнения (найдено ревью)."""
    engine._race_engineer.drs_advisory_tracker.reset()
    engine._player_gap_front = None
    engine._player_drs_allowed = None


def _lap_buf_with_gap(gap_ms: int) -> bytes:
    buf = bytearray(HEADER_SIZE + LAP_DATA_SIZE)
    base = HEADER_SIZE
    buf[base + 33] = 5   # current_lap
    ms_part = gap_ms % 60000
    minutes = gap_ms // 60000
    struct.pack_into("<H", buf, base + 14, ms_part)
    buf[base + 16] = minutes
    return bytes(buf)


def _status_buf_with_drs(allowed: int) -> bytes:
    buf = bytearray(HEADER_SIZE + CAR_STATUS_SIZE)
    base = HEADER_SIZE
    buf[base + 22] = allowed
    return bytes(buf)


def test_lap_data_tick_calls_drs_advisory_update(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    _reset_drs_state(engine)
    _drain(engine)

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf_with_gap(1500))   # baseline: далеко
    _drain(engine)
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf_with_gap(800))    # вошёл в зону

    drained = _drain(engine)
    found = [e for e in drained if e["event_code"] in
             ("DRS_PROXIMITY_ENTER", "DRS_PROXIMITY_ENTER_AND_ALLOWED")]
    assert len(found) == 1
    assert found[0]["speaker"] == SPEAKER_ENGINEER
    assert found[0]["bypass_speak_threshold"] is True
    _reset_drs_state(engine)


def test_car_status_tick_calls_drs_advisory_update(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    _reset_drs_state(engine)
    _drain(engine)

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_CAR_STATUS,
                             _status_buf_with_drs(0))
    _drain(engine)
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_CAR_STATUS,
                             _status_buf_with_drs(1))

    drained = _drain(engine)
    codes = [e["event_code"] for e in drained]
    assert "DRS_ALLOWED_ON" in codes
    _reset_drs_state(engine)


def test_chatter_disabled_suppresses_drs_events(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = False
    _reset_drs_state(engine)
    _drain(engine)

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_CAR_STATUS,
                             _status_buf_with_drs(0))
    _drain(engine)
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_CAR_STATUS,
                             _status_buf_with_drs(1))

    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"] == "DRS_ALLOWED_ON"]
    engine.settings["engineer_chatter_enabled"] = True
    _reset_drs_state(engine)


def test_leader_gap_zero_does_not_trigger_false_proximity(engine):
    """Найдено ревью: gap_front_ms==0 у лидера (машины впереди нет) — это
    сырое значение телеметрии "нет цели", НЕ "0 мс до соперника". Без фильтра
    в _drs_advisory_tick лидер получил бы абсурдную "Ты в зоне DRS, атакуй!"
    сразу как только DRS будет разрешена — тот же класс gotcha, что уже
    обходят gap_digest.py/situation_dedup.py для этого поля."""
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    _reset_drs_state(engine)
    _drain(engine)

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf_with_gap(0))   # лидер: нет машины впереди
    _drain(engine)
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_CAR_STATUS,
                             _status_buf_with_drs(1))   # DRS разрешена

    drained = _drain(engine)
    codes = [e["event_code"] for e in drained]
    assert "DRS_PROXIMITY_ENTER_AND_ALLOWED" not in codes
    assert "DRS_PROXIMITY_ENTER" not in codes
    # DRS_ALLOWED_ON — законный edge-trigger сам по себе, лидеру он тоже
    # может звучать (сессионный факт, не завязан на гэп) — не проверяем его
    # отсутствие, только что composite/proximity-код не всплыл ложно.
    _reset_drs_state(engine)


def test_flashback_resets_drs_advisory(engine, monkeypatch):
    calls = []
    monkeypatch.setattr(engine._race_engineer.drs_advisory_tracker, "reset", lambda: calls.append(True))
    engine._handle_flashback()
    assert calls == [True]
