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
from core.telemetry_adapters import TelemetryRaceEvent
from tests.telemetry import consume_f1_event_packet, consume_f1_packet


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


@pytest.fixture(autouse=True)
def _fresh_raw_event_timeline(engine):
    """Each test models a separate session despite the module-scoped engine."""
    engine._raw_event_seen.clear()
    getattr(engine, "_raw_event_source_seen", set()).clear()
    engine._raw_event_source_session_id = None
    yield
    engine._raw_event_seen.clear()
    getattr(engine, "_raw_event_source_seen", set()).clear()
    engine._raw_event_source_session_id = None


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


def test_warning_packet_is_not_counted_or_announced_as_a_penalty(engine):
    """EA PenaltyType=5 is a warning, despite arriving under event code PENA."""
    engine._player_car_index = 0
    engine._player_penalty_count = 0
    engine._player_penalty_seconds = 0
    _drain(engine)

    buf = bytearray(HEADER_SIZE + 4 + 7)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"PENA"
    struct.pack_into("<BBBBBBB", buf, HEADER_SIZE + 4,
                     5, 28, 0, 0, 0, 4, 0)
    consume_f1_event_packet(engine, bytes(buf))

    codes = [event["event_code"] for event in _drain(engine)]
    assert "PENA" not in codes
    assert "ENGINEER_PENA_TRACK_LIMITS" not in codes
    assert engine._player_penalty_count == 0
    assert engine._player_penalty_seconds == 0


def test_identical_replayed_penalty_packet_is_counted_once(engine):
    engine._player_car_index = 0
    engine._player_penalty_count = 0
    _drain(engine)

    buf = bytearray(HEADER_SIZE + 4 + 7)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"PENA"
    struct.pack_into("<BBBBBBB", buf, HEADER_SIZE + 4,
                     4, 28, 0, 0, 5, 4, 0)
    consume_f1_event_packet(engine, bytes(buf))
    consume_f1_event_packet(engine, bytes(buf))

    codes = [event["event_code"] for event in _drain(engine)]
    assert codes.count("PENA") == 1
    assert engine._player_penalty_count == 1


def _penalty_event(*, penalty_type=4, infringement_type=28):
    return {
        "event_code": "PENA",
        "penalty_type": penalty_type,
        "infringement_type": infringement_type,
        "vehicle_idx": 0,
        "other_vehicle_idx": 0,
        "time_seconds": 5,
        "lap_num": 4,
        "places_gained": 0,
    }


def test_exact_source_event_is_suppressed_for_the_whole_session(engine, monkeypatch):
    engine._player_car_index = 0
    engine._player_penalty_count = 0
    now = [0.0]
    monkeypatch.setattr(eng_mod.time, "monotonic", lambda: now[0])
    message = TelemetryRaceEvent(
        _penalty_event(),
        source_session_id=9001,
        source_event_id=123,
        source_frame_id=100,
        source_time_s=8.0,
    )

    engine._consume_telemetry_message(message)
    now[0] = 60.0  # well beyond the old ten-second PENA TTL
    engine._consume_telemetry_message(message)

    assert engine._player_penalty_count == 1


def test_same_frame_can_carry_distinct_source_events(engine, monkeypatch):
    engine._player_car_index = 0
    engine._player_penalty_count = 0
    now = [0.0]
    monkeypatch.setattr(eng_mod.time, "monotonic", lambda: now[0])

    engine._consume_telemetry_message(TelemetryRaceEvent(
        _penalty_event(penalty_type=4),
        source_session_id=9002,
        source_event_id=456,
    ))
    engine._consume_telemetry_message(TelemetryRaceEvent(
        _penalty_event(penalty_type=2),
        source_session_id=9002,
        source_event_id=456,
    ))

    assert engine._player_penalty_count == 2


def test_same_source_identity_is_new_again_in_the_next_session(engine, monkeypatch):
    engine._player_car_index = 0
    engine._player_penalty_count = 0
    now = [0.0]
    monkeypatch.setattr(eng_mod.time, "monotonic", lambda: now[0])

    for session_id in (9003, 9004):
        engine._consume_telemetry_message(TelemetryRaceEvent(
            _penalty_event(),
            source_session_id=session_id,
            source_event_id=456,
        ))
        now[0] += 1.0

    assert engine._player_penalty_count == 2


def test_warning_is_traced_once_even_though_it_is_not_a_sanction(engine, monkeypatch):
    recorded = []
    monkeypatch.setattr(
        engine.recorder,
        "record_event",
        lambda event, **identity: recorded.append((dict(event), identity)),
    )
    warning = TelemetryRaceEvent(
        _penalty_event(penalty_type=5),
        source_session_id=9005,
        source_event_id=789,
        source_frame_id=700,
        source_time_s=9.5,
    )

    engine._consume_telemetry_message(warning)
    engine._consume_telemetry_message(warning)

    assert len(recorded) == 1
    assert recorded[0][0]["penalty_type"] == 5
    assert recorded[0][1]["source_event_id"] == 789


def test_semantic_replay_window_slides_until_packets_go_quiet(engine, monkeypatch):
    engine._player_car_index = 0
    engine._player_penalty_count = 0
    now = [0.0]
    monkeypatch.setattr(eng_mod.time, "monotonic", lambda: now[0])
    event = _penalty_event()

    for observed_at in (0.0, 9.0, 18.0, 27.0):
        now[0] = observed_at
        engine._handle_race_event(dict(event))

    assert engine._player_penalty_count == 1

    now[0] = 38.0  # a real identical event is allowed after a quiet TTL
    engine._handle_race_event(dict(event))
    assert engine._player_penalty_count == 2
