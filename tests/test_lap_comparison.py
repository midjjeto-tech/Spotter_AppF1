from core.lap_comparison import LapComparisonProgress


def _comparison(lap=80_000, sectors=None):
    return {"player_best_ms": lap, "sectors": sectors}


def test_first_observation_records_lap_and_all_sectors():
    progress = LapComparisonProgress()
    sectors = {
        1: {"player_ms": 27_000, "gap_ms": 200},
        2: {"player_ms": 28_000, "gap_ms": -300},
        3: {"player_ms": 25_000, "gap_ms": 100},
    }

    milestones = progress.observe(_comparison(sectors=sectors))

    assert milestones.lap_improved is True
    assert milestones.sector_improved == 2
    assert progress.best_sector_ms == {1: 27_000, 2: 28_000, 3: 25_000}


def test_equal_values_are_not_reannounced():
    progress = LapComparisonProgress()
    comparison = _comparison(sectors={1: {"player_ms": 27_000, "gap_ms": 100}})
    progress.observe(comparison)

    milestones = progress.observe(comparison)

    assert milestones.lap_improved is False
    assert milestones.sector_improved is None


def test_reset_forgets_previous_session_progress():
    progress = LapComparisonProgress()
    comparison = _comparison()
    progress.observe(comparison)

    progress.reset()

    assert progress.observe(comparison).lap_improved is True
