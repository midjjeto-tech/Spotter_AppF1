"""Синтетические тесты parse_final_classification (packet 8) из core/packets.py.

Тот же приём, что test_packets_gaps_tyre.py::parse_player_damage — все 22
машины в одном пакете, срез по player_idx*FINAL_CLASSIFICATION_ENTRY_SIZE.
"""
import struct

import pytest

from core import packets
from core.packets import HEADER_SIZE, FINAL_CLASSIFICATION_ENTRY_SIZE


def _buf(size: int) -> bytearray:
    return bytearray(size)


def _entry_offset(idx: int) -> int:
    return HEADER_SIZE + 1 + idx * FINAL_CLASSIFICATION_ENTRY_SIZE


def test_parse_final_classification_player_fields():
    buf = _buf(HEADER_SIZE + 1 + 22 * FINAL_CLASSIFICATION_ENTRY_SIZE)
    buf[HEADER_SIZE] = 20   # m_numCars (не используется парсером напрямую)

    base = _entry_offset(3)   # player_idx = 3
    buf[base + 0] = 5      # position
    buf[base + 1] = 58     # num_laps
    buf[base + 2] = 3      # grid_position
    buf[base + 3] = 10     # points
    buf[base + 4] = 2      # num_pit_stops
    buf[base + 5] = 3      # result_status = finished
    buf[base + 6] = 8      # result_reason = mechanical failure
    struct.pack_into("<I", buf, base + 7, 83456)        # best_lap_time_ms
    struct.pack_into("<d", buf, base + 11, 5432.789)    # total_race_time_s
    buf[base + 19] = 5     # penalties_time_s
    buf[base + 20] = 1     # num_penalties

    out = packets.parse_final_classification(bytes(buf), 3)
    assert out["position"] == 5
    assert out["num_laps"] == 58
    assert out["grid_position"] == 3
    assert out["points"] == 10
    assert out["num_pit_stops"] == 2
    assert out["result_status"] == 3
    assert out["result_status_label"] == "финишировал"
    assert out["result_reason"] == 8
    assert out["result_reason_label"] == "механическая неисправность"
    assert out["best_lap_time_ms"] == 83456
    assert out["total_race_time_s"] == pytest.approx(5432.789)
    assert out["penalties_time_s"] == 5
    assert out["num_penalties"] == 1


def test_parse_final_classification_second_car_offset():
    buf = _buf(HEADER_SIZE + 1 + 22 * FINAL_CLASSIFICATION_ENTRY_SIZE)
    base = _entry_offset(0)
    buf[base + 0] = 1          # player_idx=3 должен НЕ увидеть это
    out = packets.parse_final_classification(bytes(buf), 3)
    assert out["position"] == 0


@pytest.mark.parametrize("raw, label", [
    (0, "неизвестно"), (1, "не стартовал"), (2, "в гонке"),
    (3, "финишировал"), (4, "не финишировал"), (5, "дисквалифицирован"),
    (6, "не классифицирован"), (7, "сошёл с дистанции"),
])
def test_parse_final_classification_result_status_labels(raw, label):
    buf = _buf(HEADER_SIZE + 1 + 22 * FINAL_CLASSIFICATION_ENTRY_SIZE)
    base = _entry_offset(0)
    buf[base + 5] = raw
    out = packets.parse_final_classification(bytes(buf), 0)
    assert out["result_status_label"] == label


def test_parse_final_classification_bad_size_guard():
    assert packets.parse_final_classification(_buf(HEADER_SIZE), 0) == {}
    assert packets.parse_final_classification(_buf(0), 0) == {}


def test_parse_final_classification_grid_returns_all_active_cars():
    buf = _buf(HEADER_SIZE + 1 + 22 * FINAL_CLASSIFICATION_ENTRY_SIZE)
    buf[HEADER_SIZE] = 3
    for idx, position in enumerate((2, 1, 3)):
        base = _entry_offset(idx)
        buf[base] = position
        buf[base + 3] = (18, 25, 15)[idx]
        buf[base + 5] = 3

    out = packets.parse_final_classification_grid(bytes(buf))

    assert [row["vehicle_idx"] for row in out] == [0, 1, 2]
    assert [row["position"] for row in out] == [2, 1, 3]
    assert [row["points"] for row in out] == [18, 25, 15]


def test_parse_final_classification_grid_truncated_packet_is_safe():
    assert packets.parse_final_classification_grid(_buf(HEADER_SIZE)) == []
