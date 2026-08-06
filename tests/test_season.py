import core.season as season


def _race(rows):
    return {"classification": rows}


def _driver_lookup(table):
    return lambda idx: table.get(idx, {"name": "гонщик", "team": "", "color": "#9CA3AF"})


def test_build_classification_flags_player_and_reads_points():
    grid = [
        {"vehicle_idx": 0, "position": 1, "points": 25},
        {"vehicle_idx": 4, "position": 2, "points": 18},
    ]
    lookup = _driver_lookup({0: {"name": "Max", "team": "Red Bull", "color": "#3671C6"},
                             4: {"name": "Norris", "team": "McLaren", "color": "#FF8000"}})
    rows = season.build_classification(grid, lookup, player_idx=4)
    assert rows[0] == {"position": 1, "points": 25, "driver": "Max",
                       "team": "Red Bull", "color": "#3671C6", "is_player": False}
    assert rows[1]["is_player"] is True


def test_build_classification_skips_placeholder_driver_names():
    grid = [
        {"vehicle_idx": 0, "position": 1, "points": 25},
        {"vehicle_idx": 4, "position": 2, "points": 18},
    ]
    lookup = _driver_lookup({
        0: {"name": "Driver", "team": "Mercedes", "color": "#00A19C"},
        4: {"name": "Шарль Леклер", "team": "Ferrari", "color": "#E8002D"},
    })

    rows = season.build_classification(grid, lookup, player_idx=4)

    assert [row["driver"] for row in rows] == ["Шарль Леклер"]
    assert rows[0]["is_player"] is True


def test_compute_standings_sums_points_by_driver(monkeypatch):
    monkeypatch.setattr(season.archive, "list_season_results", lambda limit=None: [
        _race([{"driver": "Max", "points": 25, "team": "Red Bull", "position": 1, "is_player": False},
               {"driver": "You", "points": 18, "team": "Ferrari", "position": 2, "is_player": True}]),
        _race([{"driver": "Max", "points": 18, "team": "Red Bull", "position": 2, "is_player": False},
               {"driver": "You", "points": 25, "team": "Ferrari", "position": 1, "is_player": True}]),
    ])
    result = season.compute_standings()
    assert result["races_counted"] == 2
    table = result["standings"]
    assert [r["driver"] for r in table] == ["Max", "You"]  # 43==43, 1 win each -> name
    assert table[0]["points"] == 43 and table[1]["points"] == 43
    assert table[0]["position"] == 1 and table[1]["position"] == 2
    assert any(r["is_player"] for r in table)


def test_compute_standings_ignores_legacy_placeholder_only_races(monkeypatch):
    monkeypatch.setattr(season.archive, "list_season_results", lambda limit=None: [
        _race([{
            "driver": "Driver", "points": 25, "team": "Mercedes",
            "position": 1, "is_player": False,
        }]),
        _race([
            {
                "driver": "Шарль Леклер", "points": 25, "team": "Ferrari",
                "position": 1, "is_player": True,
            },
            {
                "driver": "Ландо Норрис", "points": 18, "team": "McLaren",
                "position": 2, "is_player": False,
            },
        ]),
    ])

    result = season.compute_standings()

    assert result["races_counted"] == 1
    assert [row["driver"] for row in result["standings"]] == [
        "Шарль Леклер", "Ландо Норрис",
    ]


def test_placeholder_records_do_not_consume_the_sliding_window(monkeypatch):
    records = [
        _race([{"driver": "Driver", "points": 25, "position": 1}]),
        _race([{
            "driver": "Шарль Леклер", "points": 18, "position": 2,
            "is_player": True,
        }]),
        _race([{"driver": "Ландо Норрис", "points": 25, "position": 1}]),
    ]
    monkeypatch.setattr(
        season.archive,
        "list_season_results",
        lambda limit=None: records if limit is None else records[:limit],
    )

    result = season.compute_standings(window=1)

    assert result["races_counted"] == 1
    assert [row["driver"] for row in result["standings"]] == ["Шарль Леклер"]


def test_compute_standings_none_when_store_empty(monkeypatch):
    monkeypatch.setattr(season.archive, "list_season_results", lambda limit=None: [])
    assert season.compute_standings() is None


def test_pick_rival_returns_driver_ahead():
    table = [{"driver": "Max", "points": 50, "is_player": False, "position": 1},
             {"driver": "You", "points": 40, "is_player": True, "position": 2},
             {"driver": "Norris", "points": 30, "is_player": False, "position": 3}]
    assert season.pick_rival(table)["driver"] == "Max"


def test_pick_rival_when_player_leads_returns_driver_behind():
    table = [{"driver": "You", "points": 50, "is_player": True, "position": 1},
             {"driver": "Max", "points": 40, "is_player": False, "position": 2}]
    assert season.pick_rival(table)["driver"] == "Max"


def test_pick_rival_none_when_player_alone():
    assert season.pick_rival([{"driver": "You", "points": 10, "is_player": True, "position": 1}]) is None


def test_season_summary_shape(monkeypatch):
    monkeypatch.setattr(season.archive, "list_season_results", lambda limit=None: [
        _race([{"driver": "Max", "points": 50, "team": "Red Bull", "position": 1, "is_player": False},
               {"driver": "You", "points": 40, "team": "Ferrari", "position": 2, "is_player": True}]),
    ])
    summary = season.season_summary(race_points=18)
    assert summary["player_points"] == 40
    assert summary["player_position"] == 2
    assert summary["rival"] == "Max"
    assert summary["rival_position"] == 1
    assert summary["gap_to_rival"] == 10
    assert summary["race_points"] == 18
    assert summary["races_counted"] == 1


def test_season_summary_none_when_player_not_classified(monkeypatch):
    monkeypatch.setattr(season.archive, "list_season_results", lambda limit=None: [
        _race([{"driver": "Max", "points": 25, "team": "Red Bull", "position": 1, "is_player": False}]),
    ])
    assert season.season_summary() is None


def test_season_storylines_continue_rivalry_podium_and_points_streaks(monkeypatch):
    monkeypatch.setattr(season.archive, "list_season_results", lambda limit=None: [
        _race([
            {"driver": "You", "points": 18, "position": 2, "is_player": True},
            {"driver": "Max", "points": 15, "position": 3, "is_player": False},
        ]),
        _race([
            {"driver": "You", "points": 25, "position": 1, "is_player": True},
            {"driver": "Max", "points": 18, "position": 2, "is_player": False},
        ]),
        _race([
            {"driver": "You", "points": 15, "position": 3, "is_player": True},
            {"driver": "Max", "points": 12, "position": 4, "is_player": False},
        ]),
    ])

    storylines = season.season_storylines("Max")

    assert [row["id"] for row in storylines] == [
        "rivalry", "podium_streak", "points_streak",
    ]
    assert storylines[0]["value"] == "3:0"
    assert storylines[1]["value"] == "3 подряд"
    assert storylines[2]["value"] == "3 гонки"


def test_season_storylines_detects_fact_based_comeback(monkeypatch):
    monkeypatch.setattr(season.archive, "list_season_results", lambda limit=None: [
        _race([{"driver": "You", "points": 18, "position": 2, "is_player": True}]),
        _race([{"driver": "You", "points": 1, "position": 10, "is_player": True}]),
    ])

    storylines = season.season_storylines(None)

    assert storylines == [{
        "id": "comeback", "title": "Ответ после прошлого этапа",
        "value": "P10 → P2", "detail": "Прогресс на 8 позиций",
        "tone": "green",
    }]


def test_return_hook_uses_real_championship_gap_and_podium_stake():
    hook = season.return_hook(
        {
            "player_position": 2, "rival_position": 1,
            "rival": "Max", "gap_to_rival": 10,
        },
        [{"id": "podium_streak", "value": "3 подряд"}],
    )

    assert hook == {
        "title": "До Max — 10 очков",
        "detail": "Следующая гонка продолжит эту дуэль. На кону серия: 3 подряд.",
    }


def test_return_hook_handles_equal_championship_points():
    hook = season.return_hook(
        {
            "player_position": 2, "player_points": 120,
            "rival": "Max", "rival_position": 1, "rival_points": 120,
            "gap_to_rival": 0,
        },
        [],
    )

    assert hook == {
        "title": "С Max — поровну",
        "detail": "Следующая гонка решит, кто перехватит инициативу.",
    }


def test_best_result_is_players_lowest_position(monkeypatch):
    monkeypatch.setattr(season.archive, "list_season_results", lambda limit=None: [
        _race([{"driver": "You", "points": 25, "position": 1, "is_player": True}]),
        _race([{"driver": "You", "points": 12, "position": 6, "is_player": True}]),
    ])
    assert season.best_result() == 1


def test_best_result_none_when_player_never_classified(monkeypatch):
    monkeypatch.setattr(season.archive, "list_season_results", lambda limit=None: [
        _race([{"driver": "Max", "points": 25, "position": 1, "is_player": False}]),
    ])
    assert season.best_result() is None


def test_race_head_to_head_rival_ahead():
    classification = [
        {"driver": "Max", "position": 1, "is_player": False},
        {"driver": "You", "position": 3, "is_player": True},
    ]
    assert season.race_head_to_head(classification, "Max") == {
        "rival_race_position": 1, "player_race_position": 3, "rival_ahead": True}


def test_race_head_to_head_player_ahead():
    classification = [
        {"driver": "You", "position": 2, "is_player": True},
        {"driver": "Max", "position": 5, "is_player": False},
    ]
    assert season.race_head_to_head(classification, "Max")["rival_ahead"] is False


def test_race_head_to_head_none_when_rival_absent():
    classification = [{"driver": "You", "position": 1, "is_player": True}]
    assert season.race_head_to_head(classification, "Max") is None
