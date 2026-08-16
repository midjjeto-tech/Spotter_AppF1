import pytest

from core.racefeed import predictions


def _snapshot():
    return {
        "track_id": 13,
        "player_driver": "Артём",
        "teammate_driver": "Леклер",
        "player_position": 4,
        "teammate_position": 7,
        "rain_forecast": {"minutes": 15, "rain_pct": 60, "weather": 3},
    }


def test_forecast_is_deterministic_and_explains_each_pick():
    season = [{"classification": [
        {"driver": "Артём", "position": 3},
        {"driver": "Леклер", "position": 6},
    ]}]

    first = predictions.build_model_forecast(
        _snapshot(), season_results=season, game_sessions=[]
    )
    second = predictions.build_model_forecast(
        _snapshot(), season_results=season, game_sessions=[]
    )

    assert first == second
    assert first["finish"]["choice"] == "points"
    assert first["teammate"]["choice"] == "player"
    assert first["risk"]["choice"] == "rain"
    assert first["risk"]["confidence"] == 60
    assert all(first[key]["basis"] for key in ("finish", "teammate", "risk"))


def test_ticket_requires_all_three_known_choices():
    with pytest.raises(ValueError):
        predictions.normalize_ticket({"finish": "win", "teammate": "player", "risk": "rain"})
    assert predictions.normalize_ticket({
        "finish": "podium", "teammate": "player", "risk": "rain",
    }) == {"finish": "podium", "teammate": "player", "risk": "rain"}


def test_resolve_scores_reader_and_model_from_final_classification():
    forecast = {
        "finish": {"choice": "points"},
        "teammate": {"choice": "player"},
        "risk": {"choice": "rain"},
    }
    ticket = {"finish": "podium", "teammate": "player", "risk": "safety_car"}
    grid = [
        {"vehicle_idx": 0, "position": 2, "grid_position": 5,
         "best_lap_time_ms": 80_000, "points": 18},
        {"vehicle_idx": 1, "position": 6, "grid_position": 3,
         "best_lap_time_ms": 81_000, "points": 8},
    ]
    drivers = {
        0: {"name": "Артём", "team": "Ferrari"},
        1: {"name": "Леклер", "team": "Ferrari"},
    }

    result = predictions.resolve(
        forecast, ticket, grid, drivers.get, 0,
        actual_risks={"safety_car": True, "rain": False, "penalty": False},
    )

    assert result["actual"]["finish"] == "podium"
    assert result["actual"]["teammate"] == "player"
    assert result["reader_score"] == 3
    assert result["model_score"] == 1


def test_scoreboard_only_counts_races_where_reader_submitted_a_ticket():
    rows = [
        {"status": "resolved", "result": {"reader_score": 2, "model_score": 1}},
        {"status": "resolved", "result": {"reader_score": None, "model_score": 3}},
        {"status": "locked", "result": {}},
    ]
    assert predictions.scoreboard(rows) == {"reader": 2, "model": 1, "races": 1}
