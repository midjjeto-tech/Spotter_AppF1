# Гэп-дайджест инженера — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Периодическая (фиксированный интервал 40с), детерминированная (без
LLM), голосом инженера (`speaker=SPEAKER_ENGINEER`) сводка «отрыв
впереди/сзади + тренд» — только в гонке.

**Architecture:** Новый чистый модуль `core/strategy_ai/gap_digest.py`
(`GapDigestTracker`, по образцу `box_call.py`) строит готовую фразу из уже
существующих `self._player_gap_front`/`_player_gap_behind`. Новый поток
`_engineer_digest_loop` (по образцу `_ambient_loop`) с фиксированным
интервалом enqueue-ит событие с преднабранной `event["phrase"]` — минуя
LLM/`templates.render()` тем же коротким путём, что уже используют
`F1_BENCH`/`PIT_EXIT`.

**Tech Stack:** Python 3.12, pytest. Проект НЕ под git — без commit-шагов.

**Спека:** `docs/superpowers/specs/2026-07-10-engineer-gap-digest-design.md`
(реализована автономно, помечены решения, требующие review пользователя
постфактум).

---

### Task 1: `GapDigestTracker`

**Files:**
- Create: `core/strategy_ai/gap_digest.py`
- Create: `tests/test_gap_digest.py`

- [ ] **Step 1: Написать падающие тесты**

```python
# tests/test_gap_digest.py
"""GapDigestTracker — детерминированная радио-сводка по гэпам инженера.
См. docs/superpowers/specs/2026-07-10-engineer-gap-digest-design.md.
"""
from core.strategy_ai.gap_digest import TREND_THRESHOLD_MS, GapDigestTracker


def test_first_reading_has_no_trend_word():
    t = GapDigestTracker()
    out = t.build(gap_front_ms=1800, gap_behind_ms=None)
    assert out == "Отрыв впереди: 1.8."


def test_both_gaps_combined_in_one_phrase():
    t = GapDigestTracker()
    out = t.build(gap_front_ms=1800, gap_behind_ms=2500)
    assert out == "Отрыв впереди: 1.8. Отрыв сзади: 2.5."


def test_no_data_returns_none():
    t = GapDigestTracker()
    assert t.build(gap_front_ms=None, gap_behind_ms=None) is None


def test_zero_gap_filtered_as_no_car():
    """0 = сам лидер / нет машины (конвенция commentator/timeline.py::_fmt_gap),
    не «нулевой отрыв»."""
    t = GapDigestTracker()
    assert t.build(gap_front_ms=0, gap_behind_ms=None) is None


def test_closing_trend_after_second_reading():
    t = GapDigestTracker()
    t.build(gap_front_ms=1800, gap_behind_ms=None)
    out = t.build(gap_front_ms=1800 - TREND_THRESHOLD_MS, gap_behind_ms=None)
    assert out == "Отрыв впереди сокращается, 1.5."


def test_opening_trend_after_second_reading():
    t = GapDigestTracker()
    t.build(gap_front_ms=1800, gap_behind_ms=None)
    out = t.build(gap_front_ms=1800 + TREND_THRESHOLD_MS, gap_behind_ms=None)
    assert out == "Отрыв впереди растёт, 2.1."


def test_steady_trend_when_change_below_threshold():
    t = GapDigestTracker()
    t.build(gap_front_ms=1800, gap_behind_ms=None)
    out = t.build(gap_front_ms=1800 + TREND_THRESHOLD_MS - 1, gap_behind_ms=None)
    assert out == "Отрыв впереди стабилен, 2.1."


def test_reset_clears_trend_memory():
    t = GapDigestTracker()
    t.build(gap_front_ms=1800, gap_behind_ms=None)
    t.reset()
    out = t.build(gap_front_ms=1800 - TREND_THRESHOLD_MS, gap_behind_ms=None)
    assert out == "Отрыв впереди: 1.5."          # без тренда — как первый замер
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `py -3.12 -u -m pytest tests/test_gap_digest.py -q`
Expected: `ModuleNotFoundError: No module named 'core.strategy_ai.gap_digest'`

- [ ] **Step 3: Реализовать `GapDigestTracker`**

```python
# core/strategy_ai/gap_digest.py
"""
core/strategy_ai/gap_digest.py
================================
Периодическая радио-сводка инженера по гэпам впереди/сзади — детерминированная,
без LLM. См. docs/superpowers/specs/2026-07-10-engineer-gap-digest-design.md.
"""
from __future__ import annotations

TREND_THRESHOLD_MS = 300


class GapDigestTracker:
    """Строит готовую фразу-сводку и хранит предыдущие гэпы для тренда."""

    def __init__(self) -> None:
        self._prev_front_ms: int | None = None
        self._prev_behind_ms: int | None = None

    def build(self, gap_front_ms: int | None, gap_behind_ms: int | None) -> str | None:
        """Возвращает готовую фразу, либо None (нечего сказать)."""
        parts: list[str] = []
        if gap_front_ms is not None and gap_front_ms > 0:
            parts.append(_gap_phrase("впереди", gap_front_ms, self._prev_front_ms))
        if gap_behind_ms is not None and gap_behind_ms > 0:
            parts.append(_gap_phrase("сзади", gap_behind_ms, self._prev_behind_ms))
        self._prev_front_ms = gap_front_ms
        self._prev_behind_ms = gap_behind_ms
        return " ".join(parts) if parts else None

    def reset(self) -> None:
        self._prev_front_ms = None
        self._prev_behind_ms = None


def _gap_phrase(label: str, gap_ms: int, prev_ms: int | None) -> str:
    gap_s = gap_ms / 1000.0
    if prev_ms is None:
        return f"Отрыв {label}: {gap_s:.1f}."
    delta = gap_ms - prev_ms
    if delta <= -TREND_THRESHOLD_MS:
        return f"Отрыв {label} сокращается, {gap_s:.1f}."
    if delta >= TREND_THRESHOLD_MS:
        return f"Отрыв {label} растёт, {gap_s:.1f}."
    return f"Отрыв {label} стабилен, {gap_s:.1f}."
```

- [ ] **Step 4: Прогнать тесты, зелёные**

Run: `py -3.12 -u -m pytest tests/test_gap_digest.py -q`
Expected: `8 passed`

---

### Task 2: Проводка в `core/engine.py` + `config.py`

**Files:**
- Modify: `config.py`
- Modify: `core/engine.py`
- Modify: `tests/test_engine_planner.py`

- [ ] **Step 1: `config.py` — новая константа**

После блока `AMBIENT_*`/`TIMELINE_EVENTS` (строка ~55, перед
`# --- Comment Planner ---`) добавить:

```python
# Инженер: периодическая сводка по гэпам (Фаза 2, gap-digest design).
# Фиксированный интервал (НЕ адаптивный, в отличие от AMBIENT_*) — рутинная
# осведомлённость не должна подстраиваться под драму гонки.
ENGINEER_DIGEST_INTERVAL_S = 40.0
```

- [ ] **Step 2: Написать падающий тест на постановку события**

Добавить в `tests/test_engine_planner.py`:

```python
def test_engineer_digest_loop_enqueues_preset_phrase(engine):
    _drain(engine)
    engine._gap_digest.reset()
    engine._session_type = "race"
    engine._player_gap_front = 1800
    engine._player_gap_behind = None
    engine._last_significant_event_t = 0.0        # вне cooldown
    engine.state["connected"] = True              # __init__-дефолт False — иначе гейт отрубит всё

    ok = engine._maybe_emit_gap_digest(time.time())

    assert ok is True
    evt = engine.event_queue.get_nowait()
    assert evt["event_code"] == "ENGINEER_GAP_DIGEST"
    assert evt["phrase"] == "Отрыв впереди: 1.8."
    assert evt["speaker"] == "engineer"
    engine._gap_digest.reset()
    engine._session_type = "unknown"
    engine._player_gap_front = None
    engine.state["connected"] = False


def test_engineer_digest_loop_skips_outside_race(engine):
    _drain(engine)
    engine._gap_digest.reset()
    engine._session_type = "qualifying"
    engine._player_gap_front = 1800
    engine._last_significant_event_t = 0.0
    engine.state["connected"] = True

    ok = engine._maybe_emit_gap_digest(time.time())

    assert ok is False
    assert engine.event_queue.empty()
    engine._session_type = "unknown"
    engine._player_gap_front = None
    engine.state["connected"] = False


def test_engineer_digest_loop_skips_during_event_cooldown(engine):
    _drain(engine)
    engine._gap_digest.reset()
    engine._session_type = "race"
    engine._player_gap_front = 1800
    engine._last_significant_event_t = time.time()  # свежая драма
    engine.state["connected"] = True

    ok = engine._maybe_emit_gap_digest(time.time())

    assert ok is False
    assert engine.event_queue.empty()
    engine._session_type = "unknown"
    engine._player_gap_front = None
    engine._last_significant_event_t = 0.0
    engine.state["connected"] = False


def test_engineer_digest_loop_skips_when_no_gap_data(engine):
    _drain(engine)
    engine._gap_digest.reset()
    engine._session_type = "race"
    engine._player_gap_front = None
    engine._player_gap_behind = None
    engine._last_significant_event_t = 0.0
    engine.state["connected"] = True

    ok = engine._maybe_emit_gap_digest(time.time())

    assert ok is False
    assert engine.event_queue.empty()
    engine._session_type = "unknown"
    engine.state["connected"] = False


def test_engineer_digest_loop_skips_when_not_connected(engine):
    """__init__-дефолт state["connected"]=False — если телеметрия не
    поднялась (или отвалилась), сводка молчит, как и _ambient_loop."""
    _drain(engine)
    engine._gap_digest.reset()
    engine._session_type = "race"
    engine._player_gap_front = 1800
    engine._last_significant_event_t = 0.0
    engine.state["connected"] = False

    ok = engine._maybe_emit_gap_digest(time.time())

    assert ok is False
    assert engine.event_queue.empty()
    engine._session_type = "unknown"
    engine._player_gap_front = None
```

(Тесты вызывают `_maybe_emit_gap_digest(now)` — извлечённое тело тика,
без `time.sleep`/бесконечного цикла — см. Step 3 ниже: сам
`_engineer_digest_loop` тонкий и не тестируется напрямую, как `_ambient_loop`,
но его логика вынесена в вызываемый метод, который тестируется. Все тесты
явно выставляют `engine.state["connected"] = True` (кроме последнего,
который специально проверяет обратное) — `__init__`-дефолт `False` иначе
молча гасил бы каждый тест этой группы по причине, не связанной с тем, что
тест хочет проверить.)

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `py -3.12 -u -m pytest tests/test_engine_planner.py -k digest -q`
Expected: `AttributeError: 'F1Engine' object has no attribute '_gap_digest'`

- [ ] **Step 4: Импорт + инициализация**

В `core/engine.py`, рядом с существующим импортом (строка 53):
```python
from core.strategy_ai.box_call import DECISIVE_CONFIDENCE, BoxCallTracker
from core.strategy_ai.gap_digest import GapDigestTracker
```

В `__init__`, сразу после `self.strategy_analyzer = StrategyAnalyzer()`
(строка 204):
```python
        self._gap_digest = GapDigestTracker()
```

- [ ] **Step 5: Метод тика + поток**

Найти конец метода `_ambient_loop` — он заканчивается непосредственно перед
разделом `# ------------------------------------------------------------`/
`# Для UI` (следующая секция файла, метод `get_state`). Добавить новые методы
`_maybe_emit_gap_digest`/`_engineer_digest_loop` СРАЗУ ПОСЛЕ конца
`_ambient_loop`, перед этим разделом «Для UI» (НЕ рядом с
`_ambient_llm_throttled` — это разные, далеко разнесённые по файлу места;
искать по тексту `# Для UI`, не по номеру строки):

```python
    def _maybe_emit_gap_digest(self, now: float) -> bool:
        """Один тик _engineer_digest_loop: строит и ставит в очередь сводку
        по гэпам, если есть что сказать. Возвращает True, если поставил
        событие (для тестов — сам бесконечный цикл не тестируется напрямую,
        как _ambient_loop)."""
        if (self._is_paused() or self._session_type != "race"
                or self._in_event_cooldown(now)):
            return False
        with self.state_lock:
            connected = self.state.get("connected")
        if not connected:
            return False
        phrase = self._gap_digest.build(self._player_gap_front, self._player_gap_behind)
        if phrase is None:
            return False
        self._enqueue_event({
            "event_code": "ENGINEER_GAP_DIGEST", "priority": "normal",
            "phrase": phrase, "speaker": SPEAKER_ENGINEER,
            "driver": "", "color": "#38BDF8",
        })
        return True

    def _engineer_digest_loop(self) -> None:
        """Периодическая (фиксированный интервал, НЕ адаптивный) сводка
        инженера по гэпам. См. spec 2026-07-10-engineer-gap-digest-design.md."""
        while True:
            time.sleep(config.ENGINEER_DIGEST_INTERVAL_S)
            self._maybe_emit_gap_digest(time.time())
```

- [ ] **Step 6: Запуск потока в `start()`**

В `core/engine.py::start()` (строка 782), рядом с `_ambient_loop`:
```python
    def start(self):
        threading.Thread(target=self._telemetry_loop, daemon=True).start()
        threading.Thread(target=self._commentary_loop, daemon=True).start()
        threading.Thread(target=self._yandex_health_loop, daemon=True,
                         name="yandex-health").start()
        threading.Thread(target=self._ambient_loop, daemon=True,
                         name="ambient-tick").start()
        threading.Thread(target=self._engineer_digest_loop, daemon=True,
                         name="engineer-digest").start()
```

- [ ] **Step 7: Сброс на новой сессии**

В блоке `if code == "SSTA":`, рядом с `self._box_call_tracker.reset()`
(строка 1201), добавить:
```python
                self._gap_digest.reset()
```

- [ ] **Step 8: Прогнать, зелёные**

Run: `py -3.12 -u -m pytest tests/test_engine_planner.py -q`
Expected: все тесты файла зелёные (существующие + 5 новых)

---

### Task 3: Полный прогон + CONTEXT.md

- [ ] **Step 1: Полный прогон**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: 0 failed.

- [ ] **Step 2: CONTEXT.md**

Добавить сессию: гэп-дайджест инженера реализован АВТОНОМНО (пользователь
отсутствовал), автономные решения из спеки (интервал 40с, только race,
без секторов пока) требуют его review постфактум — явно пометить это в
записи, не как обычное «готово, не проверено вживую».

---

## Верификация (сквозная)

- `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q` — весь набор зелёный.
- Точечно: `pytest tests/test_gap_digest.py tests/test_engine_planner.py -q`.
- Живая проверка (звучит ли сводка раз в ~40с голосом инженера, адекватен ли
  интервал/формат) — у пользователя, недоступно в среде разработки. Учитывая,
  что дизайн принят автономно — это review, не просто smoke-test.
