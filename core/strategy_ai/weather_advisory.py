"""
core/strategy_ai/weather_advisory.py
======================================
Однократный heads-up "дождь через N минут" — детерминированный, без LLM,
armed-once (без эскалации, в отличие от box_call.py). См.
docs/superpowers/specs/2026-07-10-rain-advisory-design.md.
"""
from __future__ import annotations

RAIN_ADVISORY_HORIZON_MIN = 30

# Семантические коды банка (core/radio/phrases.py). Трекер решает ЧТО сказать,
# банк — КАК. Строку здесь больше не собираем: согласование числительных и
# подстановка горизонта живут в конвейере (горизонт волатильный, он меняется,
# пока фраза ждёт очереди).
CODE_RAIN_SOON = "weather.rain_soon"


class RainAdvisoryTracker:
    """Однократный heads-up «дождь через N минут» — armed once, без
    эскалации. Сброс, когда дождь уходит из горизонта или прогноз становится
    сухим — следующее появление снова объявляется."""

    def __init__(self) -> None:
        self._armed = False
        self._front_id = 0

    @property
    def front_id(self) -> int:
        """Номер текущего погодного фронта (1, 2, …), 0 — фронта ещё не было.

        Личность ОДНОГО погодного фронта для `situation_id`
        (core/radio/situations.py): дождь, ушедший из горизонта и вернувшийся,
        это новая ситуация, а не повтор старой. Считается здесь, потому что
        именно этот трекер знает, когда эпизод начался и когда закрылся."""
        return self._front_id

    def check(self, rain_forecast: dict | None) -> str | None:
        """rain_forecast: {"minutes", "rain_pct", "weather"} или None.

        Возвращает СЕМАНТИЧЕСКИЙ КОД банка один раз за эпизод, либо None.
        Готовую строку здесь больше не собираем: горизонт волатилен и
        подставляется перед озвучкой, а согласование числительного живёт в
        `core/radio/resolver.py::_format`."""
        if rain_forecast is None or rain_forecast["minutes"] > RAIN_ADVISORY_HORIZON_MIN:
            self._armed = False
            return None
        if self._armed:
            return None
        self._armed = True
        self._front_id += 1
        return CODE_RAIN_SOON

    def reset(self) -> None:
        self._armed = False
        # `_front_id` НЕ сбрасывается, и это безопасно: от коллизий между
        # гонками защищает не рост счётчика, а `session_id` в составе
        # `situation_id` (core/radio/situations.py). Счётчик здесь остаётся
        # локальным номером фронта внутри процесса и сам по себе идентичностью
        # не является.
        #
        # После флэшбека тот же дождь законно объявляется заново (`_armed`
        # сброшен) и получает следующий номер — это НЕ ложная новая ситуация, а
        # новое высказывание: пилот перемотал момент и предыдущего
        # предупреждения не слышал.

