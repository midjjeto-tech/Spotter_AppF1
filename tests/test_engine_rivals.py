"""tests/test_engine_rivals.py — engine wiring for opponent tyre-age/mistake
detection (design spec 2026-07-07-rival-mistake-tyre-freshness)."""
import struct
import time

import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.packets import (
    HEADER_SIZE, LAP_DATA_SIZE, CAR_STATUS_SIZE,
    PACKET_LAP_DATA, PACKET_CAR_STATUS, PACKET_CAR_DAMAGE,
)
from core.rivals.tracker import RivalTracker
from tests.telemetry import consume_f1_packet


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _lap_buf_multi(cars: dict[int, dict]) -> bytes:
    buf = bytearray(HEADER_SIZE + 22 * LAP_DATA_SIZE)
    for idx, c in cars.items():
        base = HEADER_SIZE + idx * LAP_DATA_SIZE
        buf[base + 32] = c.get("position", 0)
        buf[base + 33] = c.get("lap", 0)
        buf[base + 34] = c.get("pit_status", 0)
    return bytes(buf)


def test_lap_data_threads_pit_status_into_rival_tracker(engine):
    engine._player_car_index = 0
    engine.rival_tracker = RivalTracker()
    consume_f1_packet(engine, 
        {"player_car_index": 0}, PACKET_LAP_DATA,
        _lap_buf_multi({0: {"position": 1, "lap": 5}, 1: {"position": 3, "lap": 5}}))
    consume_f1_packet(engine, 
        {"player_car_index": 0}, PACKET_LAP_DATA,
        _lap_buf_multi({0: {"position": 1, "lap": 6},
                        1: {"position": 18, "lap": 6, "pit_status": 1}}))
    rivals = engine.rival_tracker.get_state()["rivals"]
    sainz = next(r for r in rivals if r["position"] == 18)
    assert sainz["pit_count"] == 1


def _status_buf_multi(cars: dict[int, dict]) -> bytes:
    buf = bytearray(HEADER_SIZE + 22 * CAR_STATUS_SIZE)
    for idx, c in cars.items():
        base = HEADER_SIZE + idx * CAR_STATUS_SIZE
        struct.pack_into("<f", buf, base + 5, c.get("fuel", 50.0))
        buf[base + 26] = c.get("tyre_visual", 16)
        buf[base + 27] = c.get("tyre_age", 0)
    return bytes(buf)


def test_car_status_threads_tyre_age_into_rival_tracker(engine):
    engine._player_car_index = 0
    engine.rival_tracker = RivalTracker()
    engine.rival_tracker.update(
        [{"vehicle_idx": 0, "position": 1, "lap": 5, "driver": "Player", "team": "T", "color": "#fff"},
         {"vehicle_idx": 1, "position": 2, "lap": 5, "driver": "Sainz", "team": "Ferrari", "color": "#fff"}],
        player_vehicle_idx=0, now=1.0)

    consume_f1_packet(engine, 
        {"player_car_index": 0}, PACKET_CAR_STATUS,
        _status_buf_multi({0: {"tyre_age": 3}, 1: {"tyre_age": 12}}))

    assert engine.rival_tracker.get_tyre_age(1) == 12


def _damage_buf_multi(cars: dict[int, dict], stride: int = 42) -> bytes:
    buf = bytearray(HEADER_SIZE + 22 * stride)
    for idx, c in cars.items():
        base = HEADER_SIZE + idx * stride
        buf[base + 24] = c.get("wing", 0)
        buf[base + 27] = c.get("floor", 0)
        buf[base + 32] = c.get("gearbox", 0)
        buf[base + 33] = c.get("engine", 0)
    return bytes(buf)


def test_car_damage_threads_body_damage_as_mistake_for_rivals(engine):
    engine._player_car_index = 0
    engine.rival_tracker = RivalTracker()
    engine.rival_tracker.update(
        [{"vehicle_idx": 0, "position": 1, "lap": 5, "driver": "Player", "team": "T", "color": "#fff"},
         {"vehicle_idx": 1, "position": 2, "lap": 5, "driver": "Sainz", "team": "Ferrari", "color": "#fff"}],
        player_vehicle_idx=0, now=1.0)

    consume_f1_packet(engine, 
        {"player_car_index": 0}, PACKET_CAR_DAMAGE,
        _damage_buf_multi({0: {}, 1: {"wing": 45}}))

    assert engine.rival_tracker.get_recent_mistake(1, now=time.time()) is True


def test_car_damage_below_threshold_is_not_a_mistake_for_rivals(engine):
    engine._player_car_index = 0
    engine.rival_tracker = RivalTracker()
    engine.rival_tracker.update(
        [{"vehicle_idx": 0, "position": 1, "lap": 5, "driver": "Player", "team": "T", "color": "#fff"},
         {"vehicle_idx": 1, "position": 2, "lap": 5, "driver": "Sainz", "team": "Ferrari", "color": "#fff"}],
        player_vehicle_idx=0, now=1.0)

    consume_f1_packet(engine, 
        {"player_car_index": 0}, PACKET_CAR_DAMAGE,
        _damage_buf_multi({0: {}, 1: {"wing": 5}}))

    assert engine.rival_tracker.get_recent_mistake(1, now=time.time()) is False


# ── Состав резины соперников в таблице позиций ────────────────────────────────
# Car Status уже приносил tyre_compound по ВСЕМ машинам, но движок брал оттуда
# только tyre_age — в /api/state у каждой строки грида состав отсутствовал, и
# UI рисовал всем постоянный прочерк.

def _grid_row(engine, vehicle_idx: int) -> dict:
    return next(row for row in engine._current_grid
                if row["vehicle_idx"] == vehicle_idx)


def test_car_status_records_tyre_compound_for_every_car(engine):
    engine._player_car_index = 0
    engine._grid_tyre_compounds.clear()

    consume_f1_packet(engine,
        {"player_car_index": 0}, PACKET_CAR_STATUS,
        _status_buf_multi({0: {"tyre_visual": 16},    # S
                           1: {"tyre_visual": 17},    # M
                           2: {"tyre_visual": 18}}))  # H

    assert engine._grid_tyre_compounds[0] == "S"
    assert engine._grid_tyre_compounds[1] == "M"
    assert engine._grid_tyre_compounds[2] == "H"


def test_unknown_compound_does_not_overwrite_known_one(engine):
    """Пакет по машине может прийти с ещё не заполненным составом — прочерк
    не должен затирать уже известное значение."""
    engine._player_car_index = 0
    engine._grid_tyre_compounds.clear()

    consume_f1_packet(engine,
        {"player_car_index": 0}, PACKET_CAR_STATUS,
        _status_buf_multi({1: {"tyre_visual": 17}}))
    consume_f1_packet(engine,
        {"player_car_index": 0}, PACKET_CAR_STATUS,
        _status_buf_multi({1: {"tyre_visual": 0}}))   # -> "?" в парсере

    assert engine._grid_tyre_compounds[1] == "M"


def test_grid_rows_carry_tyre_compound(engine):
    engine._player_car_index = 0
    engine._grid_tyre_compounds.clear()

    consume_f1_packet(engine,
        {"player_car_index": 0}, PACKET_CAR_STATUS,
        _status_buf_multi({0: {"tyre_visual": 18}, 1: {"tyre_visual": 16}}))
    consume_f1_packet(engine,
        {"player_car_index": 0}, PACKET_LAP_DATA,
        _lap_buf_multi({0: {"position": 1, "lap": 5}, 1: {"position": 2, "lap": 5}}))

    assert _grid_row(engine, 0)["tyre_compound"] == "H"
    assert _grid_row(engine, 1)["tyre_compound"] == "S"


def test_grid_row_without_status_yet_is_blank_not_missing(engine):
    """Пока Car Status по машине не пришёл — поле есть, но пустое: UI покажет
    прочерк как «пока неизвестно», а не упадёт на отсутствующем ключе."""
    engine._player_car_index = 0
    engine._grid_tyre_compounds.clear()

    consume_f1_packet(engine,
        {"player_car_index": 0}, PACKET_LAP_DATA,
        _lap_buf_multi({0: {"position": 1, "lap": 5}, 3: {"position": 4, "lap": 5}}))

    assert _grid_row(engine, 3)["tyre_compound"] == ""
