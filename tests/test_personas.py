"""Персоны комментатора: контракт сборки system_prompt + завязка на богатый контекст.

Персоны — это промпты-строки, поэтому проверяем не «звучание», а инварианты:
все персоны имеют лимит слов; system_prompt() корректно собирает базу + глоссарий
составов + контракт вывода; неизвестная персона уходит в дефолт; каждый промпт
реально опирается на новый контекст (отрывы/шины/темп), а не на старые триггеры.
"""
import pytest

from commentator.personas import (
    PERSONAS, WORD_LIMIT, DEFAULT_PERSONA, system_prompt,
)


def test_all_personas_have_word_limit():
    assert set(WORD_LIMIT) == set(PERSONAS)
    assert DEFAULT_PERSONA in PERSONAS


def test_calm_is_shortest():
    others = [v for k, v in WORD_LIMIT.items() if k != "calm"]
    assert WORD_LIMIT["calm"] < min(others)   # аналитик лаконичнее всех


@pytest.mark.parametrize("persona", list(PERSONAS))
def test_system_prompt_has_contract_and_resolved_limit(persona):
    out = system_prompt(persona)
    assert PERSONAS[persona][:20] in out       # база персоны на месте
    assert "{limit}" not in out                 # шаблон подставлен, без «дыр»
    assert str(WORD_LIMIT[persona]) in out      # реальный лимит слов виден
    assert "ПУСТУЮ" in out                       # право осознанно молчать
    assert "ОДНА" in out                         # ровно одна фраза


def test_unknown_persona_falls_back_to_default():
    assert system_prompt("nonexistent") == system_prompt(DEFAULT_PERSONA)


@pytest.mark.parametrize("persona", list(PERSONAS))
def test_persona_uses_rich_context(persona):
    """Каждая персона должна опираться на новый контекст: отрывы + шины + темп/износ."""
    text = PERSONAS[persona].lower()
    assert "отрыв" in text
    assert ("шин" in text) or ("резин" in text) or ("состав" in text)
    assert ("износ" in text) or ("темп" in text)


@pytest.mark.parametrize("persona", list(PERSONAS))
def test_tyre_glossary_visible_to_every_persona(persona):
    out = system_prompt(persona).lower()
    assert "софт" in out and "медиум" in out and "хард" in out


def test_calm_is_an_analyst_not_a_second_engineer():
    """После разделения каналов инженер существует отдельно, своим голосом и со
    своим банком фраз. Промпт `calm` начинался словами «Ты — гоночный инженер на
    пит-уолле, говоришь пилоту по радио» — то есть описывал ВТОРОГО инженера в
    эфире. Подпись в `core/radio/speakers.py` при этом давно гласит «RACE
    ANALYST». Тест на подстроки дешёвый и ловит откат."""
    text = PERSONAS["calm"].lower()
    for forbidden in ("инженер", "пит-уолл", "говоришь пилоту"):
        assert forbidden not in text, forbidden


def test_calm_talks_about_the_race_not_to_the_driver():
    text = PERSONAS["calm"].lower()
    assert "аналитик" in text
    assert "гонк" in text


@pytest.mark.parametrize("persona", list(PERSONAS))
def test_no_persona_addresses_the_player_by_name(persona):
    """Обращение по имени переехало к инженеру (`core/radio/address.py`), где
    частота — часть характера персонажа. Комментатору оно больше не выдаётся:
    два голоса, зовущих пилота по имени, звучали бы как один сбойный."""
    assert "ПИЛОТ:" not in PERSONAS[persona]


def test_toxic_has_no_explicit_profanity():
    """Выбран цензурный Toxic — в промпте не должно быть прямого мата."""
    text = PERSONAS["toxic"].lower()
    for bad in ("бля", "нах", "пизд", "хуй", "сук"):
        assert bad not in text


def test_output_contract_gives_precedence_to_task_directive():
    out = system_prompt("tv")
    assert "ЗАДАЧА" in out
    assert "ПРИОРИТЕТНАЯ" in out
