import core.race_recap as race_recap


def _lookup(idx):
    return {
        0: {"name": "Max"},
        4: {"name": "You"},
    }.get(idx, {})


def test_build_uses_final_classification_and_observed_overtakes():
    facts = race_recap.build(
        [
            {
                "vehicle_idx": 0, "position": 1, "grid_position": 1,
                "points": 25, "best_lap_time_ms": 80_000,
            },
            {
                "vehicle_idx": 4, "position": 2, "grid_position": 10,
                "points": 18, "num_pit_stops": 2, "num_penalties": 1,
                "best_lap_time_ms": 79_000,
            },
        ],
        _lookup,
        4,
        overtakes_by_idx={4: 6},
    )

    assert facts["race_recap"] == {
        "driver": "You",
        "finish_position": 2,
        "grid_position": 10,
        "positions_gained": 8,
        "overtakes": 6,
        "points": 18,
        "pit_stops": 2,
        "fastest_lap": True,
        "penalties": 1,
    }
    assert facts["finish_position"] == 2


def test_build_returns_none_without_a_classified_named_player():
    assert race_recap.build(
        [{"vehicle_idx": 4, "position": 0}], _lookup, 4
    ) is None
    assert race_recap.build(
        [{"vehicle_idx": 7, "position": 1}], _lookup, 4
    ) is None
