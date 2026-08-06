"""Tests for SessionGuard per-session spam prevention."""
import time
import pytest
from core.session_guard import SessionGuard


# ---------------------------------------------------------------------------
# Practice cooldowns
# ---------------------------------------------------------------------------

def test_practice_first_event_passes():
    g = SessionGuard()
    g.set_session_type("practice")
    assert g.should_emit({"event_code": "FTLP"}) is True


def test_practice_same_event_blocked_within_cooldown():
    g = SessionGuard()
    g.set_session_type("practice")
    g.should_emit({"event_code": "FTLP"})      # first: pass
    assert g.should_emit({"event_code": "FTLP"}) is False   # second: blocked


def test_practice_different_events_both_pass():
    g = SessionGuard()
    g.set_session_type("practice")
    assert g.should_emit({"event_code": "FTLP"}) is True
    assert g.should_emit({"event_code": "SSTA"}) is True


def test_practice_suppresses_race_only_events():
    g = SessionGuard()
    g.set_session_type("practice")
    assert g.should_emit({"event_code": "STRAT_PUSH"}) is False
    assert g.should_emit({"event_code": "FINAL_LAP"}) is False


def test_ers_advisories_suppressed_in_practice():
    g = SessionGuard()
    g.set_session_type("practice")
    assert g.should_emit({"event_code": "STRAT_ERS_SAVE"}) is False
    assert g.should_emit({"event_code": "STRAT_ERS_OVERTAKE"}) is False


def test_practice_critical_always_passes():
    g = SessionGuard()
    g.set_session_type("practice")
    g.should_emit({"event_code": "CHQF"})   # first pass + record
    # Critical ignores cooldown
    assert g.should_emit({"event_code": "CHQF", "priority": "critical"}) is True


def test_race_less_strict_than_practice():
    g_practice = SessionGuard()
    g_practice.set_session_type("practice")
    g_race = SessionGuard()
    g_race.set_session_type("race")
    # Both pass on first emit
    g_practice.should_emit({"event_code": "OVTK"})
    g_race.should_emit({"event_code": "OVTK"})
    # practice blocks, race may pass (race cooldown < practice cooldown)
    assert g_practice.should_emit({"event_code": "OVTK"}) is False
    # Race cooldown is also nonzero so second is blocked there too
    assert g_race.should_emit({"event_code": "OVTK"}) is False


def test_session_type_change_resets_state():
    g = SessionGuard()
    g.set_session_type("practice")
    g.should_emit({"event_code": "OVTK"})   # record
    # Change session → state clears
    g.set_session_type("race")
    assert g.should_emit({"event_code": "OVTK"}) is True  # fresh after reset


def test_qualifying_has_moderate_cooldowns():
    g = SessionGuard()
    g.set_session_type("qualifying")
    assert g.should_emit({"event_code": "FTLP"}) is True
    assert g.should_emit({"event_code": "FTLP"}) is False


def test_unknown_session_uses_race_defaults():
    g = SessionGuard()
    g.set_session_type("unknown")
    assert g.should_emit({"event_code": "OVTK"}) is True


def test_default_session_is_unknown():
    g = SessionGuard()
    assert g.should_emit({"event_code": "OVTK"}) is True


def test_race_proximity_codes_have_longer_cooldown_than_default():
    """OVTK/ATTACK/BATTLE в гонке больше не на 4-секундном default (анти-спам погони)."""
    race = SessionGuard._COOLDOWNS["race"]
    assert race["OVTK"] > race["default"]
    assert race["ATTACK"] > race["default"]
    assert race["BATTLE"] >= race["ATTACK"]
