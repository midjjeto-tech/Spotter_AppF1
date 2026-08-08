"""m_currentLapTimeInMS (LapData, офсет +4) — время текущего круга.

Нужно коучу для дельты по повороту: время на входе в зону и на выходе.
Соседние офсеты этой структуры уже подтверждены (m_lapDistance @20,
m_carPosition @32, m_currentLapNum @33), поэтому риск здесь несопоставим с
реконструированной раскладкой MotionEx.
"""
import struct

from core import packets
from core.packets import HEADER_SIZE, LAP_DATA_SIZE


def _lap_buf(cars: int = 22) -> bytearray:
    return bytearray(HEADER_SIZE + cars * LAP_DATA_SIZE)


def test_current_lap_time_parsed():
    buf = _lap_buf()
    struct.pack_into("<I", buf, HEADER_SIZE + 4, 34567)

    out = packets.parse_player_lap(bytes(buf), 0)

    assert out["current_lap_time_ms"] == 34567


def test_current_lap_time_read_at_correct_stride():
    buf = _lap_buf()
    struct.pack_into("<I", buf, HEADER_SIZE + LAP_DATA_SIZE + 4, 11111)

    out = packets.parse_player_lap(bytes(buf), 1)

    assert out["current_lap_time_ms"] == 11111


def test_absurd_current_lap_time_dropped():
    """Больше часа на круге — мусор из смещённого пакета, не время."""
    buf = _lap_buf()
    struct.pack_into("<I", buf, HEADER_SIZE + 4, 4_000_000)

    out = packets.parse_player_lap(bytes(buf), 0)

    assert out["current_lap_time_ms"] is None


def test_existing_lap_fields_unchanged():
    """Регрессия: правка не должна тронуть уже разобранные поля."""
    buf = _lap_buf()
    struct.pack_into("<f", buf, HEADER_SIZE + 20, 1234.5)
    buf[HEADER_SIZE + 32] = 7
    buf[HEADER_SIZE + 33] = 12

    out = packets.parse_player_lap(bytes(buf), 0)

    assert out["position"] == 7
    assert out["current_lap"] == 12
    assert abs(out["lap_distance_m"] - 1234.5) < 0.01
