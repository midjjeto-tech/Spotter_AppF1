"""Tests for channel routing and radio templates."""
import pytest
from commentator.channel_router import route_event, CHANNEL_COMMENTARY, CHANNEL_RADIO, CHANNEL_OVERLAY
from commentator.radio import get_radio_line


# ---------------------------------------------------------------------------
# channel routing
# ---------------------------------------------------------------------------

def test_ovtk_routes_to_commentary_in_race():
    assert route_event({"event_code": "OVTK"}, "race") == CHANNEL_COMMENTARY


def test_drse_routes_to_radio():
    assert route_event({"event_code": "DRSE"}, "race") == CHANNEL_RADIO


def test_drsd_routes_to_radio():
    assert route_event({"event_code": "DRSD"}, "race") == CHANNEL_RADIO


def test_strategy_pit_routes_to_radio():
    assert route_event({"event_code": "STRAT_PIT"}, "race") == CHANNEL_RADIO


def test_tyre_warn_routes_to_radio():
    assert route_event({"event_code": "TYRE_WARN"}, "race") == CHANNEL_RADIO


def test_major_events_always_commentary():
    for code in ("SSTA", "CHQF", "RCWN", "RTMT", "PENA",
                 "SAFETY_CAR_DEPLOYED", "SAFETY_CAR_ENDING",
                 "SAFETY_CAR_CLEAR", "RDFL"):
        channel = route_event({"event_code": code}, "practice")
        assert channel == CHANNEL_COMMENTARY, f"{code} should be commentary"


def test_drse_in_practice_routes_to_overlay():
    assert route_event({"event_code": "DRSE"}, "practice") == CHANNEL_OVERLAY


def test_ambient_always_commentary():
    assert route_event({"event_code": "AMBIENT"}, "race") == CHANNEL_COMMENTARY
    assert route_event({"event_code": "AMBIENT"}, "practice") == CHANNEL_COMMENTARY


def test_sptp_in_practice_is_overlay():
    assert route_event({"event_code": "SPTP"}, "practice") == CHANNEL_OVERLAY


def test_unknown_event_defaults_to_commentary():
    assert route_event({"event_code": "XYZZ"}, "race") == CHANNEL_COMMENTARY


def test_career_recap_always_overlay():
    assert route_event({"event_code": "CAREER_RECAP"}, "race") == CHANNEL_OVERLAY
    assert route_event({"event_code": "CAREER_RECAP"}, "practice") == CHANNEL_OVERLAY


def test_post_race_paddock_events_are_silent_overlay_only():
    for code in ("RACEFEED_DOTD", "POST_RACE_INTERVIEW", "RACE_RECAP"):
        assert route_event({"event_code": code}, "race") == CHANNEL_OVERLAY


# ---------------------------------------------------------------------------
# radio templates
# ---------------------------------------------------------------------------

def test_radio_drse_returns_string():
    line = get_radio_line("DRSE")
    assert isinstance(line, str) and len(line) > 0


def test_radio_unknown_code_returns_none():
    assert get_radio_line("NONEXISTENT") is None


def test_radio_tyre_warn_returns_string():
    line = get_radio_line("TYRE_WARN")
    assert isinstance(line, str) and len(line) > 0


def test_radio_strat_save_returns_string():
    line = get_radio_line("STRAT_SAVE")
    assert isinstance(line, str) and len(line) > 0


def test_channel_constants_are_distinct():
    assert CHANNEL_COMMENTARY != CHANNEL_RADIO != CHANNEL_OVERLAY
