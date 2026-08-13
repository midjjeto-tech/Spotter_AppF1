"""Причина потери (core/coach_ai/diagnosis.py).

Главный тест здесь — последний: поворот без причины НЕ становится работой
сессии. Именно указания вида «здесь ты теряешь время» и делали коуча
бесполезным — они не отличаются от молчания ничем, кроме раздражения.
"""
from core.coach_ai.cost import CornerCost
from core.coach_ai.diagnosis import (MIN_MISTAKE_OCCURRENCES, CornerDiagnosis,
                                     diagnose)


def _cost(corner_id: int, cost_ms: float = 300.0, share: float = 1.0) -> CornerCost:
    return CornerCost(corner_id=corner_id, corner_name=f"Turn {corner_id}",
                      cost_ms=cost_ms, laps=6, share=share)


def _mistakes(corner_id: int, kind: str, times: int) -> list[dict]:
    return [{"corner_id": corner_id, "kind": kind, "lap": lap}
            for lap in range(times)]


def test_repeated_mistake_becomes_the_cause():
    result = diagnose([_cost(7)], _mistakes(7, "lockup", 6))

    assert len(result) == 1
    assert result[0].cause == "lockup"
    assert result[0].cause_kind == "mistake"
    assert result[0].occurrences == 6
    assert "блокировка" in result[0].evidence
    assert "6 раз" in result[0].evidence


def test_single_mistake_is_not_a_cause():
    """Один срыв — это круг, а не привычка."""
    result = diagnose([_cost(7)], _mistakes(7, "lockup", MIN_MISTAKE_OCCURRENCES - 1))

    assert result[0].cause is None
    assert result[0].actionable is False


def test_technique_deviation_becomes_the_cause_when_no_mistake_repeats():
    result = diagnose([_cost(4)], [], {4: {"brake": 2.4, "throttle": 0.3}})

    assert result[0].cause == "brake"
    assert result[0].cause_kind == "technique"
    assert result[0].occurrences == 0
    assert result[0].evidence


def test_technique_below_its_threshold_is_not_a_cause():
    result = diagnose([_cost(4)], [], {4: {"brake": 0.8, "throttle": 0.9}})

    assert result[0].cause is None


def test_strongest_technique_metric_wins():
    result = diagnose([_cost(4)], [], {4: {"brake": 1.2, "min_speed": 3.1}})

    assert result[0].cause == "min_speed"


def test_repeated_mistake_beats_technique_deviation():
    """Срыв бьёт технику: сорванное колесо пилот перепроверит сам на повторе, а
    «тормозишь на пятнадцать метров раньше» ему приходится принимать на веру."""
    result = diagnose([_cost(7)], _mistakes(7, "wheelspin", 5),
                      {7: {"brake": 9.0}})

    assert result[0].cause == "wheelspin"
    assert result[0].cause_kind == "mistake"


def test_mistakes_in_another_corner_do_not_explain_this_one():
    result = diagnose([_cost(7)], _mistakes(2, "lockup", 8))

    assert result[0].cause is None


def test_dominant_mistake_kind_wins_within_a_corner():
    mistakes = _mistakes(7, "lockup", 4) + _mistakes(7, "offtrack", 9)

    result = diagnose([_cost(7)], mistakes)

    assert result[0].cause == "offtrack"
    assert result[0].occurrences == 9


def test_order_and_prices_come_from_costs_untouched():
    costs = [_cost(7, 400.0, 0.6), _cost(2, 260.0, 0.4)]

    result = diagnose(costs, [])

    assert [d.corner_id for d in result] == [7, 2]
    assert [d.cost_ms for d in result] == [400.0, 260.0]
    assert [d.share for d in result] == [0.6, 0.4]


def test_corner_without_a_cause_is_never_actionable():
    """Он остаётся в разборе как факт, но работой сессии стать не может."""
    result = diagnose([_cost(9)], [], {})

    assert result[0].cause is None
    assert result[0].evidence == ""
    assert result[0].actionable is False
    assert not any(d.actionable for d in result)


def test_broken_mistake_rows_do_not_crash_the_diagnosis():
    """Срыв вне поворота (corner_id=None) в карте есть всегда — он не причина
    потери В ПОВОРОТЕ, но и уронить разбор не должен."""
    mistakes = [{"corner_id": None, "kind": "oversteer"},
                {"corner_id": 7, "kind": None},
                {"kind": "lockup"}] + _mistakes(7, "lockup", 4)

    result = diagnose([_cost(7)], mistakes)

    assert result[0].cause == "lockup"
    assert result[0].occurrences == 4


def test_empty_costs_give_an_empty_diagnosis():
    assert diagnose([], _mistakes(7, "lockup", 9)) == []


def test_to_dict_is_flat_and_json_ready():
    row = diagnose([_cost(7)], _mistakes(7, "lockup", 4))[0]

    data = row.to_dict()

    assert isinstance(row, CornerDiagnosis)
    assert data["corner_id"] == 7
    assert data["cause"] == "lockup"
    assert isinstance(data["cost_ms"], int)
    assert all(not isinstance(v, (list, dict)) for v in data.values())
