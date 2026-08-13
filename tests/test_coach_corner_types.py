"""Потеря по типам поворотов и подпись баланса (core/coach_ai/corner_types.py).

Главный тест здесь — предпоследний: пять сносов в ОДНОЙ шпильке не должны
выдаваться за механический баланс. Именно на этой подмене (считать срывы вместо
поворотов) строится большинство ложных советов по сетапу.
"""
from core.coach_ai.corner_types import (MIN_CORNERS_FOR_PATTERN,
                                        balance_signature, by_corner_type)
from core.coach_ai.diagnosis import CornerDiagnosis


def _d(corner_id: int, cost_ms: float) -> CornerDiagnosis:
    return CornerDiagnosis(
        corner_id=corner_id, corner_name=None, cost_ms=cost_ms, share=0.0,
        laps=6, cause="understeer", cause_kind="mistake", occurrences=4,
        evidence="…")


def _mistake(corner_id: int, kind: str = "understeer") -> dict:
    return {"corner_id": corner_id, "kind": kind, "lap": 1}


#: Трасса с четырьмя медленными, четырьмя быстрыми и тремя средними.
_TYPES = {
    1: "slow", 2: "slow", 3: "slow", 4: "slow",
    5: "fast", 6: "fast", 7: "fast", 8: "fast",
    9: "medium", 10: "medium", 11: "medium",
}


# ── Потеря по типам ──────────────────────────────────────────────────────────

def test_losses_are_grouped_and_ranked_by_type():
    rows = [_d(1, 300), _d(2, 200), _d(5, 100), _d(9, 50)]

    result = by_corner_type(rows, _TYPES)

    assert [t.corner_type for t in result] == ["slow", "fast", "medium"]
    assert result[0].cost_ms == 500
    assert result[0].corners == 2
    assert abs(sum(t.share for t in result) - 1.0) < 1e-6


def test_a_corner_missing_from_the_map_is_skipped():
    result = by_corner_type([_d(99, 900), _d(1, 100)], _TYPES)

    assert [t.corner_type for t in result] == ["slow"]


def test_no_losses_is_an_empty_list():
    assert by_corner_type([], _TYPES) == []
    assert by_corner_type([_d(1, 0)], _TYPES) == []


def test_the_label_is_ready_for_the_screen():
    result = by_corner_type([_d(1, 300)], _TYPES)

    assert result[0].to_dict()["label"] == "медленные повороты"


# ── Подпись баланса ──────────────────────────────────────────────────────────

def test_understeer_across_slow_corners_points_at_mechanical_balance():
    """Прижимной силы на медленных почти нет — там машину держит механика."""
    mistakes = [_mistake(1), _mistake(2), _mistake(3)]

    signature = balance_signature(mistakes, _TYPES)

    assert signature is not None
    assert signature.kind == "understeer"
    assert signature.domain == "mechanical"
    assert signature.corners_affected == 3
    assert signature.corners_total == 4
    # Родительный после счётного оборота: «в 3 из 4 медленных ПОВОРОТОВ».
    assert "в 3 из 4 медленных поворотов" in signature.evidence
    assert "механический" in signature.advice


def test_the_same_problem_in_fast_corners_points_at_aero():
    """Одно и то же поведение в разных скоростных диапазонах имеет РАЗНЫЕ
    причины, и это физика, а не догадка."""
    mistakes = [_mistake(5), _mistake(6), _mistake(7)]

    signature = balance_signature(mistakes, _TYPES)

    assert signature.domain == "aero"
    assert "аэродинамический" in signature.advice


def test_oversteer_is_read_the_same_way():
    mistakes = [_mistake(i, "oversteer") for i in (1, 2, 3, 4)]

    signature = balance_signature(mistakes, _TYPES)

    assert signature.kind == "oversteer"
    assert signature.domain == "mechanical"


def test_medium_corners_never_produce_a_verdict():
    """Там работают оба механизма сразу, и разделить их нельзя. Молчание
    честнее любого из двух ответов."""
    mistakes = [_mistake(9), _mistake(10), _mistake(11)]

    assert balance_signature(mistakes, _TYPES) is None


def test_lockups_and_wheelspin_are_not_a_balance_problem():
    """Они про педали, а не про баланс: сдвигать сетап по ним нельзя."""
    for kind in ("lockup", "wheelspin", "offtrack"):
        mistakes = [_mistake(i, kind) for i in (1, 2, 3, 4)]

        assert balance_signature(mistakes, _TYPES) is None


def test_one_bad_corner_is_not_a_signature_however_many_times_it_happens():
    """Пять сносов в одной шпильке — это одна шпилька. Считаются ПОВОРОТЫ."""
    mistakes = [_mistake(1) for _ in range(20)]

    assert balance_signature(mistakes, _TYPES) is None


def test_a_track_with_too_few_corners_of_a_type_gives_no_verdict():
    types = {1: "slow", 2: "slow", 3: "medium"}
    mistakes = [_mistake(1), _mistake(2)]

    assert MIN_CORNERS_FOR_PATTERN > 2
    assert balance_signature(mistakes, types) is None


def test_the_stronger_pattern_wins_when_both_ends_suffer():
    mistakes = [_mistake(1), _mistake(2), _mistake(3), _mistake(4),
                _mistake(5), _mistake(6), _mistake(7)]

    signature = balance_signature(mistakes, _TYPES)

    assert signature.domain == "mechanical"     # 4 из 4 против 3 из 4
    assert signature.corners_affected == 4


def test_no_map_no_verdict():
    assert balance_signature([_mistake(1)], {}) is None
    assert balance_signature([], _TYPES) is None


def test_broken_rows_do_not_crash_the_verdict():
    mistakes = [{"kind": "understeer"}, {"corner_id": 1}, {},
                _mistake(1), _mistake(2), _mistake(3)]

    signature = balance_signature(mistakes, _TYPES)

    assert signature is not None
    assert signature.corners_affected == 3


def test_signature_dict_is_json_ready():
    data = balance_signature([_mistake(1), _mistake(2), _mistake(3)],
                             _TYPES).to_dict()

    assert data["domain"] == "mechanical"
    assert all(not isinstance(v, (list, dict, set)) for v in data.values())


def test_the_two_constructions_use_two_different_cases():
    """Заголовок строки и счётный оборот требуют РАЗНЫХ падежей, и один словарь
    на оба давал «в 3 из 4 медленных поворотах». Тесты на подстроку «3 из 4»
    это пропускали — нашлось чтением вывода."""
    label = by_corner_type([_d(1, 300)], _TYPES)[0].to_dict()["label"]
    evidence = balance_signature(
        [_mistake(1), _mistake(2), _mistake(3)], _TYPES).evidence

    assert label == "медленные повороты"
    assert evidence.endswith("медленных поворотов")
