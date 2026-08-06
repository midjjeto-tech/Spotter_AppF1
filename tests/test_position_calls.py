"""PositionCallTracker — единый settle-механизм (свой пит-стоп / сторонняя
причина), подавление рядом с OVTK игрока.
См. docs/superpowers/specs/2026-07-13-engineer-phase-a-cheap-calls-design.md.
"""
from core.strategy_ai import position_calls
from core.strategy_ai.position_calls import (
    OVTK_SUPPRESS_WINDOW_S, SETTLE_S, SETTLE_MAX_WAIT_S, PositionCallTracker,
)


def test_first_tick_never_announces():
    t = PositionCallTracker()
    assert t.check(position=10, now=100.0) is None


def test_position_change_settles_then_announces():
    t = PositionCallTracker()
    t.check(position=10, now=100.0)
    assert t.check(position=9, now=101.0) is None            # armed, ждёт settle
    phrase = t.check(position=9, now=101.0 + SETTLE_S + 0.1)  # позиция не менялась -> settled
    assert phrase == position_calls.CODE_CURRENT


def test_position_keeps_changing_restarts_settle():
    t = PositionCallTracker()
    t.check(position=10, now=100.0)
    t.check(position=9, now=101.0)                             # armed на P9
    t.check(position=8, now=101.0 + SETTLE_S - 0.1)            # меняется до settle -> перезапуск на P8
    phrase = t.check(position=8, now=101.0 + SETTLE_S - 0.1 + SETTLE_S + 0.1)
    assert phrase == position_calls.CODE_CURRENT


def test_max_wait_forces_announcement_during_continuous_change():
    """SETTLE_MAX_WAIT_S форсирует объявление, даже если позиция продолжает
    меняться на КАЖДОМ тике (settled сам по себе никогда бы не сработал).
    Найдено ревью: прежняя версия этого теста держала позицию неизменной на
    финальном вызове, поэтому проходила через settled, а не через
    проверяемый timed_out — этот вариант меняет позицию до самого конца,
    так что settled=False на решающем вызове, фраза может прийти только
    через timed_out. Шаг 0.5с (< SETTLE_S=1.5с) не даёт settled сработать
    раньше; 15 шагов по 0.5с = 7.5с < SETTLE_MAX_WAIT_S=8.0с, 16-й шаг
    впервые пересекает порог ровно на границе (now - armed_at == 8.0)."""
    t = PositionCallTracker()
    t.check(position=20, now=100.0)
    armed_at = 101.0
    t.check(position=19, now=armed_at)          # armed_at фиксируется здесь
    now, pos = armed_at, 19
    for _ in range(15):
        now += 0.5
        pos -= 1
        phrase = t.check(position=pos, now=now)
        assert phrase is None
    now += 0.5
    pos -= 1
    phrase = t.check(position=pos, now=now)
    assert now - armed_at >= SETTLE_MAX_WAIT_S
    # Позиция в текст не вписывается: она волатильна и подставляется
    # резолвером перед озвучкой — за время settle она успевает уехать.
    assert phrase == position_calls.CODE_CURRENT


def test_ovtk_suppresses_position_call():
    t = PositionCallTracker()
    t.check(position=10, now=100.0)
    t.note_ovtk_involving_player(now=100.5)
    assert t.check(position=9, now=101.0) is None
    assert t.check(position=9, now=101.0 + SETTLE_S + 0.1) is None  # не армируется вовсе


def test_ovtk_suppression_expires_after_window():
    t = PositionCallTracker()
    t.check(position=10, now=100.0)
    t.note_ovtk_involving_player(now=100.5)
    later = 100.5 + OVTK_SUPPRESS_WINDOW_S + 0.1
    t.check(position=10, now=later)                 # обновляем baseline после окна
    phrase_wait = t.check(position=9, now=later + 0.1)
    assert phrase_wait is None                        # armed, ждёт settle
    phrase = t.check(position=9, now=later + 0.1 + SETTLE_S + 0.1)
    assert phrase == position_calls.CODE_CURRENT


def test_own_pit_exit_uses_distinct_phrase():
    t = PositionCallTracker()
    t.check(position=12, now=100.0)
    t.note_own_pit_exit(position=9, now=101.0)
    assert t.check(position=9, now=101.0 + SETTLE_S - 0.1) is None
    phrase = t.check(position=9, now=101.0 + SETTLE_S + 0.1)
    assert phrase == position_calls.CODE_AFTER_PIT


def test_reset_clears_state():
    t = PositionCallTracker()
    t.check(position=10, now=100.0)
    t.note_own_pit_exit(position=9, now=101.0)
    t.reset()
    assert t.check(position=5, now=200.0) is None   # снова "первый тик"
