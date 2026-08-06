"""
core/strategy_ai/box_call.py
==============================
Императивный "боксы в этом круге" поверх уже готовой уверенности
StrategyAnalyzer — конечный автомат без I/O, полностью детерминированный.
См. docs/superpowers/specs/2026-07-09-precise-box-call-design.md.
"""
from __future__ import annotations

DECISIVE_CONFIDENCE = 0.85
MAX_TIER = 3


class BoxCallTracker:
    """Отслеживает решительный pit-сигнал по кругам и выдаёт эскалацию 1..MAX_TIER."""

    def __init__(self) -> None:
        self._armed_lap: int | None = None
        self._last_called_lap: int | None = None
        self._tier: int = 0

    def update(self, player_lap: int | None, action: str, confidence: float,
               pit_status: int | None) -> int | None:
        """Один тик анализа. Возвращает номер эскалации (1..MAX_TIER) для
        озвучки в этом тике, либо None (молчать).

        Предполагает, что вызывающий передаёт player_lap монотонно
        неубывающим (как и приходит из телеметрии). При перемотке (flashback)
        круг может откатиться назад — вызывающий (core/engine.py::
        _handle_flashback) обязан явно позвать reset() в этот момент, иначе
        откат круга здесь молча трактуется как "новый круг, эскалируем
        дальше"."""
        if pit_status:
            self.reset()
            return None
        if player_lap is None or action != "pit" or confidence < DECISIVE_CONFIDENCE:
            self.reset()
            return None

        if self._armed_lap is None:
            self._armed_lap = self._last_called_lap = player_lap
            self._tier = 1
            return self._tier

        if player_lap == self._last_called_lap:
            return None

        self._last_called_lap = player_lap
        self._tier = min(MAX_TIER, self._tier + 1)
        return self._tier

    @property
    def window_id(self) -> int | None:
        """Круг, на котором взведено текущее окно box-call, либо None.

        Личность ОКНА, а не отдельной команды: все tier'ы одной эскалации
        принадлежат одному окну и должны получить один `situation_id`
        (core/radio/situations.py). Сброс трекера закрывает окно, следующее
        взведение открывает новое."""
        return self._armed_lap

    def reset(self) -> None:
        self._armed_lap = None
        self._last_called_lap = None
        self._tier = 0
