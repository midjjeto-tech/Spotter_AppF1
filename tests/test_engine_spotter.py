"""Проводка SpotterTracker в F1Engine: PACKET_MOTION -> _spotter_tick,
дешёвый фильтр по lap_distance (self._lap_distances, из PACKET_LAP_DATA)
отсекает дальние машины ДО геометрии, событие НЕ гейтуется
engineer_chatter_enabled (решение пользователя — безопасность, не болтовня).
См. docs/superpowers/specs/2026-07-18-real-spotter-motion-design.md.
"""
import struct

import pytest

import core.engine as eng_mod
from core.engine import F1Engine, SPEAKER_ENGINEER
from core.packets import HEADER_SIZE, MOTION_SIZE, LAP_DATA_SIZE, PACKET_LAP_DATA
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


def _lap_buf_with_distance(distances: dict[int, float]) -> bytes:
    buf = bytearray(HEADER_SIZE + 22 * LAP_DATA_SIZE)
    for idx, dist in distances.items():
        base = HEADER_SIZE + idx * LAP_DATA_SIZE
        struct.pack_into("<f", buf, base + 20, dist)
    return bytes(buf)


def _motion_buf(cars: dict[int, tuple[float, float, float, float]]) -> bytes:
    """cars: {idx: (world_x, world_z, right_x, right_z)} — right_* в диапазоне
    -1..1, конвертируется в int16 как в реальном пакете."""
    n = max(cars.keys()) + 1 if cars else 1
    buf = bytearray(HEADER_SIZE + n * MOTION_SIZE)
    for idx, (wx, wz, rx, rz) in cars.items():
        base = HEADER_SIZE + idx * MOTION_SIZE
        struct.pack_into("<f", buf, base + 0, wx)
        struct.pack_into("<f", buf, base + 8, wz)
        struct.pack_into("<h", buf, base + 30, int(rx * 32767))
        struct.pack_into("<h", buf, base + 34, int(rz * 32767))
    return bytes(buf)


def test_close_car_on_right_produces_spotter_event(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    engine._race_engineer.spotter_tracker.reset()
    _drain(engine)

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf_with_distance({0: 100.0, 1: 101.0}))
    _drain(engine)

    # Игрок смотрит вдоль +Z (right = +X), соперник на +2м по X -> справа.
    from core.packets import parse_motion_all
    motion = _motion_buf({0: (0.0, 0.0, 1.0, 0.0), 1: (2.0, 0.0, 0.0, 0.0)})
    engine._spotter_tick(parse_motion_all(motion))

    drained = _drain(engine)
    found = [e for e in drained if e["event_code"] == "SPOTTER_CAR_RIGHT"]
    assert len(found) == 1
    assert found[0]["speaker"] == SPEAKER_ENGINEER
    assert found[0]["bypass_speak_threshold"] is True
    assert found[0]["priority"] == "critical"
    assert found[0]["importance"] >= 90
    engine._race_engineer.spotter_tracker.reset()


def test_far_car_by_lap_distance_is_filtered_out_before_geometry(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    engine._race_engineer.spotter_tracker.reset()
    _drain(engine)

    # 50м по lap_distance — далеко за LONGITUDINAL_WINDOW_M, даже если по
    # мировым координатам эта машина оказалась бы геометрически "рядом".
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf_with_distance({0: 100.0, 1: 150.0}))
    _drain(engine)

    motion = _motion_buf({0: (0.0, 0.0, 1.0, 0.0), 1: (2.0, 0.0, 0.0, 0.0)})
    from core.packets import parse_motion_all
    engine._spotter_tick(parse_motion_all(motion))

    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"].startswith("SPOTTER_")]
    engine._race_engineer.spotter_tracker.reset()


def test_chatter_disabled_does_not_suppress_spotter_event(engine):
    """Решение пользователя 2026-07-18: споттер — безопасность, не болтовня,
    как PENA/box-call. engineer_chatter_enabled=False НЕ должен гасить его."""
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = False
    engine._race_engineer.spotter_tracker.reset()
    _drain(engine)

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf_with_distance({0: 100.0, 1: 101.0}))
    _drain(engine)

    from core.packets import parse_motion_all
    motion = _motion_buf({0: (0.0, 0.0, 1.0, 0.0), 1: (2.0, 0.0, 0.0, 0.0)})
    engine._spotter_tick(parse_motion_all(motion))

    drained = _drain(engine)
    assert [e for e in drained if e["event_code"] == "SPOTTER_CAR_RIGHT"]
    engine.settings["engineer_chatter_enabled"] = True
    engine._race_engineer.spotter_tracker.reset()


def test_no_player_in_motion_packet_is_noop(engine):
    engine._player_car_index = 5
    engine._race_engineer.spotter_tracker.reset()
    _drain(engine)

    from core.packets import parse_motion_all
    motion = _motion_buf({0: (0.0, 0.0, 1.0, 0.0)})   # индекс 5 отсутствует
    engine._spotter_tick(parse_motion_all(motion))

    assert _drain(engine) == []
    engine._player_car_index = 0


def test_flashback_resets_spotter(engine, monkeypatch):
    calls = []
    monkeypatch.setattr(engine._race_engineer.spotter_tracker, "reset", lambda: calls.append(True))
    engine._handle_flashback()
    assert calls == [True]


def test_radar_captures_car_within_wide_window_with_signed_direction(engine):
    engine._player_car_index = 0
    engine._race_engineer.spotter_tracker.reset()
    _drain(engine)

    # 20м по lap_distance — за пределами LONGITUDINAL_WINDOW_M (6м, голосовой
    # споттер должен молчать), но внутри RADAR_WINDOW_M (25м) — радар должен
    # это увидеть.
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf_with_distance({0: 100.0, 1: 120.0}))
    _drain(engine)

    from core.packets import parse_motion_all
    motion = _motion_buf({0: (0.0, 0.0, 1.0, 0.0), 1: (2.0, 0.0, 0.0, 0.0)})
    engine._spotter_tick(parse_motion_all(motion))

    # Голосовой споттер молчит (вне его узкого окна) — существующее поведение.
    assert not [e for e in _drain(engine) if e["event_code"].startswith("SPOTTER_")]

    # Радар видит машину: она впереди (120 > 100) и справа (совпадает с
    # существующим геометрическим тестом test_close_car_on_right_produces_spotter_event).
    assert len(engine._radar) == 1
    contact = engine._radar[0]
    assert contact["vehicle_idx"] == 1
    assert contact["side"] == "right"
    assert contact["longitudinal_m"] == pytest.approx(20.0)
    assert contact["lateral_m"] == pytest.approx(2.0)
    engine._race_engineer.spotter_tracker.reset()


def test_radar_excludes_car_beyond_radar_window(engine):
    engine._player_car_index = 0
    engine._race_engineer.spotter_tracker.reset()
    _drain(engine)

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf_with_distance({0: 100.0, 1: 200.0}))
    _drain(engine)

    from core.packets import parse_motion_all
    motion = _motion_buf({0: (0.0, 0.0, 1.0, 0.0), 1: (2.0, 0.0, 0.0, 0.0)})
    engine._spotter_tick(parse_motion_all(motion))

    assert engine._radar == []
    engine._race_engineer.spotter_tracker.reset()


def test_radar_does_not_change_existing_voice_spotter_candidates(engine):
    # Регрессия: широкий радар-проход не должен подсунуть более широкий набор
    # кандидатов в SpotterTracker (узкое окно голосового споттера — отдельное).
    engine._player_car_index = 0
    engine._race_engineer.spotter_tracker.reset()
    _drain(engine)

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf_with_distance({0: 100.0, 1: 150.0}))
    _drain(engine)

    from core.packets import parse_motion_all
    motion = _motion_buf({0: (0.0, 0.0, 1.0, 0.0), 1: (2.0, 0.0, 0.0, 0.0)})
    engine._spotter_tick(parse_motion_all(motion))

    assert not [e for e in _drain(engine) if e["event_code"].startswith("SPOTTER_")]
    assert engine._radar == []  # тоже вне RADAR_WINDOW_M (25м) — 50м разница
    engine._race_engineer.spotter_tracker.reset()


def test_radar_and_voice_spotter_both_populated_from_same_tick_with_different_cars(engine):
    engine._player_car_index = 0
    engine._race_engineer.spotter_tracker.reset()
    _drain(engine)

    # Car 1: 2м по lap_distance — внутри LONGITUDINAL_WINDOW_M (6м), должна
    # звучать голосом. Car 2: 20м — только в широком радаре.
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf_with_distance({0: 100.0, 1: 102.0, 2: 120.0}))
    _drain(engine)

    from core.packets import parse_motion_all
    motion = _motion_buf({
        0: (0.0, 0.0, 1.0, 0.0),
        1: (2.0, 0.0, 0.0, 0.0),
        2: (2.0, 0.0, 0.0, 0.0),
    })
    engine._spotter_tick(parse_motion_all(motion))

    drained = _drain(engine)
    voiced = [e for e in drained if e["event_code"] == "SPOTTER_CAR_RIGHT"]
    assert len(voiced) == 1

    radar_indices = {c["vehicle_idx"] for c in engine._radar}
    assert radar_indices == {1, 2}
    engine._race_engineer.spotter_tracker.reset()


def test_get_overlay_state_exposes_radar(engine):
    engine._player_car_index = 0
    engine._radar = [{"vehicle_idx": 1, "side": "left", "lateral_m": 2.0, "longitudinal_m": -3.0}]

    overlay = engine.get_overlay_state()

    assert overlay["radar"] == [{"vehicle_idx": 1, "side": "left", "lateral_m": 2.0, "longitudinal_m": -3.0}]
    engine._radar = []
