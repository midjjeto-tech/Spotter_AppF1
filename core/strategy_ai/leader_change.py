"""
core/strategy_ai/leader_change.py
===================================
Смена лидера гонки — debounce 2с (не объявлять транзитных лидеров на волне
пит-стопов/рестартов после Safety Car). Только race — в квали/практике
"смена лидера" = "сменился обладатель быстрейшего времени сессии", это уже
покрыто существующим FTLP-событием, отдельный трекер дублировал бы его.
См. docs/superpowers/specs/2026-07-13-engineer-phase-a-cheap-calls-design.md.
"""
from __future__ import annotations

DEBOUNCE_S = 2.0


class LeaderChangeTracker:
    """Отслеживает смену лидера гонки с debounce-фильтром 2с (отсеивает
    транзитных лидеров). Первое наблюдение устанавливает базовую линию
    без объявления; откат до истечения debounce очищает отложенный таймер."""

    def __init__(self) -> None:
        self._current: int | None = None
        self._pending: int | None = None
        self._pending_since = 0.0

    def check(self, leader_idx: int | None, now: float) -> int | None:
        """Проверить смену лидера на текущем тике.

        Первый вызов с ненулевым leader_idx устанавливает _current как
        базовую линию и возвращает None (не "смена", а исходное состояние).

        Если leader_idx == _current, очищает _pending (откат до истечения
        debounce, таймер не копится, при следующей реальной смене начинается
        заново от текущего now).

        Если leader_idx != _current и != _pending, переключает _pending на
        новый индекс и запускает таймер.

        Если leader_idx == _pending и прошло >= DEBOUNCE_S, переводит
        leader_idx в _current, очищает _pending и возвращает новый индекс.

        Args:
            leader_idx: Индекс (vehicle_idx) текущего лидера, или None.
            now: Текущее время в секундах.

        Returns:
            Индекс нового лидера при окончании debounce, иначе None.
        """
        if leader_idx is None:
            return None
        if self._current is None:
            self._current = leader_idx      # базовая линия, не "смена"
            return None
        if leader_idx == self._current:
            self._pending = None            # откатился до истечения debounce
            return None
        if leader_idx != self._pending:
            self._pending = leader_idx
            self._pending_since = now
            return None
        if now - self._pending_since >= DEBOUNCE_S:
            self._current = leader_idx
            self._pending = None
            return leader_idx
        return None

    def reset(self) -> None:
        """Сброс состояния (SSTA/CHQF/flashback — как у остальных трекеров)."""
        self._current = None
        self._pending = None
