"""Проводка PitWindowApproachTracker: вызов detect_pit_window напрямую из
engine.py (НЕ через StrategyAnalyzer — тот вызывает его только условно,
см. spec), сброс на собственном пит-стопе.
См. docs/superpowers/specs/2026-07-13-engineer-phase-a-cheap-calls-design.md.
"""
import time

import pytest

from core.strategy_ai import pit_window

import core.engine as eng_mod
from core.engine import F1Engine, SPEAKER_ENGINEER


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


def test_pit_window_approach_enqueues_in_race(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "race"
    engine._strategy_module.pit_window_approach_tracker.reset()
    engine._player_lap = 10
    engine._total_laps = 30
    engine._player_tyre_age = 20
    # wear=58.0 (not 55.0): detect_pit_window's _laps_to_pit(20, wear) uses
    # int((78-wear)/2.5) -- at wear=55.0 this truncates to laps_left=9, which
    # PitWindowApproachTracker's own unit test (test_pit_window_approach_
    # silent_when_too_far, tests/test_strategy_ai.py) asserts is silent
    # (APPROACH_LAPS_THRESHOLD=8, strictly <=). wear=58.0 -> laps_left=8,
    # matching the tracker's own fires-at-8 test.
    engine._player_tyre_wear = 58.0
    engine._player_tyre_compound = "medium"
    engine._last_snap_t = 0.0
    _drain(engine)

    class _StubCoach:
        def get_state(self):
            return {}
    monkeypatch.setattr(engine, "driver_coach", _StubCoach())

    engine._maybe_snapshot()

    drained = _drain(engine)
    found = [e for e in drained if e["event_code"] == "PIT_WINDOW_APPROACH"]
    assert len(found) == 1
    assert found[0]["speaker"] == SPEAKER_ENGINEER
    engine._strategy_module.pit_window_approach_tracker.reset()
    engine._session_type = "unknown"
    engine._player_lap = None
    engine._total_laps = None
    engine._last_snap_t = 0.0


def test_own_pit_exit_resets_pit_window_approach(engine):
    engine._session_type = "race"
    engine._strategy_module.pit_window_approach_tracker.check(open_=False, laps_left=5)  # армирован

    engine._maybe_announce_pit_exit(prev_status=1, new_status=0)

    phrase = engine._strategy_module.pit_window_approach_tracker.check(open_=False, laps_left=5)
    assert phrase == pit_window.CODE_WINDOW_APPROACH   # снова армируется -> сброшен
    engine._strategy_module.pit_window_approach_tracker.reset()
    engine._session_type = "unknown"


def test_flashback_resets_pit_window_approach(engine, monkeypatch):
    calls = []
    monkeypatch.setattr(engine._strategy_module.pit_window_approach_tracker, "reset", lambda: calls.append(True))
    engine._handle_flashback()
    assert calls == [True]
