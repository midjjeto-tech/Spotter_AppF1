"""Tests for Race Situation Intelligence Layer."""
import pytest
from core.race_ai.sectors import get_sector


def test_sector_boundaries():
    assert get_sector(0.00) == 1
    assert get_sector(0.15) == 1
    assert get_sector(0.329) == 1
    assert get_sector(0.33) == 2
    assert get_sector(0.55) == 2
    assert get_sector(0.669) == 2
    assert get_sector(0.67) == 3
    assert get_sector(0.88) == 3
    assert get_sector(1.00) == 3


def test_sector_clamps_invalid():
    assert get_sector(-0.1) == 1   # below 0 → sector 1
    assert get_sector(1.5) == 3    # above 1 → sector 3


# ---------------------------------------------------------------------------
# threat.py
# ---------------------------------------------------------------------------
from core.race_ai.threat import detect_threat

THREAT_GAP = 900   # ms — safely under 1000ms threshold


def test_no_threat_when_gap_large():
    is_threat, conf = detect_threat(gap_behind_ms=1500, drs_active=False,
                                    gap_closing=False, laps_remaining=None)
    assert is_threat is False
    assert conf == 0.0


def test_threat_when_gap_below_1s():
    is_threat, conf = detect_threat(gap_behind_ms=THREAT_GAP, drs_active=False,
                                    gap_closing=False, laps_remaining=None)
    assert is_threat is True
    assert 0.4 < conf < 0.7   # base confidence only


def test_drs_increases_confidence():
    _, conf_no_drs = detect_threat(THREAT_GAP, False, False, None)
    _, conf_drs    = detect_threat(THREAT_GAP, True,  False, None)
    assert conf_drs > conf_no_drs


def test_missing_gap_no_threat():
    is_threat, conf = detect_threat(gap_behind_ms=None, drs_active=True,
                                    gap_closing=True, laps_remaining=3)
    assert is_threat is False
    assert conf == 0.0


# ---------------------------------------------------------------------------
# intensity.py
# ---------------------------------------------------------------------------
from core.race_ai.intensity import calculate_intensity, get_mode


def test_intensity_zero_when_no_inputs():
    score = calculate_intensity(
        gap_behind_ms=None, drs_active=False,
        position_battle=False, laps_remaining=None,
        total_laps=None)
    assert score == 0


def test_intensity_adds_points():
    score = calculate_intensity(
        gap_behind_ms=800, drs_active=True,
        position_battle=True, laps_remaining=3,
        total_laps=50)
    assert score == 80   # 20+20+20+20 (final laps)


def test_intensity_max_is_90():
    # 20+20+20+20+10 = 90 — max possible from formula (clamp at 100 is defence, not reachable normally)
    score = calculate_intensity(
        gap_behind_ms=100, drs_active=True,
        position_battle=True, laps_remaining=2,
        total_laps=50, fastest_lap_set=True)
    assert score == 90


@pytest.mark.parametrize("intensity,expected_mode", [
    (10,  "CALM"),
    (40,  "RACE"),
    (70,  "BATTLE"),
    (90,  "CLIMAX"),
])
def test_mode_thresholds(intensity, expected_mode):
    assert get_mode(intensity) == expected_mode


# ---------------------------------------------------------------------------
# battles.py
# ---------------------------------------------------------------------------
from core.race_ai.battles import BattleDetector


def test_battle_not_active_initially():
    det = BattleDetector()
    state = det.update(gap_behind_ms=2000, driver_behind="Sainz", player_driver="player")
    assert state.active is False


def test_battle_activates_after_sustained_proximity():
    det = BattleDetector()
    for _ in range(5):   # 5 readings within 1s gap
        state = det.update(800, "Sainz", "player")
    assert state.active is True
    assert "Sainz" in state.cars or "player" in state.cars


def test_battle_no_crash_on_none_gap():
    det = BattleDetector()
    state = det.update(gap_behind_ms=None, driver_behind="Norris", player_driver="player")
    assert state.active is False
    assert isinstance(state.intensity, int)


# ---------------------------------------------------------------------------
# decisions.py
# ---------------------------------------------------------------------------
from core.race_ai.decisions import make_decision
from core.race_ai.models import RaceEvent


def _make_attack(drs=False):
    return RaceEvent(type="attack", priority="high", confidence=0.8,
                     driver="Sainz", target="player", data={"drs": drs})


def test_attack_with_drs_returns_cover_inside():
    d = make_decision(_make_attack(drs=True), gap_front_ms=1500, gap_closing=True)
    assert d["action"] == "defend"
    assert d["advice"] == "cover_inside"


def test_attack_without_drs_returns_hold_line():
    d = make_decision(_make_attack(drs=False), gap_front_ms=1500, gap_closing=False)
    assert d["action"] == "defend"
    assert d["advice"] == "hold_line"


def test_tyre_warning_returns_pit_advice():
    event = RaceEvent(type="tyre_warning", priority="medium", confidence=0.8,
                      driver="player", target="", data={"age": 35, "wear": 75.0})
    d = make_decision(event, gap_front_ms=None, gap_closing=False)
    assert d["action"] == "pit"


# ---------------------------------------------------------------------------
# analyzer.py
# ---------------------------------------------------------------------------
from core.race_ai.analyzer import RaceAnalyzer


def _snapshot(gap_behind=None, gap_front=None, drs=False,
              pos=5, lap=10, total=50, driver_behind="Sainz",
              tyre_age=None, tyre_wear=None):
    return {
        "gap_behind_ms": gap_behind,
        "gap_front_ms": gap_front,
        "drs_active": drs,
        "player_pos": pos,
        "player_lap": lap,
        "total_laps": total,
        "driver_behind": driver_behind,
        "tyre_age": tyre_age,
        "tyre_wear": tyre_wear,
    }


def test_attack_event_on_close_gap():
    ra = RaceAnalyzer()
    event = ra.update(_snapshot(gap_behind=800))
    assert event is not None
    assert event.type == "attack"
    assert event.driver == "Sainz"


def test_no_event_when_gap_large():
    ra = RaceAnalyzer()
    event = ra.update(_snapshot(gap_behind=3000))
    assert event is None


def test_missing_telemetry_no_crash():
    ra = RaceAnalyzer()
    event = ra.update({})   # empty snapshot — must not raise
    assert event is None


def test_get_state_returns_dict():
    ra = RaceAnalyzer()
    ra.update(_snapshot(gap_behind=700, drs=True))
    s = ra.get_state()
    assert "intensity" in s
    assert "mode" in s
    assert "threat" in s
    assert "advice" in s


def test_tyre_warning_event():
    ra = RaceAnalyzer()
    event = ra.update(_snapshot(tyre_age=35, tyre_wear=65.0))
    assert event is not None
    assert event.type == "tyre_warning"


def test_final_lap_event_in_race():
    """laps_remaining<=3 in a race → final_lap event."""
    ra = RaceAnalyzer()
    snap = _snapshot(lap=48, total=50)
    snap["session_type"] = "race"
    event = ra.update(snap)
    assert event is not None
    assert event.type == "final_lap"


def test_no_final_lap_in_practice():
    """Practice reports total_laps too (e.g. a 20-lap programme), but reaching its
    end is NOT a final lap — must be suppressed by session type."""
    ra = RaceAnalyzer()
    snap = _snapshot(lap=18, total=20)
    snap["session_type"] = "practice"
    event = ra.update(snap)
    assert event is None


def test_no_final_lap_in_qualifying():
    ra = RaceAnalyzer()
    snap = _snapshot(lap=18, total=20)
    snap["session_type"] = "qualifying"
    event = ra.update(snap)
    assert event is None


# --------------------------------------------------------------------------- #
# last_battle_active — exposes BattleDetector's real state for the defense-
# event tracker (docs/superpowers/plans/2026-07-20-defense-event-damage-
# phrase-variety.md). battle.active can be masked in the returned RaceEvent
# by a same-tick "attack" (is_threat wins the if/elif), so callers that need
# the true battle state can't rely on event.type alone.
# --------------------------------------------------------------------------- #

def test_last_battle_active_false_initially():
    ra = RaceAnalyzer()
    assert ra.last_battle_active is False


def test_last_battle_active_true_after_sustained_proximity():
    ra = RaceAnalyzer()
    for _ in range(5):
        event = ra.update(_snapshot(gap_behind=800))
    assert ra.last_battle_active is True
    # Masking confirmed: is_threat's single-snapshot check also fires on the
    # same close gap, so the RETURNED event is "attack", not "battle" — proof
    # that last_battle_active is genuinely needed, not redundant with event.type.
    assert event.type == "attack"


def test_last_battle_active_false_when_gap_large():
    ra = RaceAnalyzer()
    ra.update(_snapshot(gap_behind=3000))
    assert ra.last_battle_active is False


def test_last_battle_active_resets_on_reset_transient():
    ra = RaceAnalyzer()
    for _ in range(5):
        ra.update(_snapshot(gap_behind=800))
    assert ra.last_battle_active is True
    ra.reset_transient()
    assert ra.last_battle_active is False
