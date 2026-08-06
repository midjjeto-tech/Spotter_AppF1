# tests/test_engine_track_limits.py
"""Проводка TrackLimitsTracker в F1Engine: живое предупреждение по LapData +
компаньон-реплика к трек-лимитному PENA + тумблер engineer_chatter_enabled.
См. docs/superpowers/specs/2026-07-11-track-limits-engineer-toggle-design.md.
"""
import struct

import pytest

import core.engine as eng_mod
from core.engine import F1Engine, SPEAKER_ENGINEER
from core.packets import HEADER_SIZE, LAP_DATA_SIZE, PACKET_LAP_DATA
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


def _lap_buf(*, current_lap=5, pit_status=0, corner_cutting_warnings=0):
    buf = bytearray(HEADER_SIZE + LAP_DATA_SIZE)
    base = HEADER_SIZE
    buf[base + 33] = current_lap
    buf[base + 34] = pit_status
    buf[base + 40] = corner_cutting_warnings
    return bytes(buf)


def _reset_track_limits_state(engine):
    engine._race_engineer.track_limits_tracker.reset()
    engine._prev_lap = 0
    engine._current_lap_pit = False


def test_corner_cutting_increase_enqueues_engineer_warning(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    _reset_track_limits_state(engine)
    _drain(engine)

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(corner_cutting_warnings=0))
    _drain(engine)
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(corner_cutting_warnings=1))

    drained = _drain(engine)
    found = [e for e in drained if e["event_code"] == "ENGINEER_TRACK_LIMITS_WARNING"]
    assert len(found) == 1
    assert found[0]["speaker"] == SPEAKER_ENGINEER
    assert found[0]["bypass_speak_threshold"] is True
    assert found[0]["phrase"]
    _reset_track_limits_state(engine)


def test_corner_cutting_same_value_no_warning(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    _reset_track_limits_state(engine)
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(corner_cutting_warnings=1))
    _drain(engine)
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(corner_cutting_warnings=1))
    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"] == "ENGINEER_TRACK_LIMITS_WARNING"]
    _reset_track_limits_state(engine)


def test_chatter_disabled_suppresses_track_limits_warning(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = False
    _reset_track_limits_state(engine)
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(corner_cutting_warnings=0))
    _drain(engine)
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(corner_cutting_warnings=1))
    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"] == "ENGINEER_TRACK_LIMITS_WARNING"]
    engine.settings["engineer_chatter_enabled"] = True
    _reset_track_limits_state(engine)


def test_flashback_resets_track_limits_tracker(engine, monkeypatch):
    calls = []
    monkeypatch.setattr(engine._race_engineer.track_limits_tracker, "reset", lambda: calls.append(True))
    engine._handle_flashback()
    assert calls == [True]


def test_player_track_limits_pena_enqueues_companion_line(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    engine._race_engineer.track_limits_tracker.reset()
    _drain(engine)

    buf = bytearray(HEADER_SIZE + 4 + 7)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"PENA"
    # infringement_type=25 (lap invalidated corner cutting), vehicle_idx=0 (игрок)
    struct.pack_into("<BBBBBBB", buf, HEADER_SIZE + 4, 1, 25, 0, 0, 5, 12, 0)
    consume_f1_event_packet(engine, bytes(buf))

    drained = _drain(engine)
    codes = [e["event_code"] for e in drained]
    assert "ENGINEER_PENA_TRACK_LIMITS" in codes
    companion = next(e for e in drained if e["event_code"] == "ENGINEER_PENA_TRACK_LIMITS")
    assert companion["speaker"] == SPEAKER_ENGINEER
    assert companion["bypass_speak_threshold"] is True
    assert "PENA" in codes                    # обычная драматическая реплика не тронута
    engine._race_engineer.track_limits_tracker.reset()


def test_pena_not_track_limits_no_companion_line(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    engine._race_engineer.track_limits_tracker.reset()
    _drain(engine)

    buf = bytearray(HEADER_SIZE + 4 + 7)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"PENA"
    # infringement_type=3 (Big Collision) — не трек-лимиты
    struct.pack_into("<BBBBBBB", buf, HEADER_SIZE + 4, 1, 3, 0, 0, 5, 12, 0)
    consume_f1_event_packet(engine, bytes(buf))

    drained = _drain(engine)
    codes = [e["event_code"] for e in drained]
    assert "ENGINEER_PENA_TRACK_LIMITS" not in codes
    assert "PENA" in codes
    engine._race_engineer.track_limits_tracker.reset()


def test_opponent_track_limits_pena_no_companion_line(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    engine._race_engineer.track_limits_tracker.reset()
    _drain(engine)

    buf = bytearray(HEADER_SIZE + 4 + 7)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"PENA"
    # vehicle_idx=7 (не игрок, у которого _player_car_index=0)
    struct.pack_into("<BBBBBBB", buf, HEADER_SIZE + 4, 1, 25, 7, 0, 5, 12, 0)
    consume_f1_event_packet(engine, bytes(buf))

    drained = _drain(engine)
    codes = [e["event_code"] for e in drained]
    assert "ENGINEER_PENA_TRACK_LIMITS" not in codes
    engine._race_engineer.track_limits_tracker.reset()


def test_track_limits_pena_suppresses_live_warning_same_window(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    _reset_track_limits_state(engine)
    _drain(engine)

    # Живой рост счётчика на 1
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(corner_cutting_warnings=0))
    _drain(engine)

    # Трек-лимитный PENA игрока — открывает окно подавления
    buf = bytearray(HEADER_SIZE + 4 + 7)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"PENA"
    struct.pack_into("<BBBBBBB", buf, HEADER_SIZE + 4, 1, 25, 0, 0, 5, 12, 0)
    consume_f1_event_packet(engine, bytes(buf))
    _drain(engine)

    # Следующий тик счётчика в ту же секунду — живое предупреждение подавлено
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(corner_cutting_warnings=1))
    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"] == "ENGINEER_TRACK_LIMITS_WARNING"]
    _reset_track_limits_state(engine)


def test_chatter_disabled_suppresses_pena_companion_but_not_pena(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = False
    engine._race_engineer.track_limits_tracker.reset()
    _drain(engine)

    buf = bytearray(HEADER_SIZE + 4 + 7)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"PENA"
    struct.pack_into("<BBBBBBB", buf, HEADER_SIZE + 4, 1, 25, 0, 0, 5, 12, 0)
    consume_f1_event_packet(engine, bytes(buf))

    drained = _drain(engine)
    codes = [e["event_code"] for e in drained]
    assert "ENGINEER_PENA_TRACK_LIMITS" not in codes
    assert "PENA" in codes                    # штраф всё равно объявляется
    engine.settings["engineer_chatter_enabled"] = True
    engine._race_engineer.track_limits_tracker.reset()


def test_note_penalty_recorded_even_when_chatter_disabled(engine):
    """note_penalty() вызывается БЕЗУСЛОВНО, даже когда тумблер выключен —
    иначе включение тумблера сразу после трек-лимитного штрафа (пока тот же
    инцидент ещё "свежий") ошибочно озвучило бы живое предупреждение про уже
    объявленный штраф. Отличаем это от "теговый живого предупреждения тоже
    гейтуется тумблером" тем, что тумблер включается ОБРАТНО до живого тика —
    единственная причина подавления в этот момент может быть только
    suppression window, не сам тумблер."""
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = False
    engine._race_engineer.track_limits_tracker.reset()
    _drain(engine)

    buf = bytearray(HEADER_SIZE + 4 + 7)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"PENA"
    struct.pack_into("<BBBBBBB", buf, HEADER_SIZE + 4, 1, 25, 0, 0, 5, 12, 0)
    consume_f1_event_packet(engine, bytes(buf))
    _drain(engine)

    engine.settings["engineer_chatter_enabled"] = True   # включаем ДО живого тика
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(corner_cutting_warnings=1))
    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"] == "ENGINEER_TRACK_LIMITS_WARNING"]
    engine._race_engineer.track_limits_tracker.reset()


def test_live_warning_then_pena_suppresses_companion_reverse_order(engine):
    """Обратный порядок пакетов (найдено финальным сквозным ревью): если
    LapData-тик с ростом счётчика обработан РАНЬШЕ PENA того же инцидента,
    компаньон-реплика PENA не должна дублировать уже прозвучавшее живое
    предупреждение. Симметрично test_track_limits_pena_suppresses_live_warning_same_window,
    который проверяет только прямой порядок (PENA раньше живого тика)."""
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    _reset_track_limits_state(engine)
    _drain(engine)

    # Живое предупреждение — счётчик растёт с 0 до 1
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(corner_cutting_warnings=0))
    _drain(engine)
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(corner_cutting_warnings=1))
    drained = _drain(engine)
    assert any(e["event_code"] == "ENGINEER_TRACK_LIMITS_WARNING" for e in drained)

    # Тот же инцидент чуть позже конвертируется в PENA — компаньон подавлен
    buf = bytearray(HEADER_SIZE + 4 + 7)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"PENA"
    struct.pack_into("<BBBBBBB", buf, HEADER_SIZE + 4, 1, 25, 0, 0, 5, 12, 0)
    consume_f1_event_packet(engine, bytes(buf))
    drained = _drain(engine)
    codes = [e["event_code"] for e in drained]
    assert "ENGINEER_PENA_TRACK_LIMITS" not in codes
    assert "PENA" in codes                    # штраф всё равно объявляется
    _reset_track_limits_state(engine)
