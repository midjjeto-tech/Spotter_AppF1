"""
core/strategy_ai/position_calls.py
===================================
Позиционные calls («Теперь ты P{n}») по СТОРОННИМ причинам смены позиции
игрока (сход/пит-стоп соперника и т.п.) — не дублирует уже существующую
OVTK-реплику про собственный обгон/быть обогнанным. Единый settle-механизм
на оба случая (свой пит-стоп / сторонняя причина) — не мгновенное
срабатывание, коалесцирует быструю волну изменений в одну финальную фразу.
См. docs/superpowers/specs/2026-07-13-engineer-phase-a-cheap-calls-design.md.
"""
from __future__ import annotations

OVTK_SUPPRESS_WINDOW_S = 3.0
SETTLE_S = 1.5
SETTLE_MAX_WAIT_S = 8.0

# Семантические коды банка (core/radio/phrases.py). Позиция в обеих спеках
# ВОЛАТИЛЬНАЯ: между settle-таймером, очередью событий и синтезом она успевает
# измениться, и вписанное здесь число к моменту озвучки было бы неверным.
CODE_CURRENT = "position.current"
CODE_AFTER_PIT = "position.after_pit"


class PositionCallTracker:
    """Отслеживает позиционные перемещения игрока и выдаёт объявления после
    стабилизации позиции (settle) либо при достижении таймаута.
    Подавляет объявления при OVTK события и использует разные фразы для
    собственного пит-стопа vs. сторонних причин изменения позиции."""

    def __init__(self) -> None:
        self._last_pos: int | None = None
        self._recent_ovtk_t = 0.0
        self._pending = False
        self._pending_pos: int | None = None
        self._pending_since = 0.0
        self._pending_armed_at = 0.0
        self._pending_own_pit = False

    def note_ovtk_involving_player(self, now: float) -> None:
        """Записывает момент времени OVTK события (обгон/быть обогнанным).
        В течение OVTK_SUPPRESS_WINDOW_S позиционные объявления подавляются,
        чтобы не дублировать уже имеющуюся OVTK-реплику."""
        self._recent_ovtk_t = now

    def note_own_pit_exit(self, position: int | None, now: float) -> None:
        """Записывает собственный выход из пит-бокса с новой позицией.
        Запускает settle-механизм с пометкой own_pit=True, что приведёт
        к использованию фразы "После пит-стопа ты теперь P{n}" вместо
        стандартной "Теперь ты P{n}"."""
        self._arm(position, now, own_pit=True)

    def _arm(self, position: int | None, now: float, own_pit: bool) -> None:
        """Внутренний метод: запускает settle-механизм для pending объявления.
        Запоминает текущую позицию и момент времени, когда объявление будет
        готово к озвучке если позиция не изменится за SETTLE_S секунд."""
        self._pending = True
        self._pending_pos = position
        self._pending_since = now
        self._pending_armed_at = now
        self._pending_own_pit = own_pit

    def check(self, position: int | None, now: float) -> str | None:
        """Один тик обработки. Возвращает готовую фразу для озвучки либо None.

        Логика:
        1. Если уже есть pending объявление, проверяем settle-условия:
           - Если позиция изменилась, перезапускаем таймер
           - Если позиция не менялась >= SETTLE_S сек, выдаём объявление
           - Или если прошло >= SETTLE_MAX_WAIT_S сек с момента arming,
             выдаём объявление в любом случае (даже если позиция ещё меняется)
        2. Если нет pending, и позиция изменилась от _last_pos:
           - Если недавно было OVTK событие (< OVTK_SUPPRESS_WINDOW_S сек),
             молчим и просто обновляем _last_pos
           - Иначе запускаем settle-механизм через _arm()
        3. Обновляем _last_pos текущей позицией и молчим."""
        if position is None:
            return None

        if self._pending:
            # Уже есть pending объявление — проверяем условия settle
            if position != self._pending_pos:
                # Позиция изменилась, перезапускаем таймер settle
                self._pending_pos = position
                self._pending_since = now

            # Условия для выдачи объявления
            settled = now - self._pending_since >= SETTLE_S
            timed_out = now - self._pending_armed_at >= SETTLE_MAX_WAIT_S

            if settled or timed_out:
                # Выдаём объявление
                own_pit, final_pos = self._pending_own_pit, self._pending_pos
                self._pending = False
                self._last_pos = final_pos

                # Код, а не строка: сама позиция ВОЛАТИЛЬНАЯ и подставляется
                # перед озвучкой (за время settle+очереди она может уехать).
                return CODE_AFTER_PIT if own_pit else CODE_CURRENT

            return None

        # Нет pending объявления, проверяем новое изменение позиции
        if self._last_pos is not None and position != self._last_pos:
            # Позиция изменилась — нужно выявить причину
            if now - self._recent_ovtk_t < OVTK_SUPPRESS_WINDOW_S:
                # Недавно было OVTK событие, подавляем объявление
                self._last_pos = position
                return None

            # Обычное изменение позиции, запускаем settle-механизм
            self._arm(position, now, own_pit=False)
            return None

        # Первый тик или позиция не изменилась
        self._last_pos = position
        return None

    def reset(self) -> None:
        """Сбрасывает состояние трекера. Используется при перемотке
        (flashback) или переходе на новую сессию."""
        self._last_pos = None
        self._recent_ovtk_t = 0.0
        self._pending = False
        self._pending_pos = None
        self._pending_own_pit = False
