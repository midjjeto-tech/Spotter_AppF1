import core.weekend_duel as weekend_duel


def _lookup(idx):
    return {
        4: {"name": "Ландо Норрис", "team": "McLaren"},
        5: {"name": "Оскар Пиастри", "team": "McLaren"},
        7: {"name": "Фернандо Алонсо", "team": "Aston Martin"},
    }.get(idx, {})


def test_build_compares_player_and_teammate_across_four_metrics():
    duel = weekend_duel.build([
        {
            "vehicle_idx": 4, "grid_position": 10, "position": 2,
            "best_lap_time_ms": 79_000, "points": 18,
        },
        {
            "vehicle_idx": 5, "grid_position": 4, "position": 6,
            "best_lap_time_ms": 79_400, "points": 8,
        },
        {"vehicle_idx": 7, "grid_position": 3, "position": 3},
    ], _lookup, 4)

    assert duel["team"] == "McLaren"
    assert duel["player"]["driver"] == "Ландо Норрис"
    assert duel["teammate"]["driver"] == "Оскар Пиастри"
    assert duel["player_score"] == 3
    assert duel["teammate_score"] == 1
    assert duel["winner"] == "player"


def test_build_returns_none_without_a_resolved_teammate():
    assert weekend_duel.build([
        {"vehicle_idx": 4, "grid_position": 1, "position": 1},
        {"vehicle_idx": 7, "grid_position": 2, "position": 2},
    ], _lookup, 4) is None
