"""DefenseTracker — "удержал позицию" (successfully held off a sustained
attack). Edge-triggered on battle_active True->False, suppressed if the
player was actually overtaken (position lost, not defended) shortly before.
See docs/superpowers/plans/2026-07-20-defense-event-damage-phrase-variety.md.
"""
from core.strategy_ai.defense import SUPPRESSION_WINDOW_S, DefenseTracker


def test_no_announcement_while_battle_inactive():
    t = DefenseTracker()
    assert t.update(battle_active=False, now=100.0) is None


def test_no_announcement_while_battle_stays_active():
    t = DefenseTracker()
    t.update(battle_active=True, now=100.0)
    assert t.update(battle_active=True, now=101.0) is None


def test_announces_on_active_to_inactive_edge():
    t = DefenseTracker()
    t.update(battle_active=True, now=100.0)
    result = t.update(battle_active=False, now=101.0)
    assert result is not None
    assert isinstance(result, str) and result


def test_no_double_announcement_on_repeated_inactive():
    t = DefenseTracker()
    t.update(battle_active=True, now=100.0)
    t.update(battle_active=False, now=101.0)          # announces once
    assert t.update(battle_active=False, now=102.0) is None


def test_suppressed_if_player_was_just_overtaken():
    """battle ends because the rival actually got past (position lost), not
    because the player pulled away — must not announce a 'defense'."""
    t = DefenseTracker()
    t.update(battle_active=True, now=100.0)
    result = t.update(battle_active=False, now=101.0, last_overtaken_t=100.5)
    assert result is None


def test_not_suppressed_once_overtaken_window_elapses():
    t = DefenseTracker()
    t.update(battle_active=True, now=100.0)
    last_overtaken_t = 90.0   # long before the battle even started
    result = t.update(battle_active=False, now=101.0, last_overtaken_t=last_overtaken_t)
    assert 101.0 - last_overtaken_t >= SUPPRESSION_WINDOW_S
    assert result is not None


def test_reset_clears_state():
    t = DefenseTracker()
    t.update(battle_active=True, now=100.0)
    t.reset()
    # Post-reset, battle_active=False on the next tick is NOT an edge
    # (internal state was already False after reset) — no announcement.
    assert t.update(battle_active=False, now=200.0) is None
