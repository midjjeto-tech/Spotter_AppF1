"""tests/test_strategy_sprint.py — Strategy AI mini-sprint feature tests."""
import pytest
from core.strategy_ai.analysis import LapRecord, PaceTracker, FuelTracker


# ---------------------------------------------------------------------------
# PaceTracker
# ---------------------------------------------------------------------------

def test_pace_tracker_stable_with_less_than_3_laps():
    t = PaceTracker()
    t.push(LapRecord(lap_number=1, lap_time_ms=90_000, tyre_compound="M", tyre_age=1))
    t.push(LapRecord(lap_number=2, lap_time_ms=90_200, tyre_compound="M", tyre_age=2))
    assert t.trend() == "stable"        # only 2 laps — not enough for trend


def test_pace_tracker_rising_trend():
    t = PaceTracker()
    for i, ms in enumerate([90_000, 90_300, 90_600], start=1):
        t.push(LapRecord(lap_number=i, lap_time_ms=ms, tyre_compound="M", tyre_age=i))
    assert t.trend() == "rising"        # getting slower = tyres degrading


def test_pace_tracker_falling_trend():
    t = PaceTracker()
    for i, ms in enumerate([91_000, 90_700, 90_400], start=1):
        t.push(LapRecord(lap_number=i, lap_time_ms=ms, tyre_compound="M", tyre_age=i))
    assert t.trend() == "falling"       # getting faster = good form


def test_pace_tracker_prev_lap_ms():
    t = PaceTracker()
    t.push(LapRecord(lap_number=1, lap_time_ms=90_000, tyre_compound="M", tyre_age=1))
    t.push(LapRecord(lap_number=2, lap_time_ms=90_400, tyre_compound="M", tyre_age=2))
    assert t.prev_lap_ms() == 90_000    # returns second-to-last lap time


def test_pace_tracker_no_data_returns_none():
    t = PaceTracker()
    assert t.prev_lap_ms() is None
    assert t.trend() == "stable"


# ---------------------------------------------------------------------------
# FuelTracker
# ---------------------------------------------------------------------------

def test_fuel_tracker_actual_per_lap():
    t = FuelTracker()
    t.push(lap_number=1, fuel_kg=30.0)
    t.push(lap_number=4, fuel_kg=24.6)
    assert abs(t.actual_per_lap() - 1.8) < 0.01   # (30.0 - 24.6) / 3 = 1.8


def test_fuel_tracker_attack_mode():
    t = FuelTracker()
    t.push(lap_number=1, fuel_kg=30.0)
    t.push(lap_number=3, fuel_kg=26.8)             # 1.6 kg/lap rate
    # 10 laps remaining → project 26.8 - 1.6*10 = 10.8 → surplus > 2 kg
    assert t.fuel_mode(laps_remaining=10) == "attack"


def test_fuel_tracker_save_mode():
    t = FuelTracker()
    t.push(lap_number=1, fuel_kg=30.0)
    t.push(lap_number=3, fuel_kg=26.0)             # 2.0 kg/lap rate
    # 20 laps remaining → project 26.0 - 2.0*20 = -14 → deficit
    assert t.fuel_mode(laps_remaining=20) == "save"


def test_fuel_tracker_normal_mode():
    t = FuelTracker()
    t.push(lap_number=1, fuel_kg=30.0)
    t.push(lap_number=3, fuel_kg=26.4)             # 1.8 kg/lap rate
    # 14 laps remaining → project 26.4 - 1.8*14 = 1.2 → 0 < 1.2 < 2 → normal
    assert t.fuel_mode(laps_remaining=14) == "normal"


# ---------------------------------------------------------------------------
# OpponentPitDetector
# ---------------------------------------------------------------------------

from core.strategy_ai.opponents import OpponentPitDetector


def test_opponent_no_pit_on_small_gap_change():
    d = OpponentPitDetector()
    d.update(gap_front_ms=2_000)
    d.update(gap_front_ms=2_500)    # +500ms — normal racing
    assert d.opponent_pitted is False


def test_opponent_detects_pit_on_large_gap_jump():
    d = OpponentPitDetector()
    d.update(gap_front_ms=2_000)
    d.update(gap_front_ms=25_000)   # +23000ms — opponent pitted
    assert d.opponent_pitted is True


def test_opponent_cover_recommended_with_worn_tyres():
    d = OpponentPitDetector()
    d.update(gap_front_ms=2_000)
    d.update(gap_front_ms=25_000)
    ok, conf = d.should_cover(our_tyre_status="worn")
    assert ok is True
    assert conf >= 0.6


def test_opponent_no_cover_with_fresh_tyres():
    d = OpponentPitDetector()
    d.update(gap_front_ms=2_000)
    d.update(gap_front_ms=25_000)
    ok, conf = d.should_cover(our_tyre_status="fresh")
    assert ok is False
    assert conf == 0.0


# ---------------------------------------------------------------------------
# StrategyAnalyzer — confidence filter + cover event + new state fields
# ---------------------------------------------------------------------------

from core.strategy_ai.strategy import StrategyAnalyzer


def _snapshot(**kw) -> dict:
    defaults = {
        "player_lap": 15,
        "total_laps": 50,
        "player_pos": 5,
        "gap_front_ms": 2_000,
        "gap_behind_ms": 3_000,
        "gap_leader_ms": 15_000,
        "tyre_compound": "M",
        "tyre_age": 10,
        "tyre_wear": 30.0,
        "last_lap_ms": 90_000,
        "fuel": 20.0,
    }
    return {**defaults, **kw}


def test_confidence_filter_blocks_low_conf_event():
    """Events below MIN_CONFIDENCE_EMIT should not be returned."""
    a = StrategyAnalyzer()
    ev = a.update(_snapshot(
        tyre_age=10, tyre_wear=30.0,
        gap_front_ms=5_000,
        tyre_compound="H",
    ))
    # Either None or, if emitted, confidence must be >= 0.55
    if ev is not None:
        assert ev.confidence >= 0.55


def test_confidence_filter_allows_high_conf_event():
    """A clearly critical tyre situation must fire at >= 0.55."""
    a = StrategyAnalyzer()
    ev = a.update(_snapshot(
        tyre_age=40, tyre_wear=80.0,
    ))
    assert ev is not None
    assert ev.confidence >= 0.55


def test_cover_event_when_opponent_pits_and_tyres_worn():
    """When gap_front jumps > 12s and our tyres are worn -> cover event."""
    a = StrategyAnalyzer()
    # Prime the detector: first update with small gap
    a.update(_snapshot(gap_front_ms=2_000, tyre_age=25, tyre_wear=52.0))
    # Second update: gap jumped -> opponent pitted
    ev = a.update(_snapshot(gap_front_ms=28_000, tyre_age=26, tyre_wear=54.0))
    assert ev is not None
    assert ev.type == "cover_opponent"
    assert ev.confidence >= 0.6


def test_get_state_has_fuel_mode_and_pace_trend():
    """get_state() must include fuel_mode and pace_trend keys."""
    a = StrategyAnalyzer()
    a.update(_snapshot())
    s = a.get_state()
    assert "fuel_mode" in s
    assert "pace_trend" in s
    assert s["fuel_mode"] in ("attack", "normal", "save")
    assert s["pace_trend"] in ("rising", "falling", "stable")
