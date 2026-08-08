"""Хвост CarTelemetryData (packet 6): тип покрытия под колёсами и температуры
резины.

Читаются по ЯВНЫМ офсетам, а НЕ по `CAR_TELEMETRY_FORMAT`: хвост формата
разъехался с реальной структурой начиная с внутренних температур (там 4 байта
uint8, а формат читает один H), поэтому всё, что в строке дальше — давления и
surfaceType — смещено на 4 байта. Поля 0-8, которыми пользуется
parse_player_telemetry, лежат ДО этого места и верны.
См. Task 2 плана docs/superpowers/plans/2026-08-06-driving-coach-phase1.md.
"""
import struct

from core import packets
from core.packets import CAR_TELEMETRY_SIZE, HEADER_SIZE


def _telemetry_buf(cars: int = 22) -> bytearray:
    return bytearray(HEADER_SIZE + cars * CAR_TELEMETRY_SIZE)


def test_surface_type_read_per_wheel_in_rl_rr_fl_fr_order():
    buf = _telemetry_buf()
    base = HEADER_SIZE + packets._CAR_TELEMETRY_SURFACE_OFF
    buf[base:base + 4] = bytes([0, 0, 7, 4])   # rl/rr асфальт, fl трава, fr гравий

    out = packets.parse_player_telemetry(bytes(buf), 0)

    assert out["surface"] == {"rl": "tarmac", "rr": "tarmac",
                              "fl": "grass", "fr": "gravel"}


def test_unknown_surface_code_falls_back_to_unknown():
    buf = _telemetry_buf()
    base = HEADER_SIZE + packets._CAR_TELEMETRY_SURFACE_OFF
    buf[base:base + 4] = bytes([200, 0, 0, 0])

    out = packets.parse_player_telemetry(bytes(buf), 0)

    assert out["surface"]["rl"] == "unknown"


def test_tyre_surface_temperature_read_per_wheel():
    buf = _telemetry_buf()
    base = HEADER_SIZE + packets._CAR_TELEMETRY_TYRE_SURF_TEMP_OFF
    buf[base:base + 4] = bytes([90, 95, 105, 110])

    out = packets.parse_player_telemetry(bytes(buf), 0)

    assert out["tyre_surface_temp"] == {"rl": 90, "rr": 95, "fl": 105, "fr": 110}


def test_surface_read_at_correct_stride_for_second_car():
    buf = _telemetry_buf()
    base = HEADER_SIZE + CAR_TELEMETRY_SIZE + packets._CAR_TELEMETRY_SURFACE_OFF
    buf[base:base + 4] = bytes([7, 7, 0, 0])

    out = packets.parse_player_telemetry(bytes(buf), 1)

    assert out["surface"]["rl"] == "grass"
    assert out["surface"]["fl"] == "tarmac"


def test_rumble_strip_counts_as_on_track():
    """Поребрик — часть трассы, выездом он быть не должен."""
    assert "rumble_strip" in packets.SURFACE_ON_TRACK
    assert "grass" not in packets.SURFACE_ON_TRACK


def test_existing_speed_and_gear_still_parsed():
    """Регрессия: правка хвоста не должна тронуть поля 0-8."""
    buf = _telemetry_buf()
    struct.pack_into("<H", buf, HEADER_SIZE + 0, 250)
    struct.pack_into("<b", buf, HEADER_SIZE + 15, 6)

    out = packets.parse_player_telemetry(bytes(buf), 0)

    assert out["speed"] == 250
    assert out["gear"] == "6"
