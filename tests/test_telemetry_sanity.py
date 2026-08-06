"""Tests for telemetry sanity guards in parse_player_telemetry."""
import struct
import pytest
from core.packets import (
    parse_player_telemetry, HEADER_SIZE, CAR_TELEMETRY_FORMAT, CAR_TELEMETRY_SIZE,
)


def _make_telemetry_packet(player_idx: int, speed: int, gear: int) -> bytes:
    """Build a spec-accurate CAR_TELEMETRY packet for one player at player_idx.

    Real PacketCarTelemetryData = header + CarTelemetryData[22] with NO leading
    byte. Only PacketParticipantsData carries m_numActiveCars. This matches the
    framing parse_lap_data already uses successfully against the live game.
    """
    header = b"\x00" * HEADER_SIZE
    # pad player_idx * CAR_TELEMETRY_SIZE zeros before our entry (no prefix byte)
    padding = b"\x00" * (player_idx * CAR_TELEMETRY_SIZE)
    entry = struct.pack(CAR_TELEMETRY_FORMAT,
        speed,          # H speed km/h
        0.0,            # f throttle
        0.0,            # f steer
        0.0,            # f brake
        0,              # B clutch
        gear,           # b gear
        5000,           # H engineRPM
        0, 0, 0, 0,     # BBBB
        0, 0, 0, 0,     # HHHH
        0, 0, 0, 0,     # bbbb
        0,              # H
        0.0, 0.0, 0.0, 0.0,  # ffff
        0, 0, 0, 0,     # BBBB
    )
    # Pad entry to CAR_TELEMETRY_SIZE (format is 56 bytes, size is 60)
    entry += b"\x00" * (CAR_TELEMETRY_SIZE - len(entry))
    return header + padding + entry


def test_valid_speed_returned():
    data = _make_telemetry_packet(0, speed=280, gear=5)
    result = parse_player_telemetry(data, 0)
    assert result["speed"] == 280


def test_zero_speed_allowed():
    data = _make_telemetry_packet(0, speed=0, gear=0)
    result = parse_player_telemetry(data, 0)
    assert result["speed"] == 0


def test_max_realistic_speed_allowed():
    data = _make_telemetry_packet(0, speed=400, gear=8)
    result = parse_player_telemetry(data, 0)
    assert result["speed"] == 400


def test_absurd_speed_filtered_out():
    data = _make_telemetry_packet(0, speed=65535, gear=5)
    result = parse_player_telemetry(data, 0)
    assert "speed" not in result


def test_reverse_gear_returned():
    data = _make_telemetry_packet(0, speed=5, gear=-1)
    result = parse_player_telemetry(data, 0)
    assert result["gear"] == "R"


def test_neutral_gear_returned():
    data = _make_telemetry_packet(0, speed=0, gear=0)
    result = parse_player_telemetry(data, 0)
    assert result["gear"] == "N"


def test_gear_8_returned():
    data = _make_telemetry_packet(0, speed=350, gear=8)
    result = parse_player_telemetry(data, 0)
    assert result["gear"] == "8"


def test_absurd_gear_filtered_out():
    # gear is int8 so max is 127; valid range is -1..8
    # gear=50 is valid in struct but invalid for F1
    data = _make_telemetry_packet(0, speed=100, gear=50)
    result = parse_player_telemetry(data, 0)
    assert "gear" not in result


@pytest.mark.parametrize("player_idx", [0, 7, 19])
def test_nonzero_player_index_reads_correct_car(player_idx):
    """Independent anchor: the player's car must be read at HEADER_SIZE + idx*SIZE
    (no phantom prefix). A spurious +1 in the base offset shifts the uint16 speed
    read by one byte and corrupts the value — this catches that regression."""
    data = _make_telemetry_packet(player_idx, speed=288, gear=6)
    result = parse_player_telemetry(data, player_idx)
    assert result["speed"] == 288
    assert result["gear"] == "6"
