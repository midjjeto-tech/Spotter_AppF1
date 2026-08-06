"""SpotterTracker — edge-triggered состояние (clear/left/right/both) из уже
готовых (lateral_abs_m, side) кандидатов. Анти-дребезг гасит только
ВОЗВРАТ кода (не состояние) — та же конвенция, что у DRSAdvisoryTracker.

Трекер отдаёт СЕМАНТИЧЕСКИЙ КОД банка фраз, а не готовую строку: формулировки
живут в core/radio/phrases.py, а движок переводит код в event_code. Раньше здесь
сравнивались строки, и правка текста молча меняла поведение движка.
См. docs/superpowers/specs/2026-07-18-real-spotter-motion-design.md.
"""
from core.strategy_ai.spotter import (
    CODE_BOTH, CODE_CLEAR, CODE_LEFT, CODE_RIGHT,
    LATERAL_ENTER_M, LATERAL_EXIT_M, MIN_REPEAT_S, SpotterTracker,
)


def test_no_candidates_stays_clear_no_phrase():
    t = SpotterTracker()
    assert t.update([], now=100.0) is None


def test_enters_left():
    t = SpotterTracker()
    phrase = t.update([(2.0, "left")], now=100.0)
    assert phrase == CODE_LEFT


def test_enters_right():
    t = SpotterTracker()
    phrase = t.update([(2.0, "right")], now=100.0)
    assert phrase == CODE_RIGHT


def test_enters_both_sides_simultaneously():
    t = SpotterTracker()
    phrase = t.update([(2.0, "left"), (2.0, "right")], now=100.0)
    assert phrase == CODE_BOTH


def test_stays_in_hysteresis_band_no_change():
    t = SpotterTracker()
    t.update([(2.0, "left")], now=100.0)                    # вошёл (<= ENTER)
    phrase = t.update([(3.0, "left")], now=101.0)            # между ENTER и EXIT
    assert phrase is None


def test_exits_to_clear_beyond_exit_threshold():
    t = SpotterTracker()
    t.update([(2.0, "left")], now=100.0)
    phrase = t.update([], now=110.0)   # далеко за MIN_REPEAT_S, чтобы не попасть под анти-дребезг
    assert phrase == CODE_CLEAR


def test_direct_transition_left_to_right_without_intermediate_clear():
    t = SpotterTracker()
    t.update([(2.0, "left")], now=100.0)
    phrase = t.update([(2.0, "right")], now=110.0)
    assert phrase == CODE_RIGHT


def test_repeat_of_same_state_returns_none():
    t = SpotterTracker()
    t.update([(2.0, "left")], now=100.0)
    phrase = t.update([(2.1, "left")], now=110.0)   # всё ещё left, hysteresis не даёт выйти
    assert phrase is None


def test_anti_repeat_suppresses_second_transition_within_window():
    t = SpotterTracker()
    t.update([(2.0, "left")], now=100.0)              # вошёл слева
    phrase = t.update([], now=100.0 + MIN_REPEAT_S - 0.5)  # быстрый выход, внутри окна
    assert phrase is None


def test_anti_repeat_allows_transition_after_window():
    t = SpotterTracker()
    t.update([(2.0, "left")], now=100.0)
    t.update([], now=100.0 + MIN_REPEAT_S - 0.5)      # подавлено, но состояние истинно clear
    phrase = t.update([(2.0, "right")], now=100.0 + MIN_REPEAT_S + 0.5)
    assert phrase == CODE_RIGHT


def test_closest_candidate_on_each_side_decides_hysteresis():
    """Несколько кандидатов на одной стороне -> учитывается ближайший."""
    t = SpotterTracker()
    phrase = t.update([(5.0, "left"), (2.0, "left")], now=100.0)  # ближайший 2.0 <= ENTER
    assert phrase == CODE_LEFT


def test_reset_clears_state():
    t = SpotterTracker()
    t.update([(2.0, "left")], now=100.0)
    t.reset()
    phrase = t.update([], now=100.5)   # сразу после reset — не "выход", а исходное состояние
    assert phrase is None


def test_cross_side_flip_within_window_still_announces_new_side():
    """Регрессия на найденный ревью баг: общий анти-дребезг на (left, right)
    не должен глушить НОВУЮ опасность с другой стороны только из-за
    недавнего перехода на ПЕРВОЙ. t=0 left входит и объявляется; t=1 (внутри
    MIN_REPEAT_S=3.0 от t=0) left выходит И right входит одновременно —
    right ДОЛЖЕН быть объявлен (его собственный анти-дребезг таймер свежий),
    несмотря на то что left только что менялся."""
    t = SpotterTracker()
    t.update([(2.0, "left")], now=100.0)                       # left входит, объявлено
    phrase = t.update([(2.0, "right")], now=100.5)             # left уходит, right входит
    assert phrase == CODE_RIGHT
