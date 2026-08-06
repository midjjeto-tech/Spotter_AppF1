"""
core/strategy_ai/drs_advisory.py
==================================
DRS-подсказки: вход/выход из секундной зоны до машины впереди + разрешение
DRS дирекцией гонки. Единый update(gap_front_ms, drs_allowed, now) вместо
двух независимых методов — LapData (gap) и CarStatusData (drs_allowed)
приходят разными UDP-пакетами в непредсказуемом порядке; общая точка входа
с двумя последними известными значениями даёт детерминированный результат
независимо от того, какой пакет обработан первым в этот тик.
См. docs/superpowers/specs/2026-07-13-engineer-phase-a-cheap-calls-design.md.
"""
from __future__ import annotations

ENTER_GAP_MS = 1000
EXIT_GAP_MS = 1200
MIN_REPEAT_S = 5.0

# Семантические коды банка фраз (core/radio/phrases.py). Раньше здесь лежали
# пять массивов формулировок, а core/engine.py восстанавливал по готовой строке
# код события, сравнивая её с этими массивами. Связка была хрупкой в обе стороны:
# правка текста молча меняла event_code, а совпадение строк между массивами
# перепутало бы «вошёл в зону» и «вышел из зоны».
CODE_IN_RANGE = "drs.in_range"
CODE_OUT_OF_RANGE = "drs.out_of_range"
CODE_ENABLED = "drs.enabled"
CODE_DISABLED = "drs.disabled"
CODE_IN_RANGE_AND_ENABLED = "drs.in_range_and_enabled"


class DRSAdvisoryTracker:
    """Отслеживает гэп до машины впереди (гистерезис ENTER_GAP_MS/EXIT_GAP_MS)
    и флаг drs_allowed (edge-triggered) игрока за сессию."""

    def __init__(self) -> None:
        self._in_range = False
        self._drs_allowed = False
        self._last_range_change_t = 0.0

    def update(self, gap_front_ms: int | None, drs_allowed: bool | None,
               now: float) -> str | None:
        """Один тик (LapData ИЛИ CarStatusData — вызывающий передаёт оба
        последних известных значения независимо от того, какой пакет
        обработан). gap_front_ms=None (нет машины впереди) принудительно
        считается "не в зоне". Возвращает семантический код банка фраз при входе/выходе из
        зоны или смене drs_allowed (составной — если оба условия истинны
        одновременно), либо None, если ничего не изменилось или сработал
        anti-repeat (MIN_REPEAT_S, симметричный для входа и выхода)."""
        prev_in_range, prev_allowed = self._in_range, self._drs_allowed
        if gap_front_ms is None:
            self._in_range = False
        elif gap_front_ms <= ENTER_GAP_MS:
            self._in_range = True
        elif gap_front_ms > EXIT_GAP_MS:
            self._in_range = False
        if drs_allowed is not None:
            self._drs_allowed = bool(drs_allowed)

        entered = self._in_range and not prev_in_range
        exited = (not self._in_range) and prev_in_range
        allowed_on = self._drs_allowed and not prev_allowed
        allowed_off = (not self._drs_allowed) and prev_allowed

        if (entered or exited) and now - self._last_range_change_t < MIN_REPEAT_S:
            entered = exited = False
        if entered or exited:
            self._last_range_change_t = now

        if (entered and self._drs_allowed) or (allowed_on and self._in_range):
            return CODE_IN_RANGE_AND_ENABLED
        if entered:
            return CODE_IN_RANGE
        if allowed_on:
            return CODE_ENABLED
        if exited:
            return CODE_OUT_OF_RANGE
        if allowed_off:
            return CODE_DISABLED
        return None

    def reset(self) -> None:
        """Сброс состояния (SSTA/CHQF/flashback — как у остальных трекеров)."""
        self._in_range = False
        self._drs_allowed = False
        self._last_range_change_t = 0.0
