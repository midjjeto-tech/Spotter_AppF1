import core.post_race_interview as interview


def _lookup(table):
    return lambda idx: table.get(idx, {"name": ""})


_NAMES = {
    0: {"name": "Max"},
    4: {"name": "You"},
    7: {"name": "Alonso"},
}


def test_build_selects_winner_vote_leader_and_player_without_duplicates():
    grid = [
        {"vehicle_idx": 0, "position": 1, "grid_position": 1},
        {"vehicle_idx": 7, "position": 2, "grid_position": 10},
        {"vehicle_idx": 4, "position": 5, "grid_position": 8},
    ]
    vote = {
        "dotd_driver": "Alonso",
        "dotd_candidates": [
            {
                "driver": "Alonso", "vehicle_idx": 7, "position": 2,
                "positions_gained": 8, "overtakes": 5,
            },
        ],
    }

    result = interview.build(
        grid, _lookup(_NAMES), player_idx=4,
        vote=vote, overtakes_by_idx={7: 5, 4: 2},
    )

    quotes = result["interview_quotes"]
    assert [quote["driver"] for quote in quotes] == ["Max", "Alonso", "You"]
    assert quotes[0]["role"] == "победитель"
    assert quotes[1]["overtakes"] == 5
    assert all(quote["quote"] for quote in quotes)


def test_build_deduplicates_driver_who_is_winner_vote_leader_and_player():
    grid = [
        {"vehicle_idx": 4, "position": 1, "grid_position": 4},
        {"vehicle_idx": 0, "position": 2, "grid_position": 1},
    ]
    vote = {
        "dotd_driver": "You",
        "dotd_candidates": [{
            "driver": "You", "vehicle_idx": 4, "position": 1,
            "positions_gained": 3, "overtakes": 4,
        }],
    }

    result = interview.build(
        grid, _lookup(_NAMES), player_idx=4,
        vote=vote, overtakes_by_idx={4: 4},
    )

    assert [quote["driver"] for quote in result["interview_quotes"]] == [
        "You", "Max",
    ]


def test_build_returns_none_without_usable_classified_drivers():
    assert interview.build(
        [{"vehicle_idx": 0, "position": 0, "grid_position": 0}],
        _lookup({}),
        player_idx=4,
        vote=None,
    ) is None
