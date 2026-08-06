"""Голос выбирается по КАНАЛУ сообщения, а не по маркеру speaker.

Споттер и инженер публикуются с одним и тем же speaker=SPEAKER_ENGINEER
(core/engine.py::_spotter_tick), поэтому маркер их не различает, а канал —
различает."""
import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.radio.message import build_message


def _voice_persona_for_code(code: str, speaker: str = "engineer") -> str | None:
    message = build_message(
        {"event_code": code, "priority": "normal", "importance": 50,
         "speaker": speaker},
        phrase="тест", now=1000.0, now_mono=50.0)
    return message.voice_persona


def test_spotter_and_engineer_get_different_voice_slots():
    assert _voice_persona_for_code("SPOTTER_CAR_LEFT") == "spotter"
    assert _voice_persona_for_code("STRAT_BOX_CALL_1") == "engineer"


def test_commentator_keeps_the_user_persona():
    # speaker="" здесь обязателен: маркер "engineer" — страховочное правило в
    # policy.channel_for для кодов, забытых в _ENGINEER_CODES, и он увёл бы
    # OVTK в инженерский канал, хотя это реплика комментатора.
    assert _voice_persona_for_code("OVTK", speaker="") is None


# ── Движок реально читает канал, а не маркер (core/engine.py::_voice_slot_for) ──
#
# Тесты выше проверяют только build_message() — а он выставлял voice_persona
# правильно ещё ДО того, как движок начал его читать. Значит они зелены
# независимо от того, смотрит ли _commentary_loop на message.voice_persona или
# вернулся к снесённой таблице _SPEAKER_VOICE. _commentary_loop — бесконечный
# поток, который в проекте намеренно не юнит-тестируется напрямую (см.
# tests/test_engine_planner.py:202), поэтому решение вынесено в именованный
# метод _voice_slot_for(), и тестируется он, а не цикл вокруг него.

@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None              # без Yandex/сети → фолбэк
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def test_engine_takes_the_voice_slot_from_the_message_channel(engine):
    """Проводка, ради которой всё делалось: движок обязан читать канал
    сообщения. Прежний код брал голос из маркера speaker и отдавал инженеру и
    споттеру ОДИН голос — маркер у них одинаковый."""
    for code, expected in (("SPOTTER_CAR_LEFT", "spotter"),
                           ("STRAT_BOX_CALL_1", "engineer")):
        event = {"event_code": code, "priority": "normal", "importance": 50,
                 "speaker": "engineer"}
        message = build_message(event, phrase="тест", now=1000.0, now_mono=50.0)
        assert engine._voice_slot_for(event, message) == expected


def test_engine_leaves_the_commentator_on_the_user_persona(engine):
    event = {"event_code": "OVTK", "priority": "normal", "importance": 50,
             "speaker": ""}
    message = build_message(event, phrase="тест", now=1000.0, now_mono=50.0)
    assert engine._voice_slot_for(event, message) is None


def test_engine_falls_back_to_the_marker_when_the_message_did_not_build(engine):
    """`_build_radio_message` возвращает None при сбое сборки. Тогда голос
    берётся из маркера — прежнее поведение, чтобы инженерская реплика не ушла
    голосом комментатора."""
    assert engine._voice_slot_for({"speaker": "engineer"}, None) == "engineer"
    assert engine._voice_slot_for({"speaker": ""}, None) is None


# ── PTT-ответ (core/engine.py::_say_ptt_answer) ──────────────────────────────

def test_say_ptt_answer_uses_the_engineer_voice(engine, monkeypatch):
    """`_say_ptt_answer` не строит RadioMessage сам — он берёт готовый из
    `_ptt_answer_message` и читает `message.voice_persona`. Проверяем именно
    вызов `voice.say()`, а не промежуточное сообщение (то уже проверено в
    tests/test_radio_ptt_dialogue.py::test_ptt_answer_uses_the_engineer_voice) —
    здесь важно, что персона реально доезжает до синтеза."""
    said = []
    monkeypatch.setattr(engine.voice, "say",
                        lambda text, priority="normal", **kw:
                        said.append((text, priority, kw.get("persona"))) or True)
    engine._say_ptt_answer("Передние 48, задние 39.")
    assert len(said) == 1
    text, priority, persona = said[0]
    assert text == "Передние 48, задние 39."
    assert persona == "engineer"


# ── Предстартовая накачка (core/engine.py::_generate_pre_race_pep_talk) ──────
#
# Этот путь уже покрыт тестом
# tests/test_engine_pre_race_pep_talk.py::test_generate_pre_race_pep_talk_speaks_with_the_engineer_voice
# — он перехватывает engine.voice.say и проверяет persona == voice_cast.SLOT_ENGINEER.
# Не дублируется здесь намеренно.
