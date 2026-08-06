"""derive_safety_car_event — pure raw SCAR (safety_car_type, event_reason)
-> synthetic engine event_code/description/sc_type, or None for sub-states
that aren't announcement-worthy. См. docs/superpowers/plans/
2026-07-19-safety-car-vsc-red-flag.md.
"""
from core.strategy_ai.safety_car import derive_safety_car_event


def test_full_sc_deployed():
    out = derive_safety_car_event(safety_car_type=1, event_reason=0)
    assert out["event_code"] == "SAFETY_CAR_DEPLOYED"
    assert out["sc_type"] == "Safety car"


def test_full_sc_ending():
    out = derive_safety_car_event(safety_car_type=1, event_reason=1)
    assert out["event_code"] == "SAFETY_CAR_ENDING"
    assert out["sc_type"] == "Safety car"


def test_full_sc_clear():
    out = derive_safety_car_event(safety_car_type=1, event_reason=3)
    assert out["event_code"] == "SAFETY_CAR_CLEAR"
    assert out["sc_type"] == "Safety car"


def test_vsc_deployed_uses_vsc_label():
    out = derive_safety_car_event(safety_car_type=2, event_reason=0)
    assert out["event_code"] == "SAFETY_CAR_DEPLOYED"
    assert out["sc_type"] == "Virtual Safety Car"


def test_vsc_ending():
    out = derive_safety_car_event(safety_car_type=2, event_reason=1)
    assert out["event_code"] == "SAFETY_CAR_ENDING"
    assert out["sc_type"] == "Virtual Safety Car"


def test_vsc_clear():
    out = derive_safety_car_event(safety_car_type=2, event_reason=3)
    assert out["event_code"] == "SAFETY_CAR_CLEAR"
    assert out["sc_type"] == "Virtual Safety Car"


def test_returned_is_suppressed_no_third_announcement():
    assert derive_safety_car_event(safety_car_type=1, event_reason=2) is None
    assert derive_safety_car_event(safety_car_type=2, event_reason=2) is None


def test_formation_lap_sc_always_suppressed():
    for event_reason in (0, 1, 2, 3):
        assert derive_safety_car_event(
            safety_car_type=3, event_reason=event_reason) is None


def test_no_safety_car_type_suppressed():
    # safety_car_type=0 ("none") should never reach this function via a real
    # SCAR event, but guard defensively rather than crash/announce garbage.
    assert derive_safety_car_event(safety_car_type=0, event_reason=0) is None


def test_deployed_sets_color_and_description():
    out = derive_safety_car_event(safety_car_type=1, event_reason=0)
    assert out["color"] == "#FBBF24"
    assert "Safety car" in out["description"]


def test_clear_sets_green_color():
    out = derive_safety_car_event(safety_car_type=1, event_reason=3)
    assert out["color"] == "#22C55E"
