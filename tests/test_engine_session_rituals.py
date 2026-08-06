"""Ритуалы сессии: проверка радио на старте и итог на финише.

Начало и конец — самые запоминающиеся точки заезда, и до этой работы они были
пустыми: `session.pep_talk` существовал, а связь никто не проверял и на финиш
инженер не реагировал вовсе.

**Поправка к плану.** План предполагал, что `CHQF` приходит на каждого
финиширующего, и требовал теста «объявляем только игрока». В этом проекте это
не так: `CHQF` — событие СЕССИИ без `vehicle_idx` (`core/packets.py`), оно
приходит один раз. Поэтому проверяется то, что риском действительно является:
названа позиция ИГРОКА (а не первая попавшаяся из таблицы), объявлено ровно
один раз, и при неизвестной позиции инженер молчит, а не произносит мусор.
"""
import struct

import pytest

import core.engine as eng_mod
from core.engine import F1Engine, SPEAKER_ENGINEER
from core.packets import HEADER_SIZE, PACKET_SESSION
from tests.telemetry import consume_f1_packet


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


def _codes(engine) -> list[str]:
    return [e.get("event_code") for e in _drain(engine)]


def _session_packet(session_type_raw: int, track_id: int = 5) -> bytes:
    """PACKET_SESSION с заданным сырым session_type — см.
    tests/test_engine_pre_race_pep_talk.py, откуда взят офсет."""
    header = b"\x00" * HEADER_SIZE
    payload = struct.pack("<BBbBHBb", 0, 25, 20, 10, 5793, session_type_raw, track_id)
    return header + payload


class _StubThread:
    def __init__(self, target=None, daemon=None, name=None):
        pass

    def start(self):
        pass


def _patch_thread_spawn(monkeypatch, spawned: list) -> None:
    def _fake_thread(target, daemon, name):
        spawned.append(name)
        return _StubThread()
    monkeypatch.setattr(eng_mod.threading, "Thread", _fake_thread)


# ── Проверка радио ───────────────────────────────────────────────────────────

def test_radio_check_fires_once_per_session(engine, monkeypatch):
    """Проверка радио на КАЖДЫЙ пакет телеметрии — это не ритуал, это
    неисправность. Нужен edge-trigger, как у остальных тиков инженера."""
    engine._session_type = "unknown"
    engine._track_id = 5
    _patch_thread_spawn(monkeypatch, [])
    _drain(engine)

    consume_f1_packet(engine, {"player_car_index": PLAYER}, PACKET_SESSION,
                      _session_packet(session_type_raw=15))          # -> race
    assert _codes(engine).count("SESSION_RADIO_CHECK") == 1

    consume_f1_packet(engine, {"player_car_index": PLAYER}, PACKET_SESSION,
                      _session_packet(session_type_raw=15))          # тот же тип
    assert "SESSION_RADIO_CHECK" not in _codes(engine)


def test_radio_check_comes_before_the_pep_talk(engine, monkeypatch):
    """Сначала связь, потом разговор. Напутствие в молчащую рацию бессмысленно.

    Напутствие уходит в фоновый поток с задержкой, поэтому «раньше» здесь —
    это «опубликовано до того, как поток вообще был запущен»."""
    engine._session_type = "unknown"
    engine._track_id = 5
    spawned: list = []
    order: list[str] = []
    _drain(engine)

    def _fake_thread(target, daemon, name):
        spawned.append(name)
        order.append(f"thread:{name}")
        return _StubThread()
    monkeypatch.setattr(eng_mod.threading, "Thread", _fake_thread)

    orig_publish = engine._commentary_events.publish

    def _spy(draft):
        order.append(f"publish:{draft.get('event_code')}")
        return orig_publish(draft)
    monkeypatch.setattr(engine._commentary_events, "publish", _spy)

    consume_f1_packet(engine, {"player_car_index": PLAYER}, PACKET_SESSION,
                      _session_packet(session_type_raw=15))

    assert "publish:SESSION_RADIO_CHECK" in order
    assert "thread:pre-race-pep-talk" in order
    assert (order.index("publish:SESSION_RADIO_CHECK")
            < order.index("thread:pre-race-pep-talk"))


def test_radio_check_respects_the_chatter_setting(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = False
    engine._session_type = "unknown"
    engine._track_id = 5
    _patch_thread_spawn(monkeypatch, [])
    _drain(engine)

    consume_f1_packet(engine, {"player_car_index": PLAYER}, PACKET_SESSION,
                      _session_packet(session_type_raw=15))
    assert "SESSION_RADIO_CHECK" not in _codes(engine)


def test_radio_check_is_an_engineer_line(engine, monkeypatch):
    engine._session_type = "unknown"
    engine._track_id = 5
    _patch_thread_spawn(monkeypatch, [])
    _drain(engine)

    consume_f1_packet(engine, {"player_car_index": PLAYER}, PACKET_SESSION,
                      _session_packet(session_type_raw=15))
    check = [e for e in _drain(engine)
             if e.get("event_code") == "SESSION_RADIO_CHECK"]
    assert check and check[0]["speaker"] == SPEAKER_ENGINEER
    assert check[0]["phrase"]


# ── Итог сессии ──────────────────────────────────────────────────────────────

def test_result_carries_the_players_finishing_position(engine):
    """`position` — required_fields: без него спека не соберётся, и вместо
    итога прозвучит тишина. Позиция обязана быть ИГРОКА, а не соседа по
    таблице — назвать чужой результат своим значит дезинформировать пилота."""
    engine._positions = {PLAYER: 4, RIVAL: 1}
    engine._handle_race_event({"event_code": "CHQF"})
    result = [e for e in _drain(engine) if e.get("event_code") == "SESSION_RESULT"]
    assert result, "итог сессии не объявлен"
    assert "четвёртый" in result[0]["phrase"].lower(), result[0]["phrase"]


def test_result_is_announced_once(engine):
    """Повторный CHQF (перезаезд, повтор пакета) не должен давать второй итог."""
    engine._positions = {PLAYER: 4}
    engine._handle_race_event({"event_code": "CHQF"})
    engine._handle_race_event({"event_code": "CHQF"})
    assert _codes(engine).count("SESSION_RESULT") == 1


def test_result_stays_silent_when_the_position_is_unknown(engine):
    """Позиции нет (игрок-зритель, потерянный LapData) — молчание честнее, чем
    итог с пустым местом."""
    engine._positions = {}
    engine._handle_race_event({"event_code": "CHQF"})
    assert "SESSION_RESULT" not in _codes(engine)


def test_result_respects_the_chatter_setting(engine):
    engine.settings["engineer_chatter_enabled"] = False
    engine._positions = {PLAYER: 4}
    engine._handle_race_event({"event_code": "CHQF"})
    assert "SESSION_RESULT" not in _codes(engine)


def test_ritual_codes_are_routed_to_the_engineer_channel():
    """Категория `session` с КОНЕЧНЫМ TTL. План просил `None`, но бессрочность в
    этом проекте — обоснованное исключение для сообщений, требующих действия или
    запрошенных пилотом (`policy.never_expiring_categories`), а ритуалы ни то ни
    другое. Проверка радио через минуту после старта — нелепость, и категория у
    неё общая с итогом заезда."""
    from core.radio import policy

    for code in ("SESSION_RADIO_CHECK", "SESSION_RESULT"):
        assert policy.channel_for({"event_code": code}) == policy.CHANNEL_ENGINEER
        assert policy.category_for(code) == "session"
        assert policy.ttl_for(code) == 30.0
    assert "session" not in policy.never_expiring_categories()
