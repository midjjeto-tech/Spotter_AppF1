import core.driver_of_the_day as dotd


def _lookup(table):
    return lambda idx: table.get(idx, {"name": ""})


def _grid(rows):
    # rows: (vehicle_idx, position, grid_position)
    return [{"vehicle_idx": i, "position": p, "grid_position": g} for i, p, g in rows]


_NAMES = {0: {"name": "Max"}, 1: {"name": "Norris"}, 4: {"name": "You"}, 7: {"name": "Alonso"}}


def test_biggest_climber_is_driver_of_the_day():
    grid = _grid([(0, 1, 1), (4, 4, 12), (1, 2, 2), (7, 6, 8)])  # You: 12->4 = +8
    result = dotd.compute(grid, _lookup(_NAMES), player_idx=4)
    assert result["dotd_driver"] == "You"
    assert result["dotd_gained"] == 8
    assert result["player_is_dotd"] is True
    assert result["dotd_pct"] > 0
    assert result["dotd_participants"][0] == "You"


def test_falls_back_to_winner_when_nobody_climbed():
    grid = _grid([(0, 1, 1), (1, 2, 3), (4, 3, 4)])  # nobody gained vs grid
    result = dotd.compute(grid, _lookup(_NAMES), player_idx=4)
    assert result["dotd_driver"] == "Max"  # the winner (P1)


def test_second_candidate_is_reported():
    grid = _grid([(4, 3, 12), (0, 1, 5), (1, 8, 9)])  # You +9, Max +4
    result = dotd.compute(grid, _lookup(_NAMES), player_idx=4)
    assert result["dotd_driver"] == "You"
    assert result["dotd_second_driver"] == "Max"
    assert 0 < result["dotd_second_pct"] < result["dotd_pct"]


def test_none_when_no_classified_cars():
    grid = _grid([(0, 0, 0)])  # pit/unknown only
    assert dotd.compute(grid, _lookup(_NAMES), player_idx=4) is None


def test_participants_capped_at_three():
    grid = _grid([(0, 5, 20), (1, 4, 18), (4, 3, 15), (7, 2, 12)])
    result = dotd.compute(grid, _lookup(_NAMES), player_idx=4)
    assert len(result["dotd_participants"]) == 3


def test_overtakes_contribute_to_candidate_score_and_vote_percentages_total_100():
    grid = _grid([
        (0, 1, 3),   # Max: +2 and one overtake
        (4, 2, 10),  # You: +8 and six overtakes
        (1, 3, 1),   # Norris: -2 and no overtakes
    ])

    result = dotd.compute(
        grid,
        _lookup(_NAMES),
        player_idx=4,
        overtakes_by_idx={0: 1, 4: 6},
    )

    candidates = result["dotd_candidates"]
    assert candidates[0]["driver"] == "You"
    assert candidates[0]["overtakes"] == 6
    assert candidates[0]["positions_gained"] == 8
    assert sum(candidate["vote_pct"] for candidate in candidates) == 100
    assert candidates[0]["score"] > candidates[1]["score"]


def test_fastest_lap_and_penalties_are_reflected_in_candidate_facts():
    grid = [
        {
            "vehicle_idx": 0, "position": 1, "grid_position": 2,
            "best_lap_time_ms": 80_000, "num_penalties": 2,
        },
        {
            "vehicle_idx": 4, "position": 2, "grid_position": 3,
            "best_lap_time_ms": 79_000, "num_penalties": 0,
        },
    ]

    result = dotd.compute(grid, _lookup(_NAMES), player_idx=4)
    by_driver = {candidate["driver"]: candidate
                 for candidate in result["dotd_candidates"]}

    assert by_driver["You"]["fastest_lap"] is True
    assert by_driver["You"]["penalties"] == 0
    assert by_driver["Max"]["penalties"] == 2
