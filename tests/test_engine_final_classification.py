# tests/test_engine_final_classification.py
"""_update_final_classification — проводка parse_final_classification() в
состояние движка. См. docs/superpowers/plans/2026-07-19-tyre-sets-final-
classification.md."""
import pytest

import core.engine as eng_mod
from core.engine import F1Engine


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def test_update_final_classification_stores_state(engine):
    parsed = {"position": 5, "num_laps": 58, "grid_position": 3, "points": 10,
              "num_pit_stops": 2, "result_status": 3,
              "result_status_label": "финишировал", "best_lap_time_ms": 83456,
              "total_race_time_s": 5432.789, "penalties_time_s": 5,
              "num_penalties": 1}
    engine._update_final_classification(parsed)
    assert engine._final_classification == parsed
    assert engine.get_state()["final_classification"] == parsed


def test_update_final_classification_ignores_empty_dict(engine):
    engine._final_classification = {"position": 1}
    engine._update_final_classification({})
    assert engine._final_classification == {"position": 1}   # unchanged


def test_full_grid_dispatches_one_enriched_auto_result(engine, monkeypatch):
    calls = []
    engine._telemetry_source = "f1"
    engine._session_type = "race"
    engine._track_id = 10
    engine._game_year = 2026
    engine._reality_result_sent = False
    engine.race_state.update_drivers({
        0: {"name": "Driver", "team": "Mercedes", "team_id": 0,
            "number": 63, "color": "#fff"},
    })

    def immediate(target, *, name, args=(), task=False):
        calls.append((name, task, target(*args)))

    monkeypatch.setattr(engine, "_spawn_thread", immediate)
    monkeypatch.setattr(engine, "_maybe_record_championship", lambda grid: None)
    monkeypatch.setattr(
        eng_mod.reality_mod_bridge, "submit_final_classification",
        lambda classification, *, track_id, game_year: calls.append(
            (classification, track_id, game_year)
        ) or True,
    )

    grid = [{"vehicle_idx": 0, "position": 1, "points": 25, "result_status": 3}]
    engine._update_final_classification_grid(grid)
    engine._update_final_classification_grid(grid)

    payload_calls = [item for item in calls if isinstance(item[0], list)]
    assert len(payload_calls) == 1
    assert payload_calls[0][0][0]["team"] == "Mercedes"
    assert payload_calls[0][0][0]["team_id"] == 0
    assert payload_calls[0][1:] == (10, 2026)


def test_sprint_result_does_not_advance_auto_season(engine, monkeypatch):
    calls = []
    engine._telemetry_source = "f1"
    engine._session_type = "race"
    engine._reality_result_sent = False
    monkeypatch.setattr(engine, "_spawn_thread", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(engine, "_maybe_record_championship", lambda grid: None)

    engine._update_final_classification_grid([
        {"vehicle_idx": 0, "position": 1, "points": 8, "result_status": 3},
        {"vehicle_idx": 1, "position": 2, "points": 7, "result_status": 3},
    ])

    assert calls == []
    assert engine._reality_result_sent is False


def test_post_race_paddock_publishes_interview_then_structured_vote(
    engine, monkeypatch
):
    drafts = []
    monkeypatch.setattr(
        engine._commentary_events,
        "publish",
        lambda draft: drafts.append(draft),
    )
    engine._player_car_index = 4
    engine.race_state.update_drivers({
        0: {"name": "Max", "team": "Red Bull", "color": "#3671C6"},
        4: {"name": "You", "team": "Ferrari", "color": "#E8002D"},
        5: {"name": "Leclerc", "team": "Ferrari", "color": "#E8002D"},
        7: {"name": "Alonso", "team": "Aston Martin", "color": "#229971"},
    })
    engine._race_overtakes_by_driver = {4: 6, 7: 3}
    grid = [
        {
            "vehicle_idx": 0, "position": 1, "grid_position": 1,
            "best_lap_time_ms": 80_000, "num_penalties": 0,
        },
        {
            "vehicle_idx": 4, "position": 2, "grid_position": 10,
            "best_lap_time_ms": 79_000, "num_penalties": 0, "points": 18,
        },
        {
            "vehicle_idx": 7, "position": 3, "grid_position": 6,
            "best_lap_time_ms": 81_000, "num_penalties": 0,
        },
        {
            "vehicle_idx": 5, "position": 5, "grid_position": 4,
            "best_lap_time_ms": 79_500, "num_penalties": 0, "points": 10,
        },
    ]

    engine._publish_post_race_paddock(grid)

    assert [draft["event_code"] for draft in drafts] == [
        "RACE_RECAP", "POST_RACE_INTERVIEW", "RACEFEED_DOTD",
    ]
    assert drafts[0]["race_recap"]["positions_gained"] == 8
    assert drafts[0]["race_recap"]["overtakes"] == 6
    assert drafts[0]["weekend_duel"]["teammate"]["driver"] == "Leclerc"
    assert drafts[0]["weekend_duel"]["player_score"] == 3
    assert drafts[1]["interview_quotes"]
    assert drafts[2]["dotd_candidates"][0]["driver"] == "You"
    assert drafts[2]["dotd_candidates"][0]["overtakes"] == 6
