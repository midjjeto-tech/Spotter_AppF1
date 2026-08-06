"""_update_session_history + _nearest_rival_idx + сектор-сравнение в гэп-
дайджесте. Пакет ПОЦИКЛОВОЙ (один car_idx за раз, включая игрока — в
отличие от Tyre Sets, здесь нужны данные СОПЕРНИКОВ, поэтому кэшируем
каждую машину, не только игрока). См. docs/superpowers/plans/2026-07-20-
session-history-sector-comparison.md.
"""
import time

import pytest

import core.engine as eng_mod
from core.engine import F1Engine, SPEAKER_ENGINEER
from tests.telemetry import set_connection


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _drain(engine):
    drained = []
    while not engine._commentary_events.empty():
        drained.append(engine._commentary_events.get_nowait())
    return drained


def test_update_session_history_caches_by_car_idx(engine):
    parsed = {"car_idx": 5, "num_laps": 10, "best_lap_ms": 88000,
              "best_sector_ms": {1: 28000, 2: 29000, 3: 31000}, "tyre_stints": []}
    engine._update_session_history(parsed)
    assert engine._session_history[5] == parsed


def test_update_session_history_caches_player_car_too(engine):
    """В отличие от Tyre Sets, здесь НЕТ фильтра "только игрок" — пакет
    цикличен по всем машинам, и данные соперников — весь смысл фичи."""
    engine._player_car_index = 0
    parsed = {"car_idx": 0, "num_laps": 10, "best_lap_ms": 87000,
              "best_sector_ms": {1: 27500}, "tyre_stints": []}
    engine._update_session_history(parsed)
    assert engine._session_history[0] == parsed


def test_update_session_history_ignores_empty_dict(engine):
    engine._session_history[3] = {"car_idx": 3, "num_laps": 1,
                                   "best_lap_ms": 90000, "best_sector_ms": {},
                                   "tyre_stints": []}
    engine._update_session_history({})
    assert engine._session_history[3]["num_laps"] == 1   # unchanged


def test_flashback_resets_session_history(engine):
    engine._session_history[9] = {"car_idx": 9}
    engine._handle_flashback()
    assert engine._session_history == {}


# --- _nearest_rival_idx ---

def test_nearest_rival_idx_picks_smaller_gap_ahead(engine):
    engine._player_car_index = 0
    engine._player_pos = 3
    engine._positions = {0: 3, 1: 2, 2: 4}
    engine._player_gap_front = 500
    engine._player_gap_behind = 2000
    try:
        assert engine._nearest_rival_idx() == 1   # ahead, smaller gap
    finally:
        engine._positions = {}
        engine._player_pos = None
        engine._player_gap_front = None
        engine._player_gap_behind = None


def test_nearest_rival_idx_picks_smaller_gap_behind(engine):
    engine._player_car_index = 0
    engine._player_pos = 3
    engine._positions = {0: 3, 1: 2, 2: 4}
    engine._player_gap_front = 3000
    engine._player_gap_behind = 400
    try:
        assert engine._nearest_rival_idx() == 2   # behind, smaller gap
    finally:
        engine._positions = {}
        engine._player_pos = None
        engine._player_gap_front = None
        engine._player_gap_behind = None


def test_nearest_rival_idx_falls_back_to_only_known_side(engine):
    engine._player_car_index = 0
    engine._player_pos = 1
    engine._positions = {0: 1, 1: 2}
    engine._player_gap_front = None
    engine._player_gap_behind = 1200
    try:
        assert engine._nearest_rival_idx() == 1
    finally:
        engine._positions = {}
        engine._player_pos = None
        engine._player_gap_behind = None


def test_nearest_rival_idx_none_when_no_neighbors(engine):
    engine._player_car_index = 0
    engine._player_pos = None
    engine._positions = {}
    assert engine._nearest_rival_idx() is None


# --- full pipeline: _maybe_emit_gap_digest includes sector comparison ---

def test_gap_digest_includes_sector_comparison_when_both_cached(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "race"
    engine._session_active = True
    engine._race_engineer.gap_digest_tracker.reset()
    engine._player_car_index = 0
    engine._player_pos = 3
    engine._positions = {0: 3, 1: 2}
    engine._player_gap_front = 1500
    engine._player_gap_behind = None
    engine._session_history[0] = {"car_idx": 0, "best_sector_ms": {2: 29500}}
    engine._session_history[1] = {"car_idx": 1, "best_sector_ms": {2: 30200}}
    set_connection(engine, True)
    _drain(engine)
    try:
        fired = engine._maybe_emit_gap_digest(time.time())
        assert fired is True
        drained = _drain(engine)
        found = [e for e in drained if e["event_code"] == "ENGINEER_GAP_DIGEST"]
        assert len(found) == 1
        assert "секторе" in found[0]["phrase"]
        assert found[0]["speaker"] == SPEAKER_ENGINEER
    finally:
        engine._positions = {}
        engine._player_pos = None
        engine._player_gap_front = None
        engine._session_history.clear()
        engine._session_type = "unknown"
        engine._session_active = False


def test_gap_digest_omits_sector_comparison_when_rival_not_cached(engine):
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "race"
    engine._session_active = True
    engine._race_engineer.gap_digest_tracker.reset()
    engine._player_car_index = 0
    engine._player_pos = 3
    engine._positions = {0: 3, 1: 2}
    engine._player_gap_front = 1500
    engine._player_gap_behind = None
    engine._session_history.clear()   # соперник ещё не кэширован (поцикловый пакет)
    set_connection(engine, True)
    _drain(engine)
    try:
        fired = engine._maybe_emit_gap_digest(time.time())
        assert fired is True
        drained = _drain(engine)
        found = [e for e in drained if e["event_code"] == "ENGINEER_GAP_DIGEST"]
        assert len(found) == 1
        assert "секторе" not in found[0]["phrase"]
    finally:
        engine._positions = {}
        engine._player_pos = None
        engine._player_gap_front = None
        engine._session_type = "unknown"
        engine._session_active = False
