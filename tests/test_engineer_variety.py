"""Фолбэк race_ai после слияния банков: `commentator/radio.py::race_ai_phrase`.

Раньше эти ситуации обслуживал второй банк `commentator/engineer.py` — со
своими пулами, своим лимитом длины (20 слов против 9–18) и без единого
инварианта общего банка. Достижим он был ТОЛЬКО при отказе LLM, поэтому манера
речи менялась ровно тогда, когда что-то ломалось. Модуль удалён, эти тесты
стерегут то же, что стерегли раньше, но на новом пути.

Одно свойство изменилось СОЗНАТЕЛЬНО и здесь зафиксировано: старый банк на
каждый вызов выдавал новую формулировку (shuffle-bag), новый закрепляет её за
ситуацией. Так и должно быть — повторный пакет телеметрии по той же ситуации
обязан давать ту же строку, иначе он переписывает уже произнесённую реплику.
Разнообразие между РАЗНЫМИ ситуациями обеспечивает `core/radio/variety.py`.
"""
import pytest

from commentator import radio, templates
from core.radio import phrases, variety


@pytest.fixture(autouse=True)
def _clean():
    variety.reset()
    yield
    variety.reset()


def _corner_data(advice: str = "none", phase: str = "braking",
                 drs: bool = False) -> dict:
    return {
        "driver": "Норрис",
        "drs": drs,
        "track": {"corner": "Stowe", "phase": phase, "defense_advice": advice},
    }


# ── Привязка к трассе не потеряна ────────────────────────────────────────────

def test_corner_name_reaches_the_phrase():
    line = radio.race_ai_phrase("attack", _corner_data(), selector_key="k")
    assert "Stowe" in line, line


def test_rival_name_reaches_the_phrase():
    line = radio.race_ai_phrase("attack", _corner_data(), selector_key="k")
    assert "Норрис" in line, line


def test_inside_advice_produces_inside_wording():
    """Главное, что нельзя было потерять при слиянии: тип совета — это
    СЕМАНТИКА. «Сохрани выход» вместо «закрой внутреннюю» — другое указание,
    а не другая формулировка того же."""
    line = radio.race_ai_phrase(
        "attack", _corner_data(advice="cover_inside"), selector_key="k")
    assert "Stowe" in line
    assert any(m in line.lower() for m in ("внутрен", "внутрь", "двер", "апекс")), line


def test_hold_line_advice_produces_line_wording():
    line = radio.race_ai_phrase(
        "attack", _corner_data(advice="hold_line"), selector_key="k")
    assert any(m in line.lower() for m in ("лини", "траектор", "предсказу")), line


def test_drs_is_mentioned_when_the_rival_has_it():
    line = radio.race_ai_phrase(
        "attack", _corner_data(drs=True), selector_key="k")
    assert any(m in line.lower() for m in ("drs", "крыл")), line


def test_explicit_advice_wins_over_drs():
    """Порядок приоритетов перенесён из удалённого модуля без изменений:
    явный совет важнее признака DRS."""
    line = radio.race_ai_phrase(
        "attack", _corner_data(advice="cover_inside", drs=True),
        selector_key="k")
    assert any(m in line.lower() for m in ("внутрен", "внутрь", "двер", "апекс")), line


def test_approach_phase_gets_the_general_advice():
    line = radio.race_ai_phrase(
        "attack", _corner_data(phase="straight"), selector_key="k")
    assert "Stowe" in line, line


def test_side_by_side_battle_is_not_defence():
    """Соперник уже рядом — указание другое: «оставь место», а не «закрой
    дверь»."""
    line = radio.race_ai_phrase("battle", _corner_data(), selector_key="k")
    assert any(m in line.lower() for m in ("борьб", "рядом", "место", "бок")), line


# ── Без привязки к трассе ────────────────────────────────────────────────────

def test_no_corner_falls_back_to_a_plain_line():
    line = radio.race_ai_phrase("attack", {"driver": "Норрис"}, selector_key="k")
    assert line and "{" not in line, line
    assert "Норрис" in line


@pytest.mark.parametrize("event_type", [
    "attack", "battle", "tyre_warning", "final_lap", "stable", "нет такого",
])
def test_every_event_type_produces_a_usable_line(event_type):
    """Неизвестный тип не имеет права дать пустоту или строку с токенами:
    это фолбэк, он работает, когда всё остальное уже отказало."""
    line = radio.race_ai_phrase(event_type, {"driver": "Норрис"},
                                selector_key="k")
    assert line and "{" not in line, (event_type, line)


def test_tyre_warning_carries_no_stale_number():
    """Точный износ — волатильное поле, оно связывается поздно, у порога
    озвучки. Подставить его здесь значило бы назвать цифру, снятую за десятки
    секунд до звука."""
    line = radio.race_ai_phrase("tyre_warning", {"wear": 67.4}, selector_key="k")
    assert "67" not in line, line
    assert "{" not in line, line


# ── Свойства единого банка теперь распространяются и сюда ────────────────────

def test_the_fallback_obeys_the_bank_length_limit():
    """То, ради чего слияние и делалось: у старого банка был свой лимит в 20
    слов, и при отказе LLM реплики становились длиннее обычных."""
    for event_type in ("attack", "battle", "tyre_warning", "final_lap", "stable"):
        line = radio.race_ai_phrase(event_type, _corner_data(), selector_key="k")
        assert phrases.word_count(line) <= phrases.MAX_WORDS_NORMAL, line


def test_the_same_situation_gives_the_same_wording():
    first = radio.race_ai_phrase("attack", _corner_data(), selector_key="sit-1")
    for _ in range(4):
        assert radio.race_ai_phrase(
            "attack", _corner_data(), selector_key="sit-1") == first


def test_different_situations_do_not_repeat_back_to_back():
    said = [radio.race_ai_phrase("attack", _corner_data(), selector_key=f"s{i}")
            for i in range(12)]
    assert not [1 for a, b in zip(said, said[1:]) if a == b]


# ── Проводка ─────────────────────────────────────────────────────────────────

def test_event_driver_reaches_the_template_path():
    event = {
        "event_code": "ATTACK",
        "driver": "Норрис",
        "race_ai_data": {"gap": 0.7, "confidence": 0.8},
    }
    assert "Норрис" in templates.render(event, "tv")


def test_the_old_module_is_gone():
    """Слияние не считается сделанным, пока второй банк существует: он
    возвращается в код первым же `from commentator import engineer`."""
    with pytest.raises(ImportError):
        from commentator import engineer  # noqa: F401
