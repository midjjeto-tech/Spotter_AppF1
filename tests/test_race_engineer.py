from core.race_engineer import RaceEngineer


def test_reset_clears_gap_and_rain_observations_together():
    engineer = RaceEngineer()
    engineer.gap_digest(1000, None)
    assert engineer.rain_advisory(
        {"minutes": 5, "rain_pct": 80, "weather": 5}
    ) is not None

    engineer.reset("session_ended")

    # Fresh measurements must not inherit a trend or armed rain advisory.
    assert "стабилен" not in engineer.gap_digest(1000, None)
    assert engineer.rain_advisory(
        {"minutes": 5, "rain_pct": 80, "weather": 5}
    ) is not None


def test_position_tracker_is_available_only_through_owned_interface():
    engineer = RaceEngineer()
    engineer.note_own_pit_exit(5, 100.0)

    assert engineer.position_advisory(6, 101.0) is None

    engineer.reset("flashback")
    assert engineer.position_advisory(6, 102.0) is None
