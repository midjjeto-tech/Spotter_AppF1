"""Tests for Strategy AI layer — deterministic pit/tyre/pace logic."""
import pytest

from core.strategy_ai import pit_window

from core.strategy_ai.tyres import tyre_status, needs_pit_soon, tyre_saving_recommended
from core.strategy_ai.pit_window import (
    PIT_LOSS_MS,
    detect_undercut,
    detect_overcut,
    detect_pit_window,
)
from core.strategy_ai.analysis import pace_mode, fuel_save_recommended, ers_save_recommended, ers_overtake_recommended
from core.strategy_ai.strategy import StrategyAnalyzer


# ---------------------------------------------------------------------------
# tyres.py
# ---------------------------------------------------------------------------

def test_tyre_status_fresh():
    assert tyre_status(age=5, wear=20.0) == "fresh"


def test_tyre_status_worn():
    assert tyre_status(age=22, wear=48.0) == "worn"


def test_tyre_status_critical():
    assert tyre_status(age=32, wear=62.0) == "critical"


def test_tyre_status_cliff():
    assert tyre_status(age=40, wear=78.0) == "cliff"


def test_soft_compound_degrades_faster():
    assert tyre_status(age=18, wear=40.0, compound="S") == "worn"
    assert tyre_status(age=18, wear=35.0, compound="H") == "fresh"


def test_needs_pit_soon():
    assert needs_pit_soon(age=35, wear=70.0) is True
    assert needs_pit_soon(age=10, wear=30.0) is False


def test_tyre_saving_recommended():
    assert tyre_saving_recommended(age=25, wear=50.0) is True
    assert tyre_saving_recommended(age=8, wear=25.0) is False


# ---------------------------------------------------------------------------
# pit_window.py
# ---------------------------------------------------------------------------

def test_undercut_when_close_and_worn():
    ok, conf = detect_undercut(
        gap_front_ms=2000, tyre_age=28, tyre_wear=58.0, laps_remaining=20)
    assert ok is True
    assert conf > 0.5


def test_no_undercut_when_gap_large():
    ok, _ = detect_undercut(
        gap_front_ms=5000, tyre_age=30, tyre_wear=60.0, laps_remaining=20)
    assert ok is False


def test_no_undercut_end_of_race():
    ok, _ = detect_undercut(
        gap_front_ms=2000, tyre_age=30, tyre_wear=60.0, laps_remaining=3)
    assert ok is False


def test_overcut_fresh_tyres_moderate_gap():
    ok, conf = detect_overcut(
        gap_front_ms=4500, tyre_age=10, tyre_wear=30.0, laps_remaining=25)
    assert ok is True
    assert conf > 0.4


def test_no_overcut_worn_tyres():
    ok, _ = detect_overcut(
        gap_front_ms=4500, tyre_age=25, tyre_wear=55.0, laps_remaining=25)
    assert ok is False


def test_pit_window_critical_tyres():
    ok, conf, laps = detect_pit_window(
        tyre_age=35, tyre_wear=65.0, laps_remaining=15)
    assert ok is True
    assert conf >= 0.85
    assert laps is not None


def test_pit_window_closed_early_race_fresh():
    ok, _, _ = detect_pit_window(tyre_age=8, tyre_wear=25.0, laps_remaining=40)
    assert ok is False


def test_pit_loss_constant_sane():
    assert 20_000 <= PIT_LOSS_MS <= 28_000


# ---------------------------------------------------------------------------
# analysis.py
# ---------------------------------------------------------------------------

def test_pace_mode_push_when_close():
    mode, conf = pace_mode(
        last_lap_ms=90_000, prev_lap_ms=90_500,
        gap_front_ms=1200, gap_behind_ms=3000,
        tyre_age=12, tyre_wear=40.0)
    assert mode == "push"
    assert conf > 0.5


def test_pace_mode_save_when_worn_and_safe():
    mode, conf = pace_mode(
        last_lap_ms=92_000, prev_lap_ms=91_000,
        gap_front_ms=4000, gap_behind_ms=3500,
        tyre_age=28, tyre_wear=58.0)
    assert mode == "save"
    assert conf > 0.5


def test_fuel_save_low_fuel():
    ok, conf = fuel_save_recommended(fuel_kg=1.5, laps_remaining=8)
    assert ok is True
    assert conf > 0.6


def test_fuel_save_ok():
    ok, _ = fuel_save_recommended(fuel_kg=8.0, laps_remaining=20)
    assert ok is False


def test_ers_save_low_battery():
    ok, conf = ers_save_recommended(ers_percent=5.0)
    assert ok is True
    assert conf > 0.6


def test_ers_save_ok_when_charged():
    ok, _ = ers_save_recommended(ers_percent=60.0)
    assert ok is False


def test_ers_save_none_safe():
    assert ers_save_recommended(ers_percent=None) == (False, 0.0)


def test_ers_overtake_when_charged_and_close():
    ok, conf = ers_overtake_recommended(
        ers_percent=70.0, ers_deploy_mode=1, gap_front_ms=800)
    assert ok is True
    assert conf > 0.6


def test_ers_overtake_suppressed_when_already_overtake_mode():
    ok, _ = ers_overtake_recommended(
        ers_percent=70.0, ers_deploy_mode=2, gap_front_ms=800)
    assert ok is False


def test_ers_overtake_suppressed_when_low_battery():
    ok, _ = ers_overtake_recommended(
        ers_percent=30.0, ers_deploy_mode=1, gap_front_ms=800)
    assert ok is False


def test_ers_overtake_suppressed_when_gap_large():
    ok, _ = ers_overtake_recommended(
        ers_percent=70.0, ers_deploy_mode=1, gap_front_ms=5000)
    assert ok is False


def test_ers_overtake_none_safe():
    assert ers_overtake_recommended(None, None, None) == (False, 0.0)


# ---------------------------------------------------------------------------
# strategy.py (analyzer)
# ---------------------------------------------------------------------------

def _snapshot(**kw):
    base = {
        "player_lap": 20,
        "total_laps": 50,
        "player_pos": 5,
        "gap_front_ms": 2500,
        "gap_behind_ms": 3000,
        "gap_leader_ms": 8000,
        "tyre_compound": "M",
        "tyre_age": 10,
        "tyre_wear": 35.0,
        "last_lap_ms": 90_000,
        "fuel": 10.0,
    }
    base.update(kw)
    return base


def test_analyzer_undercut_event():
    sa = StrategyAnalyzer()
    event = sa.update(_snapshot(
        gap_front_ms=2200, tyre_age=30, tyre_wear=62.0, laps_remaining=30))
    assert event is not None
    assert event.type == "undercut"
    assert event.decision.action == "pit"


def test_analyzer_pit_window_event():
    sa = StrategyAnalyzer()
    event = sa.update(_snapshot(tyre_age=36, tyre_wear=68.0))
    assert event is not None
    assert event.type in ("pit_window", "undercut")


def test_analyzer_empty_snapshot_no_crash():
    sa = StrategyAnalyzer()
    event = sa.update({})
    assert event is None


def test_get_state_contract():
    sa = StrategyAnalyzer()
    sa.update(_snapshot(tyre_age=35, tyre_wear=70.0))
    s = sa.get_state()
    for key in ("action", "confidence", "reason", "advice", "mode", "tyre_status"):
        assert key in s


def test_get_state_tyre_status_reflects_wear():
    sa = StrategyAnalyzer()
    sa.update(_snapshot(tyre_age=5, tyre_wear=20.0))
    assert sa.get_state()["tyre_status"] == "fresh"


def test_reset_clears_pace_fuel_opponent_and_current_decision():
    analyzer = StrategyAnalyzer()
    base = {
        "total_laps": 50,
        "player_pos": 5,
        "gap_behind_ms": None,
        "gap_leader_ms": None,
        "tyre_compound": "MEDIUM",
        "tyre_age": 2,
        "tyre_wear": 5.0,
        "ers_percent": None,
        "ers_deploy_mode": None,
    }
    for lap, lap_time, fuel in ((1, 90_000, 50.0), (2, 91_000, 48.0), (3, 92_000, 46.0)):
        analyzer.update({
            **base,
            "player_lap": lap,
            "last_lap_ms": lap_time,
            "fuel": fuel,
            "gap_front_ms": 2_000,
        })
    assert analyzer.get_state()["pace_trend"] == "rising"

    analyzer.update({
        **base,
        "player_lap": 4,
        "last_lap_ms": 93_000,
        "fuel": 44.0,
        "gap_front_ms": 1_000,
        "tyre_age": 24,
        "tyre_wear": 60.0,
    })
    event = analyzer.update({
        **base,
        "player_lap": 5,
        "last_lap_ms": 94_000,
        "fuel": 42.0,
        "gap_front_ms": 20_000,
        "tyre_age": 24,
        "tyre_wear": 60.0,
    })
    assert event is not None and event.type == "cover_opponent"

    analyzer.reset()

    state = analyzer.get_state()
    assert state["action"] == "hold"
    assert state["current_event"] is None
    assert state["pace_trend"] == "stable"
    assert state["fuel_mode"] == "normal"
    event_after_reset = analyzer.update({
        **base,
        "player_lap": 5,
        "last_lap_ms": 94_000,
        "fuel": 42.0,
        "gap_front_ms": 20_000,
        "tyre_age": 24,
        "tyre_wear": 60.0,
    })
    assert event_after_reset is None or event_after_reset.type != "cover_opponent"


def test_analyzer_ers_overtake_event():
    sa = StrategyAnalyzer()
    event = sa.update(_snapshot(
        gap_front_ms=800, ers_percent=70.0, ers_deploy_mode=1,
        tyre_age=8, tyre_wear=20.0))
    assert event is not None
    assert event.type == "ers_overtake"


def test_analyzer_ers_save_event():
    sa = StrategyAnalyzer()
    event = sa.update(_snapshot(
        gap_front_ms=8000, gap_behind_ms=8000, ers_percent=4.0,
        tyre_age=8, tyre_wear=20.0))
    assert event is not None
    assert event.type == "ers_save"


# ---------------------------------------------------------------------------
# PitWindowApproachTracker — армируется один раз за стинт
# ---------------------------------------------------------------------------

def test_pit_window_approach_fires_when_close_and_not_open():
    from core.strategy_ai.pit_window import PitWindowApproachTracker
    t = PitWindowApproachTracker()
    phrase = t.check(open_=False, laps_left=8)
    assert phrase == pit_window.CODE_WINDOW_APPROACH


def test_pit_window_approach_silent_when_already_open():
    from core.strategy_ai.pit_window import PitWindowApproachTracker
    t = PitWindowApproachTracker()
    assert t.check(open_=True, laps_left=2) is None


def test_pit_window_approach_silent_when_too_far():
    from core.strategy_ai.pit_window import PitWindowApproachTracker
    t = PitWindowApproachTracker()
    assert t.check(open_=False, laps_left=9) is None


def test_pit_window_approach_fires_once_per_stint():
    from core.strategy_ai.pit_window import PitWindowApproachTracker
    t = PitWindowApproachTracker()
    t.check(open_=False, laps_left=8)
    assert t.check(open_=False, laps_left=7) is None
    assert t.check(open_=False, laps_left=9) is None   # колебания laps_left тоже не повторяют


def test_pit_window_approach_fires_again_after_reset():
    from core.strategy_ai.pit_window import PitWindowApproachTracker
    t = PitWindowApproachTracker()
    t.check(open_=False, laps_left=8)
    t.reset()
    phrase = t.check(open_=False, laps_left=8)
    assert phrase == pit_window.CODE_WINDOW_APPROACH


def test_pit_window_approach_none_laps_left_silent():
    from core.strategy_ai.pit_window import PitWindowApproachTracker
    t = PitWindowApproachTracker()
    assert t.check(open_=False, laps_left=None) is None
