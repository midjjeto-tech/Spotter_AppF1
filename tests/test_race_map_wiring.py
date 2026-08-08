"""Проводка карты гонки: снимок на круге игрока -> эндпоинт -> файл сессии.

Карта не публикует событий и не едет в /api/state: сетка на 22 машины × 60
кругов — это больше тысячи чисел, а /api/state опрашивают восемь окон оверлея
каждые 250 мс. У неё свой эндпоинт, который дебриф читает по запросу.
"""
import pytest

import core.engine as eng_mod
from core.engine import F1Engine


@pytest.fixture
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def test_race_map_exists_and_starts_empty(engine):
    assert engine.get_race_map()["rows"] == []


def test_lap_completion_records_a_snapshot(engine):
    engine._player_car_index = 0
    engine._positions = {0: 4, 1: 1}

    engine._record_race_map_lap(lap=7, player_pit=False)

    data = engine.get_race_map()
    assert data["laps"] == [7]
    assert next(r for r in data["rows"] if r["vehicle_idx"] == 0)["is_player"] is True


def test_pit_lap_is_marked(engine):
    engine._player_car_index = 0
    engine._positions = {0: 12}

    engine._record_race_map_lap(lap=3, player_pit=True)

    assert engine.get_race_map()["pit_laps"] == [3]


def test_snapshot_without_positions_is_skipped(engine):
    engine._player_car_index = 0
    engine._positions = {}

    engine._record_race_map_lap(lap=2, player_pit=False)

    assert engine.get_race_map()["laps"] == []


def test_race_map_is_not_in_the_live_state(engine):
    """Сетка в /api/state — это лишний килобайт каждые 250 мс на восемь окон."""
    engine._player_car_index = 0
    engine._positions = {0: 1}
    engine._record_race_map_lap(lap=1, player_pit=False)

    state = engine.get_state()

    assert "race_map" not in state
    assert "race_map" not in (state.get("coach_ai") or {})


def test_race_map_publishes_nothing(engine, monkeypatch):
    drafts = []
    monkeypatch.setattr(engine._commentary_events, "publish", drafts.append)
    engine._player_car_index = 0
    engine._positions = {0: 1}

    engine._record_race_map_lap(lap=1, player_pit=False)

    assert drafts == []
