"""PTT-диалог: новые темы, команды и радио-сеанс через движок (Task 5).

ТЗ §12 перечисляет минимальный набор тем. Здесь проверяется, что каждая
распознаётся, отвечает по снимку телеметрии и НЕ выдумывает данных, которых нет.
"""
import pytest

import core.engine as eng_mod
from commentator import radio_answer
from core.engine import F1Engine
from core.radio.message import STATE_COMPLETED, STATE_PLAYING, build_message
from core.radio.phrases import NO_DATA_ANSWERS


@pytest.fixture
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _answer(question, **kwargs):
    defaults = dict(
        weather=None, rain_forecast=None, gap_front_ms=None, gap_behind_ms=None,
        tyre_wear=None)
    defaults.update(kwargs)
    return radio_answer.answer_radio_question(question, **defaults)


# ── Классификация всех тем из ТЗ §12 ────────────────────────────────────────

@pytest.mark.parametrize("question,topic", [
    ("какой отрыв впереди", "gap_ahead"),
    ("сколько сзади", "gap_behind"),
    ("какая у меня позиция", "position"),
    ("что с шинами", "tyres"),
    ("какой износ", "tyres"),
    ("что с передним крылом", "front_wing"),
    ("как машина", "car_state"),
    ("сколько топлива", "fuel"),
    ("какой заряд батареи", "ers"),
    ("что с погодой", "weather"),
    ("когда мне в питы", "pit_window"),
    ("стоит ли заезжать", "should_pit"),
    ("какой у нас план", "strategy"),
    ("что с сейфти каром", "safety_car"),
    ("какое время последнего круга", "last_lap"),
    ("с кем я борюсь", "rival"),
])
def test_every_topic_from_the_brief_is_classified(question, topic):
    assert radio_answer.classify_topic(question) == topic


@pytest.mark.parametrize("question,command", [
    ("повтори", "repeat"),
    ("не расслышал", "repeat"),
    ("ещё раз", "repeat"),
    ("тише", "toggle_commentary"),
    ("помолчи", "toggle_commentary"),
    ("говори чаще", "talk_more"),
    ("рассказывай больше", "talk_more"),
])
def test_every_command_from_the_brief_is_classified(question, command):
    assert radio_answer.classify_command(question) == command


def test_repeat_wins_over_a_topic_stem():
    """«повтори про шины» — это команда повтора, не свежий ответ про шины:
    пилот не расслышал, а не спросил заново."""
    assert radio_answer.classify_command("повтори про шины") == "repeat"


def test_commands_are_checked_before_topics():
    """Порядок гарантирует движок, но стемы не должны конфликтовать сами с
    собой."""
    assert radio_answer.classify_command("тише") == "toggle_commentary"


# ── Новые темы отвечают по данным ───────────────────────────────────────────

def test_front_wing_reports_its_own_damage():
    answer = _answer("что с передним крылом",
                     damage={"wing_damage": 45, "floor_damage": 0,
                             "gearbox_damage": 0, "engine_damage": 0})
    assert "45" in answer


def test_intact_front_wing_says_so():
    answer = _answer("что с передним крылом",
                     damage={"wing_damage": 2, "floor_damage": 0,
                             "gearbox_damage": 0, "engine_damage": 0})
    assert "порядке" in answer


def test_car_state_summarises_damage():
    answer = _answer("как машина",
                     damage={"wing_damage": 0, "floor_damage": 55,
                             "gearbox_damage": 0, "engine_damage": 0})
    assert "пол" in answer.lower()


def test_car_state_mentions_worn_tyres_when_the_body_is_fine():
    answer = _answer("как машина", damage={}, tyre_wear=72.0)
    assert "72" in answer


def test_intact_car_reports_being_fine():
    answer = _answer("как машина", damage={}, tyre_wear=10.0, fuel_kg=30.0)
    assert "цела" in answer


def test_strategy_reports_the_active_plan():
    answer = _answer("какой у нас план",
                     strategy={"action": "hold", "advice": "Держим темп."})
    assert "плане" in answer or "план" in answer.lower()


def test_strategy_translates_the_action_for_speech():
    answer = _answer("какой у нас план", strategy={"action": "pit"})
    assert "боксы" in answer.lower()


@pytest.mark.parametrize("status,expected", [
    (0, "чистая"), (1, "Safety Car"), (2, "иртуальный"),
])
def test_safety_car_status_is_reported(status, expected):
    assert expected in _answer("что с сейфти каром", safety_car_status=status)


def test_last_lap_time_is_formatted_as_minutes_and_seconds():
    answer = _answer("какое время последнего круга", last_lap_ms=92_400)
    assert "1:32.4" in answer


def test_short_lap_time_omits_the_minutes():
    answer = _answer("какое время последнего круга", last_lap_ms=45_300)
    assert "45.3" in answer


def test_should_pit_is_a_decision_not_a_description():
    yes = _answer("стоит ли заезжать", tyre_age=30, tyre_wear=85.0,
                  laps_remaining=10, tyre_compound="S")
    assert yes.startswith("Да") or yes.startswith("Нет")


def test_rival_names_the_drivers_around():
    answer = _answer("с кем я борюсь", ahead_name="Норрис",
                     behind_name="Албон", gap_front_ms=900,
                     gap_behind_ms=1500)
    assert "Норрис" in answer and "Албон" in answer


def test_rival_falls_back_to_numbers_when_names_are_unknown():
    """Имён нет, но цифры есть — отдать их лучше, чем отказать."""
    answer = _answer("с кем я борюсь", gap_front_ms=900)
    assert "0.9" in answer


def test_gap_ahead_and_behind_are_separately_answerable():
    ahead = _answer("какой отрыв впереди", gap_front_ms=1300)
    behind = _answer("сколько сзади", gap_behind_ms=2600)
    assert "1.3" in ahead and "сзади" not in ahead
    assert "2.6" in behind and "впереди" not in behind


def test_leader_is_told_there_is_nobody_ahead():
    assert "лидируешь" in _answer("какой отрыв впереди", gap_front_ms=None)


# ── Не выдумывать данных ────────────────────────────────────────────────────

@pytest.mark.parametrize("question", [
    "что с передним крылом",
    "какой у нас план",
    "что с сейфти каром",
    "какое время последнего круга",
    "с кем я борюсь",
])
def test_missing_data_gives_a_short_honest_refusal(question):
    """ТЗ §12: короткий честный отказ, не длинная универсальная отговорка."""
    answer = _answer(question)
    assert answer in NO_DATA_ANSWERS, answer
    assert len(answer.split()) <= 5


def test_unrecognised_question_still_gets_an_answer():
    assert _answer("расскажи анекдот") == radio_answer.OFF_TOPIC_ANSWER


# ── «Повтори» через движок ──────────────────────────────────────────────────

def _spoken(engine, phrase):
    event = {"event_code": "ENGINEER_GAP_DIGEST", "speaker": "engineer",
             "created_at": 1000.0, "created_mono": 0.0}
    message = build_message(event, phrase=phrase, now=1000.0, now_mono=0.0)
    engine.radio_session.note(message.with_state(STATE_PLAYING, now=1.0))
    engine.radio_session.note(
        message.with_state(STATE_PLAYING, now=1.0)
        .with_state(STATE_COMPLETED, now=2.0))


def test_repeat_command_returns_the_last_spoken_engineer_line(engine):
    _spoken(engine, "Передние 48, задние 39.")
    assert engine._execute_voice_command("repeat") == "Передние 48, задние 39."


def test_repeat_command_when_nothing_was_spoken_says_so(engine):
    answer = engine._execute_voice_command("repeat")
    assert "нечего" in answer.lower()


def test_repeat_command_does_not_change_settings(engine):
    _spoken(engine, "Реплика.")
    before = dict(engine.settings)
    engine._execute_voice_command("repeat")
    assert engine.settings == before


def test_talk_more_enables_the_engineer_channel(engine):
    engine.apply_settings({"engineer_chatter_enabled": False,
                           "commentary_enabled": False})
    answer = engine._execute_voice_command("talk_more")

    assert engine.settings["engineer_chatter_enabled"] is True
    assert engine.settings["commentary_enabled"] is True
    assert "чаще" in answer.lower()


def test_quiet_command_still_works(engine):
    engine.apply_settings({"commentary_enabled": True})
    engine._execute_voice_command("toggle_commentary")
    assert engine.settings["commentary_enabled"] is False


# ── Радио-сеанс в проекции ──────────────────────────────────────────────────

def test_state_exposes_the_radio_section(engine):
    state = engine.get_state()
    assert "radio" in state
    assert set(state["radio"]) == {"revision", "speakers", "status",
                                   "active_message", "history", "ptt",
                                   "repeatable"}


def test_legacy_fields_are_still_present(engine):
    """ТЗ §18: расширяем проекцию, а не заменяем. `speaking`/`now_speaking`/
    `radio_message`/`voice_query` читают «Обзор» и игровой оверлей."""
    state = engine.get_state()
    for key in ("speaking", "now_speaking", "radio_message", "voice_query"):
        assert key in state


def test_radio_section_is_json_serialisable(engine):
    import json

    _spoken(engine, "Реплика.")
    engine.radio_session.note_driver_line("Какой износ?")
    payload = engine.get_state()["radio"]
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload


def test_ptt_status_flows_into_the_radio_section(engine):
    engine._set_voice_query(status="listening")
    assert engine.get_state()["radio"]["ptt"]["state"] == "listening"


def test_ptt_dialogue_reaches_the_radio_section(engine):
    engine._set_voice_query(status="thinking", question="Какой износ?")
    engine._set_voice_query(status="done", answer="Передние 48.")

    ptt = engine.get_state()["radio"]["ptt"]
    assert ptt["state"] == "done"
    assert ptt["engineer_text"] == "Передние 48."


def test_driver_question_appears_in_the_radio_history(engine):
    engine.radio_session.note_driver_line("Какой износ?")
    history = engine.get_state()["radio"]["history"]
    assert any(entry["source"] == "driver" for entry in history)


def test_repeatable_is_reported_to_the_ui(engine):
    _spoken(engine, "Передние 48.")
    assert engine.get_state()["radio"]["repeatable"] == "Передние 48."


# ── PTT-ответ проходит тем же путём, что автоматические сообщения ───────────

def test_ptt_answer_lands_in_the_radio_history(engine):
    """ТЗ §13 и критерий готовности №7: автоматические и PTT-сообщения
    отображаются ЕДИНЫМ способом. Раньше ответ уходил прямо в `voice.say()` в
    обход конвейера и для истории не существовал."""
    engine._note_ptt_answer_unvoiced("Передние 48, задние 39.")

    history = engine.get_state()["radio"]["history"]
    entry = next(e for e in history if e["text"] == "Передние 48, задние 39.")
    assert entry["source"] == "engineer"


def test_ptt_answer_becomes_repeatable(engine):
    engine._note_ptt_answer_unvoiced("Передние 48, задние 39.")
    assert engine._execute_voice_command("repeat") == "Передние 48, задние 39."


def test_ptt_answer_is_an_engineer_message_with_a_human_title(engine):
    message = engine._ptt_answer_message("Передние 48.")
    assert message is not None
    assert message.channel == "engineer"
    assert message.ui_title
    assert "USER_Q" not in message.ui_title


def test_ptt_answer_never_expires(engine):
    """Пилот спросил сам — опоздавший ответ лучше молчания."""
    message = engine._ptt_answer_message("Передние 48.")
    assert message.ttl is None
    assert not message.is_expired(1_000_000.0)


def test_ptt_answer_uses_the_engineer_voice(engine):
    message = engine._ptt_answer_message("Передние 48.")
    assert message.voice_persona == "engineer"


def test_two_ptt_answers_are_separate_situations(engine):
    """Два одинаковых вопроса — два законных запроса, не повтор одного."""
    first = engine._ptt_answer_message("Передние 48.")
    second = engine._ptt_answer_message("Передние 48.")
    assert first.id != second.id
