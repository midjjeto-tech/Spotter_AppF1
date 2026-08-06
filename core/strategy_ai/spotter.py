"""
core/strategy_ai/spotter.py
=============================
Настоящий споттер: определяет, есть ли машина слева/справа/с двух сторон или
рядом чисто, — из готовых (lateral_abs_m, side) кандидатов, уже прошедших дешёвый
продольный фильтр по lap_distance в core/engine.py::_spotter_tick. Не парсит
пакеты и не занимается геометрией — pure edge-triggered состояние, тот же
паттерн, что DRSAdvisoryTracker.

Возвращает СЕМАНТИЧЕСКИЙ КОД, а не готовую строку. Раньше отдавалась строка, и
`core/engine.py` восстанавливал по ней код события, сравнивая фразу со списками
`_LEFT_ENTER`/`_BOTH`/`_CLEAR`. Связка была хрупкой в обе стороны: правка текста
в этом файле молча меняла event_code в движке, а совпадение строк между списками
сделало бы предупреждение о машине слева событием «чисто». Формулировки теперь
живут в `core/radio/phrases.py`, здесь — только логика.

См. docs/superpowers/specs/2026-07-18-real-spotter-motion-design.md.
"""
from __future__ import annotations

LONGITUDINAL_WINDOW_M = 6.0     # длина машины F1 + запас — НЕ откалибровано
LATERAL_ENTER_M = 2.5           # НЕ откалибровано, нужна живая проверка
LATERAL_EXIT_M = 4.0            # НЕ откалибровано, гистерезис как ENTER/EXIT_GAP_MS у DRS
MIN_REPEAT_S = 3.0              # НЕ откалибровано, анти-дребезг на границе порога

# Семантические коды банка фраз (core/radio/phrases.py).
CODE_LEFT = "spotter.left"
CODE_RIGHT = "spotter.right"
CODE_BOTH = "spotter.both"
CODE_CLEAR = "spotter.clear"


class SpotterTracker:
    """Анти-дребезг (MIN_REPEAT_S) — НЕЗАВИСИМО по каждой стороне (см.
    docs/superpowers/specs/2026-07-18-real-spotter-motion-design.md, раздел
    3 «Ревизия после code-quality-ревью» — общий таймер на комбинированное
    состояние глушил новую опасность с другой стороны). Гасит только
    ВОЗВРАТ кода, не внутреннее состояние — self._left/self._right всегда
    остаются правдивым снимком текущей геометрии. _last_left_change_t/
    _last_right_change_t обновляются ТОЛЬКО когда переход по ЭТОЙ стороне
    реально учтён в объявлении."""

    def __init__(self) -> None:
        self._left = False
        self._right = False
        self._last_left_change_t = 0.0
        self._last_right_change_t = 0.0

    def update(self, candidates: list[tuple[float, str]], now: float) -> str | None:
        """candidates: [(lateral_abs_m, side), ...] — только те, что уже
        прошли продольный фильтр (LONGITUDINAL_WINDOW_M) в engine.py.
        side: "left" | "right". Возвращает семантический код банка фраз, если
        хотя бы одна сторона прошла свой анти-дребезг, либо None."""
        left_dists = [d for d, s in candidates if s == "left"]
        right_dists = [d for d, s in candidates if s == "right"]
        prev_left, prev_right = self._left, self._right

        if left_dists and min(left_dists) <= LATERAL_ENTER_M:
            self._left = True
        elif not left_dists or min(left_dists) > LATERAL_EXIT_M:
            self._left = False

        if right_dists and min(right_dists) <= LATERAL_ENTER_M:
            self._right = True
        elif not right_dists or min(right_dists) > LATERAL_EXIT_M:
            self._right = False

        left_changed = self._left != prev_left
        right_changed = self._right != prev_right

        left_announceable = left_changed and (now - self._last_left_change_t >= MIN_REPEAT_S)
        right_announceable = right_changed and (now - self._last_right_change_t >= MIN_REPEAT_S)

        if left_announceable:
            self._last_left_change_t = now
        if right_announceable:
            self._last_right_change_t = now

        if not (left_announceable or right_announceable):
            return None

        if self._left and self._right:
            return CODE_BOTH
        if self._left:
            return CODE_LEFT
        if self._right:
            return CODE_RIGHT
        return CODE_CLEAR

    def reset(self) -> None:
        """Сброс состояния (SSTA/CHQF/flashback — как у остальных трекеров)."""
        self._left = False
        self._right = False
        self._last_left_change_t = 0.0
        self._last_right_change_t = 0.0
