# tests/test_box_call.py
"""BoxCallTracker — детерминированный автомат эскалации 'боксы в этом круге'.
См. docs/superpowers/specs/2026-07-09-precise-box-call-design.md.
"""
from core.strategy_ai.box_call import DECISIVE_CONFIDENCE, MAX_TIER, BoxCallTracker


def test_arms_on_first_decisive_tick():
    t = BoxCallTracker()
    tier = t.update(player_lap=10, action="pit", confidence=0.9, pit_status=0)
    assert tier == 1


def test_does_not_repeat_within_same_lap():
    t = BoxCallTracker()
    t.update(player_lap=10, action="pit", confidence=0.9, pit_status=0)
    tier = t.update(player_lap=10, action="pit", confidence=0.9, pit_status=0)
    assert tier is None


def test_escalates_on_next_lap_if_still_not_pitted():
    t = BoxCallTracker()
    t.update(player_lap=10, action="pit", confidence=0.9, pit_status=0)
    tier2 = t.update(player_lap=11, action="pit", confidence=0.9, pit_status=0)
    tier3 = t.update(player_lap=12, action="pit", confidence=0.9, pit_status=0)
    assert (tier2, tier3) == (2, 3)


def test_plateaus_at_max_tier():
    t = BoxCallTracker()
    t.update(player_lap=10, action="pit", confidence=0.9, pit_status=0)
    t.update(player_lap=11, action="pit", confidence=0.9, pit_status=0)
    t.update(player_lap=12, action="pit", confidence=0.9, pit_status=0)
    tier4 = t.update(player_lap=13, action="pit", confidence=0.9, pit_status=0)
    assert tier4 == MAX_TIER == 3


def test_pit_status_resets_and_rearms_fresh():
    t = BoxCallTracker()
    t.update(player_lap=10, action="pit", confidence=0.9, pit_status=0)
    t.update(player_lap=11, action="pit", confidence=0.9, pit_status=0)
    during_stop = t.update(player_lap=11, action="pit", confidence=0.9, pit_status=1)
    assert during_stop is None
    tier = t.update(player_lap=15, action="pit", confidence=0.9, pit_status=0)
    assert tier == 1                     # свежий цикл, не продолжение эскалации


def test_confidence_below_threshold_resets():
    t = BoxCallTracker()
    t.update(player_lap=10, action="pit", confidence=0.9, pit_status=0)
    tier = t.update(player_lap=11, action="pit", confidence=0.5, pit_status=0)
    assert tier is None
    tier2 = t.update(player_lap=12, action="pit", confidence=0.9, pit_status=0)
    assert tier2 == 1                    # не escalation 3 — новый цикл


def test_action_not_pit_resets():
    t = BoxCallTracker()
    t.update(player_lap=10, action="pit", confidence=0.9, pit_status=0)
    tier = t.update(player_lap=11, action="hold", confidence=0.9, pit_status=0)
    assert tier is None


def test_low_confidence_never_arms():
    t = BoxCallTracker()
    tier = t.update(player_lap=10, action="pit", confidence=DECISIVE_CONFIDENCE - 0.01,
                     pit_status=0)
    assert tier is None


def test_player_lap_none_is_safe_noop():
    t = BoxCallTracker()
    tier = t.update(player_lap=None, action="pit", confidence=0.9, pit_status=0)
    assert tier is None


def test_confidence_exactly_at_threshold_arms():
    t = BoxCallTracker()
    tier = t.update(player_lap=10, action="pit", confidence=DECISIVE_CONFIDENCE,
                     pit_status=0)
    assert tier == 1
