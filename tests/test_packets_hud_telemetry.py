"""Разбор телеметрии для in-game HUD: педали/руль/RPM/рев-лайты (CarTelemetry)
и мощность PU / харвест-деплой ERS / DRS-дистанция (CarStatus).

Те же правила, что в test_packets_gaps_tyre.py: синтетический буфер, офсеты из
golden-раскладки, без сети и живой игры. Визуальный референс полей —
pits-n-giggles 4.2.0 (hud_overlay.qml / input_telemetry.qml / pu.qml).
"""
import struct

from core import packets
from core.packets import CAR_STATUS_SIZE, CAR_TELEMETRY_SIZE, HEADER_SIZE


def _buf(size: int) -> bytearray:
    return bytearray(size)


# --------------------------------------------------------------------------- #
# parse_player_telemetry — driver inputs
# --------------------------------------------------------------------------- #

def _telemetry_buf(idx: int, *, speed=200, throttle=0.0, steer=0.0, brake=0.0,
                   gear=4, rpm=0, drs=0, rev_lights=0) -> bytes:
    buf = _buf(HEADER_SIZE + 22 * CAR_TELEMETRY_SIZE)
    base = HEADER_SIZE + idx * CAR_TELEMETRY_SIZE
    struct.pack_into("<H", buf, base + 0, speed)
    struct.pack_into("<f", buf, base + 2, throttle)
    struct.pack_into("<f", buf, base + 6, steer)
    struct.pack_into("<f", buf, base + 10, brake)
    struct.pack_into("<b", buf, base + 15, gear)
    struct.pack_into("<H", buf, base + 16, rpm)
    buf[base + 18] = drs
    buf[base + 19] = rev_lights
    return bytes(buf)


def test_pedals_are_exposed_as_percentages():
    # The game sends 0.0-1.0 floats; the HUD should never have to know that.
    data = _telemetry_buf(0, throttle=1.0, brake=0.25)

    result = packets.parse_player_telemetry(data, 0)

    assert result["throttle_pct"] == 100.0
    assert result["brake_pct"] == 25.0


def test_steering_keeps_its_sign_so_the_trace_can_go_both_ways():
    left = packets.parse_player_telemetry(_telemetry_buf(0, steer=-0.5), 0)
    right = packets.parse_player_telemetry(_telemetry_buf(0, steer=0.5), 0)

    assert left["steer"] == -0.5
    assert right["steer"] == 0.5


def test_rpm_rev_lights_and_drs_flap_are_read():
    data = _telemetry_buf(0, rpm=11500, rev_lights=87, drs=1)

    result = packets.parse_player_telemetry(data, 0)

    assert result["rpm"] == 11500
    assert result["rev_lights_pct"] == 87
    # m_drs is the flap being OPEN right now — distinct from CarStatus'
    # m_drsAllowed ("you may open it"), which the HUD colours differently.
    assert result["drs_active"] is True


def test_absurd_inputs_are_dropped_like_speed_and_gear():
    buf = bytearray(_telemetry_buf(0, rpm=11000))
    base = HEADER_SIZE + 0 * CAR_TELEMETRY_SIZE
    struct.pack_into("<f", buf, base + 2, 5.0)      # throttle way out of range
    struct.pack_into("<f", buf, base + 6, -9.0)     # steer way out of range
    struct.pack_into("<H", buf, base + 16, 60000)   # impossible RPM

    result = packets.parse_player_telemetry(bytes(buf), 0)

    assert "throttle_pct" not in result
    assert "steer" not in result
    assert "rpm" not in result
    # A bad field must not poison the rest of the packet.
    assert result["speed"] == 200


# --------------------------------------------------------------------------- #
# _car_status_fields — power unit, ERS flow, DRS zone
# --------------------------------------------------------------------------- #

def _status_buf(idx: int, **fields) -> tuple[bytes, int]:
    buf = _buf(HEADER_SIZE + 22 * CAR_STATUS_SIZE)
    base = HEADER_SIZE + idx * CAR_STATUS_SIZE
    struct.pack_into("<f", buf, base + 5, fields.get("fuel", 30.0))
    struct.pack_into("<f", buf, base + 13, fields.get("fuel_laps", 0.0))
    struct.pack_into("<H", buf, base + 23, fields.get("drs_distance", 0))
    struct.pack_into("<f", buf, base + 29, fields.get("ice_w", 0.0))
    struct.pack_into("<f", buf, base + 33, fields.get("mguk_w", 0.0))
    struct.pack_into("<f", buf, base + 37, fields.get("store_j", 0.0))
    struct.pack_into("<f", buf, base + 42, fields.get("harv_mguk_j", 0.0))
    struct.pack_into("<f", buf, base + 46, fields.get("harv_mguh_j", 0.0))
    struct.pack_into("<f", buf, base + 50, fields.get("deployed_j", 0.0))
    return bytes(buf), base


def test_power_unit_split_is_reported_in_kilowatts():
    data, base = _status_buf(0, ice_w=560_000.0, mguk_w=120_000.0)

    result = packets._car_status_fields(data, base)

    assert result["power_ice_kw"] == 560.0
    assert result["power_mguk_kw"] == 120.0


def test_power_mguk_is_not_confused_with_the_adjacent_ers_store():
    # m_enginePowerMGUK@33 sits immediately before m_ersStoreEnergy@37 and both
    # are floats of a similar magnitude — the same trap the ERS test guards.
    data, base = _status_buf(0, mguk_w=120_000.0, store_j=packets.ERS_MAX_JOULES)

    result = packets._car_status_fields(data, base)

    assert result["power_mguk_kw"] == 120.0
    assert result["ers_percent"] == 100.0


def test_harvest_sums_both_generators_and_deploy_is_separate():
    data, base = _status_buf(
        0,
        harv_mguk_j=packets.ERS_MAX_JOULES * 0.30,
        harv_mguh_j=packets.ERS_MAX_JOULES * 0.20,
        deployed_j=packets.ERS_MAX_JOULES * 0.40,
    )

    result = packets._car_status_fields(data, base)

    # One harvest arc on the HUD ring = MGU-K + MGU-H.
    assert result["ers_harvested_pct"] == 50.0
    assert result["ers_deployed_pct"] == 40.0


def test_drs_zone_distance_and_fuel_laps_are_read():
    data, base = _status_buf(0, drs_distance=180, fuel_laps=-1.25)

    result = packets._car_status_fields(data, base)

    assert result["drs_distance_m"] == 180
    # Negative = short of the finish on current consumption.
    assert result["fuel_remaining_laps"] == -1.25
