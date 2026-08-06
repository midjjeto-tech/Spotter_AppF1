# Точный box-вызов — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить императивный, детерминированный (без LLM) вызов «боксы в этом
круге» с эскалацией по кругам, поверх уже существующей уверенности
`StrategyAnalyzer`, — не мягкий совет, а решительная команда, как у настоящего
инженера F1.

**Architecture:** Новый чистый конечный автомат `BoxCallTracker`
(`core/strategy_ai/box_call.py`) следит за порогом уверенности 0.85 у уже
готового `StrategyEvent` и выдаёт номер эскалации (1→2→3, плато) по кругам.
Три новых кода (`STRAT_BOX_CALL_1/2/3`) регистрируются как ещё одна strategy-AI
запись (`commentator/templates.py` + `commentator/strategist.py`, тот же паттерн,
что уже используют `STRAT_PIT`/`STRAT_UNDERCUT` и т.д.), и получают bypass
LLM в `commentator/brain.py::create()` — гарантированная моментальная фраза.

**Tech Stack:** Python 3.12, pytest. Проект НЕ под git (см. `CONTEXT.md`) — шаги
«commit» в этом плане заменены на «проверить тестами», коммитить нечего.

**Спека:** `docs/superpowers/specs/2026-07-09-precise-box-call-design.md`

---

### Task 1: `BoxCallTracker` — конечный автомат эскалации

**Files:**
- Create: `core/strategy_ai/box_call.py`
- Test: `tests/test_box_call.py`

- [ ] **Step 1: Написать падающие тесты**

```python
# tests/test_box_call.py
"""BoxCallTracker — детерминированный автомат эскалации 'боксы в этом круге'.
См. docs/superpowers/specs/2026-07-09-precise-box-call-design.md.
"""
from core.strategy_ai.box_call import DECISIVE_CONFIDENCE, MAX_TIER, BoxCallTracker


def test_arms_on_first_decisive_tick():
    t = BoxCallTracker()
    tier = t.update(player_lap=10, action="pit", confidence=0.9, pit_status=0)
    assert tier == 1


def test_does_not_repeat_within_same_lap():
    t = BoxCallTracker()
    t.update(player_lap=10, action="pit", confidence=0.9, pit_status=0)
    tier = t.update(player_lap=10, action="pit", confidence=0.9, pit_status=0)
    assert tier is None


def test_escalates_on_next_lap_if_still_not_pitted():
    t = BoxCallTracker()
    t.update(player_lap=10, action="pit", confidence=0.9, pit_status=0)
    tier2 = t.update(player_lap=11, action="pit", confidence=0.9, pit_status=0)
    tier3 = t.update(player_lap=12, action="pit", confidence=0.9, pit_status=0)
    assert (tier2, tier3) == (2, 3)


def test_plateaus_at_max_tier():
    t = BoxCallTracker()
    t.update(player_lap=10, action="pit", confidence=0.9, pit_status=0)
    t.update(player_lap=11, action="pit", confidence=0.9, pit_status=0)
    t.update(player_lap=12, action="pit", confidence=0.9, pit_status=0)
    tier4 = t.update(player_lap=13, action="pit", confidence=0.9, pit_status=0)
    assert tier4 == MAX_TIER == 3


def test_pit_status_resets_and_rearms_fresh():
    t = BoxCallTracker()
    t.update(player_lap=10, action="pit", confidence=0.9, pit_status=0)
    t.update(player_lap=11, action="pit", confidence=0.9, pit_status=0)
    during_stop = t.update(player_lap=11, action="pit", confidence=0.9, pit_status=1)
    assert during_stop is None
    tier = t.update(player_lap=15, action="pit", confidence=0.9, pit_status=0)
    assert tier == 1                     # свежий цикл, не продолжение эскалации


def test_confidence_below_threshold_resets():
    t = BoxCallTracker()
    t.update(player_lap=10, action="pit", confidence=0.9, pit_status=0)
    tier = t.update(player_lap=11, action="pit", confidence=0.5, pit_status=0)
    assert tier is None
    tier2 = t.update(player_lap=12, action="pit", confidence=0.9, pit_status=0)
    assert tier2 == 1                    # не escalation 3 — новый цикл


def test_action_not_pit_resets():
    t = BoxCallTracker()
    t.update(player_lap=10, action="pit", confidence=0.9, pit_status=0)
    tier = t.update(player_lap=11, action="hold", confidence=0.9, pit_status=0)
    assert tier is None


def test_low_confidence_never_arms():
    t = BoxCallTracker()
    tier = t.update(player_lap=10, action="pit", confidence=DECISIVE_CONFIDENCE - 0.01,
                     pit_status=0)
    assert tier is None


def test_player_lap_none_is_safe_noop():
    t = BoxCallTracker()
    tier = t.update(player_lap=None, action="pit", confidence=0.9, pit_status=0)
    assert tier is None
```

- [ ] **Step 2: Убедиться, что тесты падают (модуля ещё нет)**

Run: `py -3.12 -u -m pytest tests/test_box_call.py -q`
Expected: `ModuleNotFoundError: No module named 'core.strategy_ai.box_call'`

- [ ] **Step 3: Реализовать `BoxCallTracker`**

```python
# core/strategy_ai/box_call.py
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
        озвучки в этом тике, либо None (молчать)."""
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

    def reset(self) -> None:
        self._armed_lap = None
        self._last_called_lap = None
        self._tier = 0
```

- [ ] **Step 4: Прогнать тесты, убедиться что зелёные**

Run: `py -3.12 -u -m pytest tests/test_box_call.py -q`
Expected: `9 passed`

---

### Task 2: Фразы эскалации — `strategist.py` + `templates.py`

**Files:**
- Modify: `commentator/strategist.py:10-40` (словарь `_MESSAGES`)
- Modify: `commentator/templates.py:22-29` (словарь `_STRATEGY_AI_CODES`)
- Create: `tests/test_strategist.py` (подтверждено: файла сейчас нет в `tests/`)
- Create: `tests/test_templates.py` (подтверждено: файла сейчас нет в `tests/`)

- [ ] **Step 1: Написать падающий тест на новые фразы**

```python
# tests/test_strategist.py (новый файл)
from commentator.strategist import get_message


def test_box_call_tier_1_message():
    assert get_message("box_call_1") == "Бокс в этом круге. Повторяю, бокс в этом круге."


def test_box_call_tier_2_message():
    assert get_message("box_call_2") == "Бокс, бокс — заезжай сейчас."


def test_box_call_tier_3_message():
    assert get_message("box_call_3") == "Ты теряешь время каждый круг — боксы!"
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `py -3.12 -u -m pytest tests/test_strategist.py -q`
Expected: FAIL — `get_message("box_call_1")` возвращает случайную фразу из
`_MESSAGES["stable"]` (фолбэк на неизвестный ключ), не совпадает с ожидаемой.

- [ ] **Step 3: Добавить фразы в `commentator/strategist.py`**

В словарь `_MESSAGES` (после `"fuel_save": [...]`, перед `"stable": [...]`)
добавить:

```python
    "box_call_1": ["Бокс в этом круге. Повторяю, бокс в этом круге."],
    "box_call_2": ["Бокс, бокс — заезжай сейчас."],
    "box_call_3": ["Ты теряешь время каждый круг — боксы!"],
```

- [ ] **Step 4: Прогнать тест strategist, убедиться что зелёный**

Run: `py -3.12 -u -m pytest tests/test_strategist.py -q`
Expected: `3 passed` (плюс уже существовавшие тесты в этом файле, если были)

- [ ] **Step 5: Зарегистрировать коды событий в `commentator/templates.py`**

В словарь `_STRATEGY_AI_CODES` (строки 22-29) добавить три записи:

```python
_STRATEGY_AI_CODES = {
    "STRAT_UNDERCUT": "undercut",
    "STRAT_OVERCUT":  "overcut",
    "STRAT_PIT":      "pit_window",
    "STRAT_SAVE":     "tyre_save",
    "STRAT_PUSH":     "push_pace",
    "STRAT_FUEL":     "fuel_save",
    "STRAT_BOX_CALL_1": "box_call_1",
    "STRAT_BOX_CALL_2": "box_call_2",
    "STRAT_BOX_CALL_3": "box_call_3",
}
```

- [ ] **Step 6: Написать и прогнать тест на `templates.render()`**

```python
# tests/test_templates.py (новый файл — подтверждено: сейчас его нет в tests/)
from commentator import templates


def test_render_strat_box_call_routes_to_strategist():
    out = templates.render({"event_code": "STRAT_BOX_CALL_1"}, "tv")
    assert out == "Бокс в этом круге. Повторяю, бокс в этом круге."
```

Run: `py -3.12 -u -m pytest tests/test_templates.py -k box_call -q`
Expected: `1 passed`

---

### Task 3: Bypass LLM для box-call кодов в `commentator/brain.py`

**Files:**
- Modify: `commentator/brain.py`
- Test: `tests/test_brain.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `tests/test_brain.py` (использует уже существующий `FakeAI` из этого
файла, см. верх файла):

```python
def test_box_call_bypasses_llm_even_when_available():
    ai = FakeAI(result="не должно прозвучать — LLM не должен вызываться")
    out = Commentator(ai, "tv").create(
        {"event_code": "STRAT_BOX_CALL_1"}, "ctx", ai_ok=True)
    assert ai.calls == []                                  # LLM не дёргали вообще
    assert out == "Бокс в этом круге. Повторяю, бокс в этом круге."
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `py -3.12 -u -m pytest tests/test_brain.py -k box_call -q`
Expected: FAIL — `ai.calls` не пуст (сейчас `create()` безусловно идёт в LLM,
если `self.ai.available and ai_ok`).

- [ ] **Step 3: Добавить bypass в начало `Commentator.create()`**

В `commentator/brain.py`, добавить рядом с остальными модульными константами
(после `_SILENCE_ECHOES`, перед `class Commentator:`):

```python
# Императивные box-call коды НИКОГДА не идут в LLM — гарантированная,
# мгновенная, ровно одобренная формулировка для решающей команды.
# См. docs/superpowers/specs/2026-07-09-precise-box-call-design.md.
_TEMPLATE_ONLY_CODES = frozenset({
    "STRAT_BOX_CALL_1", "STRAT_BOX_CALL_2", "STRAT_BOX_CALL_3",
})
```

В начале метода `create()` (сразу после строки `code = (event or {}).get("event_code", "")`,
перед `if self.ai.available and ai_ok:`) добавить:

```python
        if code in _TEMPLATE_ONLY_CODES:
            phrase = templates.render(event, self.persona)
            if phrase:
                self.memory.append(phrase, code)
            return phrase
```

- [ ] **Step 4: Прогнать тест, убедиться что зелёный**

Run: `py -3.12 -u -m pytest tests/test_brain.py -q`
Expected: все тесты файла зелёные (включая новый и 6 уже существовавших)

---

### Task 4: Проводка в `core/engine.py`

**Files:**
- Modify: `core/engine.py`
- Test: `tests/test_engine_planner.py` (добавить тесты рядом с уже существующими
  для `_enqueue_event`, используя фикстуру `engine` из этого файла)

- [ ] **Step 1: Импорт и инициализация трекера**

В `core/engine.py`, рядом с существующим импортом (строка 52):

```python
from core.strategy_ai.strategy import StrategyAnalyzer
from core.strategy_ai.box_call import BoxCallTracker
```

В `__init__`, сразу после `self._last_strategy_ai_event_t: float = 0.0` (строка 194):

```python
        self._box_call_tracker = BoxCallTracker()
```

- [ ] **Step 2: Написать падающий тест на постановку события в очередь**

Добавить в `tests/test_engine_planner.py`:

```python
def test_box_call_enqueues_critical_event_on_decisive_strategy(engine, monkeypatch):
    _drain(engine)
    engine._box_call_tracker.reset()
    engine._player_lap = 20
    engine._player_pit_status = 0
    engine._last_snap_t = 0.0                    # обойти троттлинг 1с

    class _FakeDecision:
        action = "pit"

    class _FakeEvent:
        decision = _FakeDecision()
        confidence = 0.9

    monkeypatch.setattr(engine.strategy_analyzer, "update", lambda snap: _FakeEvent())
    engine._maybe_snapshot()

    drained = []
    while not engine.event_queue.empty():
        drained.append(engine.event_queue.get_nowait())
    found = [e for e in drained if e["event_code"] == "STRAT_BOX_CALL_1"]
    assert len(found) == 1
    assert found[0]["priority"] == "critical"
    engine._box_call_tracker.reset()              # не протекать в следующие тесты
```

- [ ] **Step 2b: Убедиться, что тест падает**

Run: `py -3.12 -u -m pytest tests/test_engine_planner.py -k box_call -q`
Expected: FAIL — `STRAT_BOX_CALL_1` в очереди нет (проводки ещё нет)

- [ ] **Step 3: Добавить вызов трекера в `_maybe_snapshot()`**

В `core/engine.py`, сразу после `strategy_event = self.strategy_analyzer.update(st_snapshot)`
(строка 1031), добавить:

```python
        # Императивный box-call — единый порог уверенности (0.85) поверх уже
        # готового StrategyEvent, независимо от причины (шины/андеркат/cover).
        # Вызывается КАЖДЫЙ тик (не только когда strategy_event не None) —
        # иначе трекер не сбросится при резком исчезновении решительного
        # состояния. См. spec 2026-07-09-precise-box-call-design.md.
        _bc_action = strategy_event.decision.action if strategy_event else "hold"
        _bc_confidence = strategy_event.confidence if strategy_event else 0.0
        box_tier = self._box_call_tracker.update(
            self._player_lap, _bc_action, _bc_confidence, self._player_pit_status)
        if box_tier is not None:
            self._enqueue_event({
                "event_code": f"STRAT_BOX_CALL_{box_tier}",
                "priority": "critical",
                "driver": "player", "color": "#EF4444",
            })
```

- [ ] **Step 4: Прогнать тест, убедиться что зелёный**

Run: `py -3.12 -u -m pytest tests/test_engine_planner.py -q`
Expected: все тесты файла зелёные (включая новый)

- [ ] **Step 5: Сброс трекера во флешбеке**

В `core/engine.py`, в методе `_handle_flashback()`, рядом с
`self._situation_dedup.reset()` (строка 1133), добавить:

```python
        self._box_call_tracker.reset()
```

- [ ] **Step 6: Сброс трекера на старте новой сессии и на финише**

В блоке `if code == "SSTA":` (строка 1505), рядом с обнулением
`self._damage_announced` (строки 1513-1515), добавить:

```python
                self._box_call_tracker.reset()
```

В блоке `elif code in ("CHQF", "SEND"):` (строка 1533), сразу после
`self._session_events.append(code)` на первой строке этого блока, добавить:

```python
                self._box_call_tracker.reset()
```

- [ ] **Step 7: Написать тест на сброс во флешбеке**

Добавить в `tests/test_engine_planner.py`:

```python
def test_flashback_resets_box_call_tracker(engine):
    engine._box_call_tracker.update(player_lap=5, action="pit", confidence=0.9, pit_status=0)
    engine._handle_flashback()
    tier = engine._box_call_tracker.update(
        player_lap=6, action="pit", confidence=0.9, pit_status=0)
    assert tier == 1                              # не 2 — состояние было сброшено
    engine._box_call_tracker.reset()
```

- [ ] **Step 8: Прогнать тест, убедиться что зелёный**

Run: `py -3.12 -u -m pytest tests/test_engine_planner.py -q`
Expected: все тесты файла зелёные

---

### Task 5: Полный прогон и документация

**Files:**
- Modify: `CONTEXT.md`

- [ ] **Step 1: Полный прогон тестов**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: все тесты зелёные, 0 failed

- [ ] **Step 2: Обновить CONTEXT.md**

Добавить короткую запись в раздел «На чём остановились» / открытые баги —
фаза 1 из 4 («точный box-вызов») закрыта, спека + план в
`docs/superpowers/specs/2026-07-09-precise-box-call-design.md` /
`docs/superpowers/plans/2026-07-09-precise-box-call.md`; фазы 2-4 (сводки по
гэпу, топливо/ERS, погода/трек-лимиты) — впереди, каждая отдельным
brainstorming-циклом. Отметить: **не проверено вживую** — нужна реальная
гонка с приближением к обрыву резины/андеркату, чтобы услышать эскалацию
своими ушами.

---

## Верификация (сквозная)

- `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q` — весь набор зелёный.
- Точечно: `pytest tests/test_box_call.py tests/test_strategist.py tests/test_templates.py tests/test_brain.py tests/test_engine_planner.py -q`.
- Живая проверка в игре (F1 25, гонка, довести шины до "cliff"/"critical" или
  сымитировать высокую уверенность андерката) — недоступна в среде разработки,
  нужна пользователю после сборки.
