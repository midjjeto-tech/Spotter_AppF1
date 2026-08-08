"""Советы по гаражу (core/coach_ai/setup_advice.py).

Три связки, и ни одной больше. Тесты ниже стоят в том числе на том, чего
модуль делать НЕ должен: советовать по крыльям и подвеске, срабатывать на
единичном случае и выдавать совет без наблюдения.
"""
from core.coach_ai.setup_advice import MIN_OCCURRENCES, build_hints


def _mistakes(kind, count, wheel=None, phase="braking"):
    return [{"kind": kind, "wheel": wheel, "phase": phase, "corner_id": 3}
            for _ in range(count)]


_SETUP = {"brake_bias": 54, "diff_on_throttle": 75, "front_wing": 8,
          "rear_wing": 11}


def test_no_hints_without_setup_data():
    assert build_hints(_mistakes("lockup", 20, wheel="fl"), None) == []


def test_no_hints_on_a_clean_session():
    assert build_hints([], _SETUP) == []


def test_single_lockup_is_not_enough():
    hints = build_hints(_mistakes("lockup", 1, wheel="fl"), _SETUP)
    assert hints == []


def test_repeated_front_lockups_move_brake_bias_rearward():
    hints = build_hints(_mistakes("lockup", MIN_OCCURRENCES, wheel="fl"), _SETUP)
    assert len(hints) == 1
    assert hints[0].parameter == "brake_bias"
    assert hints[0].direction == "down"
    assert "назад" in hints[0].advice


def test_repeated_rear_lockups_move_brake_bias_forward():
    hints = build_hints(_mistakes("lockup", MIN_OCCURRENCES, wheel="rl"), _SETUP)
    assert len(hints) == 1
    assert hints[0].parameter == "brake_bias"
    assert hints[0].direction == "up"
    assert "вперёд" in hints[0].advice


def test_front_and_rear_lockups_together_give_no_brake_hint():
    """Блокирует и передние, и задние — это не баланс, а перетормаживание.
    Сдвиг в любую сторону сделает хуже одной из осей."""
    mistakes = (_mistakes("lockup", MIN_OCCURRENCES, wheel="fl")
                + _mistakes("lockup", MIN_OCCURRENCES, wheel="rr"))
    assert build_hints(mistakes, _SETUP) == []


def test_repeated_wheelspin_softens_the_differential():
    hints = build_hints(
        _mistakes("wheelspin", MIN_OCCURRENCES, wheel="rl", phase="exit"), _SETUP)
    assert len(hints) == 1
    assert hints[0].parameter == "diff_on_throttle"
    assert hints[0].direction == "down"


def test_every_hint_carries_its_evidence():
    hints = build_hints(_mistakes("lockup", MIN_OCCURRENCES, wheel="fl"), _SETUP)
    assert hints[0].evidence
    assert str(MIN_OCCURRENCES) in hints[0].evidence
    assert "54" in hints[0].evidence


def test_understeer_never_produces_a_wing_hint():
    """Крылья и подвеска сознательно вне советов: причинной модели F1 25 у нас
    нет, а догадку пилот не отличит от обоснованного вывода."""
    hints = build_hints(_mistakes("understeer", 50, phase="entry"), _SETUP)
    assert hints == []


def test_offtrack_produces_no_hint():
    assert build_hints(_mistakes("offtrack", 50, phase="exit"), _SETUP) == []


def test_brake_bias_at_the_limit_is_not_pushed_further():
    """Совет двигать то, что уже на краю диапазона, — мусор."""
    hints = build_hints(_mistakes("lockup", MIN_OCCURRENCES, wheel="fl"),
                        {**_SETUP, "brake_bias": 50})
    assert hints == []


def test_two_independent_problems_give_two_hints():
    mistakes = (_mistakes("lockup", MIN_OCCURRENCES, wheel="fl")
                + _mistakes("wheelspin", MIN_OCCURRENCES, wheel="rl", phase="exit"))
    hints = build_hints(mistakes, _SETUP)
    assert {h.parameter for h in hints} == {"brake_bias", "diff_on_throttle"}
