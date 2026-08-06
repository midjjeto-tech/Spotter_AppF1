import core.milestones as milestones


def _sessions(positions):
    """Newest-first race sessions from a list of final positions (index 0 = latest)."""
    return [{"session_type": "race", "final_position": p} for p in positions]


def test_first_win_fires_on_debut_victory():
    m = milestones.detect(_sessions([1, 4, 7]))
    assert m["milestone"] == "first_win"
    assert m["position"] == 1


def test_repeat_win_is_not_first_win():
    # already won before (P1 in history) → not a first win; P1 again isn't a
    # strict career-best either, and no streak trigger → nothing
    m = milestones.detect(_sessions([1, 1, 5]))
    assert m is None


def test_first_podium_fires_when_no_prior_podium():
    m = milestones.detect(_sessions([3, 8, 10]))
    assert m["milestone"] == "first_podium"


def test_first_win_beats_first_podium_priority():
    m = milestones.detect(_sessions([1, 8, 9]))  # also the first podium ever
    assert m["milestone"] == "first_win"


def test_career_best_when_strictly_better_than_all_previous():
    m = milestones.detect(_sessions([4, 6, 5, 8]))  # best-ever P4, prev best was 5
    assert m["milestone"] == "career_best"
    assert m["position"] == 4


def test_no_career_best_when_not_improved():
    m = milestones.detect(_sessions([6, 4, 5]))  # P6 now, already had P4 — not better
    assert m is None


def test_career_best_needs_a_previous_race():
    # first race ever finishing P4 is a first-anything only if it's a podium/win;
    # P4 debut is neither → no milestone (career_best requires prior races)
    assert milestones.detect(_sessions([4])) is None


def test_podium_streak_fires_at_three():
    m = milestones.detect(_sessions([2, 3, 1, 9]))  # 3 podiums in a row, but P2 isn't career-best (had P1)
    assert m["milestone"] == "podium_streak"
    assert m["streak"] == 3


def test_points_streak_fires_at_five():
    m = milestones.detect(_sessions([7, 8, 6, 9, 10, 15]))  # 5 straight points finishes
    assert m["milestone"] == "points_streak"
    assert m["streak"] == 5


def test_race_milestone_on_round_count():
    # 10th career race, this finish (P8) is worse than a prior P5 → not a
    # career-best, no streak → the round-number race is what fires
    m = milestones.detect(_sessions([8, 5] + [15] * 8))
    assert m["milestone"] == "race_milestone"
    assert m["race_count"] == 10


def test_none_when_nothing_notable():
    # P11 now, a prior P8 exists (not a career-best), no streak, not a round race
    assert milestones.detect(_sessions([11, 8, 9])) is None


def test_none_on_empty_history():
    assert milestones.detect([]) is None
