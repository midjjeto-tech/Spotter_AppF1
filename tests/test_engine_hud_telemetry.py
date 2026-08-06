"""Engine → /api/overlay: the new HUD telemetry must survive the whole chain."""
import struct
import pytest
import core.engine as eng_mod
from core.engine import F1Engine
from core.packets import (HEADER_SIZE, CAR_TELEMETRY_SIZE, CAR_STATUS_SIZE,
                          PACKET_CAR_TELEMETRY, PACKET_CAR_STATUS)
from tests.telemetry import consume_f1_packet


@pytest.fixture()
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def test_hud_telemetry_reaches_the_overlay_api(engine):
    engine._player_car_index = 0

    tel = bytearray(HEADER_SIZE + 22 * CAR_TELEMETRY_SIZE)
    struct.pack_into("<H", tel, HEADER_SIZE + 0, 288)
    struct.pack_into("<f", tel, HEADER_SIZE + 2, 1.0)     # throttle
    struct.pack_into("<f", tel, HEADER_SIZE + 6, -0.25)   # steer
    struct.pack_into("<f", tel, HEADER_SIZE + 10, 0.0)    # brake
    struct.pack_into("<b", tel, HEADER_SIZE + 15, 7)      # gear
    struct.pack_into("<H", tel, HEADER_SIZE + 16, 11900)  # rpm
    tel[HEADER_SIZE + 19] = 93                            # rev lights
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_CAR_TELEMETRY, bytes(tel))

    st = bytearray(HEADER_SIZE + 22 * CAR_STATUS_SIZE)
    struct.pack_into("<f", st, HEADER_SIZE + 5, 28.4)          # fuel
    struct.pack_into("<H", st, HEADER_SIZE + 23, 140)          # drs distance
    struct.pack_into("<f", st, HEADER_SIZE + 29, 540_000.0)    # ICE W
    struct.pack_into("<f", st, HEADER_SIZE + 33, 118_000.0)    # MGU-K W
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_CAR_STATUS, bytes(st))

    overlay = engine.get_overlay_state()

    assert overlay["inputs"]["throttle_pct"] == 100.0
    assert overlay["inputs"]["steer"] == -0.25
    assert overlay["inputs"]["rpm"] == 11900
    assert overlay["inputs"]["rev_lights_pct"] == 93
    assert overlay["car"]["power_ice_kw"] == 540.0
    assert overlay["car"]["power_mguk_kw"] == 118.0
    assert overlay["session"]["drs_distance_m"] == 140
