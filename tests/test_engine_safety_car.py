"""Проводка Phase B (Safety Car/VSC/красный флаг) в F1Engine: raw SCAR ->
синтетический event_code через derive_safety_car_event() ДО enrich()/
record_event(), RDFL идёт без проводки (как RTMT), m_safetyCarStatus
из PACKET_SESSION виден в self.state["race"] и сбрасывается на SSTA.
См. docs/superpowers/plans/2026-07-19-safety-car-vsc-red-flag.md.
"""
import struct

import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.packets import HEADER_SIZE, PACKET_SESSION
from tests.telemetry import consume_f1_event_packet, consume_f1_packet


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


def _scar_buf(safety_car_type: int, event_reason: int) -> bytes:
    buf = bytearray(HEADER_SIZE + 4 + 2)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"SCAR"
    struct.pack_into("<BB", buf, HEADER_SIZE + 4, safety_car_type, event_reason)
    return bytes(buf)


def _session_buf(safety_car_status: int = 0) -> bytes:
    buf = bytearray(HEADER_SIZE + 125)
    buf[HEADER_SIZE + 124] = safety_car_status
    return bytes(buf)


def test_safety_car_status_initialized_before_any_packet():
    """_safety_car_status must be readable right after __init__, before any
    PACKET_SESSION or SSTA has been processed (regression: was previously only
    set inside _update_telemetry/SSTA handling, so reading it earlier raised
    AttributeError)."""
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        fresh = F1Engine({})
        assert fresh._safety_car_status == 0
    finally:
        eng_mod.yc.load = orig


def test_full_sc_deployed_produces_synthetic_event(engine):
    _drain(engine)
    consume_f1_event_packet(engine, _scar_buf(safety_car_type=1, event_reason=0))

    drained = _drain(engine)
    codes = [e["event_code"] for e in drained]
    assert "SAFETY_CAR_DEPLOYED" in codes
    assert "SCAR" not in codes                # raw code fully replaced
    ev = next(e for e in drained if e["event_code"] == "SAFETY_CAR_DEPLOYED")
    assert ev["sc_type"] == "Safety car"
    assert ev["color"] == "#FBBF24"
    assert ev["priority"] == "critical"


def test_vsc_ending_produces_synthetic_event(engine):
    _drain(engine)
    consume_f1_event_packet(engine, _scar_buf(safety_car_type=2, event_reason=1))

    drained = _drain(engine)
    ev = next(e for e in drained if e["event_code"] == "SAFETY_CAR_ENDING")
    assert ev["sc_type"] == "Virtual Safety Car"


def test_formation_lap_sc_is_noop(engine):
    _drain(engine)
    consume_f1_event_packet(engine, _scar_buf(safety_car_type=3, event_reason=0))
    assert _drain(engine) == []


def test_returned_sub_state_is_noop(engine):
    _drain(engine)
    consume_f1_event_packet(engine, _scar_buf(safety_car_type=1, event_reason=2))
    assert _drain(engine) == []


def test_rdfl_flows_through_as_critical_event(engine):
    _drain(engine)
    buf = bytearray(HEADER_SIZE + 4)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"RDFL"
    consume_f1_event_packet(engine, bytes(buf))

    drained = _drain(engine)
    codes = [e["event_code"] for e in drained]
    assert "RDFL" in codes
    ev = next(e for e in drained if e["event_code"] == "RDFL")
    assert ev["priority"] == "critical"


def test_packet_session_exposes_safety_car_status(engine):
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_SESSION,
                             _session_buf(safety_car_status=2))
    assert engine._safety_car_status == 2
    assert engine.get_state()["race"]["safety_car_status"] == 2


def test_ssta_resets_safety_car_status(engine):
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_SESSION,
                             _session_buf(safety_car_status=1))
    assert engine._safety_car_status == 1

    buf = bytearray(HEADER_SIZE + 4)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"SSTA"
    consume_f1_event_packet(engine, bytes(buf))

    assert engine._safety_car_status == 0
    assert engine.get_state()["race"]["safety_car_status"] == 0
