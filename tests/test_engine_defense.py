"""Проводка DefenseTracker: race_analyzer.last_battle_active -> _defense_tick(),
только race, подавление после реального обгона игрока, сброс на
SSTA/flashback/CHQF. См. docs/superpowers/plans/2026-07-20-defense-event-
damage-phrase-variety.md.
"""
import time

import pytest

import core.engine as eng_mod
from core.engine import F1Engine, SPEAKER_ENGINEER


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


def _reset(engine):
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "race"
    engine._race_engineer.defense_tracker.reset()
    engine._last_overtaken_t = 0.0
    engine.race_analyzer.last_battle_active = False
    _drain(engine)


def test_defense_tick_fires_on_battle_edge(engine, monkeypatch):
    _reset(engine)
    monkeypatch.setattr(time, "time", lambda: 9000.0)
    engine.race_analyzer.last_battle_active = True
    engine._defense_tick()
    _drain(engine)

    monkeypatch.setattr(time, "time", lambda: 9001.0)
    engine.race_analyzer.last_battle_active = False
    engine._defense_tick()
    drained = _drain(engine)
    found = [e for e in drained if e["event_code"] == "DEFENSE"]
    assert len(found) == 1
    assert found[0]["speaker"] == SPEAKER_ENGINEER


def test_defense_tick_gated_outside_race(engine, monkeypatch):
    _reset(engine)
    engine._session_type = "qualifying"
    monkeypatch.setattr(time, "time", lambda: 9100.0)
    engine.race_analyzer.last_battle_active = True
    engine._defense_tick()
    monkeypatch.setattr(time, "time", lambda: 9101.0)
    engine.race_analyzer.last_battle_active = False
    engine._defense_tick()
    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"] == "DEFENSE"]
    engine._session_type = "race"


def test_defense_tick_suppressed_after_player_overtaken(engine, monkeypatch):
    _reset(engine)
    monkeypatch.setattr(time, "time", lambda: 9200.0)
    engine.race_analyzer.last_battle_active = True
    engine._defense_tick()
    _drain(engine)

    engine._last_overtaken_t = 9200.5   # игрока обогнали во время борьбы
    monkeypatch.setattr(time, "time", lambda: 9201.0)
    engine.race_analyzer.last_battle_active = False
    engine._defense_tick()
    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"] == "DEFENSE"]


def test_defense_tick_respects_engineer_chatter_toggle(engine, monkeypatch):
    _reset(engine)
    engine.settings["engineer_chatter_enabled"] = False
    monkeypatch.setattr(time, "time", lambda: 9300.0)
    engine.race_analyzer.last_battle_active = True
    engine._defense_tick()
    monkeypatch.setattr(time, "time", lambda: 9301.0)
    engine.race_analyzer.last_battle_active = False
    engine._defense_tick()
    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"] == "DEFENSE"]
    engine.settings["engineer_chatter_enabled"] = True


def test_flashback_resets_defense(engine, monkeypatch):
    calls = []
    monkeypatch.setattr(engine._race_engineer.defense_tracker, "reset", lambda: calls.append(True))
    engine._handle_flashback()
    assert calls == [True]
