# tests/test_engine_damage.py
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


def test_event_involves_collision_either_side(engine):
    event = {"event_code": "COLL", "vehicle1_idx": 3, "vehicle2_idx": 7}
    assert engine._event_involves(event, 3) is True
    assert engine._event_involves(event, 7) is True
    assert engine._event_involves(event, 12) is False


def test_damage_state_updates_every_tick(engine):
    engine._damage_announced = {"wing": False, "floor": False, "gearbox": False, "engine": False}
    dmg = {"wing_damage": 5, "floor_damage": 3, "gearbox_damage": 0, "engine_damage": 0}
    engine._update_damage(dmg)
    state = engine.get_state().get("damage")
    assert state == {"wing_damage": 5, "floor_damage": 3, "gearbox_damage": 0, "engine_damage": 0}


def test_damage_voice_fires_once_on_threshold_cross(engine):
    engine._damage_announced = {"wing": False, "floor": False, "gearbox": False, "engine": False}
    while not engine._commentary_events.empty():
        engine._commentary_events.get_nowait()

    engine._update_damage({"wing_damage": 25, "floor_damage": 0, "gearbox_damage": 0, "engine_damage": 0})
    evt = engine._commentary_events.get_nowait()
    assert evt["event_code"] == "DAMAGE_WING"
    assert "крыло" in evt["phrase"].lower()
    assert engine._damage_announced["wing"] is True

    # тот же тик снова >= порога -> тишина (флаг уже True)
    engine._update_damage({"wing_damage": 30, "floor_damage": 0, "gearbox_damage": 0, "engine_damage": 0})
    assert engine._commentary_events.empty()


def test_damage_voice_silent_below_threshold(engine):
    engine._damage_announced = {"wing": False, "floor": False, "gearbox": False, "engine": False}
    while not engine._commentary_events.empty():
        engine._commentary_events.get_nowait()
    engine._update_damage({"wing_damage": 19, "floor_damage": 0, "gearbox_damage": 0, "engine_damage": 0})
    assert engine._commentary_events.empty()
    assert engine._damage_announced["wing"] is False


def test_damage_voice_refires_after_repair_and_new_damage(engine):
    engine._damage_announced = {"wing": True, "floor": False, "gearbox": False, "engine": False}
    while not engine._commentary_events.empty():
        engine._commentary_events.get_nowait()

    # ремонт в боксах -> падает ниже порога -> флаг сбрасывается, тишина
    engine._update_damage({"wing_damage": 0, "floor_damage": 0, "gearbox_damage": 0, "engine_damage": 0})
    assert engine._commentary_events.empty()
    assert engine._damage_announced["wing"] is False

    # новая поломка того же крыла -> объявляется заново
    engine._update_damage({"wing_damage": 45, "floor_damage": 0, "gearbox_damage": 0, "engine_damage": 0})
    evt = engine._commentary_events.get_nowait()
    assert evt["event_code"] == "DAMAGE_WING"
    assert engine._damage_announced["wing"] is True


def test_damage_voice_fires_independently_per_category(engine):
    engine._damage_announced = {"wing": False, "floor": False, "gearbox": False, "engine": False}
    while not engine._commentary_events.empty():
        engine._commentary_events.get_nowait()

    engine._update_damage({"wing_damage": 25, "floor_damage": 25, "gearbox_damage": 0, "engine_damage": 0})
    events = []
    while not engine._commentary_events.empty():
        events.append(engine._commentary_events.get_nowait())
    codes = {e["event_code"] for e in events}
    assert codes == {"DAMAGE_WING", "DAMAGE_FLOOR"}


# --------------------------------------------------------------------------- #
# Phrase variety (item 6 backlog: "формат комментариев" -> was one fixed
# string per category, no variation). See docs/superpowers/plans/2026-07-20-
# defense-event-damage-phrase-variety.md.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("category, damage_key, event_code", [
    ("wing", "wing_damage", "DAMAGE_WING"),
    ("floor", "floor_damage", "DAMAGE_FLOOR"),
    ("gearbox", "gearbox_damage", "DAMAGE_GEARBOX"),
    ("engine", "engine_damage", "DAMAGE_ENGINE"),
])
def test_damage_phrase_drawn_from_pool(engine, category, damage_key, event_code):
    """Вариативность теперь измеряется МЕЖДУ ситуациями, а не между повторами
    одной.

    Раньше выбор был случайным (`pick_phrase`), и тест гонял одно и то же
    повреждение 30 раз, ожидая разные строки. С переходом на банк выбор стал
    детерминированным по `dedupe_key`: одна ситуация — одна формулировка, чтобы
    повторный пакет телеметрии не переписывал уже произнесённую реплику. Поэтому
    30 повторов ОДНОГО повреждения на одном круге обязаны дать одну строку, а
    разные круги — разные."""
    from core.radio import phrases as radio_phrases

    spec = radio_phrases.spec_for(f"damage.{category}")

    def announce(lap):
        engine._player_lap = lap
        engine._damage_announced = {"wing": False, "floor": False,
                                    "gearbox": False, "engine": False}
        while not engine._commentary_events.empty():
            engine._commentary_events.get_nowait()
        engine._update_damage({"wing_damage": 0, "floor_damage": 0,
                               "gearbox_damage": 0, "engine_damage": 0,
                               damage_key: 45})
        evt = engine._commentary_events.get_nowait()
        assert evt["event_code"] == event_code
        assert evt["phrase"] in spec.variants
        return evt["phrase"]

    # Одна ситуация: формулировка закреплена.
    same_situation = {announce(12) for _ in range(10)}
    assert len(same_situation) == 1

    # Разные ситуации: банк отдаёт разные варианты.
    across_laps = {announce(lap) for lap in range(1, 40)}
    assert len(across_laps) > 1
