"""Проводка PositionCallTracker: подавление рядом с OVTK игрока, свой
пит-стоп через _maybe_announce_pit_exit, сторонние причины.
См. docs/superpowers/specs/2026-07-13-engineer-phase-a-cheap-calls-design.md.
"""
import struct
import time

import pytest

import core.engine as eng_mod
from core.engine import F1Engine, SPEAKER_ENGINEER
from core.packets import HEADER_SIZE, LAP_DATA_SIZE, PACKET_LAP_DATA
from core.strategy_ai.position_calls import SETTLE_S
from tests.telemetry import consume_f1_event_packet, consume_f1_packet


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


def _lap_buf(*, position: int, current_lap=5, pit_status=0):
    buf = bytearray(HEADER_SIZE + LAP_DATA_SIZE)
    base = HEADER_SIZE
    buf[base + 32] = position
    buf[base + 33] = current_lap
    buf[base + 34] = pit_status
    return bytes(buf)


def _ovtk_buf(*, overtaking_idx: int, being_overtaken_idx: int) -> bytes:
    buf = bytearray(HEADER_SIZE + 4 + 2)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"OVTK"
    struct.pack_into("<BB", buf, HEADER_SIZE + 4, overtaking_idx, being_overtaken_idx)
    return bytes(buf)


def test_third_party_position_change_settles_and_announces(engine, monkeypatch):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "race"
    engine._race_engineer.position_call_tracker.reset()
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    _drain(engine)

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(position=10))
    _drain(engine)
    monkeypatch.setattr(time, "time", lambda: 1001.0)
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(position=9))
    _drain(engine)   # armed, settle ещё не прошёл

    monkeypatch.setattr(time, "time", lambda: 1001.0 + SETTLE_S + 0.5)
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(position=9))
    drained = _drain(engine)
    found = [e for e in drained if e["event_code"] == "POSITION_CALL"]
    assert len(found) == 1
    assert "{position}" in found[0]["phrase"]
    assert found[0]["speaker"] == SPEAKER_ENGINEER
    engine._race_engineer.position_call_tracker.reset()
    engine._session_type = "unknown"


def test_ovtk_suppresses_position_call(engine, monkeypatch):
    """Гоняет РЕАЛЬНЫЙ OVTK-пакет через _handle_event_packet (не вызывает
    note_ovtk_involving_player напрямую) — иначе тест не проверял бы саму
    проводку (обогащение OVTK -> note_ovtk_involving_player), только логику
    трекера, уже покрытую tests/test_position_calls.py. Найдено ревью:
    удаление строки проводки в engine.py не роняло прежнюю версию теста."""
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "race"
    engine._race_engineer.position_call_tracker.reset()
    monkeypatch.setattr(time, "time", lambda: 2000.0)
    _drain(engine)

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(position=10))
    _drain(engine)

    monkeypatch.setattr(time, "time", lambda: 2000.5)
    consume_f1_event_packet(engine, _ovtk_buf(overtaking_idx=0, being_overtaken_idx=5))
    _drain(engine)   # драматическая реплика OVTK самого комментатора — не проверяем здесь

    monkeypatch.setattr(time, "time", lambda: 2001.0)
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(position=9))
    monkeypatch.setattr(time, "time", lambda: 2001.0 + SETTLE_S + 0.5)
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(position=9))
    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"] == "POSITION_CALL"]
    engine._race_engineer.position_call_tracker.reset()
    engine._session_type = "unknown"


def test_own_pit_exit_notifies_position_calls(engine, monkeypatch):
    engine._player_car_index = 0
    engine._session_type = "race"
    engine._race_engineer.position_call_tracker.reset()
    calls = []
    monkeypatch.setattr(engine._race_engineer.position_call_tracker, "note_own_pit_exit",
                         lambda pos, now: calls.append((pos, now)))

    engine._maybe_announce_pit_exit(prev_status=1, new_status=0)

    assert len(calls) == 1
    engine._session_type = "unknown"


def test_own_pit_exit_settle_routes_to_own_pit_event_code(engine, monkeypatch):
    """End-to-end (не мок): реальный _maybe_announce_pit_exit армирует
    трекер, реальный settle-цикл через LapData доводит до объявления —
    проверяем, что итоговый event_code действительно POSITION_CALL_OWN_PIT,
    а не просто что note_own_pit_exit был вызван (это уже покрыто соседним
    тестом). Найдено ревью: маршрутизация в engine.py завязана на подстроку
    "пит-стопа" в готовой фразе трекера — это должно быть покрыто end-to-end,
    а не только раздельно (юнит трекера + мок вызова)."""
    engine._player_car_index = 0
    engine._session_type = "race"
    engine.settings["engineer_chatter_enabled"] = True
    engine._race_engineer.position_call_tracker.reset()
    engine._player_pos = 9
    monkeypatch.setattr(time, "time", lambda: 3000.0)
    _drain(engine)

    engine._maybe_announce_pit_exit(prev_status=1, new_status=0)
    _drain(engine)   # PIT_EXIT сам по себе — не проверяем здесь

    monkeypatch.setattr(time, "time", lambda: 3000.0 + SETTLE_S + 0.5)
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(position=9))
    drained = _drain(engine)
    found = [e for e in drained if e["event_code"] == "POSITION_CALL_OWN_PIT"]
    assert len(found) == 1
    # Формулировка приходит из банка (position.after_pit, 4 варианта), а
    # позиция ВОЛАТИЛЬНА и подставляется перед озвучкой — здесь она ещё токен.
    assert "{position}" in found[0]["phrase"]
    engine._race_engineer.position_call_tracker.reset()
    engine._session_type = "unknown"


def test_flashback_resets_position_calls(engine, monkeypatch):
    calls = []
    monkeypatch.setattr(engine._race_engineer.position_call_tracker, "reset", lambda: calls.append(True))
    engine._handle_flashback()
    assert calls == [True]
