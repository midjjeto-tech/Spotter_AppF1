"""Проводка LeaderChangeTracker: смена _leader_idx доходит до трекера,
debounce 2с, только race.
См. docs/superpowers/specs/2026-07-13-engineer-phase-a-cheap-calls-design.md.
"""
import time

import pytest

import core.engine as eng_mod
from core.engine import F1Engine, SPEAKER_ENGINEER
from core.packets import HEADER_SIZE, LAP_DATA_SIZE, PACKET_LAP_DATA
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


def _grid_buf_with_leader(leader_vehicle_idx: int) -> bytes:
    """22-слотовый LapData-буфер: ровно один car_idx с m_carPosition==1
    (лидер), остальные — P2..P22 по порядку слота."""
    buf = bytearray(HEADER_SIZE + 22 * LAP_DATA_SIZE)
    positions = [p for p in range(2, 23)]
    pos_iter = iter(positions)
    for idx in range(22):
        base = HEADER_SIZE + idx * LAP_DATA_SIZE
        pos = 1 if idx == leader_vehicle_idx else next(pos_iter)
        buf[base + 32] = pos
        buf[base + 33] = 5   # current_lap
    return bytes(buf)


def test_lap_data_tick_calls_leader_change_tick(engine, monkeypatch):
    """Сквозной тест проводки: _update_telemetry с реальным LapData-буфером
    доходит до _leader_change_tick(), не просто вызов метода напрямую."""
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "race"
    engine._race_engineer.leader_change_tracker.reset()
    _drain(engine)

    monkeypatch.setattr(time, "time", lambda: 7000.0)
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _grid_buf_with_leader(3))     # базовая линия: лидер idx=3
    _drain(engine)

    monkeypatch.setattr(time, "time", lambda: 7001.0)
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _grid_buf_with_leader(7))     # смена лидера на idx=7
    _drain(engine)   # pending, debounce не истёк

    monkeypatch.setattr(time, "time", lambda: 7001.0 + 2.1)
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _grid_buf_with_leader(7))     # держится >=2с
    drained = _drain(engine)
    found = [e for e in drained if e["event_code"] == "LEADER_CHANGE"]
    assert len(found) == 1
    assert found[0]["speaker"] == SPEAKER_ENGINEER
    engine._race_engineer.leader_change_tracker.reset()
    engine._session_type = "unknown"


def test_leader_change_announced_after_debounce(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "race"
    engine._race_engineer.leader_change_tracker.reset()
    _drain(engine)

    monkeypatch.setattr(time, "time", lambda: 5000.0)
    engine._leader_idx = 3
    engine._leader_change_tick()
    _drain(engine)

    monkeypatch.setattr(time, "time", lambda: 5001.0)
    engine._leader_idx = 7
    engine._leader_change_tick()
    _drain(engine)   # pending, debounce не истёк

    monkeypatch.setattr(time, "time", lambda: 5001.0 + 2.1)
    engine._leader_change_tick()
    drained = _drain(engine)
    found = [e for e in drained if e["event_code"] == "LEADER_CHANGE"]
    assert len(found) == 1
    assert found[0]["speaker"] == SPEAKER_ENGINEER
    engine._race_engineer.leader_change_tracker.reset()
    engine._session_type = "unknown"


def test_leader_change_suppressed_when_player_becomes_leader(engine, monkeypatch):
    """Найдено финальным сквозным ревью Фазы A: если новый лидер — сам игрок
    (например, унаследовал P1 после схода/пит-стопа прежнего лидера, без
    OVTK), LEADER_CHANGE звучал бы третьим лицом («Новый лидер гонки —
    {имя игрока}.») ОДНОВРЕМЕННО с уже существующим PositionCallTracker
    («Теперь ты P1.») — избыточная, странно звучащая пара реплик об одном и
    том же факте. LEADER_CHANGE для этого случая подавляется полностью;
    смену позиции на P1 уже озвучивает POSITION_CALL."""
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "race"
    engine._race_engineer.leader_change_tracker.reset()
    _drain(engine)

    monkeypatch.setattr(time, "time", lambda: 8000.0)
    engine._leader_idx = 3
    engine._leader_change_tick()
    _drain(engine)

    monkeypatch.setattr(time, "time", lambda: 8001.0)
    engine._leader_idx = 0   # игрок унаследовал лидерство
    engine._leader_change_tick()
    _drain(engine)

    monkeypatch.setattr(time, "time", lambda: 8001.0 + 2.1)
    engine._leader_change_tick()
    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"] == "LEADER_CHANGE"]
    engine._race_engineer.leader_change_tracker.reset()
    engine._session_type = "unknown"


def test_leader_change_gated_outside_race(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "qualifying"
    engine._race_engineer.leader_change_tracker.reset()
    _drain(engine)

    monkeypatch.setattr(time, "time", lambda: 6000.0)
    engine._leader_idx = 3
    engine._leader_change_tick()
    monkeypatch.setattr(time, "time", lambda: 6001.0)
    engine._leader_idx = 7
    engine._leader_change_tick()
    monkeypatch.setattr(time, "time", lambda: 6001.0 + 2.1)
    engine._leader_change_tick()

    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"] == "LEADER_CHANGE"]
    engine._race_engineer.leader_change_tracker.reset()
    engine._session_type = "unknown"


def test_flashback_resets_leader_change(engine, monkeypatch):
    calls = []
    monkeypatch.setattr(engine._race_engineer.leader_change_tracker, "reset", lambda: calls.append(True))
    engine._handle_flashback()
    assert calls == [True]
