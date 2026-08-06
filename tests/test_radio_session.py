"""core/radio/session.py — активная передача, история, «повтори», PTT-сеанс.

Главное различие, которое легко потерять (ТЗ §12): «повтори» повторяет ТОЛЬКО
последнее ПОЛНОСТЬЮ ПРОЗВУЧАВШЕЕ сообщение ИНЖЕНЕРСКОГО канала — не последнее
событие, не текст комментатора, не прерванную реплику и не отменённую до озвучки.
"""
import json

import pytest

from core.radio import policy
from core.radio.message import (
    STATE_COMPLETED, STATE_INTERRUPTED, STATE_PLAYING, STATE_SYNTHESIZING,
    RadioCancelReason, build_message,
)
from core.radio.session import MAX_HISTORY, RadioSession


def _msg(phrase, *, code="ENGINEER_GAP_DIGEST", mono=0.0):
    event = {"event_code": code, "speaker": "engineer",
             "created_at": 1000.0, "created_mono": mono}
    return build_message(event, phrase=phrase, now=1000.0, now_mono=mono)


def _commentator(phrase):
    event = {"event_code": "OVTK", "created_at": 1000.0, "created_mono": 0.0}
    return build_message(event, phrase=phrase, now=1000.0, now_mono=0.0)


def _play_through(session, message):
    """Провести сообщение полным путём до completed."""
    session.note(message)
    playing = message.with_state(STATE_PLAYING, now=1.0)
    session.note(playing)
    done = playing.with_state(STATE_COMPLETED, now=2.0)
    session.note(done)
    return done


@pytest.fixture
def session():
    return RadioSession(clock=lambda: 1000.0)


# ── Активная передача ───────────────────────────────────────────────────────

def test_no_active_message_initially(session):
    assert session.active() is None
    assert session.status() == "idle"


def test_playing_message_becomes_active(session):
    message = _msg("Боксы в конце круга.")
    session.note(message.with_state(STATE_PLAYING, now=1.0))

    assert session.active() is not None
    assert session.active().id == message.id
    assert session.status() == STATE_PLAYING


def test_synthesizing_message_is_already_active(session):
    """Панель должна показать «синтезируется», а не пустоту."""
    message = _msg("Текст")
    session.note(message.with_state(STATE_SYNTHESIZING, now=1.0))
    assert session.status() == STATE_SYNTHESIZING


def test_completed_message_stops_being_active(session):
    _play_through(session, _msg("Текст"))
    assert session.active() is None
    assert session.status() == "idle"


def test_cancelled_message_stops_being_active(session):
    message = _msg("Текст")
    session.note(message.with_state(STATE_SYNTHESIZING, now=1.0))
    session.note(message.with_state(STATE_SYNTHESIZING, now=1.0).cancelled(
        RadioCancelReason.EXPIRED, now=2.0))
    assert session.active() is None


# ── «Повтори» ───────────────────────────────────────────────────────────────

def test_repeat_returns_the_last_completed_engineer_line(session):
    _play_through(session, _msg("Передние 48, задние 39."))
    assert session.repeatable_text() == "Передние 48, задние 39."


def test_repeat_ignores_an_interrupted_message(session):
    """Прерванную реплику пилот не слышал целиком — повторять надо предыдущую
    завершённую."""
    _play_through(session, _msg("Первая полностью прозвучала."))

    interrupted = _msg("Вторая оборвалась.")
    session.note(interrupted.with_state(STATE_PLAYING, now=3.0))
    session.note(interrupted.with_state(STATE_PLAYING, now=3.0)
                 .with_state(STATE_INTERRUPTED, now=3.5))

    assert session.repeatable_text() == "Первая полностью прозвучала."


def test_repeat_ignores_a_message_cancelled_before_playback(session):
    _play_through(session, _msg("Прозвучавшая реплика."))

    cancelled = _msg("Отменённая реплика.")
    session.note(cancelled)
    session.note(cancelled.cancelled(RadioCancelReason.EXPIRED, now=3.0))

    assert session.repeatable_text() == "Прозвучавшая реплика."


def test_repeat_ignores_commentator_lines(session):
    """Комментатор — не инженер: «повтори» относится к радиообмену с командой."""
    _play_through(session, _msg("Реплика инженера."))
    _play_through(session, _commentator("Комментатор рассказывает историю."))

    assert session.repeatable_text() == "Реплика инженера."


def test_repeat_ignores_a_merely_queued_message(session):
    _play_through(session, _msg("Прозвучало."))
    session.note(_msg("Только в очереди."))

    assert session.repeatable_text() == "Прозвучало."


def test_repeat_is_none_before_anything_was_spoken(session):
    assert session.repeatable_text() is None
    assert session.last_completed_engineer() is None


def test_repeat_follows_the_newest_completed_line(session):
    _play_through(session, _msg("Старая."))
    _play_through(session, _msg("Новая."))
    assert session.repeatable_text() == "Новая."


def test_empty_phrase_never_becomes_repeatable(session):
    _play_through(session, _msg("   "))
    assert session.repeatable_text() is None


# ── История ─────────────────────────────────────────────────────────────────

def test_history_records_the_message_once_not_once_per_transition(session):
    """ТЗ §15: не дублировать один event двумя одинаковыми строками."""
    _play_through(session, _msg("Одна реплика."))

    entries = [e for e in session.history() if e["source"] != "driver"]
    assert len(entries) == 1
    assert entries[0]["state"] == STATE_COMPLETED


def test_history_keeps_the_final_state_of_each_message(session):
    _play_through(session, _msg("Первая."))
    cancelled = _msg("Вторая.")
    session.note(cancelled)
    session.note(cancelled.cancelled(RadioCancelReason.SUPERSEDED, now=3.0))

    states = {e["text"]: e["state"] for e in session.history()}
    assert states["Первая."] == STATE_COMPLETED
    assert states["Вторая."] == "cancelled"


def test_history_exposes_the_cancel_reason(session):
    message = _msg("Отменённая.")
    session.note(message)
    session.note(message.cancelled(RadioCancelReason.TARGET_CHANGED, now=2.0))

    entry = next(e for e in session.history() if e["text"] == "Отменённая.")
    assert entry["cancel_reason"] == "target_changed"


def test_history_is_bounded(session):
    for index in range(MAX_HISTORY * 3):
        _play_through(session, _msg(f"Реплика {index}."))
    assert len(session.history()) <= MAX_HISTORY


def test_history_carries_human_titles_not_raw_codes(session):
    _play_through(session, _msg("Бокс, бокс.", code="STRAT_BOX_CALL_1"))
    entry = session.history()[-1]
    assert entry["title"]
    assert "STRAT_BOX_CALL_1" not in entry["title"]


def test_history_marks_the_channel_of_every_line(session):
    _play_through(session, _msg("Инженер."))
    _play_through(session, _commentator("Комментатор."))

    sources = {e["text"]: e["source"] for e in session.history()}
    assert sources["Инженер."] == policy.CHANNEL_ENGINEER
    assert sources["Комментатор."] == policy.CHANNEL_COMMENTATOR


def test_clear_history_keeps_the_repeatable_line(session):
    _play_through(session, _msg("Прозвучало."))
    session.clear_history()

    assert session.history() == ()
    assert session.repeatable_text() == "Прозвучало."


# ── Реплика пилота ──────────────────────────────────────────────────────────

def test_driver_line_appears_in_history(session):
    session.note_driver_line("Какой износ?")
    entry = session.history()[-1]

    assert entry["source"] == "driver"
    assert entry["text"] == "Какой износ?"


def test_automatic_messages_get_no_fake_driver_line(session):
    """ТЗ §13: автоматические сообщения попадают в историю без выдуманного
    вопроса пилота."""
    _play_through(session, _msg("Автоматическая сводка."))
    assert all(e["source"] != "driver" for e in session.history())


def test_blank_driver_line_is_ignored(session):
    session.note_driver_line("   ")
    assert session.history() == ()


def test_driver_line_never_becomes_repeatable(session):
    """«Повтори» повторяет инженера, а не собственные слова пилота."""
    session.note_driver_line("Какой износ?")
    assert session.repeatable_text() is None


# ── PTT-сеанс ───────────────────────────────────────────────────────────────

def test_ptt_starts_idle(session):
    assert session.ptt_state() == "idle"


def test_ptt_cycle_is_reflected(session):
    for state in ("listening", "recognizing", "thinking", "done"):
        session.set_ptt(state)
        assert session.ptt_state() == state


def test_ptt_busy_states_win_the_channel_status(session):
    """Пока идёт запрос пилота, панель показывает его, а не «idle»."""
    session.set_ptt("listening")
    assert session.status() == "listening"


def test_ptt_done_does_not_mask_an_active_transmission(session):
    session.set_ptt("done")
    session.note(_msg("Ответ инженера.").with_state(STATE_PLAYING, now=1.0))
    assert session.status() == STATE_PLAYING


def test_ptt_carries_both_sides_of_the_dialogue(session):
    session.set_ptt("done", driver_text="Какой износ?",
                    engineer_text="Передние 48.")
    ptt = session.to_ui_dict()["ptt"]

    assert ptt["driver_text"] == "Какой износ?"
    assert ptt["engineer_text"] == "Передние 48."


def test_ptt_error_is_exposed(session):
    session.set_ptt("error", error="Микрофон недоступен")
    assert session.to_ui_dict()["ptt"]["error"] == "Микрофон недоступен"


# ── Проекция в UI ───────────────────────────────────────────────────────────

def test_projection_is_json_serialisable(session):
    _play_through(session, _msg("Реплика."))
    session.note_driver_line("Вопрос?")
    session.set_ptt("done", driver_text="Вопрос?", engineer_text="Ответ.")

    payload = session.to_ui_dict()
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload


def test_projection_has_the_documented_shape(session):
    payload = session.to_ui_dict()
    assert set(payload) == {"revision", "speakers", "status", "active_message",
                            "history", "ptt", "repeatable"}


def test_projection_separates_active_state_from_history(session):
    """ТЗ §18: активное состояние и история — разные поля, чтобы UI не
    перерисовывал ленту из-за смены активной передачи."""
    message = _msg("Звучит сейчас.")
    session.note(message.with_state(STATE_PLAYING, now=1.0))

    payload = session.to_ui_dict()
    assert payload["active_message"]["text"] == "Звучит сейчас."
    assert isinstance(payload["history"], list)


def test_projection_active_message_has_a_stable_id(session):
    message = _msg("Текст")
    session.note(message.with_state(STATE_PLAYING, now=1.0))
    first = session.to_ui_dict()["active_message"]["id"]
    second = session.to_ui_dict()["active_message"]["id"]
    assert first == second == message.id


def test_projection_never_exposes_the_telemetry_snapshot(session):
    event = {"event_code": "ENGINEER_GAP_DIGEST", "speaker": "engineer"}
    message = build_message(event, phrase="Текст", now=0.0, now_mono=0.0,
                            telemetry={"ers_percent": 60.0})
    session.note(message.with_state(STATE_PLAYING, now=1.0))

    encoded = json.dumps(session.to_ui_dict(), ensure_ascii=False)
    assert "ers_percent" not in encoded


def test_projection_reports_what_repeat_would_say(session):
    _play_through(session, _msg("Передние 48."))
    assert session.to_ui_dict()["repeatable"] == "Передние 48."


def test_history_in_the_projection_is_a_copy(session):
    _play_through(session, _msg("Текст"))
    payload = session.to_ui_dict()
    payload["history"].clear()
    assert session.to_ui_dict()["history"]


# ── Сброс ───────────────────────────────────────────────────────────────────

def test_reset_clears_everything(session):
    _play_through(session, _msg("Текст"))
    session.note_driver_line("Вопрос?")
    session.set_ptt("done")

    session.reset()

    assert session.history() == ()
    assert session.active() is None
    assert session.repeatable_text() is None
    assert session.ptt_state() == "idle"


def test_message_registry_does_not_grow_without_bound(session):
    for index in range(MAX_HISTORY * 4):
        _play_through(session, _msg(f"Реплика {index}."))
    assert len(session._messages) <= MAX_HISTORY * 2 + 4
