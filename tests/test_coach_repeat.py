"""Общее правило повтора (core/coach_ai/repeat.py).

Правилом пользуются обе фазы коуча — срывы сцепления и отклонения от эталона.
Две копии разошлись бы и дали коучу два разных характера внутри одной функции.
"""
from core.coach_ai.repeat import RepeatGate


def test_single_observation_does_not_fire():
    g = RepeatGate()
    assert g.observe("a", lap=1) is False


def test_three_of_five_laps_fire():
    g = RepeatGate()
    g.observe("a", lap=1)
    g.observe("a", lap=2)
    assert g.observe("a", lap=3) is True


def test_same_lap_counts_once():
    g = RepeatGate()
    g.observe("a", lap=1)
    g.observe("a", lap=1)
    assert g.observe("a", lap=1) is False


def test_spread_beyond_window_does_not_fire():
    g = RepeatGate()
    g.observe("a", lap=1)
    g.observe("a", lap=4)
    assert g.observe("a", lap=9) is False


def test_signatures_are_independent():
    g = RepeatGate()
    g.observe("a", lap=1)
    g.observe("b", lap=2)
    assert g.observe("a", lap=3) is False


def test_tuple_signatures_work():
    """Фаза 2 ключует по паре (метрика, поворот)."""
    g = RepeatGate()
    for lap in (1, 2):
        g.observe(("brake", 3), lap=lap)
    assert g.observe(("brake", 3), lap=3) is True


def test_cooldown_blocks_the_next_lap():
    g = RepeatGate()
    for lap in (1, 2, 3):
        g.observe("a", lap=lap)
    assert g.observe("a", lap=4) is False


def test_fires_again_after_cooldown():
    g = RepeatGate()
    for lap in (1, 2, 3, 4, 5, 6, 7):
        g.observe("a", lap=lap)
    assert g.observe("a", lap=8) is True


def test_reset_clears_state():
    g = RepeatGate()
    g.observe("a", lap=1)
    g.observe("a", lap=2)
    g.reset()
    assert g.observe("a", lap=3) is False
