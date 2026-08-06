"""Инженер хвалит за удачные моменты — но только пилота и только по делу.

До этой работы на весь банк была одна спека одобрения (battle.held): инженер
только предупреждал и командовал, отсюда ощущение ассистента, а не напарника.
"""
import pytest

import core.engine as eng_mod
from core.engine import F1Engine, SPEAKER_ENGINEER


PLAYER = 3
RIVAL = 7


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({"engineer_chatter_enabled": True})
    e._player_car_index = PLAYER
    e._session_type = "race"
    return e


def _drain(engine) -> list[dict]:
    out = []
    while not engine._commentary_events.empty():
        out.append(engine._commentary_events.get_nowait())
    return out


def _codes(engine) -> set[str]:
    return {e.get("event_code") for e in _drain(engine)}


def test_player_overtake_is_praised(engine):
    engine._handle_race_event({
        "event_code": "OVTK", "overtaking_idx": PLAYER,
        "being_overtaken_idx": RIVAL,
    })
    assert "PRAISE_OVERTAKE" in _codes(engine)


def test_being_overtaken_is_not_praised(engine):
    """Игрока обогнали — это повод для обороны, а не для похвалы. Перепутать
    направление обгона значит поздравлять пилота с потерей позиции."""
    engine._handle_race_event({
        "event_code": "OVTK", "overtaking_idx": RIVAL,
        "being_overtaken_idx": PLAYER,
    })
    assert "PRAISE_OVERTAKE" not in _codes(engine)


def test_someone_elses_overtake_is_not_praised(engine):
    engine._handle_race_event({
        "event_code": "OVTK", "overtaking_idx": RIVAL,
        "being_overtaken_idx": 11,
    })
    assert "PRAISE_OVERTAKE" not in _codes(engine)


def test_praise_is_marked_as_an_engineer_line(engine):
    engine._handle_race_event({
        "event_code": "OVTK", "overtaking_idx": PLAYER,
        "being_overtaken_idx": RIVAL,
    })
    praise = [e for e in _drain(engine) if e.get("event_code") == "PRAISE_OVERTAKE"]
    assert praise and praise[0]["speaker"] == SPEAKER_ENGINEER
    assert praise[0]["phrase"]


def test_praise_respects_the_chatter_setting(engine):
    """`engineer_chatter_enabled` — общий тумблер болтливости инженера. Похвала
    обязана его уважать, как и все остальные тики."""
    engine.settings["engineer_chatter_enabled"] = False
    engine._handle_race_event({
        "event_code": "OVTK", "overtaking_idx": PLAYER,
        "being_overtaken_idx": RIVAL,
    })
    assert "PRAISE_OVERTAKE" not in _codes(engine)


def test_overtake_praise_is_race_only(engine):
    """В практике машины обгоняют друг друга непрерывно — похвала там стала бы
    фоном. Тот же гейт, что у _leader_change_tick и _maybe_announce_pit_exit."""
    engine._session_type = "practice"
    engine._handle_race_event({
        "event_code": "OVTK", "overtaking_idx": PLAYER,
        "being_overtaken_idx": RIVAL,
    })
    assert "PRAISE_OVERTAKE" not in _codes(engine)


def test_player_fastest_lap_is_praised(engine):
    engine._handle_race_event({"event_code": "FTLP", "vehicle_idx": PLAYER})
    assert "PRAISE_FASTEST_LAP" in _codes(engine)


def test_someone_elses_fastest_lap_is_not_praised(engine):
    """FTLP приходит на любого пилота круга. Хвалить игрока за чужой рекорд —
    прямая дезинформация."""
    engine._handle_race_event({"event_code": "FTLP", "vehicle_idx": RIVAL})
    assert "PRAISE_FASTEST_LAP" not in _codes(engine)


def test_praise_is_routed_to_the_engineer_channel():
    """Код, которого нет в таблицах policy, поехал бы на канал комментатора и
    получил бы TTL по умолчанию. Похвала — реплика инженера и живёт 12 секунд."""
    from core.radio import policy

    for code in ("PRAISE_OVERTAKE", "PRAISE_FASTEST_LAP"):
        assert policy.channel_for({"event_code": code}) == policy.CHANNEL_ENGINEER
        assert policy.category_for(code) == "praise"
    assert policy.ttl_for("PRAISE_OVERTAKE") == 12.0
