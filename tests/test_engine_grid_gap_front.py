"""core/engine.py: gap_front_ms (уже парсится parse_lap_data для всех 22
машин) должен долетать до grid-строк движка, не только до gap игрока.
См. docs/superpowers/specs/2026-07-22-overlay-radar-relative-design.md."""
import struct

import pytest

import core.engine as eng_mod
from core.engine import F1Engine
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


def _lap_buf_with_positions_and_gaps(cars: dict[int, dict]) -> bytes:
    buf = bytearray(HEADER_SIZE + 22 * LAP_DATA_SIZE)
    for idx, c in cars.items():
        base = HEADER_SIZE + idx * LAP_DATA_SIZE
        buf[base + 32] = c["position"]
        buf[base + 33] = c.get("lap", 1)
        struct.pack_into("<H", buf, base + 14, c.get("gap_front_ms", 0) & 0xFFFF)
    return bytes(buf)


def test_grid_rows_carry_each_cars_own_gap_to_car_in_front(engine):
    engine._player_car_index = 0

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
        _lap_buf_with_positions_and_gaps({
            0: {"position": 1, "gap_front_ms": 0},
            1: {"position": 2, "gap_front_ms": 742},
            2: {"position": 3, "gap_front_ms": 1106},
        }))

    by_pos = {row["position"]: row for row in engine._current_grid}
    assert by_pos[2]["gap_front_ms"] == 742
    assert by_pos[3]["gap_front_ms"] == 1106
    # Лидер: 0 — сырое значение телеметрии "машины впереди нет", а не
    # "0мс до соперника" (см. комментарий в core/engine.py рядом с gap_front_ms).
    assert by_pos[1]["gap_front_ms"] == 0
