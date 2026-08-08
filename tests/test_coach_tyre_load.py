"""Асимметрия износа и температур резины (core/coach_ai/tyre_load.py).

Сравнение идёт ВНУТРИ оси: у передних и задних колёс разная работа, и
«передняя левая против задней правой» ничего не значит.
"""
import pytest

from core.coach_ai.tyre_load import TyreLoadTracker


def _even():
    return {"rl": 20.0, "rr": 20.0, "fl": 20.0, "fr": 20.0}


def test_no_report_without_observations():
    assert TyreLoadTracker().report() is None


def test_even_wear_produces_no_asymmetry():
    t = TyreLoadTracker()
    t.observe(wear=_even(), surface_temp={"rl": 90, "rr": 90, "fl": 90, "fr": 90})
    rep = t.report()
    assert rep is not None
    assert rep.worst_wheel is None
    assert rep.wear_spread_pct == pytest.approx(0.0)


def test_asymmetry_is_measured_within_the_axle():
    """Передняя левая изношена сильнее передней правой — это перекос. То, что
    передние в целом изношены сильнее задних, перекосом НЕ считается."""
    t = TyreLoadTracker()
    t.observe(wear={"rl": 10.0, "rr": 10.0, "fl": 40.0, "fr": 20.0},
              surface_temp={"rl": 85, "rr": 85, "fl": 110, "fr": 95})
    rep = t.report()
    assert rep.worst_wheel == "fl"
    assert rep.worst_axle == "front"
    assert rep.wear_spread_pct == pytest.approx(20.0)


def test_front_heavier_than_rear_alone_is_not_asymmetry():
    t = TyreLoadTracker()
    t.observe(wear={"rl": 10.0, "rr": 10.0, "fl": 40.0, "fr": 40.0},
              surface_temp=None)
    rep = t.report()
    assert rep.worst_wheel is None


def test_latest_observation_wins_wear_is_monotonic():
    """Износ только растёт: отчёт должен опираться на последний снимок, а не
    на первый и не на среднее за сессию."""
    t = TyreLoadTracker()
    t.observe(wear={"rl": 5.0, "rr": 5.0, "fl": 6.0, "fr": 5.0}, surface_temp=None)
    t.observe(wear={"rl": 10.0, "rr": 10.0, "fl": 45.0, "fr": 15.0}, surface_temp=None)
    rep = t.report()
    assert rep.worst_wheel == "fl"
    assert rep.wear_spread_pct == pytest.approx(30.0)


def test_overheated_wheel_reported_from_surface_temperature():
    t = TyreLoadTracker()
    t.observe(wear=_even(),
              surface_temp={"rl": 88, "rr": 90, "fl": 128, "fr": 92})
    rep = t.report()
    assert rep.hottest_wheel == "fl"
    # Разброс считается от САМОГО холодного колеса (rl=88), а не от напарника
    # по оси: перегрев виден на фоне всей машины.
    assert rep.temp_spread_c == pytest.approx(40.0)


def test_small_temperature_spread_is_not_reported():
    t = TyreLoadTracker()
    t.observe(wear=_even(),
              surface_temp={"rl": 90, "rr": 92, "fl": 95, "fr": 93})
    assert t.report().hottest_wheel is None


def test_reset_clears_state():
    t = TyreLoadTracker()
    t.observe(wear={"rl": 10.0, "rr": 10.0, "fl": 40.0, "fr": 20.0}, surface_temp=None)
    t.reset()
    assert t.report() is None


def test_missing_wheels_are_ignored_without_crashing():
    t = TyreLoadTracker()
    t.observe(wear={"fl": 40.0}, surface_temp=None)
    assert t.report().worst_wheel is None
