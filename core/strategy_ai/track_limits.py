"""
core/strategy_ai/track_limits.py
==================================
Живое предупреждение "осторожно, трек-лимиты" по росту счётчика
m_cornerCuttingWarnings (LapData) — edge-triggered, без эскалации (в отличие
от box_call.py). Симметрично подавляется на SUPPRESSION_WINDOW_S вокруг
трек-лимитного PENA — тот же инцидент не объявляется дважды (живое
предупреждение + штраф), независимо от того, какой из двух пакетов (LapData
или Event) движок обработает первым в этот тик.
См. docs/superpowers/specs/2026-07-11-track-limits-engineer-toggle-design.md.

Найдено финальным сквозным ревью (не первичной реализацией): исходная версия
подавляла только направление "PENA → потом живой тик" через одностороннюю
`_last_penalty_t`. Обратный порядок (живой тик обработан раньше PENA того же
инцидента) не подавлялся вовсе — оба объявления звучали подряд. Фикс:
единая `_last_announcement_t`, которую обновляет КАЖДАЯ сторона при реальном
объявлении, и каждая сторона проверяет её перед тем, как говорить.
"""
from __future__ import annotations

SUPPRESSION_WINDOW_S = 5.0

# Семантический код банка (core/radio/phrases.py::track_limits.warning).
# Формулировка живёт там: у неё четыре варианта, а трекер решает только «пора
# предупредить», не «какими словами».
CODE_WARNING = "track_limits.warning"


class TrackLimitsTracker:
    """Отслеживает рост m_cornerCuttingWarnings игрока за сессию."""

    def __init__(self) -> None:
        self._last_count: int | None = None
        self._last_announcement_t: float = 0.0

    def check_warning(self, count: int, now: float) -> str | None:
        """Один тик LapData. count — текущее значение
        m_cornerCuttingWarnings. Возвращает готовую фразу при росте
        относительно предыдущего тика, иначе None (в том числе если
        трек-лимитный PENA того же инцидента уже был объявлен только что)."""
        prev, self._last_count = self._last_count, count
        if prev is None or count <= prev:
            return None
        if now - self._last_announcement_t < SUPPRESSION_WINDOW_S:
            return None
        self._last_announcement_t = now
        return CODE_WARNING

    def note_penalty(self, now: float) -> bool:
        """Вызывается при трек-лимитном PENA игрока — записывает инцидент
        БЕЗУСЛОВНО (даже если возвращает False), чтобы окно подавления
        будущих живых предупреждений про тот же инцидент работало всегда,
        независимо от того, объявлялась ли эта конкретная компаньон-реплика.
        Возвращает False, если живое предупреждение по тому же инциденту
        уже прозвучало только что (в пределах SUPPRESSION_WINDOW_S) — тогда
        вызывающий не должен ставить компаньон-реплику в очередь ещё раз."""
        should_announce = now - self._last_announcement_t >= SUPPRESSION_WINDOW_S
        self._last_announcement_t = now
        return should_announce

    def reset(self) -> None:
        self._last_count = None
        self._last_announcement_t = 0.0
