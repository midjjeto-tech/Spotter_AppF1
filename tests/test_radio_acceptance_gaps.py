"""Сценарии из живого acceptance-прогона, которые проверяемы автоматически.

Полный прогон (пункты про реальные формулировки Yandex STT и про перебивание
длинного ответа новым PTT) требует запущенной игры и живого микрофона — их здесь
нет. Остальное закрывается тестами, и два дефекта, найденные при разборе этих
сценариев, зафиксированы регрессиями.
"""
import time

import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.radio import resolver
from core.radio.message import (
    STATE_COMPLETED, STATE_PLAYING, RadioCancelReason, build_message,
)


@pytest.fixture
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _snapshot(**overrides):
    base = {"pit_status": 0, "gap_target_idx": 7, "safety_car_status": 0,
            "gap_front_ms": 1300, "ers_percent": 60.0, "tyre_wear": 40.0,
            "tyre_set_id": 18, "position": 5}
    base.update(overrides)
    return base


def _ptt(_engine, answer, topic, snapshot=None):
    """Собрать PTT-ответ так, как это делает движок.

    Движок не нужен — код события выбирается по той же карте, что в
    `_ptt_answer_message`, а снимок передаётся явно."""
    code = eng_mod._PTT_ANSWER_EVENT_CODE.get(topic, "USER_Q")
    event = {"event_code": code, "speaker": "engineer",
             "created_at": 1000.0, "created_mono": 0.0}
    return build_message(event, phrase=answer, now=1000.0, now_mono=0.0,
                         telemetry=snapshot or _snapshot())


# ── Дефект 1: действенный PTT-ответ проходил без guard и без TTL ────────────

def test_pit_decision_answer_is_cancelled_once_the_player_is_pitting():
    """«Да, окно открыто. Заезжай.» не должно звучать, когда игрок уже в
    пит-лейне — даже если вопрос задал он сам."""
    message = _ptt(None, "Да, окно открыто. Заезжай.", "should_pit")
    result = resolver.resolve_for_playback(
        message, _snapshot(pit_status=2), 5.0)

    assert isinstance(result, resolver.Cancellation)
    assert result.reason is RadioCancelReason.SITUATION_ENDED


def test_pit_decision_answer_expires():
    """Справочный ответ может опоздать без вреда, решение — нет."""
    message = _ptt(None, "Да, окно открыто. Заезжай.", "should_pit")
    assert message.ttl is not None

    result = resolver.resolve_for_playback(message, _snapshot(), 30.0)
    assert isinstance(result, resolver.Cancellation)
    assert result.reason is RadioCancelReason.EXPIRED


def test_gap_answer_is_cancelled_when_the_rival_changed():
    message = _ptt(None, "Отрыв впереди 1,3 — это Норрис.", "gap_ahead")
    result = resolver.resolve_for_playback(
        message, _snapshot(gap_target_idx=4), 2.0)

    assert isinstance(result, resolver.Cancellation)
    assert result.reason is RadioCancelReason.TARGET_CHANGED


def test_safety_car_answer_is_cancelled_when_the_phase_changed():
    """На момент вопроса SC был на трассе; к моменту озвучки — зелёный флаг."""
    message = _ptt(None, "На трассе Safety Car.", "safety_car",
                   snapshot=_snapshot(safety_car_status=1))
    result = resolver.resolve_for_playback(
        message, _snapshot(safety_car_status=0), 2.0)

    assert isinstance(result, resolver.Cancellation)
    assert result.reason is RadioCancelReason.SITUATION_ENDED


def test_safety_car_answer_survives_while_the_phase_holds():
    message = _ptt(None, "На трассе Safety Car.", "safety_car",
                   snapshot=_snapshot(safety_car_status=1))
    result = resolver.resolve_for_playback(
        message, _snapshot(safety_car_status=1), 2.0)

    assert not isinstance(result, resolver.Cancellation)


def test_informational_answers_keep_living_without_a_ttl():
    """Обратная сторона: «износ 48%» и «данных нет» опоздать могут."""
    for topic in ("tyres", "fuel", "ers", "position", "weather", None):
        message = _ptt(None, "Износ 48 процентов.", topic)
        assert message.ttl is None, topic
        assert isinstance(
            resolver.resolve_for_playback(message, _snapshot(), 10_000.0),
            type(resolver.resolve_for_playback(message, _snapshot(), 1.0)))


def test_actionable_and_informational_answers_get_different_codes():
    assert eng_mod._PTT_ANSWER_EVENT_CODE["should_pit"] == "USER_Q_PIT"
    assert eng_mod._PTT_ANSWER_EVENT_CODE["gap_ahead"] == "USER_Q_GAP"
    assert eng_mod._PTT_ANSWER_EVENT_CODE["safety_car"] == "USER_Q_SAFETY_CAR"
    assert "tyres" not in eng_mod._PTT_ANSWER_EVENT_CODE


def test_actionable_answers_are_still_engineer_channel_with_a_human_title(engine):
    for topic in ("should_pit", "gap_ahead", "safety_car"):
        message = engine._ptt_answer_message("Ответ.", topic)
        assert message.channel == "engineer", topic
        assert message.ui_title and "USER_Q" not in message.ui_title, topic


# ── Дефект 2: talk_more подтверждал, но ничего не менял ─────────────────────

def test_talk_more_actually_shortens_the_pause(engine):
    before = float(engine._get_setting("min_comment_gap", 9.0))
    engine._execute_voice_command("talk_more")
    after = float(engine._get_setting("min_comment_gap", 9.0))
    assert after < before


def test_talk_more_stops_at_a_floor_and_says_so(engine):
    for _ in range(10):
        answer = engine._execute_voice_command("talk_more")
    gap = float(engine._get_setting("min_comment_gap", 9.0))

    assert gap == eng_mod._TALK_MORE_GAP_FLOOR
    assert "максимальной" in answer


def test_talk_more_does_not_claim_a_change_it_did_not_make(engine):
    """Главный дефект: подтверждение без действия."""
    for _ in range(10):
        engine._execute_voice_command("talk_more")
    answer = engine._execute_voice_command("talk_more")
    assert "чаще" not in answer


def test_talk_more_also_reopens_muted_channels(engine):
    engine.apply_settings({"engineer_chatter_enabled": False,
                           "commentary_enabled": False})
    engine._execute_voice_command("talk_more")

    assert engine.settings["engineer_chatter_enabled"] is True
    assert engine.settings["commentary_enabled"] is True


def test_the_shortened_pause_is_the_one_the_commentary_loop_reads(engine):
    """Настройка обязана быть ТЕМ ЖЕ ключом, что гейт в `_commentary_loop`, —
    иначе команда меняет мёртвое значение."""
    engine._execute_voice_command("talk_more")
    assert engine._get_setting("min_comment_gap", None) == \
        engine.settings["min_comment_gap"]


# ── Сценарий 3: автоозвучка выключена ──────────────────────────────────────

def test_unvoiced_answer_is_completed_and_repeatable(engine):
    """Сообщение доставлено субтитром: считается завершённым и повторяется."""
    engine._note_ptt_answer_unvoiced("Передние 48, задние 39.", "tyres")

    assert engine.radio_session.repeatable_text() == "Передние 48, задние 39."
    entry = engine.get_state()["radio"]["history"][-1]
    assert entry["state"] == STATE_COMPLETED
    assert entry["source"] == "engineer"


def test_unvoiced_answer_is_not_marked_cancelled(engine):
    engine._note_ptt_answer_unvoiced("Ответ.", "tyres")
    entry = engine.get_state()["radio"]["history"][-1]
    assert entry["cancel_reason"] is None


# ── Сценарий 4: flashback после автоматической реплики и после PTT ──────────

def test_flashback_after_an_automatic_line_keeps_it_repeatable(engine):
    """Прозвучавшая до перемотки реплика уже услышана — «повтори» её помнит."""
    event = {"event_code": "ENGINEER_GAP_DIGEST", "speaker": "engineer",
             "created_at": 1000.0, "created_mono": 0.0}
    message = build_message(event, phrase="Отрыв впереди 1,3.",
                            now=1000.0, now_mono=0.0)
    engine.radio_session.note(message.with_state(STATE_PLAYING, now=1.0))
    engine.radio_session.note(message.with_state(STATE_PLAYING, now=1.0)
                              .with_state(STATE_COMPLETED, now=2.0))

    engine._handle_flashback()

    assert engine.radio_session.repeatable_text() == "Отрыв впереди 1,3."


def test_flashback_after_a_ptt_answer_keeps_it_repeatable(engine):
    engine._note_ptt_answer_unvoiced("Передние 48.", "tyres")
    engine._handle_flashback()
    assert engine.radio_session.repeatable_text() == "Передние 48."


def test_flashback_cancels_only_what_had_not_been_heard(engine):
    pending = build_message(
        {"event_code": "ENGINEER_GAP_DIGEST", "speaker": "engineer"},
        phrase="Ещё не звучало.", now=0.0, now_mono=0.0)
    engine._radio_lifecycle[pending.id] = pending
    engine.radio_session.note(pending)

    engine._handle_flashback()

    entry = next(e for e in engine.get_state()["radio"]["history"]
                 if e["text"] == "Ещё не звучало.")
    assert entry["cancel_reason"] == "flashback"


# ── Сценарий 5: ситуация меняется во время синтеза ─────────────────────────

def test_situation_change_during_synthesis_cancels_the_answer(engine):
    """Резолв идёт в воркере, поэтому смена ситуации между постановкой и
    синтезом обязана отменить реплику."""
    message = engine._ptt_answer_message("Да, окно открыто. Заезжай.",
                                         "should_pit")
    engine.radio_session.note(message)
    prepare = engine._make_prepare(message)

    engine._player_pit_status = 2          # заехал, пока шёл синтез

    assert prepare() is None
    entry = next(e for e in engine.get_state()["radio"]["history"]
                 if e["id"] == message.id)
    assert entry["cancel_reason"] == "situation_ended"


def test_a_still_current_answer_survives_synthesis(engine):
    engine._player_pit_status = 0
    message = engine._ptt_answer_message("Нет, оставайся на трассе.",
                                         "should_pit")
    assert engine._make_prepare(message)() is not None


# ── Сценарий 7: новая сессия не протекает в новый заезд ────────────────────

def test_session_reset_clears_history_active_and_repeatable(engine):
    engine._note_ptt_answer_unvoiced("Старая гонка.", "tyres")
    event = {"event_code": "ENGINEER_GAP_DIGEST", "speaker": "engineer"}
    active = build_message(event, phrase="Звучит.", now=0.0, now_mono=0.0)
    engine.radio_session.note(active.with_state(STATE_PLAYING, now=1.0))

    assert engine.radio_session.repeatable_text() == "Старая гонка."
    assert engine.radio_session.active() is not None

    engine.radio_session.reset()

    assert engine.radio_session.history() == ()
    assert engine.radio_session.active() is None
    assert engine.radio_session.repeatable_text() is None
    assert engine.get_state()["radio"]["repeatable"] is None


def test_session_reset_also_clears_the_supersede_registry(engine):
    """Иначе первая ситуация нового заезда считалась бы вытесненной сообщением
    из прошлого."""
    event = {"event_code": "STRAT_BOX_CALL_1", "priority": "critical",
             "speaker": "engineer", "radio": {"box_call_window": 12}}
    message = build_message(event, phrase="Бокс.", now=0.0, now_mono=0.0,
                            session_id="old")
    engine._note_radio_newest(message)
    assert engine._radio_newest

    engine._radio_newest.clear()
    engine.radio_session.reset()

    assert not engine._radio_newest
