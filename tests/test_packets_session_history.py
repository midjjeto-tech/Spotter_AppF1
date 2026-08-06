"""Синтетические тесты parse_session_history (packet 11) из core/packets.py.

Без сети и без живой игры — вручную собираем байтовый буфер по офсетам,
которые читает код (см. docs/superpowers/plans/2026-07-20-session-history-
sector-comparison.md). Пакет ПОЦИКЛОВОЙ — один car_idx за раз, не все 22
машины разом (та же схема, что уже у Tyre Sets, packet 12).
"""
from core import packets
from core.packets import HEADER_SIZE, LAP_HISTORY_SIZE, TYRE_STINT_HISTORY_SIZE

_LAP_HISTORY_OFF = 7
_NUM_LAPS_SLOT = 100
_TYRE_STINTS_OFF = _LAP_HISTORY_OFF + _NUM_LAPS_SLOT * LAP_HISTORY_SIZE
_BODY_SIZE = _TYRE_STINTS_OFF + 8 * TYRE_STINT_HISTORY_SIZE


def _buf() -> bytearray:
    return bytearray(HEADER_SIZE + _BODY_SIZE)


def _lap_offset(lap_index: int) -> int:
    """lap_index — 0-based позиция в m_lapHistoryData."""
    return HEADER_SIZE + _LAP_HISTORY_OFF + lap_index * LAP_HISTORY_SIZE


def _stint_offset(stint_index: int) -> int:
    return HEADER_SIZE + _TYRE_STINTS_OFF + stint_index * TYRE_STINT_HISTORY_SIZE


def _set_lap(buf: bytearray, lap_index: int, *, lap_ms: int,
             s1_ms: int, s2_ms: int, s3_ms: int, valid_flags: int = 0x0F) -> None:
    import struct
    base = _lap_offset(lap_index)
    struct.pack_into("<I", buf, base + 0, lap_ms)
    struct.pack_into("<H", buf, base + 4, s1_ms % 60000)
    buf[base + 6] = s1_ms // 60000
    struct.pack_into("<H", buf, base + 7, s2_ms % 60000)
    buf[base + 9] = s2_ms // 60000
    struct.pack_into("<H", buf, base + 10, s3_ms % 60000)
    buf[base + 12] = s3_ms // 60000
    buf[base + 13] = valid_flags


def test_parse_session_history_extracts_best_sector_times():
    buf = _buf()
    buf[HEADER_SIZE + 0] = 3      # car_idx
    buf[HEADER_SIZE + 1] = 3      # num_laps
    buf[HEADER_SIZE + 3] = 2      # bestLapTimeLapNum -> lap 2 (index 1)
    buf[HEADER_SIZE + 4] = 1      # bestSector1LapNum -> lap 1 (index 0)
    buf[HEADER_SIZE + 5] = 3      # bestSector2LapNum -> lap 3 (index 2)
    buf[HEADER_SIZE + 6] = 2      # bestSector3LapNum -> lap 2 (index 1)

    _set_lap(buf, 0, lap_ms=90000, s1_ms=28000, s2_ms=31000, s3_ms=31000)
    _set_lap(buf, 1, lap_ms=88500, s1_ms=29000, s2_ms=30500, s3_ms=29000)
    _set_lap(buf, 2, lap_ms=91000, s1_ms=30000, s2_ms=29500, s3_ms=31500)

    out = packets.parse_session_history(bytes(buf))
    assert out["car_idx"] == 3
    assert out["num_laps"] == 3
    assert out["best_lap_ms"] == 88500
    assert out["best_sector_ms"] == {1: 28000, 2: 29500, 3: 29000}


def test_parse_session_history_guards_out_of_range_lap_num():
    buf = _buf()
    buf[HEADER_SIZE + 0] = 0
    buf[HEADER_SIZE + 1] = 2      # num_laps = 2
    buf[HEADER_SIZE + 3] = 0      # bestLapTimeLapNum = 0 -> "not set" sentinel
    buf[HEADER_SIZE + 4] = 5      # bestSector1LapNum > num_laps -> invalid
    buf[HEADER_SIZE + 5] = 1      # valid
    buf[HEADER_SIZE + 6] = 0      # not set

    _set_lap(buf, 0, lap_ms=90000, s1_ms=28000, s2_ms=31000, s3_ms=31000)
    _set_lap(buf, 1, lap_ms=88500, s1_ms=29000, s2_ms=30500, s3_ms=29000)

    out = packets.parse_session_history(bytes(buf))
    assert out["best_lap_ms"] is None
    assert out["best_sector_ms"] == {2: 31000}


def test_parse_session_history_short_data_returns_empty_dict():
    assert packets.parse_session_history(bytes(HEADER_SIZE)) == {}
    assert packets.parse_session_history(b"") == {}
    assert packets.parse_session_history(bytes(HEADER_SIZE + 100)) == {}


def test_parse_session_history_tyre_stints():
    buf = _buf()
    buf[HEADER_SIZE + 0] = 7
    buf[HEADER_SIZE + 2] = 2   # num_tyre_stints = 2

    s0 = _stint_offset(0)
    buf[s0 + 0] = 18   # end_lap
    buf[s0 + 1] = 16   # actual compound
    buf[s0 + 2] = 16   # visual compound (S)

    s1 = _stint_offset(1)
    buf[s1 + 0] = 40
    buf[s1 + 1] = 17
    buf[s1 + 2] = 17   # visual compound (M)

    # Гарбаж в третьей записи — не должен попасть в результат (num_tyre_stints=2).
    s2 = _stint_offset(2)
    buf[s2 + 0] = 99
    buf[s2 + 1] = 18
    buf[s2 + 2] = 18

    out = packets.parse_session_history(bytes(buf))
    assert out["car_idx"] == 7
    assert out["tyre_stints"] == [
        {"end_lap": 18, "actual_compound": 16, "visual_compound": 16},
        {"end_lap": 40, "actual_compound": 17, "visual_compound": 17},
    ]
