# tests/test_race_state.py
from core.race_state import RaceState


def _make_state():
    s = RaceState()
    s.update_drivers({
        3: {"name": "Ферстаппен", "team": "Red Bull", "color": "#3671C6"},
        7: {"name": "Хэмилтон", "team": "Ferrari", "color": "#E80020"},
    })
    return s


def test_enrich_vehicle_idx_event():
    s = _make_state()
    out = s.enrich({"event_code": "RTMT", "vehicle_idx": 3})
    assert out["driver"] == "Ферстаппен"
    assert out["team"] == "Red Bull"
    assert out["color"] == "#3671C6"


def test_enrich_overtake_event():
    s = _make_state()
    out = s.enrich({"event_code": "OVTK", "overtaking_idx": 3, "being_overtaken_idx": 7})
    assert out["driver"] == "Ферстаппен"
    assert out["target"] == "Хэмилтон"


def test_enrich_collision_event_resolves_both_names():
    s = _make_state()
    out = s.enrich({"event_code": "COLL", "vehicle1_idx": 3, "vehicle2_idx": 7})
    assert out["driver"] == "Ферстаппен"
    assert out["team"] == "Red Bull"
    assert out["color"] == "#3671C6"
    assert out["target"] == "Хэмилтон"
    assert out["target_team"] == "Ferrari"


def test_enrich_collision_unknown_vehicle_falls_back_gracefully():
    s = _make_state()
    out = s.enrich({"event_code": "COLL", "vehicle1_idx": 3, "vehicle2_idx": 99})
    assert out["driver"] == "Ферстаппен"
    assert out["target"] == "гонщик"    # неизвестный vehicle_idx -> дефолт RaceState.driver()


def test_enrich_collision_does_not_set_battle_flag():
    """battle — понятие только для повторяющихся обгонов (OVTK), не для аварий."""
    s = _make_state()
    out = s.enrich({"event_code": "COLL", "vehicle1_idx": 3, "vehicle2_idx": 7})
    assert out["battle"] is False


def test_count_recent_overtakes_zero_when_no_history():
    s = _make_state()
    assert s._count_recent_overtakes(3, 7) == 0


def test_count_recent_overtakes_counts_both_directions():
    """Обгон в любую сторону между той же парой считается — пара сравнивается
    как frozenset, направление не важно для счётчика затяжной борьбы."""
    s = _make_state()
    s.record_event({"event_code": "OVTK", "overtaking_idx": 3, "being_overtaken_idx": 7})
    s.record_event({"event_code": "OVTK", "overtaking_idx": 7, "being_overtaken_idx": 3})
    assert s._count_recent_overtakes(3, 7) == 2


def test_count_recent_overtakes_ignores_other_pairs():
    s = _make_state()
    s.record_event({"event_code": "OVTK", "overtaking_idx": 3, "being_overtaken_idx": 7})
    s.record_event({"event_code": "OVTK", "overtaking_idx": 1, "being_overtaken_idx": 2})
    assert s._count_recent_overtakes(3, 7) == 1


def test_is_battle_unchanged_behavior_below_threshold():
    """is_battle() сохраняет свой прежний контракт (bool, порог BATTLE_THRESHOLD=2)
    — это не должно измениться этим планом."""
    s = _make_state()
    s.record_event({"event_code": "OVTK", "overtaking_idx": 3, "being_overtaken_idx": 7})
    assert s.is_battle(3, 7) is False


def test_is_battle_unchanged_behavior_at_threshold():
    s = _make_state()
    s.record_event({"event_code": "OVTK", "overtaking_idx": 3, "being_overtaken_idx": 7})
    s.record_event({"event_code": "OVTK", "overtaking_idx": 7, "being_overtaken_idx": 3})
    assert s.is_battle(3, 7) is True


def test_enrich_overtake_event_includes_battle_count():
    """В реальном _event_loop (core/engine.py) enrich() вызывается ДО
    record_event() для ТЕКУЩЕГО события — то есть battle_count всегда считает
    только ПРЕДЫДУЩИЕ обгоны той же пары, никогда не включает текущий вызов.
    Здесь имитируем это: один прошлый обгон уже записан в history, затем
    enrich() вызывается на "втором" (текущем) обгоне той же пары."""
    s = _make_state()
    s.record_event({"event_code": "OVTK", "overtaking_idx": 3, "being_overtaken_idx": 7})
    out = s.enrich({"event_code": "OVTK", "overtaking_idx": 3, "being_overtaken_idx": 7})
    assert out["battle_count"] == 1


def test_enrich_overtake_event_battle_count_zero_when_no_prior_history():
    s = _make_state()
    out = s.enrich({"event_code": "OVTK", "overtaking_idx": 3, "being_overtaken_idx": 7})
    assert out["battle_count"] == 0
