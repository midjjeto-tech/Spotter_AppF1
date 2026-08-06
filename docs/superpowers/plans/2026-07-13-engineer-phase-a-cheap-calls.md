# Фаза A «дешёвых» реплик инженера — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** DRS-подсказки (вход/выход из секунды + разрешение DRS), позиционные
calls, смена лидера, приближение к окну пит-стопа — четыре периодические
реплики инженера поверх уже трекаемых данных (плюс одно новое поле
`drs_allowed`, чей офсет уже статически подтверждён).

**Architecture:** Четыре новых чистых трекера в `core/strategy_ai/` (стиль
`box_call.py`/`track_limits.py` — без I/O, edge-triggered состояния) +
проводка в `core/engine.py` (готовая фраза через `event["phrase"]`, в обход
LLM/templates.py, тот же короткий путь, что у всех engineer-трекеров).
Гейтинг — уже существующий `engineer_chatter_enabled`, новый тумблер не
нужен.

**Tech Stack:** Python 3.12, pytest.

**Спека:** `docs/superpowers/specs/2026-07-13-engineer-phase-a-cheap-calls-design.md`.

**Проект НЕ под git** — шаги "Commit" опущены, как в предыдущих планах этого
проекта.

---

### Task 1: `DRSAdvisoryTracker` — чистый трекер DRS-подсказок

**Files:**
- Create: `core/strategy_ai/drs_advisory.py`
- Test: `tests/test_drs_advisory.py`

- [ ] **Step 1: Написать падающие тесты**

```python
# tests/test_drs_advisory.py
"""DRSAdvisoryTracker — единый update(gap_front_ms, drs_allowed, now),
детерминированный независимо от порядка UDP-пакетов (LapData/CarStatusData).
См. docs/superpowers/specs/2026-07-13-engineer-phase-a-cheap-calls-design.md.
"""
from core.strategy_ai.drs_advisory import (
    ENTER_GAP_MS, EXIT_GAP_MS, MIN_REPEAT_S, DRSAdvisoryTracker,
)


def test_enters_range_below_1000ms():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=1500, drs_allowed=False, now=100.0)   # baseline: не в зоне
    phrase = t.update(gap_front_ms=900, drs_allowed=False, now=101.0)
    assert phrase is not None


def test_stays_in_hysteresis_band_no_change():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=900, drs_allowed=False, now=100.0)     # вошёл
    phrase = t.update(gap_front_ms=1100, drs_allowed=False, now=101.0)  # в полосе 1000-1200
    assert phrase is None


def test_exits_range_above_1200ms():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=900, drs_allowed=False, now=100.0)
    phrase = t.update(gap_front_ms=1300, drs_allowed=False, now=101.0)
    assert phrase is not None


def test_gap_none_forces_out_of_range():
    """Машина впереди пропала (пит/сход) -> _in_range сбрасывается
    принудительно, иначе новая близкая машина не даст 'вход'."""
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=900, drs_allowed=False, now=100.0)          # вошёл
    t.update(gap_front_ms=None, drs_allowed=False, now=100.5)         # машина пропала
    # Anti-repeat 5с ещё не истёк с предыдущего входа -> следующий вход подавлен,
    # проверяем внутреннее состояние по следующему тесту с достаточным разрывом.
    phrase = t.update(gap_front_ms=800, drs_allowed=False, now=110.0)  # новая близкая машина
    assert phrase is not None   # без фикса None молчал бы (уже "в зоне")


def test_drs_allowed_edge_trigger_on():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=1500, drs_allowed=False, now=100.0)
    phrase = t.update(gap_front_ms=1500, drs_allowed=True, now=101.0)
    assert phrase is not None


def test_drs_allowed_edge_trigger_off():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=1500, drs_allowed=True, now=100.0)
    phrase = t.update(gap_front_ms=1500, drs_allowed=False, now=101.0)
    assert phrase is not None


def test_combined_phrase_when_entering_range_already_allowed():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=1500, drs_allowed=True, now=100.0)   # DRS уже разрешена
    phrase = t.update(gap_front_ms=900, drs_allowed=True, now=101.0)  # входит в зону
    from core.strategy_ai.drs_advisory import _ENTERED_AND_ALLOWED
    assert phrase in _ENTERED_AND_ALLOWED


def test_combined_phrase_when_allowed_turns_on_already_in_range():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=900, drs_allowed=False, now=100.0)   # уже в зоне
    phrase = t.update(gap_front_ms=900, drs_allowed=True, now=101.0)  # DRS включается
    from core.strategy_ai.drs_advisory import _ENTERED_AND_ALLOWED
    assert phrase in _ENTERED_AND_ALLOWED


def test_anti_repeat_suppresses_second_enter_within_window():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=1500, drs_allowed=False, now=100.0)
    t.update(gap_front_ms=900, drs_allowed=False, now=101.0)    # вошёл, фраза 1
    t.update(gap_front_ms=1300, drs_allowed=False, now=102.0)   # вышел (за пределами MIN_REPEAT для входа, это выход)
    phrase = t.update(gap_front_ms=900, drs_allowed=False, now=103.0)  # вошёл снова, но < 5с с первого входа
    assert phrase is None


def test_anti_repeat_allows_enter_after_window():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=1500, drs_allowed=False, now=100.0)
    t.update(gap_front_ms=900, drs_allowed=False, now=101.0)
    t.update(gap_front_ms=1300, drs_allowed=False, now=102.0)
    phrase = t.update(gap_front_ms=900, drs_allowed=False,
                       now=101.0 + MIN_REPEAT_S + 0.1)
    assert phrase is not None


def test_reset_clears_state():
    t = DRSAdvisoryTracker()
    t.update(gap_front_ms=900, drs_allowed=True, now=100.0)
    t.reset()
    phrase = t.update(gap_front_ms=1500, drs_allowed=False, now=100.5)
    assert phrase is None   # после сброса это не "выход", а исходное состояние
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `py -3.12 -u -m pytest tests/test_drs_advisory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.strategy_ai.drs_advisory'`

- [ ] **Step 3: Реализация**

```python
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

import random

ENTER_GAP_MS = 1000
EXIT_GAP_MS = 1200
MIN_REPEAT_S = 5.0

_ENTERED_RANGE = [
    "До машины впереди меньше секунды. Готовься использовать DRS.",
    "Ты в зоне DRS.",
    "Есть шанс атаковать, держись в секунде.",
    "Интервал меньше секунды, DRS должен помочь.",
    "Держи этот темп, DRS будет доступна.",
]
_EXITED_RANGE = [
    "Интервал вырос, DRS больше не будет доступна.",
    "Потерял секунду до соперника.",
    "Вышел из зоны DRS.",
    "Соперник начинает уезжать, сокращай отставание.",
    "Нужно вернуть интервал меньше секунды.",
]
_DRS_ALLOWED = [
    "DRS разрешена.",
    "Можно открывать DRS.",
    "DRS активирована.",
    "Используй DRS на ближайшей зоне.",
    "Не забудь про DRS.",
]
_DRS_DISABLED = [
    "DRS сейчас недоступна.",
    "DRS отключена дирекцией гонки.",
    "Гонка проходит без DRS.",
    "Использовать DRS сейчас нельзя.",
]
_ENTERED_AND_ALLOWED = [
    "До машины впереди меньше секунды. DRS разрешена — атакуй.",
    "Ты в зоне DRS, и она разрешена. Дави!",
    "Меньше секунды и открытая DRS — самое время для обгона.",
]


class DRSAdvisoryTracker:
    def __init__(self) -> None:
        self._in_range = False
        self._drs_allowed = False
        self._last_range_change_t = 0.0

    def update(self, gap_front_ms: int | None, drs_allowed: bool | None,
               now: float) -> str | None:
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
            return random.choice(_ENTERED_AND_ALLOWED)
        if entered:
            return random.choice(_ENTERED_RANGE)
        if allowed_on:
            return random.choice(_DRS_ALLOWED)
        if exited:
            return random.choice(_EXITED_RANGE)
        if allowed_off:
            return random.choice(_DRS_DISABLED)
        return None

    def reset(self) -> None:
        self._in_range = False
        self._drs_allowed = False
        self._last_range_change_t = 0.0
```

- [ ] **Step 4: Запустить тесты снова**

Run: `py -3.12 -u -m pytest tests/test_drs_advisory.py -v`
Expected: PASS, 11 passed

---

### Task 2: `PositionCallTracker` — чистый трекер позиционных calls

**Files:**
- Create: `core/strategy_ai/position_calls.py`
- Test: `tests/test_position_calls.py`

- [ ] **Step 1: Написать падающие тесты**

```python
# tests/test_position_calls.py
"""PositionCallTracker — единый settle-механизм (свой пит-стоп / сторонняя
причина), подавление рядом с OVTK игрока.
См. docs/superpowers/specs/2026-07-13-engineer-phase-a-cheap-calls-design.md.
"""
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
    assert phrase == "Теперь ты P9."


def test_position_keeps_changing_restarts_settle():
    t = PositionCallTracker()
    t.check(position=10, now=100.0)
    t.check(position=9, now=101.0)                             # armed на P9
    t.check(position=8, now=101.0 + SETTLE_S - 0.1)            # меняется до settle -> перезапуск на P8
    phrase = t.check(position=8, now=101.0 + SETTLE_S - 0.1 + SETTLE_S + 0.1)
    assert phrase == "Теперь ты P8."


def test_max_wait_forces_announcement_during_continuous_change():
    t = PositionCallTracker()
    t.check(position=12, now=100.0)
    now = 100.0
    for pos in (11, 10, 9, 8):
        now += 1.0
        t.check(position=pos, now=now)   # каждый раз меняется, settle не успевает
    phrase = t.check(position=8, now=100.0 + SETTLE_MAX_WAIT_S + 0.1)
    assert phrase == "Теперь ты P8."


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
    assert phrase == "Теперь ты P9."


def test_own_pit_exit_uses_distinct_phrase():
    t = PositionCallTracker()
    t.check(position=12, now=100.0)
    t.note_own_pit_exit(position=9, now=101.0)
    assert t.check(position=9, now=101.0 + SETTLE_S - 0.1) is None
    phrase = t.check(position=9, now=101.0 + SETTLE_S + 0.1)
    assert phrase == "После пит-стопа ты теперь P9."


def test_reset_clears_state():
    t = PositionCallTracker()
    t.check(position=10, now=100.0)
    t.note_own_pit_exit(position=9, now=101.0)
    t.reset()
    assert t.check(position=5, now=200.0) is None   # снова "первый тик"
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `py -3.12 -u -m pytest tests/test_position_calls.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.strategy_ai.position_calls'`

- [ ] **Step 3: Реализация**

```python
"""
core/strategy_ai/position_calls.py
====================================
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


class PositionCallTracker:
    def __init__(self) -> None:
        self._last_pos: int | None = None
        self._recent_ovtk_t = 0.0
        self._pending = False
        self._pending_pos: int | None = None
        self._pending_since = 0.0
        self._pending_armed_at = 0.0
        self._pending_own_pit = False

    def note_ovtk_involving_player(self, now: float) -> None:
        self._recent_ovtk_t = now

    def note_own_pit_exit(self, position: int | None, now: float) -> None:
        self._arm(position, now, own_pit=True)

    def _arm(self, position: int | None, now: float, own_pit: bool) -> None:
        self._pending = True
        self._pending_pos = position
        self._pending_since = now
        self._pending_armed_at = now
        self._pending_own_pit = own_pit

    def check(self, position: int | None, now: float) -> str | None:
        if position is None:
            return None
        if self._pending:
            if position != self._pending_pos:
                self._pending_pos = position
                self._pending_since = now
            settled = now - self._pending_since >= SETTLE_S
            timed_out = now - self._pending_armed_at >= SETTLE_MAX_WAIT_S
            if settled or timed_out:
                own_pit, final_pos = self._pending_own_pit, self._pending_pos
                self._pending = False
                self._last_pos = final_pos
                if own_pit:
                    return f"После пит-стопа ты теперь P{final_pos}."
                return f"Теперь ты P{final_pos}."
            return None
        if self._last_pos is not None and position != self._last_pos:
            if now - self._recent_ovtk_t < OVTK_SUPPRESS_WINDOW_S:
                self._last_pos = position
                return None
            self._arm(position, now, own_pit=False)
            return None
        self._last_pos = position
        return None

    def reset(self) -> None:
        self._last_pos = None
        self._recent_ovtk_t = 0.0
        self._pending = False
        self._pending_pos = None
        self._pending_own_pit = False
```

- [ ] **Step 4: Запустить тесты снова**

Run: `py -3.12 -u -m pytest tests/test_position_calls.py -v`
Expected: PASS, 7 passed

---

### Task 3: `LeaderChangeTracker` — чистый трекер смены лидера

**Files:**
- Create: `core/strategy_ai/leader_change.py`
- Test: `tests/test_leader_change.py`

- [ ] **Step 1: Написать падающие тесты**

```python
# tests/test_leader_change.py
"""LeaderChangeTracker — debounce 2с, первое наблюдение = базовая линия
(не объявляется), откат до истечения debounce не оставляет устаревший
_pending. См. docs/superpowers/specs/2026-07-13-engineer-phase-a-cheap-calls-design.md.
"""
from core.strategy_ai.leader_change import DEBOUNCE_S, LeaderChangeTracker


def test_first_observation_sets_baseline_no_announcement():
    t = LeaderChangeTracker()
    assert t.check(leader_idx=3, now=100.0) is None


def test_same_leader_no_announcement():
    t = LeaderChangeTracker()
    t.check(leader_idx=3, now=100.0)
    assert t.check(leader_idx=3, now=101.0) is None


def test_new_leader_announced_after_debounce():
    t = LeaderChangeTracker()
    t.check(leader_idx=3, now=100.0)             # базовая линия
    assert t.check(leader_idx=7, now=101.0) is None   # pending, ждёт debounce
    result = t.check(leader_idx=7, now=101.0 + DEBOUNCE_S + 0.1)
    assert result == 7


def test_new_leader_not_announced_before_debounce_elapses():
    t = LeaderChangeTracker()
    t.check(leader_idx=3, now=100.0)
    t.check(leader_idx=7, now=101.0)
    result = t.check(leader_idx=7, now=101.0 + DEBOUNCE_S - 0.1)
    assert result is None


def test_revert_before_debounce_does_not_announce_and_clears_pending():
    """A->B->A откат до истечения debounce -> не объявляет B, и следующая
    настоящая смена на B позже ждёт полные DEBOUNCE_S заново (не мгновенно
    по старому таймеру) — найдено самопроверкой спеки."""
    t = LeaderChangeTracker()
    t.check(leader_idx="A", now=100.0)              # базовая линия
    t.check(leader_idx="B", now=101.0)               # pending B
    result_revert = t.check(leader_idx="A", now=101.5)  # откат до истечения debounce
    assert result_revert is None

    # Спустя долгое время (>> DEBOUNCE_S с первого pending на B) — настоящая смена на B.
    result_too_soon = t.check(leader_idx="B", now=101.6)   # только что переармировали
    assert result_too_soon is None
    result = t.check(leader_idx="B", now=101.6 + DEBOUNCE_S + 0.1)
    assert result == "B"


def test_reset_clears_state():
    t = LeaderChangeTracker()
    t.check(leader_idx=3, now=100.0)
    t.check(leader_idx=7, now=101.0)
    t.reset()
    assert t.check(leader_idx=7, now=200.0) is None   # снова базовая линия
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `py -3.12 -u -m pytest tests/test_leader_change.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.strategy_ai.leader_change'`

- [ ] **Step 3: Реализация**

```python
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
from typing import Any

DEBOUNCE_S = 2.0


class LeaderChangeTracker:
    def __init__(self) -> None:
        self._current: Any = None
        self._pending: Any = None
        self._pending_since = 0.0

    def check(self, leader_idx: Any, now: float) -> Any:
        if leader_idx is None:
            return None
        if self._current is None:
            self._current = leader_idx
            return None
        if leader_idx == self._current:
            self._pending = None
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
        self._current = None
        self._pending = None
```

- [ ] **Step 4: Запустить тесты снова**

Run: `py -3.12 -u -m pytest tests/test_leader_change.py -v`
Expected: PASS, 6 passed

---

### Task 4: `PitWindowApproachTracker` — армируется один раз за стинт

**Files:**
- Modify: `core/strategy_ai/pit_window.py` (добавить класс рядом с существующими функциями)
- Test: `tests/test_strategy_ai.py` (расширить существующий файл — там уже тестируется `detect_pit_window`)

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/test_strategy_ai.py`:

```python
# --------------------------------------------------------------------------- #
# PitWindowApproachTracker — армируется один раз за стинт
# --------------------------------------------------------------------------- #

def test_pit_window_approach_fires_when_close_and_not_open():
    from core.strategy_ai.pit_window import PitWindowApproachTracker
    t = PitWindowApproachTracker()
    phrase = t.check(open_=False, laps_left=8)
    assert phrase == "Приближаемся к окну пит-стопа."


def test_pit_window_approach_silent_when_already_open():
    from core.strategy_ai.pit_window import PitWindowApproachTracker
    t = PitWindowApproachTracker()
    assert t.check(open_=True, laps_left=2) is None


def test_pit_window_approach_silent_when_too_far():
    from core.strategy_ai.pit_window import PitWindowApproachTracker
    t = PitWindowApproachTracker()
    assert t.check(open_=False, laps_left=9) is None


def test_pit_window_approach_fires_once_per_stint():
    from core.strategy_ai.pit_window import PitWindowApproachTracker
    t = PitWindowApproachTracker()
    t.check(open_=False, laps_left=8)
    assert t.check(open_=False, laps_left=7) is None
    assert t.check(open_=False, laps_left=9) is None   # колебания laps_left тоже не повторяют


def test_pit_window_approach_fires_again_after_reset():
    from core.strategy_ai.pit_window import PitWindowApproachTracker
    t = PitWindowApproachTracker()
    t.check(open_=False, laps_left=8)
    t.reset()
    phrase = t.check(open_=False, laps_left=8)
    assert phrase == "Приближаемся к окну пит-стопа."


def test_pit_window_approach_none_laps_left_silent():
    from core.strategy_ai.pit_window import PitWindowApproachTracker
    t = PitWindowApproachTracker()
    assert t.check(open_=False, laps_left=None) is None
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `py -3.12 -u -m pytest tests/test_strategy_ai.py -k pit_window_approach -v`
Expected: FAIL — `ImportError: cannot import name 'PitWindowApproachTracker'`

- [ ] **Step 3: Реализация**

В `core/strategy_ai/pit_window.py`, добавить в конец файла:

```python
APPROACH_LAPS_THRESHOLD = 8


class PitWindowApproachTracker:
    """Разовый heads-up "приближаемся к окну пит-стопа" — армируется ОДИН
    раз за стинт (не за тик), не повторяется при колебаниях laps_left из-за
    смены темпа/стратегии внутри одного стинта. Сброс — только на реальном
    начале нового стинта (собственный пит-стоп) или сессионных границах.

    TODO (не в объёме Фазы A): полный пересчёт стратегии посреди стинта
    (например, дождь -> смена на интермедиэйты) сейчас НЕ сбрасывает
    _announced_this_stint — редкий кейс, осознанно отложено."""

    def __init__(self) -> None:
        self._announced_this_stint = False

    def check(self, open_: bool, laps_left: int | None) -> str | None:
        if self._announced_this_stint:
            return None
        if not open_ and laps_left is not None and laps_left <= APPROACH_LAPS_THRESHOLD:
            self._announced_this_stint = True
            return "Приближаемся к окну пит-стопа."
        return None

    def reset(self) -> None:
        self._announced_this_stint = False
```

- [ ] **Step 4: Запустить тесты снова**

Run: `py -3.12 -u -m pytest tests/test_strategy_ai.py -v`
Expected: PASS, все тесты файла зелёные (было 34, стало 40)

---

### Task 5: `core/packets.py` — поле `drs_allowed`

**Files:**
- Modify: `core/packets.py:522-536` (`_car_status_fields`)
- Test: `tests/test_packets_gaps_tyre.py`

Офсет 22 (`m_drsAllowed`, uint8) УЖЕ входит в golden-master
`_CAR_STATUS_LAYOUT` (сверен на ERS 2026-07-10) — новой сверки не требуется,
только добавить чтение.

- [ ] **Step 1: Написать падающий тест**

Добавить в `tests/test_packets_gaps_tyre.py`:

```python
def test_car_status_drs_allowed_true():
    buf = _buf(HEADER_SIZE + CAR_STATUS_SIZE)
    base = HEADER_SIZE
    buf[base + 22] = 1
    out = packets.parse_player_status(buf, 0)
    assert out["drs_allowed"] is True


def test_car_status_drs_allowed_false():
    buf = _buf(HEADER_SIZE + CAR_STATUS_SIZE)
    base = HEADER_SIZE
    buf[base + 22] = 0
    out = packets.parse_player_status(buf, 0)
    assert out["drs_allowed"] is False


def test_car_status_drs_allowed_none_when_packet_too_short():
    buf = _buf(HEADER_SIZE + 22)   # base+23 > len(data) -> поле недоступно
    out = packets.parse_player_status(buf, 0)
    assert "drs_allowed" not in out
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `py -3.12 -u -m pytest tests/test_packets_gaps_tyre.py -k drs_allowed -v`
Expected: FAIL — `KeyError: 'drs_allowed'`

- [ ] **Step 3: Реализация**

В `core/packets.py`, `_car_status_fields()` — вставить между чтением `fuel`
(offset 5) и блоком `tyre_compound`/`tyre_age` (offset 26-27):

```python
def _car_status_fields(data: bytes, base: int) -> dict:
    fuel = struct.unpack_from("<f", data, base + 5)[0]
    out = {"fuel": round(fuel, 1)}
    if base + 23 <= len(data):
        # m_drsAllowed @22 (uint8) — офсет уже в golden-master _CAR_STATUS_LAYOUT
        # (сверен на ERS 2026-07-10), новой сверки не требуется.
        out["drs_allowed"] = bool(data[base + 22])
    if base + 28 <= len(data):
        visual = data[base + 26]
        out["tyre_compound"] = TYRE_VISUAL.get(visual, "?")
        out["tyre_age"] = data[base + 27]
    if base + 42 <= len(data):
        ers_energy = struct.unpack_from("<f", data, base + 37)[0]
        out["ers_percent"] = round(ers_energy / ERS_MAX_JOULES * 100, 1)
        out["ers_deploy_mode"] = data[base + 41]
    return out
```

- [ ] **Step 4: Запустить тесты снова**

Run: `py -3.12 -u -m pytest tests/test_packets_gaps_tyre.py -v`
Expected: PASS, все тесты файла зелёные

---

### Task 6: `commentator/planner.py` — таблица важности

**Files:**
- Modify: `commentator/planner.py:45-59` (`_BASE_IMPORTANCE`)

Не TDD-задача (константы, не поведение) — просто изменить таблицу и
прогнать существующие тесты планировщика на регрессию.

- [ ] **Step 1: Зафиксировать baseline**

Run: `py -3.12 -u -m pytest tests/test_planner.py -v`
Expected: все тесты проходят — записать точное число для сравнения.

- [ ] **Step 2: Изменить `_BASE_IMPORTANCE`**

```python
_BASE_IMPORTANCE: dict[str, int] = {
    "COLL": 90, "RTMT": 90,
    "PENA": 88, "RCWN": 88, "CHQF": 88,
    "OVTK": 60,
    "FTLP": 55,
    "DAMAGE_WING": 65, "DAMAGE_FLOOR": 65, "DAMAGE_GEARBOX": 65, "DAMAGE_ENGINE": 65,
    "F1_BENCH": 55, "CAREER_PB": 55,
    "F1_SECTOR_BENCH": 45, "CAREER_SECTOR_PB": 45,
    "SSTA": 70, "STLG": 70,
    "SEND": 40,
    "TMPT": 30, "SPTP": 30, "DRSE": 30, "DRSD": 30,
    "FLBK": 25,
    "AMBIENT": 20,
    "PIT_EXIT": 65,
    "DRS_PROXIMITY_ENTER": 30, "DRS_PROXIMITY_EXIT": 30,
    "DRS_ALLOWED_ON": 30, "DRS_ALLOWED_OFF": 30,
    "DRS_PROXIMITY_ENTER_AND_ALLOWED": 30,
    "POSITION_CALL": 55, "POSITION_CALL_OWN_PIT": 55,
    "LEADER_CHANGE": 55,
    "PIT_WINDOW_APPROACH": 55,
}
```
(Единственное изменение существующего значения: `PIT_EXIT` 60→65 — найдено
ревью: подтверждённый факт «ты выехал на Pn» важнее прогноза «окно скоро
откроется».)

- [ ] **Step 3: Запустить тесты планировщика снова**

Run: `py -3.12 -u -m pytest tests/test_planner.py -v`
Expected: PASS, тот же набор тестов, что в baseline (0 regressions). Если
какой-то тест жёстко ожидал `PIT_EXIT == 60` — обновить ожидание на `65` в
этом тесте (единственное намеренное изменение поведения в этой задаче).

---

### Task 7: `core/engine.py` — проводка DRS

**Files:**
- Modify: `core/engine.py` (импорты, `__init__`, `_update_telemetry` — ветки `PACKET_CAR_STATUS` и `PACKET_LAP_DATA`, сброс x3)
- Test: `tests/test_engine_drs_advisory.py` (новый)

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_engine_drs_advisory.py
"""Проводка DRSAdvisoryTracker в F1Engine: обе ветки _update_telemetry
(LapData и CarStatus) вызывают update() с последними известными значениями.
См. docs/superpowers/specs/2026-07-13-engineer-phase-a-cheap-calls-design.md.
"""
import struct

import pytest

import core.engine as eng_mod
from core.engine import F1Engine, SPEAKER_ENGINEER
from core.packets import HEADER_SIZE, CAR_STATUS_SIZE, LAP_DATA_SIZE, PACKET_CAR_STATUS, PACKET_LAP_DATA


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _drain(engine):
    drained = []
    while not engine.event_queue.empty():
        drained.append(engine.event_queue.get_nowait())
    return drained


def _lap_buf_with_gap(gap_ms: int) -> bytes:
    buf = bytearray(HEADER_SIZE + LAP_DATA_SIZE)
    base = HEADER_SIZE
    buf[base + 33] = 5   # current_lap
    ms_part = gap_ms % 60000
    minutes = gap_ms // 60000
    struct.pack_into("<H", buf, base + 14, ms_part)
    buf[base + 16] = minutes
    return bytes(buf)


def _status_buf_with_drs(allowed: int) -> bytes:
    buf = bytearray(HEADER_SIZE + CAR_STATUS_SIZE)
    base = HEADER_SIZE
    buf[base + 22] = allowed
    return bytes(buf)


def test_lap_data_tick_calls_drs_advisory_update(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    engine._drs_advisory.reset()
    _drain(engine)

    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf_with_gap(1500))   # baseline: далеко
    _drain(engine)
    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf_with_gap(800))    # вошёл в зону

    drained = _drain(engine)
    found = [e for e in drained if e["event_code"] in
             ("DRS_PROXIMITY_ENTER", "DRS_PROXIMITY_ENTER_AND_ALLOWED")]
    assert len(found) == 1
    assert found[0]["speaker"] == SPEAKER_ENGINEER
    assert found[0]["bypass_speak_threshold"] is True
    engine._drs_advisory.reset()


def test_car_status_tick_calls_drs_advisory_update(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    engine._drs_advisory.reset()
    _drain(engine)

    engine._update_telemetry({"player_car_index": 0}, PACKET_CAR_STATUS,
                             _status_buf_with_drs(0))
    _drain(engine)
    engine._update_telemetry({"player_car_index": 0}, PACKET_CAR_STATUS,
                             _status_buf_with_drs(1))

    drained = _drain(engine)
    codes = [e["event_code"] for e in drained]
    assert "DRS_ALLOWED_ON" in codes
    engine._drs_advisory.reset()


def test_chatter_disabled_suppresses_drs_events(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = False
    engine._drs_advisory.reset()
    _drain(engine)

    engine._update_telemetry({"player_car_index": 0}, PACKET_CAR_STATUS,
                             _status_buf_with_drs(0))
    _drain(engine)
    engine._update_telemetry({"player_car_index": 0}, PACKET_CAR_STATUS,
                             _status_buf_with_drs(1))

    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"] == "DRS_ALLOWED_ON"]
    engine.settings["engineer_chatter_enabled"] = True
    engine._drs_advisory.reset()


def test_flashback_resets_drs_advisory(engine, monkeypatch):
    calls = []
    monkeypatch.setattr(engine._drs_advisory, "reset", lambda: calls.append(True))
    engine._handle_flashback()
    assert calls == [True]
```

**Важно про event_code:** в спеке фразы делятся на 5 логических типов
(вошёл / вышел / allowed-on / allowed-off / составная вошёл+allowed), но
`DRSAdvisoryTracker.update()` возвращает только готовую ФРАЗУ, не тип. Для
`event_code` в `_enqueue_event` движок должен сам определить тип по тому,
какой ветке кода принадлежит вызов — простое решение: завести helper
`_drs_event_code(phrase)`, сверяющий `phrase in _ENTERED_RANGE` и т.д. (импорт
пулов из `drs_advisory` модуля), либо (проще и надёжнее) добавить
служебный метод `DRSAdvisoryTracker.last_kind` не нужен — вместо этого
Step 3 ниже показывает точный код: движок вызывает `update()` один раз и
классифицирует результат по членству в пуле.

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `py -3.12 -u -m pytest tests/test_engine_drs_advisory.py -v`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute '_drs_advisory'`

- [ ] **Step 3: Проводка в `core/engine.py`**

Импорт (рядом с `from core.strategy_ai.track_limits import TrackLimitsTracker`):

```python
from core.strategy_ai.drs_advisory import (
    DRSAdvisoryTracker, _ENTERED_RANGE, _EXITED_RANGE,
    _DRS_ALLOWED, _DRS_DISABLED, _ENTERED_AND_ALLOWED,
)
```

Инициализация в `__init__` (рядом с `self._track_limits = TrackLimitsTracker()`):

```python
        self._drs_advisory = DRSAdvisoryTracker()
        self._player_drs_allowed: bool | None = None
```

Новый приватный метод класса `F1Engine` (рядом с другими `_maybe_*`
методами, например после `_maybe_announce_pit_exit`):

```python
    def _drs_advisory_tick(self) -> None:
        """Вызывается из ОБЕИХ веток _update_telemetry (LapData и CarStatus)
        — DRSAdvisoryTracker детерминирован независимо от того, какой пакет
        обработан первым. См. spec 2026-07-13-engineer-phase-a-cheap-calls-design.md."""
        phrase = self._drs_advisory.update(
            self._player_gap_front, self._player_drs_allowed, time.time())
        if not phrase or not self._get_setting("engineer_chatter_enabled", True):
            return
        if phrase in _ENTERED_AND_ALLOWED:
            code = "DRS_PROXIMITY_ENTER_AND_ALLOWED"
        elif phrase in _ENTERED_RANGE:
            code = "DRS_PROXIMITY_ENTER"
        elif phrase in _DRS_ALLOWED:
            code = "DRS_ALLOWED_ON"
        elif phrase in _EXITED_RANGE:
            code = "DRS_PROXIMITY_EXIT"
        else:
            code = "DRS_ALLOWED_OFF"
        self._enqueue_event({
            "event_code": code, "priority": "normal",
            "phrase": phrase, "speaker": SPEAKER_ENGINEER,
            "driver": "", "color": "#38BDF8",
            "bypass_speak_threshold": True,
        })
```

**Проверено чтением реального кода `_update_telemetry`** (не найдено вслепую):
и `PACKET_LAP_DATA`, и `PACKET_CAR_STATUS` — это ветки одной и той же
elif-цепочки внутри `_update_telemetry`; результат КАЖДОЙ ветки складывается
в локальный `telem: dict`, а затем ОБЩИЙ блок `with self.state_lock:` (идёт
ПОСЛЕ elif-цепочки, выполняется на КАЖДЫЙ вызов `_update_telemetry`
независимо от типа пакета) переносит поля из `telem` в `self._player_*`.
Именно этот общий блок уже содержит ряд `if telem.get("X") is not None:
self._player_X = telem["X"]` (строки 1041-1051 — `fuel`, `tyre_compound`,
`tyre_age`, `ers_percent`, `ers_deploy_mode`). Это даёт естественную точку
для ОДНОГО вызова `_drs_advisory_tick()`, который автоматически покрывает
и LapData-, и CarStatus-тики — два отдельных места вызова, как думалось в
спеке изначально, не нужны.

В `core/packets.py::_car_status_fields` поле уже добавлено в Task 5 —
`parse_player_status()` кладёт `drs_allowed` в свой результат, который
`_update_telemetry`'s ветка `elif packet_id == PACKET_CAR_STATUS and
self._player_car_index < 22:` (строка 1001) уже мержит в `telem` через
`telem.update(parse_player_status(...))` (строка 1002) — это уже работает
БЕЗ изменений в этой ветке.

В `_update_telemetry`, в общем блоке `with self.state_lock:` — сразу после
существующей строки `self._player_ers_deploy_mode = telem["ers_deploy_mode"]`
(последняя строка блока перед `def _maybe_snapshot`):

```python
            if telem.get("ers_deploy_mode") is not None:
                self._player_ers_deploy_mode = telem["ers_deploy_mode"]
            if telem.get("drs_allowed") is not None:
                self._player_drs_allowed = telem["drs_allowed"]
            self._drs_advisory_tick()
```

Сброс на SSTA/CHQF/flashback (`_handle_event_packet`, три существующие
точки — SSTA-блок, CHQF/SEND-блок, `_handle_flashback()`):

```python
self._drs_advisory.reset()
```

- [ ] **Step 4: Запустить тест снова**

Run: `py -3.12 -u -m pytest tests/test_engine_drs_advisory.py -v`
Expected: PASS, 4 passed

Затем полный прогон: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: 0 failed

---

### Task 8: `core/engine.py` — проводка Position Calls

**Files:**
- Modify: `core/engine.py` (импорты, `__init__`, OVTK-обогащение, `_maybe_announce_pit_exit`, `_update_telemetry` LapData-ветка, сброс x3)
- Test: `tests/test_engine_position_calls.py` (новый)

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_engine_position_calls.py
"""Проводка PositionCallTracker: подавление рядом с OVTK игрока, свой
пит-стоп через _maybe_announce_pit_exit, сторонние причины.
См. docs/superpowers/specs/2026-07-13-engineer-phase-a-cheap-calls-design.md.
"""
import struct
import time

import pytest

import core.engine as eng_mod
from core.engine import F1Engine, SPEAKER_ENGINEER
from core.packets import HEADER_SIZE, LAP_DATA_SIZE, PACKET_LAP_DATA
from core.strategy_ai.position_calls import SETTLE_S


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _drain(engine):
    drained = []
    while not engine.event_queue.empty():
        drained.append(engine.event_queue.get_nowait())
    return drained


def _lap_buf(*, position: int, current_lap=5, pit_status=0):
    buf = bytearray(HEADER_SIZE + LAP_DATA_SIZE)
    base = HEADER_SIZE
    buf[base + 32] = position
    buf[base + 33] = current_lap
    buf[base + 34] = pit_status
    return bytes(buf)


def test_third_party_position_change_settles_and_announces(engine, monkeypatch):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "race"
    engine._position_calls.reset()
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    _drain(engine)

    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(position=10))
    _drain(engine)
    monkeypatch.setattr(time, "time", lambda: 1001.0)
    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(position=9))
    _drain(engine)   # armed, settle ещё не прошёл

    monkeypatch.setattr(time, "time", lambda: 1001.0 + SETTLE_S + 0.5)
    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(position=9))
    drained = _drain(engine)
    found = [e for e in drained if e["event_code"] == "POSITION_CALL"]
    assert len(found) == 1
    assert found[0]["phrase"] == "Теперь ты P9."
    assert found[0]["speaker"] == SPEAKER_ENGINEER
    engine._position_calls.reset()
    engine._session_type = "unknown"


def test_ovtk_suppresses_position_call(engine, monkeypatch):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "race"
    engine._position_calls.reset()
    monkeypatch.setattr(time, "time", lambda: 2000.0)
    _drain(engine)

    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(position=10))
    _drain(engine)

    engine._position_calls.note_ovtk_involving_player(2000.5)
    monkeypatch.setattr(time, "time", lambda: 2001.0)
    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(position=9))
    monkeypatch.setattr(time, "time", lambda: 2001.0 + SETTLE_S + 0.5)
    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(position=9))
    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"] == "POSITION_CALL"]
    engine._position_calls.reset()
    engine._session_type = "unknown"


def test_own_pit_exit_notifies_position_calls(engine, monkeypatch):
    engine._player_car_index = 0
    engine._session_type = "race"
    engine._position_calls.reset()
    calls = []
    monkeypatch.setattr(engine._position_calls, "note_own_pit_exit",
                         lambda pos, now: calls.append((pos, now)))

    engine._maybe_announce_pit_exit(prev_status=1, new_status=0)

    assert len(calls) == 1
    engine._session_type = "unknown"


def test_flashback_resets_position_calls(engine, monkeypatch):
    calls = []
    monkeypatch.setattr(engine._position_calls, "reset", lambda: calls.append(True))
    engine._handle_flashback()
    assert calls == [True]
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `py -3.12 -u -m pytest tests/test_engine_position_calls.py -v`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute '_position_calls'`

- [ ] **Step 3: Проводка в `core/engine.py`**

Импорт:

```python
from core.strategy_ai.position_calls import PositionCallTracker
```

Инициализация в `__init__`:

```python
        self._position_calls = PositionCallTracker()
```

**Проверено чтением реального кода.** В `_update_telemetry`, ветка
`PACKET_LAP_DATA`, внутри `if self._player_car_index < 22:` — существующая
строка `self._maybe_announce_pit_exit(_prev_pit_status,
self._player_pit_status)` (сразу после неё уже идёт код Задачи 4/6 из
предыдущей фичи — `cc = pl.get("corner_cutting_warnings")` и трек-лимиты;
новый код добавляется ПОСЛЕ этого блока трек-лимитов, перед
`if pl.get("pit_status"): self._current_lap_pit = True`):

```python
                self._maybe_announce_pit_exit(_prev_pit_status, self._player_pit_status)
                cc = pl.get("corner_cutting_warnings")
                if cc is not None:
                    tl_phrase = self._track_limits.check_warning(cc, time.time())
                    if tl_phrase and self._get_setting("engineer_chatter_enabled", True):
                        self._enqueue_event({
                            "event_code": "ENGINEER_TRACK_LIMITS_WARNING",
                            "priority": "normal",
                            "phrase": tl_phrase, "speaker": SPEAKER_ENGINEER,
                            "driver": "", "color": "#38BDF8",
                            "bypass_speak_threshold": True,
                        })
                if self._session_type == "race":
                    pc_phrase = self._position_calls.check(self._player_pos, time.time())
                    if pc_phrase and self._get_setting("engineer_chatter_enabled", True):
                        self._enqueue_event({
                            "event_code": "POSITION_CALL_OWN_PIT" if "пит-стопа" in pc_phrase
                                          else "POSITION_CALL",
                            "priority": "normal",
                            "phrase": pc_phrase, "speaker": SPEAKER_ENGINEER,
                            "driver": "", "color": "#38BDF8",
                            "bypass_speak_threshold": True,
                        })
                if pl.get("pit_status"):
                    self._current_lap_pit = True
```
(`check()` вызывается КАЖДЫЙ тик независимо от того, изменилась ли позиция
в конкретном пакете — сам трекер решает, армировать/держать/озвучить.)

В `_handle_event_packet`, блок обогащения OVTK (существующий, полный текст
для точной вставки — проверено чтением реального кода):

```python
        enriched = self.race_state.enrich(event)
        # COLL тоже двухмашинное событие (vehicle1_idx/vehicle2_idx), но стиль
        # соперника сознательно ограничен OVTK (design spec 2026-07-05-race-memory)
        # — не забыто, не техническое ограничение get_style().
        if enriched.get("event_code") == "OVTK":
            overtaking_idx = enriched.get("overtaking_idx")
            being_overtaken_idx = enriched.get("being_overtaken_idx")
            now = time.time()
            if self._player_car_index in (overtaking_idx, being_overtaken_idx):
                self._position_calls.note_ovtk_involving_player(now)
            enriched["driver_style"] = self.rival_tracker.get_style(overtaking_idx)
            enriched["target_style"] = self.rival_tracker.get_style(being_overtaken_idx)
            enriched["driver_recent_mistake"] = self.rival_tracker.get_recent_mistake(overtaking_idx, now)
            enriched["target_recent_mistake"] = self.rival_tracker.get_recent_mistake(being_overtaken_idx, now)
            enriched["driver_tyre_age"] = self.rival_tracker.get_tyre_age(overtaking_idx)
            enriched["target_tyre_age"] = self.rival_tracker.get_tyre_age(being_overtaken_idx)
```
(Единственная новая строка — `if self._player_car_index in (...): self._position_calls.note_ovtk_involving_player(now)`,
сразу после уже существующей `now = time.time()`; всё остальное в блоке —
без изменений, показано полностью для точной вставки.)

`_maybe_announce_pit_exit` — полный текст метода на данный момент (проверено
чтением реального кода), с новой строкой:

```python
    def _maybe_announce_pit_exit(self, prev_status: int | None, new_status: int | None) -> None:
        """Выезд из боксов — новое синтетическое событие (design spec
        2026-07-05-final-laps-attacks-pitstop). Едж-детект перехода "в боксах"
        (1/2) -> "не в боксах" (0): физически может сработать только один раз
        за заезд, отдельный анти-спам флаг не нужен (в отличие от
        _update_damage, где severity может держаться выше порога много тиков
        подряд). Только гонка — в практике/квалификации пит-стопы постоянны и
        не несут смысла (та же причина, по которой OVTK/FTLP уже приглушены
        вне гонки, см. score_importance)."""
        if prev_status in (1, 2) and new_status == 0 and self._session_type == "race":
            self._position_calls.note_own_pit_exit(self._player_pos, time.time())
            self._enqueue_event({
                "event_code": "PIT_EXIT", "priority": "normal",
                "driver": "", "color": "#38BDF8",
                "tyre_compound": self._player_tyre_compound,
            })
```
(Новая строка — `self._position_calls.note_own_pit_exit(...)`, добавлена
ПЕРЕД существующим `self._enqueue_event({...})`.)

Сброс на SSTA/CHQF/flashback (три существующие точки):

```python
self._position_calls.reset()
```

- [ ] **Step 4: Запустить тест снова**

Run: `py -3.12 -u -m pytest tests/test_engine_position_calls.py -v`
Expected: PASS, 4 passed

Затем полный прогон: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: 0 failed

---

### Task 9: `core/engine.py` — проводка Leader Change

**Files:**
- Modify: `core/engine.py` (импорты, `__init__`, `_update_telemetry` LapData-ветка, сброс x3)
- Test: `tests/test_engine_leader_change.py` (новый)

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_engine_leader_change.py
"""Проводка LeaderChangeTracker: смена _leader_idx доходит до трекера,
debounce 2с, только race.
См. docs/superpowers/specs/2026-07-13-engineer-phase-a-cheap-calls-design.md.
"""
import time

import pytest

import core.engine as eng_mod
from core.engine import F1Engine, SPEAKER_ENGINEER
from core.packets import HEADER_SIZE, LAP_DATA_SIZE, PACKET_LAP_DATA


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _drain(engine):
    drained = []
    while not engine.event_queue.empty():
        drained.append(engine.event_queue.get_nowait())
    return drained


def _grid_buf_with_leader(leader_vehicle_idx: int) -> bytes:
    """22-слотовый LapData-буфер: ровно один car_idx с m_carPosition==1
    (лидер), остальные — P2..P22 по порядку слота."""
    buf = bytearray(HEADER_SIZE + 22 * LAP_DATA_SIZE)
    positions = [p for p in range(2, 23)]
    pos_iter = iter(positions)
    for idx in range(22):
        base = HEADER_SIZE + idx * LAP_DATA_SIZE
        pos = 1 if idx == leader_vehicle_idx else next(pos_iter)
        buf[base + 32] = pos
        buf[base + 33] = 5   # current_lap
    return bytes(buf)


def test_lap_data_tick_calls_leader_change_tick(engine, monkeypatch):
    """Сквозной тест проводки: _update_telemetry с реальным LapData-буфером
    доходит до _leader_change_tick(), не просто вызов метода напрямую."""
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "race"
    engine._leader_change.reset()
    _drain(engine)

    monkeypatch.setattr(time, "time", lambda: 7000.0)
    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _grid_buf_with_leader(3))     # базовая линия: лидер idx=3
    _drain(engine)

    monkeypatch.setattr(time, "time", lambda: 7001.0)
    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _grid_buf_with_leader(7))     # смена лидера на idx=7
    _drain(engine)   # pending, debounce не истёк

    monkeypatch.setattr(time, "time", lambda: 7001.0 + 2.1)
    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _grid_buf_with_leader(7))     # держится >=2с
    drained = _drain(engine)
    found = [e for e in drained if e["event_code"] == "LEADER_CHANGE"]
    assert len(found) == 1
    assert found[0]["speaker"] == SPEAKER_ENGINEER
    engine._leader_change.reset()
    engine._session_type = "unknown"


def test_leader_change_announced_after_debounce(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "race"
    engine._leader_change.reset()
    _drain(engine)

    monkeypatch.setattr(time, "time", lambda: 5000.0)
    engine._leader_idx = 3
    engine._leader_change_tick()
    _drain(engine)

    monkeypatch.setattr(time, "time", lambda: 5001.0)
    engine._leader_idx = 7
    engine._leader_change_tick()
    _drain(engine)   # pending, debounce не истёк

    monkeypatch.setattr(time, "time", lambda: 5001.0 + 2.1)
    engine._leader_change_tick()
    drained = _drain(engine)
    found = [e for e in drained if e["event_code"] == "LEADER_CHANGE"]
    assert len(found) == 1
    assert found[0]["speaker"] == SPEAKER_ENGINEER
    engine._leader_change.reset()
    engine._session_type = "unknown"


def test_leader_change_gated_outside_race(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "qualifying"
    engine._leader_change.reset()
    _drain(engine)

    monkeypatch.setattr(time, "time", lambda: 6000.0)
    engine._leader_idx = 3
    engine._leader_change_tick()
    monkeypatch.setattr(time, "time", lambda: 6001.0)
    engine._leader_idx = 7
    engine._leader_change_tick()
    monkeypatch.setattr(time, "time", lambda: 6001.0 + 2.1)
    engine._leader_change_tick()

    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"] == "LEADER_CHANGE"]
    engine._leader_change.reset()
    engine._session_type = "unknown"


def test_flashback_resets_leader_change(engine, monkeypatch):
    calls = []
    monkeypatch.setattr(engine._leader_change, "reset", lambda: calls.append(True))
    engine._handle_flashback()
    assert calls == [True]
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `py -3.12 -u -m pytest tests/test_engine_leader_change.py -v`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute '_leader_change'`

- [ ] **Step 3: Проводка в `core/engine.py`**

Импорт:

```python
from core.strategy_ai.leader_change import LeaderChangeTracker
```

Инициализация в `__init__`:

```python
        self._leader_change = LeaderChangeTracker()
```

Новый метод класса `F1Engine`:

```python
    def _leader_change_tick(self) -> None:
        """Вызывается каждый LapData-тик — только race (см. spec, квали/практика
        уже покрыты FTLP)."""
        if self._session_type != "race":
            return
        new_leader = self._leader_change.check(self._leader_idx, time.time())
        if new_leader is None or not self._get_setting("engineer_chatter_enabled", True):
            return
        driver_name = self.race_state.driver(new_leader)["name"]
        self._enqueue_event({
            "event_code": "LEADER_CHANGE", "priority": "normal",
            "phrase": f"Новый лидер гонки — {driver_name}.",
            "speaker": SPEAKER_ENGINEER, "driver": "", "color": "#38BDF8",
            "bypass_speak_threshold": True,
        })
```

В `_update_telemetry`, ветка `PACKET_LAP_DATA` — сразу после
`self._leader_idx = lap_info.get("leader_idx")` (~строка 889):

```python
            self._leader_idx = lap_info.get("leader_idx")
            self._leader_change_tick()
```

Сброс на SSTA/CHQF/flashback (три существующие точки):

```python
self._leader_change.reset()
```

- [ ] **Step 4: Запустить тест снова**

Run: `py -3.12 -u -m pytest tests/test_engine_leader_change.py -v`
Expected: PASS, 4 passed

Затем полный прогон: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: 0 failed

---

### Task 10: `core/engine.py` — проводка Pit Window Approach

**Files:**
- Modify: `core/engine.py` (импорты, `__init__`, `_maybe_snapshot`, `_maybe_announce_pit_exit`, сброс x3)
- Test: `tests/test_engine_pit_window_approach.py` (новый)

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_engine_pit_window_approach.py
"""Проводка PitWindowApproachTracker: вызов detect_pit_window напрямую из
engine.py (НЕ через StrategyAnalyzer — тот вызывает его только условно,
см. spec), сброс на собственном пит-стопе.
См. docs/superpowers/specs/2026-07-13-engineer-phase-a-cheap-calls-design.md.
"""
import time

import pytest

import core.engine as eng_mod
from core.engine import F1Engine, SPEAKER_ENGINEER


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _drain(engine):
    drained = []
    while not engine.event_queue.empty():
        drained.append(engine.event_queue.get_nowait())
    return drained


def test_pit_window_approach_enqueues_in_race(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "race"
    engine._pit_window_approach.reset()
    engine._player_lap = 10
    engine._total_laps = 30
    engine._player_tyre_age = 20
    engine._player_tyre_wear = 55.0
    engine._player_tyre_compound = "medium"
    engine._last_snap_t = 0.0
    _drain(engine)

    class _StubCoach:
        def get_state(self):
            return {}
    monkeypatch.setattr(engine, "driver_coach", _StubCoach())

    engine._maybe_snapshot()

    drained = _drain(engine)
    found = [e for e in drained if e["event_code"] == "PIT_WINDOW_APPROACH"]
    assert len(found) == 1
    assert found[0]["speaker"] == SPEAKER_ENGINEER
    engine._pit_window_approach.reset()
    engine._session_type = "unknown"
    engine._player_lap = None
    engine._total_laps = None
    engine._last_snap_t = 0.0


def test_own_pit_exit_resets_pit_window_approach(engine):
    engine._session_type = "race"
    engine._pit_window_approach.check(open_=False, laps_left=5)  # армирован

    engine._maybe_announce_pit_exit(prev_status=1, new_status=0)

    phrase = engine._pit_window_approach.check(open_=False, laps_left=5)
    assert phrase == "Приближаемся к окну пит-стопа."   # снова армируется -> сброшен
    engine._pit_window_approach.reset()
    engine._session_type = "unknown"


def test_flashback_resets_pit_window_approach(engine, monkeypatch):
    calls = []
    monkeypatch.setattr(engine._pit_window_approach, "reset", lambda: calls.append(True))
    engine._handle_flashback()
    assert calls == [True]
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `py -3.12 -u -m pytest tests/test_engine_pit_window_approach.py -v`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute '_pit_window_approach'`

- [ ] **Step 3: Проводка в `core/engine.py`**

Импорт (расширить существующий `from core.strategy_ai.pit_window import ...`,
если он уже есть — иначе добавить новый):

```python
from core.strategy_ai.pit_window import detect_pit_window, PitWindowApproachTracker
```

Инициализация в `__init__`:

```python
        self._pit_window_approach = PitWindowApproachTracker()
```

В `_maybe_snapshot()`, сразу после блока, где строится `st_snapshot` и вызывается
`strategy_event = self.strategy_analyzer.update(st_snapshot)` (используем
уже собранные в `st_snapshot` значения `tyre_age`/`tyre_wear`/`tyre_compound`
и уже вычисленный `total_laps`):

```python
        _pw_total_laps = getattr(self, "_total_laps", None)
        _pw_laps_remaining = (
            _pw_total_laps - self._player_lap
            if _pw_total_laps and self._player_lap is not None
            else None
        )
        _pw_open, _pw_conf, _pw_laps_left = detect_pit_window(
            self._player_tyre_age, self._player_tyre_wear,
            _pw_laps_remaining, self._player_tyre_compound)
        if self._session_type == "race":
            pw_phrase = self._pit_window_approach.check(_pw_open, _pw_laps_left)
            if pw_phrase and self._get_setting("engineer_chatter_enabled", True):
                self._enqueue_event({
                    "event_code": "PIT_WINDOW_APPROACH", "priority": "normal",
                    "phrase": pw_phrase, "speaker": SPEAKER_ENGINEER,
                    "driver": "", "color": "#38BDF8",
                    "bypass_speak_threshold": True,
                })
```

**Примечание:** `detect_pit_window` вызывается здесь НАПРЯМУЮ, а не через
`StrategyAnalyzer` — внутри `StrategyAnalyzer.update()` он вызывается
условно (`if not event:`, только когда `cover_opponent`/`undercut` ещё не
сработали на этом тике), поэтому полагаться на его внутренний вызов
ненадёжно (см. `core/strategy_ai/strategy.py:161`). Прямой вызов даёт
гарантированный тик каждый раз.

`_maybe_announce_pit_exit` — полный текст метода ПОСЛЕ правки Task 8 (уже
содержит `note_own_pit_exit`), с новой строкой этой задачи:

```python
    def _maybe_announce_pit_exit(self, prev_status: int | None, new_status: int | None) -> None:
        """Выезд из боксов — новое синтетическое событие (design spec
        2026-07-05-final-laps-attacks-pitstop). Едж-детект перехода "в боксах"
        (1/2) -> "не в боксах" (0): физически может сработать только один раз
        за заезд, отдельный анти-спам флаг не нужен (в отличие от
        _update_damage, где severity может держаться выше порога много тиков
        подряд). Только гонка — в практике/квалификации пит-стопы постоянны и
        не несут смысла (та же причина, по которой OVTK/FTLP уже приглушены
        вне гонки, см. score_importance)."""
        if prev_status in (1, 2) and new_status == 0 and self._session_type == "race":
            self._position_calls.note_own_pit_exit(self._player_pos, time.time())
            self._pit_window_approach.reset()
            self._enqueue_event({
                "event_code": "PIT_EXIT", "priority": "normal",
                "driver": "", "color": "#38BDF8",
                "tyre_compound": self._player_tyre_compound,
            })
```
(Новая строка — `self._pit_window_approach.reset()`, добавлена сразу после
`note_own_pit_exit(...)` из Task 8.)

Сброс на SSTA/CHQF/flashback (три существующие точки):

```python
self._pit_window_approach.reset()
```

- [ ] **Step 4: Запустить тест снова**

Run: `py -3.12 -u -m pytest tests/test_engine_pit_window_approach.py -v`
Expected: PASS, 3 passed

Затем полный прогон: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: 0 failed

---

### Task 11: Финальная проверка + CONTEXT.md

**Files:**
- Modify: `CONTEXT.md`

- [ ] **Step 1: Полный прогон всех тестов**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q --junitxml=<путь>`
(если краткий вывод `-q` ненадёжен в среде — известный сторонний баг с
RuntimeWarning при завершении, см. предыдущие сессии — использовать
`--junitxml` для точного счёта)
Expected: 0 failed, 0 errors

- [ ] **Step 2: Обновить CONTEXT.md**

В раздел «На чём остановились» добавить запись в начало (самое свежее
первым) — Фаза A «дешёвых» реплик инженера: 4 новых трекера (DRS,
позиционные calls, смена лидера, приближение к окну пит-стопа), новое поле
`drs_allowed` (офсет уже был в golden-master, только чтение добавлено),
правка важности `PIT_EXIT` 60→65, ссылка на спеку/план этого документа,
результат финального прогона, и явно — **не проверено вживую** (нужна
реальная гонка).

Обновить сводную заметку про открытые пункты «замены инженера»: указать,
что Фаза A закрыта (код), следующие кандидаты — Фаза B (Race Control + SC/
флаги) или живая проверка накопившихся фаз, по решению пользователя.

Следовать конвенции файла (не разрастать сверх ~100 пунктов; если файл уже
превышает лимит из-за параллельной сессии — не делать архивацию в рамках
этой задачи, только оставить заметку, что архивация нужна отдельным
заходом, как уже отмечено в предыдущей сессии).
