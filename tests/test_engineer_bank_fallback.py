"""Инженерский код без своей формулировки берёт текст в БАНКЕ, а не у LLM.

Разбор живого заезда 2026-08-27 (Монреаль): голосом инженера пять раз за
гонку прозвучало «Леклер получил штраф — упускает шансы на прорыв! Потеря
времени и позиций...» и дважды нечто похожее про Safety Car. Это текст
комментатора — третье лицо о пилоте, сказанное пилоту в наушники.

Механика была такая: `policy.channel_for` относит PENA и SAFETY_CAR_* к каналу
инженера (кто ГОВОРИТ), но точки вызова банка у этих кодов не было, поэтому в
`_commentary_loop` они доходили до генерации с пустой `phrase` и получали текст
у LLM (кто ПИШЕТ). Канал и источник текста — разные вопросы, и это стоило
целой гонки не того тона.

Здесь проверяется путь наружу, а не таблица: таблицу держит
tests/test_radio_policy.py.
"""
import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.radio import phrases, policy


@pytest.fixture
def engine():
    """Тот же приём, что в tests/test_coach_wiring.py: подменяем загрузку
    креденшелов, чтобы конструктор не лез в сеть."""
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _event(code, **extra):
    event = {"event_code": code, "dedupe_key": f"k:{code}"}
    event.update(extra)
    return event


def test_penalty_speaks_the_bank_not_a_broadcast_line(engine):
    """Именно та реплика, что уехала в эфир живой гонкой."""
    phrase = engine._engineer_bank_phrase(_event("PENA"))

    assert phrase in phrases.spec_for("penalty.received").variants
    # Инженер обращается к пилоту, а не рассказывает о нём. Фамилия в реплике
    # инженера — признак того, что текст снова пишет комментатор.
    assert "Леклер" not in phrase


@pytest.mark.parametrize("code", sorted(policy.BANK_CODE_BY_EVENT))
def test_every_mapped_code_produces_a_bank_line(engine, code):
    """Отображение есть у всех кодов таблицы — значит и текст обязан быть.

    Кроме одного случая: `LEADER_CHANGE` требует имени соперника, и без него
    банк отказывает намеренно (проверяется отдельно ниже)."""
    event = _event(code)
    if code == "LEADER_CHANGE":
        event["driver"] = "Норрис"

    phrase = engine._engineer_bank_phrase(event)

    assert phrase, f"{code}: банк не дал формулировки"
    # Токены позднего связывания (`{wear}`, `{ers}`) обязаны ОСТАТЬСЯ токенами:
    # заряд и износ устаревают за время очереди и синтеза, и подставлять их
    # здесь — та самая ошибка «батарея называет не те цифры» (ТЗ §8). Поэтому
    # проверяется не отсутствие скобок, а отсутствие ЧУЖИХ имён в них.
    spec = phrases.spec_for(policy.BANK_CODE_BY_EVENT[code])
    leftover = phrases.tokens_in(phrase) - spec.volatile_fields
    assert not leftover, f"{code}: неразрешённые поля {sorted(leftover)} в {phrase!r}"


def test_leader_change_without_a_name_falls_through_instead_of_lying(engine):
    """Отказ банка — не поломка, а развилка: реплику напишет LLM, как раньше.

    Молчать здесь нельзя (событие стоит озвучить), выдумывать имя — тем более.
    """
    assert engine._engineer_bank_phrase(_event("LEADER_CHANGE")) == ""


def test_codes_with_their_own_render_are_left_alone(engine):
    """Фолбэк не имеет права перебивать трекер, который уже всё сложил сам."""
    for code in ("STRAT_BOX_CALL_1", "ENGINEER_GAP_DIGEST", "PRAISE_OVERTAKE"):
        assert engine._engineer_bank_phrase(_event(code)) == "", code


def test_commentator_codes_are_not_touched(engine):
    """Банк принадлежит инженерскому конвейеру: OVTK и CHQF — не его дело."""
    for code in ("OVTK", "CHQF", "RCWN"):
        assert engine._engineer_bank_phrase(_event(code)) == "", code


def test_the_bank_line_is_shorter_than_a_broadcast_sentence(engine):
    """Косвенная, но говорящая проверка тона.

    Потолок длины по срочности (ТЗ §10) — то, чем инженер отличается от
    комментатора на слух. Реплика LLM, уехавшая в эфир 08-27, была на 11 слов
    при потолке 9 для critical.
    """
    for code, bank_code in policy.BANK_CODE_BY_EVENT.items():
        event = _event(code)
        if code == "LEADER_CHANGE":
            event["driver"] = "Норрис"
        phrase = engine._engineer_bank_phrase(event)
        if not phrase:
            continue
        limit = phrases.spec_for(bank_code).max_words
        assert phrases.word_count(phrase) <= limit, (
            f"{code}: {phrases.word_count(phrase)} слов при потолке {limit}")
