# tests/test_engine_tyre_sets.py
"""_update_tyre_sets — проводка parse_tyre_sets() в состояние движка. Пакет
ПОЦИКЛОВОЙ (один car_idx за раз), поэтому метод должен игнорировать пакеты
не про машину игрока — единственная реальная логика здесь (см.
docs/superpowers/plans/2026-07-19-tyre-sets-final-classification.md)."""
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


def test_update_tyre_sets_stores_player_data(engine):
    engine._player_car_index = 4
    parsed = {"car_idx": 4, "available_by_compound": {"S": 2, "M": 1},
              "fitted_compound": "M", "fitted_wear": 12}
    engine._update_tyre_sets(parsed)
    assert engine._player_tyre_sets_available == {"S": 2, "M": 1}
    assert engine._player_tyre_sets_fitted == {"compound": "M", "wear": 12}


def test_update_tyre_sets_ignores_other_car(engine):
    engine._player_car_index = 4
    engine._player_tyre_sets_available = {"H": 3}
    parsed = {"car_idx": 9, "available_by_compound": {"S": 5},
              "fitted_compound": "S", "fitted_wear": 0}
    engine._update_tyre_sets(parsed)
    assert engine._player_tyre_sets_available == {"H": 3}   # unchanged


def test_update_tyre_sets_ignores_empty_dict(engine):
    engine._player_car_index = 4
    engine._player_tyre_sets_available = {"H": 3}
    engine._update_tyre_sets({})
    assert engine._player_tyre_sets_available == {"H": 3}   # unchanged
