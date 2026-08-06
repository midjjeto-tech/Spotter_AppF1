"""Tests for session type parsing in parse_session."""
import struct
import pytest
from core.packets import parse_session, HEADER_SIZE, SESSION_TYPE_MAP


def _make_session_packet(total_laps: int, session_type_raw: int, track_id: int = 5) -> bytes:
    """Minimal session packet: header + 8 bytes payload."""
    header = b"\x00" * HEADER_SIZE
    # offset 0: weather, 1: trackTemp(i8), 2: airTemp(i8), 3: totalLaps
    # 4-5: trackLength(u16), 6: sessionType(u8), 7: trackId(i8)
    payload = struct.pack("<BBbBHBb",
        0,             # weather
        25,            # trackTemp
        20,            # airTemp  (signed)
        total_laps,    # totalLaps
        5793,          # trackLength
        session_type_raw,
        track_id,
    )
    return header + payload


def test_practice_p1_maps_to_practice():
    data = _make_session_packet(20, session_type_raw=1)
    result = parse_session(data)
    assert result["session_type"] == "practice"


def test_practice_p3_maps_to_practice():
    data = _make_session_packet(20, session_type_raw=3)
    result = parse_session(data)
    assert result["session_type"] == "practice"


def test_qualifying_q1_maps_to_qualifying():
    data = _make_session_packet(0, session_type_raw=5)
    result = parse_session(data)
    assert result["session_type"] == "qualifying"


def test_race_maps_to_race():
    data = _make_session_packet(58, session_type_raw=15)
    result = parse_session(data)
    assert result["session_type"] == "race"


def test_race2_maps_to_race():
    data = _make_session_packet(58, session_type_raw=16)
    result = parse_session(data)
    assert result["session_type"] == "race"


def test_race3_maps_to_race():
    data = _make_session_packet(58, session_type_raw=17)
    result = parse_session(data)
    assert result["session_type"] == "race"


def test_sprint_shootout_maps_to_qualifying():
    """F1 25 вставил Sprint Shootout (10-14) МЕЖДУ Qualifying и Race — той же
    квалификационной природы (single-lap, решётка спринта), не Race и не
    Practice. Найдено живой проверкой 2026-07-18 (реальная гонка пришла с
    session_type_raw=15, не 10 — старая F1 23/24 карта маппила это в
    "unknown", и все race-only фичи молчали)."""
    for raw in (10, 11, 12, 13, 14):
        data = _make_session_packet(0, session_type_raw=raw)
        result = parse_session(data)
        assert result["session_type"] == "qualifying", f"raw={raw}"


def test_unknown_type_maps_to_unknown():
    data = _make_session_packet(20, session_type_raw=99)
    result = parse_session(data)
    assert result["session_type"] == "unknown"


def test_time_trial_maps_to_practice():
    data = _make_session_packet(0, session_type_raw=18)
    result = parse_session(data)
    assert result["session_type"] == "practice"


def test_session_type_raw_preserved():
    data = _make_session_packet(20, session_type_raw=3)
    result = parse_session(data)
    assert result["session_type_raw"] == 3


def test_total_laps_still_present():
    data = _make_session_packet(58, session_type_raw=10)
    result = parse_session(data)
    assert result["total_laps"] == 58


def test_too_short_returns_empty():
    result = parse_session(b"\x00" * 5)
    assert result == {}
