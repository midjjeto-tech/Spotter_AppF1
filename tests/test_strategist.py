"""commentator/strategist.py — карта strategy_ai_type -> код банка.

Собственных пулов у модуля больше нет: формулировки живут в
`core/radio/phrases.py`. Тесты проверяют карту и то, что каждый тип реально
резолвится в существующую спеку.
"""
import pytest

from commentator.strategist import _STRATEGY_CODE, get_message, strategy_phrase_code
from core.radio import phrases


@pytest.mark.parametrize("event_type", sorted(_STRATEGY_CODE))
def test_every_mapped_type_resolves_to_a_real_spec(event_type):
    """Карта не должна указывать на код, которого в банке нет — иначе
    `get_message` молча свалится в дефолтную «стратегия стабильна»."""
    assert strategy_phrase_code(event_type) in phrases.codes()


@pytest.mark.parametrize("event_type", sorted(_STRATEGY_CODE))
def test_every_type_produces_a_variant_of_its_own_spec(event_type):
    spec = phrases.spec_for(strategy_phrase_code(event_type))
    assert get_message(event_type) in spec.variants


def test_unknown_type_falls_back_to_stable():
    spec = phrases.spec_for("strategy.stable")
    assert get_message("совершенно неизвестный тип") in spec.variants


@pytest.mark.parametrize("event_type", ["box_call_1", "box_call_2", "box_call_3"])
def test_box_calls_stay_imperative(event_type):
    """Эскалация — команда, а не сообщение: каждый tier обязан звать в боксы."""
    assert "бокс" in get_message(event_type).lower()


def test_pit_window_with_known_laps_counts_them():
    """Единственная фраза со счётом кругов: число известно только здесь и
    волатильным не является."""
    assert get_message("pit_window", {"laps_to_pit": 3}) == "Пит через 3 круга"


@pytest.mark.parametrize("laps,tail", [(1, "круг"), (2, "круга"), (5, "кругов")])
def test_lap_count_agreement(laps, tail):
    assert get_message("pit_window", {"laps_to_pit": laps}).endswith(tail)


def test_selector_key_pins_the_variant_to_a_situation():
    """Один ключ — одна формулировка, иначе повторная телеметрия переписывала бы
    уже произнесённую реплику."""
    first = get_message("tyre_save", selector_key="situation-1")
    again = get_message("tyre_save", selector_key="situation-1")
    assert first == again
