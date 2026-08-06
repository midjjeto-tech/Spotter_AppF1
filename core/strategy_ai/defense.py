"""
core/strategy_ai/defense.py
=============================
"Удержал позицию" — успешная защита от устойчивой атаки. Edge-triggered на
переход battle_active True->False (core/race_ai/analyzer.py::RaceAnalyzer.
last_battle_active), подавляется, если позиция реально потеряна (игрока
только что обогнали) — тот же класс проблемы "два связанных сигнала, не
дублировать объявление", что уже решает core/strategy_ai/track_limits.py::
SUPPRESSION_WINDOW_S. Чистая функция, без I/O — тот же паттерн, что
core/strategy_ai/spotter.py/drs_advisory.py.

См. docs/superpowers/plans/2026-07-20-defense-event-damage-phrase-variety.md.
"""
from __future__ import annotations

SUPPRESSION_WINDOW_S = 5.0   # НЕ откалибровано, нужна живая проверка

# Семантический код банка фраз (core/radio/phrases.py). Формулировки живут там,
# здесь — только логика edge-detect.
CODE_HELD = "battle.held"


class DefenseTracker:
    def __init__(self) -> None:
        self._active = False

    def update(self, battle_active: bool, now: float,
               last_overtaken_t: float = 0.0) -> str | None:
        """Один тик. battle_active — текущее устойчивое состояние борьбы
        (RaceAnalyzer.last_battle_active). Возвращает семантический код ровно на
        переходе active->inactive, ЕСЛИ игрока не обогнали незадолго до
        этого (иначе позиция реально потеряна, а не защищена)."""
        was_active = self._active
        self._active = battle_active
        if was_active and not battle_active:
            if now - last_overtaken_t < SUPPRESSION_WINDOW_S:
                return None
            return CODE_HELD
        return None

    def reset(self) -> None:
        self._active = False
