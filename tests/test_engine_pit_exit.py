"""Выезд из боксов — новое синтетическое событие PIT_EXIT (см. design spec
2026-07-05-final-laps-attacks-pitstop-design.md). Едж-детект перехода
pit_status 1/2 -> 0, только в гонке, без повторного срабатывания — тот же
паттерн проверки, что и в tests/test_engine_damage.py.
"""
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


def _drain(engine):
    while not engine._commentary_events.empty():
        engine._commentary_events.get_nowait()


def test_pit_exit_fires_on_transition_to_zero_in_race(engine):
    _drain(engine)
    engine._session_type = "race"
    engine._player_tyre_compound = "M"
    engine._maybe_announce_pit_exit(1, 0)
    evt = engine._commentary_events.get_nowait()
    assert evt["event_code"] == "PIT_EXIT"
    assert evt["tyre_compound"] == "M"


def test_pit_exit_fires_from_either_pit_status_value(engine):
    _drain(engine)
    engine._session_type = "race"
    engine._maybe_announce_pit_exit(2, 0)
    evt = engine._commentary_events.get_nowait()
    assert evt["event_code"] == "PIT_EXIT"


def test_pit_exit_carries_player_vehicle_identity(engine):
    _drain(engine)
    engine._session_type = "race"
    engine._player_car_index = 9

    engine._maybe_announce_pit_exit(1, 0)

    assert engine._commentary_events.get_nowait()["vehicle_idx"] == 9


def test_pit_exit_does_not_fire_on_entry(engine):
    _drain(engine)
    engine._session_type = "race"
    engine._maybe_announce_pit_exit(0, 1)
    assert engine._commentary_events.empty()


def test_pit_exit_does_not_fire_while_already_out(engine):
    _drain(engine)
    engine._session_type = "race"
    engine._maybe_announce_pit_exit(0, 0)
    assert engine._commentary_events.empty()


def test_pit_exit_does_not_fire_outside_race(engine):
    _drain(engine)
    engine._session_type = "practice"
    engine._maybe_announce_pit_exit(1, 0)
    assert engine._commentary_events.empty()
    engine._session_type = "race"


def test_pit_exit_does_not_refire_without_new_stop(engine):
    _drain(engine)
    engine._session_type = "race"
    engine._maybe_announce_pit_exit(1, 0)
    assert not engine._commentary_events.empty()
    _drain(engine)
    engine._maybe_announce_pit_exit(0, 0)
    assert engine._commentary_events.empty()
