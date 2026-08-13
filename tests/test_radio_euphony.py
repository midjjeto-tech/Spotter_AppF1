"""Беглый гласный в предлоге (core/radio/euphony.py).

Дефект жил на СТЫКЕ: шаблон банка держит предлог, числительное приезжает
подстановкой, и ни одна из сторон не видит другую. В эфире это звучало как
«в втором повороте» — на каждой трассе, во всех репликах коуча.
"""
import pytest

from core.radio import phrases
from core.radio.corner_words import ordinal_prepositional
from core.radio.euphony import fix_prepositions
from core.strategy_ai.sector_comparison import compare_best_sectors


def test_preposition_gains_the_vowel_before_a_cluster():
    assert fix_prepositions("в втором повороте") == "во втором повороте"


def test_capital_preposition_keeps_its_case():
    assert fix_prepositions("В втором повороте чисто.") == "Во втором повороте чисто."


def test_the_fix_is_idempotent():
    once = fix_prepositions("в втором")
    assert fix_prepositions(once) == once


def test_ordinary_prepositions_are_left_alone():
    for text in ("в седьмом повороте", "в апексе", "в боксы",
                 "в третьем секторе", "в первом"):
        assert fix_prepositions(text) == text


def test_a_word_ending_in_v_is_not_mistaken_for_the_preposition():
    """«Иванов встал» — «в» здесь конец фамилии, а не предлог."""
    assert fix_prepositions("Иванов встал") == "Иванов встал"


def test_empty_text_survives():
    assert fix_prepositions("") == ""
    assert fix_prepositions(None) is None


# ── Стык, ради которого модуль и появился ────────────────────────────────────

@pytest.mark.parametrize("code", [
    "coach.lockup_front_left", "coach.wheelspin", "coach.understeer",
    "coach.ref_brake_early", "coach.focus_set", "coach.focus_fixed",
])
def test_no_coach_line_about_turn_two_says_v_vtorom(code):
    """Второй поворот есть на каждой трассе календаря — эта реплика звучала
    неправильно чаще всех остальных вместе взятых."""
    spec = phrases.spec_for(code)
    available = {"corner_no": ordinal_prepositional(2), "loss": "три десятых",
                 "gain": "две десятых"}
    fields = {k: v for k, v in available.items() if k in spec.required_fields}
    for selector in range(len(spec.variants) * 2):
        text = phrases.render(code, fields, selector_key=str(selector))
        assert "в втором" not in text.lower(), text
        assert "во втором" in text.lower(), text


def test_sector_comparison_gets_the_same_fix_outside_the_bank():
    """Строка сравнения секторов идёт в эфир мимо банка — правило зовётся там
    отдельно, и разойтись эти два места не должны."""
    result = compare_best_sectors({2: 29000}, {2: 28000}, "Норрис")

    assert "во втором секторе" in result
    assert "в втором" not in result
