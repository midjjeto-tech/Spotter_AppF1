"""Позднее связывание и жизненный цикл через реальную проводку (Task 4).

Резолвер сам по себе покрыт в `test_radio_resolver.py`. Здесь проверяется, что
он вызывается В НУЖНОМ МЕСТЕ: воркером очереди, после всех ожиданий, и что
сообщение не остаётся в неизвестном состоянии.
"""
import threading
import time

import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.radio import plumbing
from core.radio.message import (
    STATE_CANCELLED, STATE_COMPLETED, STATE_PLAYING, RadioCancelReason,
    build_message,
)
from new_tts.queue_handler import TTSQueue


@pytest.fixture
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _msg(engine, phrase, *, code="ENGINEER_GAP_DIGEST", phrase_code=None,
         snapshot=None):
    event = {"event_code": code, "speaker": "engineer",
             "created_at": time.time(), "created_mono": time.monotonic()}
    return build_message(
        event, phrase=phrase, phrase_code=phrase_code,
        now=time.time(), now_mono=time.monotonic(),
        telemetry=snapshot if snapshot is not None else engine._volatile_snapshot(),
        session_id=engine._radio_session_id,
        timeline_revision=engine._timeline_revision)


def _state(engine, message):
    return engine._radio_lifecycle.get(message.id, message).state


def _reason(engine, message):
    return engine._radio_lifecycle.get(message.id, message).cancel_reason


# ── Резолв происходит в воркере, а не при постановке ────────────────────────

def test_prepare_is_called_by_the_worker_not_by_enqueue():
    """Ключевое место Task 4: между постановкой и синтезом стоит ожидание, и
    резолв обязан случиться ПОСЛЕ него."""
    calls = []
    release = threading.Event()
    spoken = []

    def speak(text, _persona):
        spoken.append(text)

    q = TTSQueue(speak_fn=speak, maxsize=4)
    try:
        def prepare():
            calls.append("resolved")
            release.set()
            return "финальный текст"

        assert not calls                      # до enqueue резолва нет
        q.enqueue("черновик", prepare=prepare)
        assert release.wait(timeout=2.0)
        time.sleep(0.05)

        assert calls == ["resolved"]
        assert spoken == ["финальный текст"]   # озвучен РЕЗОЛВЛЕННЫЙ текст
    finally:
        q.stop(timeout=1.0)


def test_prepare_returning_none_skips_synthesis_entirely():
    spoken = []
    done = threading.Event()

    def speak(text, _persona):
        spoken.append(text)

    q = TTSQueue(speak_fn=speak, maxsize=4)
    try:
        q.enqueue("черновик", prepare=lambda: None)
        q.enqueue("следующая", prepare=lambda: (done.set(), "вторая")[1])
        assert done.wait(timeout=2.0)
        time.sleep(0.05)

        assert spoken == ["вторая"]            # первая не озвучена вовсе
    finally:
        q.stop(timeout=1.0)


def test_value_changed_while_waiting_in_the_queue_uses_the_new_value(engine):
    """Значение меняется, пока сообщение стоит в очереди воспроизведения."""
    engine._player_ers_percent = 60.0
    message = _msg(engine, "Батарея {ers}.")
    prepare = engine._make_prepare(message)

    engine._player_ers_percent = 14.0          # разряд, пока фраза ждала
    text = prepare()

    assert text is not None and "14" in text
    assert "60" not in text


def test_a_worker_exception_does_not_kill_the_queue():
    """Регрессия того же класса, что найденный `_build_radio_message` seam."""
    spoken = []
    done = threading.Event()

    def speak(text, _persona):
        if text == "плохая":
            raise RuntimeError("синтез упал")
        spoken.append(text)
        done.set()

    q = TTSQueue(speak_fn=speak, maxsize=4)
    try:
        q.enqueue("плохая")
        q.enqueue("хорошая")
        assert done.wait(timeout=2.0)
        assert spoken == ["хорошая"]
    finally:
        q.stop(timeout=1.0)


def test_a_prepare_exception_does_not_kill_the_queue():
    spoken = []
    done = threading.Event()

    q = TTSQueue(speak_fn=lambda t, _p: (spoken.append(t), done.set()),
                 maxsize=4)
    try:
        q.enqueue("первая", prepare=lambda: (_ for _ in ()).throw(
            RuntimeError("резолв упал")))
        q.enqueue("вторая")
        assert done.wait(timeout=2.0)
        assert spoken == ["вторая"]
    finally:
        q.stop(timeout=1.0)


# ── Terminal state и структурированная причина ──────────────────────────────

def test_cancelled_message_gets_a_terminal_state_and_a_reason(engine):
    engine._player_gap_front = None
    message = _msg(engine, "Отрыв впереди {gap}.")

    assert engine._make_prepare(message)() is None
    assert _state(engine, message) == STATE_CANCELLED
    assert _reason(engine, message) is RadioCancelReason.DATA_UNAVAILABLE


def test_expired_message_reports_expiry(engine):
    message = _msg(engine, "Держи слева!", code="SPOTTER_CAR_LEFT")
    # Спотер живёт 2 секунды — сдвигаем монотонную отметку в прошлое.
    stale = message.__class__(**{
        **{f: getattr(message, f) for f in message.__slots__},
        "created_mono": time.monotonic() - 100.0,
        "expires_mono": time.monotonic() - 98.0,
    })
    assert engine._make_prepare(stale)() is None
    assert _reason(engine, stale) is RadioCancelReason.EXPIRED


def test_a_terminal_state_is_never_overwritten(engine):
    engine._player_gap_front = None
    message = _msg(engine, "Отрыв впереди {gap}.")
    engine._make_prepare(message)()
    first = _reason(engine, message)

    engine._note_radio_cancel(message, RadioCancelReason.SESSION_RESET)

    assert _reason(engine, message) is first


def test_not_voiced_message_still_reaches_a_terminal_state(engine):
    message = _msg(engine, "Текст")
    engine._note_radio_state(message, STATE_COMPLETED)
    assert _state(engine, message) == STATE_COMPLETED


# ── Вытеснение более новым сообщением о той же ситуации ─────────────────────

def _box_call(engine, tier):
    event = {"event_code": f"STRAT_BOX_CALL_{tier}", "priority": "critical",
             "speaker": "engineer", "created_at": time.time(),
             "created_mono": time.monotonic(),
             **plumbing.attach(box_call_window=12)}
    return build_message(event, phrase="Бокс, бокс.",
                         phrase_code=f"box.call_{tier}",
                         now=time.time(), now_mono=time.monotonic(),
                         telemetry=engine._volatile_snapshot(),
                         session_id=engine._radio_session_id)


def test_tier_two_supersedes_a_pending_tier_one(engine):
    engine._player_pit_status = 0
    tier1 = _box_call(engine, 1)
    tier2 = _box_call(engine, 2)

    engine._note_radio_newest(tier1)
    engine._note_radio_newest(tier2)

    assert engine._is_superseded(tier1)
    assert not engine._is_superseded(tier2)


def test_superseded_message_is_cancelled_with_its_own_reason(engine):
    tier1 = _box_call(engine, 1)
    tier2 = _box_call(engine, 2)
    engine._note_radio_newest(tier1)
    engine._note_radio_newest(tier2)

    assert engine._make_prepare(tier1)() is None
    assert _reason(engine, tier1) is RadioCancelReason.SUPERSEDED


def test_tier_three_supersedes_tier_two(engine):
    tier2 = _box_call(engine, 2)
    tier3 = _box_call(engine, 3)
    engine._note_radio_newest(tier2)
    engine._note_radio_newest(tier3)

    assert engine._is_superseded(tier2)
    assert engine._make_prepare(tier3)() is not None


def test_box_call_tiers_share_one_situation_so_supersession_works(engine):
    assert _box_call(engine, 1).situation_id == _box_call(engine, 2).situation_id


def test_messages_about_different_situations_do_not_supersede_each_other(engine):
    gap = _msg(engine, "Отрыв впереди {gap}.")
    box = _box_call(engine, 1)
    engine._note_radio_newest(gap)
    engine._note_radio_newest(box)

    assert not engine._is_superseded(gap)
    assert not engine._is_superseded(box)


def test_the_situation_registry_does_not_grow_without_bound(engine):
    """Регистрация идёт только через публичный метод — он и обрезает реестр."""
    for index in range(eng_mod._RADIO_SITUATION_LIMIT * 3):
        message = _box_call(engine, 1)
        # Каждый раз новая ситуация.
        engine._note_radio_newest(
            message.__class__(**{
                **{f: getattr(message, f) for f in message.__slots__},
                "situation_id": f"situation-{index}",
            }))
    assert len(engine._radio_newest) <= eng_mod._RADIO_SITUATION_LIMIT


# ── Ситуация закончилась ────────────────────────────────────────────────────

def test_box_call_is_cancelled_once_the_player_is_in_the_pit_lane(engine):
    message = _box_call(engine, 2)
    engine._player_pit_status = 1               # уже в пит-лейне

    assert engine._make_prepare(message)() is None
    assert _reason(engine, message) is RadioCancelReason.SITUATION_ENDED


def test_box_call_survives_while_the_player_is_still_on_track(engine):
    message = _box_call(engine, 2)
    engine._player_pit_status = 0
    assert engine._make_prepare(message)() is not None


# ── Flashback: физическая ситуация против высказывания ──────────────────────

def test_flashback_keeps_the_physical_situation_but_changes_the_utterance(engine):
    event = {"event_code": "ENGINEER_RAIN_ADVISORY", "speaker": "engineer",
             **plumbing.attach(rain_front_id=1)}

    before = build_message(event, phrase="Дождь скоро.", now=0.0, now_mono=0.0,
                           session_id="S", timeline_revision=0)
    after = build_message(event, phrase="Дождь скоро.", now=0.0, now_mono=0.0,
                          session_id="S", timeline_revision=1)

    # Физический фронт тот же — историю RaceFeed дробить нельзя.
    assert before.situation_id == after.situation_id
    # Высказывание другое — дедуп не заблокирует повторное предупреждение.
    assert before.dedupe_key != after.dedupe_key


def test_flashback_raises_the_timeline_revision(engine):
    before = engine._timeline_revision
    engine._handle_flashback()
    assert engine._timeline_revision == before + 1


def test_flashback_cancels_messages_from_the_abandoned_future(engine):
    message = _msg(engine, "Текст")
    engine._radio_lifecycle[message.id] = message

    engine._handle_flashback()

    assert _state(engine, message) == STATE_CANCELLED
    assert _reason(engine, message) is RadioCancelReason.FLASHBACK


def test_a_new_session_closes_pending_messages_with_its_own_reason(engine):
    message = _msg(engine, "Текст")
    engine._radio_lifecycle[message.id] = message

    engine._cancel_pending_radio(RadioCancelReason.SESSION_RESET)

    assert _reason(engine, message) is RadioCancelReason.SESSION_RESET


# ── Реальное воспроизведение управляет speaking ─────────────────────────────

def test_speaking_is_raised_by_the_playback_event_not_by_enqueue(engine):
    message = _msg(engine, "Боксы в конце круга.")
    engine._radio_lifecycle[message.id] = message

    assert engine._ui_state.snapshot()["speaking"] is False

    engine._on_playback_event("playing", message.id)
    state = engine._ui_state.snapshot()
    assert state["speaking"] is True
    assert state["now_speaking"] == "Боксы в конце круга."

    engine._on_playback_event("completed", message.id)
    assert engine._ui_state.snapshot()["speaking"] is False


def test_playback_events_drive_the_message_state(engine):
    message = _msg(engine, "Текст")
    engine._radio_lifecycle[message.id] = message

    engine._on_playback_event("playing", message.id)
    assert _state(engine, message) == STATE_PLAYING

    engine._on_playback_event("completed", message.id)
    assert _state(engine, message) == STATE_COMPLETED


def test_playback_event_for_an_unknown_message_is_harmless(engine):
    engine._on_playback_event("playing", "radio-does-not-exist")
    engine._on_playback_event("completed", None)


def test_playback_gate_blocks_an_expired_message_after_synthesis(engine):
    message = _msg(engine, "Держи слева!", code="SPOTTER_CAR_LEFT")
    gate = engine._make_playback_gate(message)
    assert gate() is True                       # свежее — играем

    stale = message.__class__(**{
        **{f: getattr(message, f) for f in message.__slots__},
        "created_mono": time.monotonic() - 100.0,
        "expires_mono": time.monotonic() - 98.0,
    })
    assert engine._make_playback_gate(stale)() is False
    assert _reason(engine, stale) is RadioCancelReason.EXPIRED


def test_voice_gate_defaults_to_playing_when_nothing_is_registered():
    """Отсутствие гейта не должно глушить речь."""
    from voice.tts import Voice

    voice = Voice()
    assert voice._playback_gate() is True


def test_display_text_never_shows_curly_braces(engine):
    engine._player_ers_percent = None
    message = _msg(engine, "Батарея {ers}.")
    assert "{" not in engine._display_text(message, "фолбэк")
