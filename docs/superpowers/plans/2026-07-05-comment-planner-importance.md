# Comment Planner + Importance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every commentary event a graded importance (0–100) instead of today's binary `critical`/`normal`, and make Python — not the LLM — decide WHAT to comment on (focus/reaction/length/emotion) so the LLM only formulates text, fixing the documented trigger↔phrase desync (LLM re-narrating the dominant drama on any trigger).

**Architecture:** New pure module `commentator/planner.py` scores importance and builds a `CommentPlan` directive. A new `core/event_queue.py::ImportanceQueue` wraps `queue.PriorityQueue` behind the same dict-in/dict-out interface `core/engine.py` already uses, so existing call sites barely change. `core/engine.py` gains one funnel (`_enqueue_event`) that all 10 existing `event_queue.put({...})` call sites go through, plus a decaying speak/mute threshold and importance-driven gap/interrupt logic. `commentator/brain.py` accepts an optional `plan` and, when present, puts a "ЗАДАЧА: …" directive as the FIRST block of LLM context; `commentator/personas.py`'s system prompt is updated so it defers to that directive instead of always "deciding for itself".

**Tech Stack:** Python 3.12, standard library `queue`/`dataclasses`, pytest. No frontend changes in this plan.

> ⚠️ **Репозиторий НЕ под git** (`Is a git repository: false`). Шаги «Commit» заменены на **Checkpoint** — прогон тестов задачи. Команды тестов: `py -3.12 -m pytest ... -q`.

**Спека:** [`docs/superpowers/specs/2026-07-05-comment-planner-importance-design.md`](../specs/2026-07-05-comment-planner-importance-design.md).

---

## Файловая структура

| Файл | Действие | Ответственность |
|------|----------|-----------------|
| `commentator/planner.py` | создать | `PlanContext`, `CommentPlan`, `score_importance()`, `build_plan()` |
| `core/event_queue.py` | создать | `ImportanceQueue` — очередь по важности, dict-интерфейс как у `queue.Queue` |
| `config.py` | изменить | константы `PLAN_*` |
| `core/engine.py` | изменить | `ImportanceQueue`, `_enqueue_event()`/`_plan_context()`, порог говорить/молчать, вытеснение по staleness+importance, гэп/прерывание по важности, вызов `build_plan()` |
| `commentator/brain.py` | изменить | `create()`/`_compose()` принимают `CommentPlan`, директива — первым блоком |
| `commentator/personas.py` | изменить | контракт «КАК РАБОТАТЬ» уступает директиве ЗАДАЧА, если она есть |
| `tests/test_planner.py` | создать | |
| `tests/test_event_queue.py` | создать | |
| `tests/test_engine_planner.py` | создать | |
| `tests/test_commentary_backlog.py` | изменить | staleness теперь по importance+age, не по `qsize()` |
| `tests/test_brain.py` | изменить | новые тесты на `plan=` |
| `tests/test_personas.py` | изменить | новый тест на приоритет директивы |
| `CONTEXT.md` | изменить | запись новой сессии |

---

## Task 1: `commentator/planner.py` — оценка важности + план реплики

**Files:**
- Create: `commentator/planner.py`
- Test: `tests/test_planner.py` (новый)

- [ ] **Step 1: Write the failing tests**

Создать `tests/test_planner.py`:

```python
"""Comment Planner: важность события + план реплики (фокус/тип/длина/эмоция).
Чистые функции, без I/O — см. docs/superpowers/specs/2026-07-05-comment-planner-importance-design.md
"""
from commentator.planner import PlanContext, score_importance, build_plan

_CTX = PlanContext()


# --------------------------------------------------------------------------- #
# score_importance
# --------------------------------------------------------------------------- #

def test_score_default_for_unknown_code():
    assert score_importance({"event_code": "WTF"}, _CTX) == 50


def test_score_base_table_ovtk():
    assert score_importance({"event_code": "OVTK"}, _CTX) == 60


def test_score_base_table_ambient():
    assert score_importance({"event_code": "AMBIENT"}, _CTX) == 20


def test_score_player_involved_modifier():
    ctx = PlanContext(player_involved=True)
    assert score_importance({"event_code": "OVTK"}, ctx) == 80


def test_score_battle_modifier():
    ctx = PlanContext(battle=True)
    assert score_importance({"event_code": "OVTK"}, ctx) == 75


def test_score_laps_remaining_modifier():
    ctx = PlanContext(laps_remaining=2)
    assert score_importance({"event_code": "OVTK"}, ctx) == 70


def test_score_laps_remaining_above_threshold_no_modifier():
    ctx = PlanContext(laps_remaining=10)
    assert score_importance({"event_code": "OVTK"}, ctx) == 60


def test_score_non_race_session_penalizes_ovtk_ftlp():
    ctx = PlanContext(session_type="practice")
    assert score_importance({"event_code": "OVTK"}, ctx) == 50
    assert score_importance({"event_code": "FTLP"}, ctx) == 45


def test_score_non_race_session_does_not_affect_other_codes():
    ctx = PlanContext(session_type="practice")
    assert score_importance({"event_code": "PENA"}, ctx) == 88


def test_score_clamped_to_100():
    ctx = PlanContext(player_involved=True, battle=True, laps_remaining=1)
    # 60 + 20 + 15 + 10 = 105 -> зажато в 100
    assert score_importance({"event_code": "OVTK"}, ctx) == 100


def test_score_clamped_to_0():
    # синтетический случай: код с отрицательной эффективной важностью не встречается
    # в реальной таблице, но зажим должен работать в обе стороны
    ctx = PlanContext(session_type="practice")
    event = {"event_code": "FTLP"}
    assert score_importance(event, ctx) >= 0


def test_score_critical_priority_floors_at_90():
    # низкий базовый код, но помечен critical -> обязан получить пол 90
    assert score_importance({"event_code": "WTF", "priority": "critical"}, _CTX) == 90


def test_score_critical_does_not_lower_already_higher_score():
    ctx = PlanContext(player_involved=True, battle=True)
    # COLL: база 90 + 20 + 15 = 125 -> уже выше пола, max() не понижает до 90
    assert score_importance({"event_code": "COLL", "priority": "critical"}, ctx) == 100


# --------------------------------------------------------------------------- #
# build_plan
# --------------------------------------------------------------------------- #

def test_build_plan_focus_with_target():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри"}
    plan = build_plan(event, importance=80, persona="tv")
    assert plan.focus == "атака: Норрис и Пиастри"
    assert plan.reaction == "атака"
    assert plan.must_mention == ("Норрис", "Пиастри")


def test_build_plan_focus_driver_only():
    event = {"event_code": "FTLP", "driver": "Ферстаппен"}
    plan = build_plan(event, importance=55, persona="tv")
    assert plan.focus == "рекорд круга: Ферстаппен"
    assert plan.must_mention == ("Ферстаппен",)


def test_build_plan_focus_no_names():
    event = {"event_code": "SSTA"}
    plan = build_plan(event, importance=70, persona="tv")
    assert plan.focus == "старт"
    assert plan.must_mention == ()


def test_build_plan_unknown_code_uses_default_reaction():
    event = {"event_code": "WTF"}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.reaction == "ремарка"
    assert plan.focus == "ремарка"


def test_build_plan_length_short_above_threshold():
    event = {"event_code": "COLL", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=90, persona="tv")
    assert plan.length == "короткая ударная"
    assert plan.emotion == "на пределе"


def test_build_plan_length_normal_mid_tier():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=65, persona="tv")
    assert plan.length == "обычная"
    assert plan.emotion == "оживлённо"


def test_build_plan_length_normal_low_tier():
    event = {"event_code": "AMBIENT"}
    plan = build_plan(event, importance=20, persona="tv")
    assert plan.length == "обычная"
    assert plan.emotion == "спокойно"


def test_build_plan_persona_calm_lowers_emotion():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=65, persona="calm")
    assert plan.emotion == "спокойно"          # "оживлённо" на ступень ниже


def test_build_plan_persona_hype_raises_emotion():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=65, persona="hype")
    assert plan.emotion == "на пределе"        # "оживлённо" на ступень выше


def test_build_plan_persona_toxic_raises_emotion():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=65, persona="toxic")
    assert plan.emotion == "на пределе"


def test_build_plan_persona_hype_caps_at_top():
    event = {"event_code": "COLL", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=90, persona="hype")
    assert plan.emotion == "на пределе"        # уже макс, +1 не уходит за пределы


def test_build_plan_persona_calm_caps_at_bottom():
    event = {"event_code": "AMBIENT"}
    plan = build_plan(event, importance=20, persona="calm")
    assert plan.emotion == "спокойно"          # уже мин, -1 не уходит за пределы


def test_build_plan_unknown_persona_does_not_shift():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б"}
    plan = build_plan(event, importance=65, persona="nonexistent")
    assert plan.emotion == "оживлённо"         # нет сдвига для неизвестной персоны


def test_build_plan_importance_is_carried_through():
    plan = build_plan({"event_code": "SSTA"}, importance=42, persona="tv")
    assert plan.importance == 42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_planner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'commentator.planner'`

- [ ] **Step 3: Implement `commentator/planner.py`**

```python
"""
commentator/planner.py
========================
Планировщик реплики: Python оценивает ВАЖНОСТЬ события (0-100) и решает, О ЧЁМ
и КАК говорить (focus/reaction/length/emotion) — LLM формулирует текст СТРОГО по
этой директиве, а не выбирает тему сам. Чинит корневую причину рассинхрона
триггер↔фраза (LLM пересказывает доминантную драму таймлайна на любой триггер),
задокументированную в CONTEXT.md.

Чистые функции без I/O и без сети — полностью юнит-тестируемы отдельно от engine.
См. docs/superpowers/specs/2026-07-05-comment-planner-importance-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanContext:
    """Срез состояния гонки, нужный только для оценки важности. F1Engine строит
    это по значению (см. _plan_context()) — planner в state/lock'и НЕ лезет."""
    player_involved: bool = False
    battle: bool = False
    laps_remaining: int | None = None
    session_type: str = "race"


@dataclass(frozen=True)
class CommentPlan:
    """Директива для LLM: ЧТО комментировать и КАК. Собирается build_plan()
    ПОСЛЕ entity resolution — driver/target в event должны быть настоящими
    именами, не '#N'/'гонщик'."""
    focus: str
    reaction: str
    length: str
    emotion: str
    importance: int
    must_mention: tuple[str, ...] = ()


# Базовый балл по event_code — см. design spec §"score_importance — базовая таблица".
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
}
_DEFAULT_IMPORTANCE = 50

# Модификаторы (design spec §"score_importance"): суммируются, итог зажимается [0,100].
_PLAYER_INVOLVED_BONUS = 20
_BATTLE_BONUS = 15
_FINAL_LAPS_BONUS = 10
_FINAL_LAPS_THRESHOLD = 3
_NON_RACE_PENALTY = 10
_NON_RACE_PENALIZED_CODES = ("OVTK", "FTLP")
_CRITICAL_FLOOR = 90


def score_importance(event: dict, ctx: PlanContext) -> int:
    """Важность 0..100. Событие с priority == 'critical' всегда получает ХОТЯ БЫ
    90 — сегодняшние гарантии critical (гэп/прерывание/анти-вытеснение) сохранены."""
    code = event.get("event_code", "")
    score = _BASE_IMPORTANCE.get(code, _DEFAULT_IMPORTANCE)

    if ctx.player_involved:
        score += _PLAYER_INVOLVED_BONUS
    if ctx.battle:
        score += _BATTLE_BONUS
    if ctx.laps_remaining is not None and ctx.laps_remaining <= _FINAL_LAPS_THRESHOLD:
        score += _FINAL_LAPS_BONUS
    if ctx.session_type != "race" and code in _NON_RACE_PENALIZED_CODES:
        score -= _NON_RACE_PENALTY

    if event.get("priority") == "critical":
        score = max(score, _CRITICAL_FLOOR)

    return max(0, min(100, score))


# Тип реакции по коду события — участвует в директиве LLM (build_plan()).
_REACTION_BY_CODE: dict[str, str] = {
    "COLL": "авария",
    "RTMT": "сход",
    "PENA": "штраф",
    "RCWN": "победитель определён",
    "CHQF": "финиш",
    "OVTK": "атака",
    "FTLP": "рекорд круга",
    "DAMAGE_WING": "разбор повреждения",
    "DAMAGE_FLOOR": "разбор повреждения",
    "DAMAGE_GEARBOX": "разбор повреждения",
    "DAMAGE_ENGINE": "разбор повреждения",
    "F1_BENCH": "рекорд", "CAREER_PB": "рекорд",
    "F1_SECTOR_BENCH": "рекорд", "CAREER_SECTOR_PB": "рекорд",
    "SSTA": "старт", "STLG": "старт",
    "SEND": "итог сессии",
    "TMPT": "предупреждение", "SPTP": "разбор",
    "DRSE": "ремарка", "DRSD": "ремарка",
    "FLBK": "ремарка",
    "AMBIENT": "разбор",
}
_DEFAULT_REACTION = "ремарка"

# Длина: только два состояния (design spec §"build_plan — маппинг важности в стиль").
_LENGTH_SHORT_THRESHOLD = 80
_LENGTH_SHORT = "короткая ударная"
_LENGTH_NORMAL = "обычная"

# Эмоция: три ступени по важности, персона сдвигает результат на одну ступень.
_EMOTION_LADDER = ["спокойно", "оживлённо", "на пределе"]
_EMOTION_HIGH_THRESHOLD = 80
_EMOTION_MID_THRESHOLD = 50
_PERSONA_EMOTION_SHIFT = {"calm": -1, "hype": 1, "toxic": 1}


def _base_emotion(importance: int) -> str:
    if importance >= _EMOTION_HIGH_THRESHOLD:
        return _EMOTION_LADDER[2]
    if importance >= _EMOTION_MID_THRESHOLD:
        return _EMOTION_LADDER[1]
    return _EMOTION_LADDER[0]


def _shift_emotion(emotion: str, persona: str) -> str:
    shift = _PERSONA_EMOTION_SHIFT.get(persona, 0)
    if shift == 0:
        return emotion
    idx = _EMOTION_LADDER.index(emotion) + shift
    idx = max(0, min(len(_EMOTION_LADDER) - 1, idx))
    return _EMOTION_LADDER[idx]


def build_plan(event: dict, importance: int, persona: str) -> CommentPlan:
    """Строит директиву для LLM. Вызывать ПОСЛЕ entity resolution — driver/target
    в event должны быть уже резолвнутыми именами (см. _commentary_loop в
    core/engine.py: entity resolution идёт раньше build_plan() в пайплайне)."""
    code = event.get("event_code", "")
    driver = event.get("driver") or ""
    target = event.get("target") or ""
    reaction = _REACTION_BY_CODE.get(code, _DEFAULT_REACTION)

    if target:
        focus = f"{reaction}: {driver} и {target}".strip()
    elif driver:
        focus = f"{reaction}: {driver}".strip()
    else:
        focus = reaction

    length = _LENGTH_SHORT if importance >= _LENGTH_SHORT_THRESHOLD else _LENGTH_NORMAL
    emotion = _shift_emotion(_base_emotion(importance), persona)
    must_mention = tuple(name for name in (driver, target) if name)

    return CommentPlan(
        focus=focus,
        reaction=reaction,
        length=length,
        emotion=emotion,
        importance=importance,
        must_mention=must_mention,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_planner.py -q`
Expected: PASS (27 passed)

- [ ] **Step 5: Checkpoint** — тесты задачи зелёные.

---

## Task 2: `core/event_queue.py` — очередь по важности

**Files:**
- Create: `core/event_queue.py`
- Test: `tests/test_event_queue.py` (новый)

- [ ] **Step 1: Write the failing tests**

Создать `tests/test_event_queue.py`:

```python
"""ImportanceQueue: очередь по важности события за dict-интерфейсом queue.Queue.
См. docs/superpowers/specs/2026-07-05-comment-planner-importance-design.md."""
import queue

import pytest

from core.event_queue import ImportanceQueue


def test_higher_importance_drains_first():
    q = ImportanceQueue()
    q.put({"event_code": "LOW", "importance": 20})
    q.put({"event_code": "HIGH", "importance": 90})
    assert q.get_nowait()["event_code"] == "HIGH"
    assert q.get_nowait()["event_code"] == "LOW"


def test_equal_importance_is_fifo():
    q = ImportanceQueue()
    q.put({"event_code": "FIRST", "importance": 50})
    q.put({"event_code": "SECOND", "importance": 50})
    assert q.get_nowait()["event_code"] == "FIRST"
    assert q.get_nowait()["event_code"] == "SECOND"


def test_missing_importance_defaults_to_50():
    q = ImportanceQueue()
    q.put({"event_code": "NO_IMPORTANCE"})
    q.put({"event_code": "LOW", "importance": 10})
    assert q.get_nowait()["event_code"] == "NO_IMPORTANCE"
    assert q.get_nowait()["event_code"] == "LOW"


def test_get_nowait_raises_when_empty():
    q = ImportanceQueue()
    with pytest.raises(queue.Empty):
        q.get_nowait()


def test_empty_and_qsize():
    q = ImportanceQueue()
    assert q.empty() is True
    assert q.qsize() == 0
    q.put({"event_code": "X", "importance": 50})
    assert q.empty() is False
    assert q.qsize() == 1


def test_get_blocking_returns_dict():
    q = ImportanceQueue()
    q.put({"event_code": "X", "importance": 50})
    evt = q.get()
    assert evt["event_code"] == "X"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_event_queue.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.event_queue'`

- [ ] **Step 3: Implement `core/event_queue.py`**

```python
"""
core/event_queue.py
=====================
ImportanceQueue — обёртка над queue.PriorityQueue, скрывающая сортировочный
кортеж от вызывающего кода: put()/get()/get_nowait() работают с обычными
dict-событиями, как раньше работал queue.Queue. Сортировка — по
event["importance"] (выше важность -> раньше достаётся из очереди), при равной
важности — стабильный FIFO (монотонный счётчик как tie-breaker).

Важность в событие кладёт F1Engine._enqueue_event() ДО put(); если её там нет
(прямой put() в обход движка, как делают некоторые тесты) — нейтральный дефолт.
"""
from __future__ import annotations

import itertools
import queue

_DEFAULT_IMPORTANCE = 50


class ImportanceQueue:
    def __init__(self) -> None:
        self._q: "queue.PriorityQueue[tuple[int, int, dict]]" = queue.PriorityQueue()
        self._counter = itertools.count()

    def put(self, event: dict) -> None:
        importance = event.get("importance", _DEFAULT_IMPORTANCE)
        self._q.put((-importance, next(self._counter), event))

    def get(self) -> dict:
        return self._q.get()[2]

    def get_nowait(self) -> dict:
        return self._q.get_nowait()[2]

    def empty(self) -> bool:
        return self._q.empty()

    def qsize(self) -> int:
        return self._q.qsize()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_event_queue.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Checkpoint** — тесты задачи зелёные.

---

## Task 3: `config.py` + `core/engine.py` — очередь по важности вместо FIFO

**Files:**
- Modify: `config.py`
- Modify: `core/engine.py`
- Test: `tests/test_engine_planner.py` (новый)

- [ ] **Step 1: Write the failing tests**

Создать `tests/test_engine_planner.py`:

```python
"""Comment Planner wiring в F1Engine: очередь по важности, _enqueue_event(),
_plan_context(). См. docs/superpowers/specs/2026-07-05-comment-planner-importance-design.md.
"""
import time

import pytest

import core.engine as eng_mod
from core.engine import F1Engine


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _drain(engine):
    while not engine.event_queue.empty():
        engine.event_queue.get_nowait()


# --------------------------------------------------------------------------- #
# _enqueue_event
# --------------------------------------------------------------------------- #

def test_enqueue_event_computes_importance(engine):
    _drain(engine)
    engine._enqueue_event({"event_code": "OVTK", "priority": "normal"})
    evt = engine.event_queue.get_nowait()
    assert evt["importance"] == 60          # база OVTK, без модификаторов (нет "battle" и т.п.)


def test_enqueue_event_respects_precomputed_importance(engine):
    _drain(engine)
    engine._enqueue_event({"event_code": "OVTK", "importance": 99})
    evt = engine.event_queue.get_nowait()
    assert evt["importance"] == 99          # уже посчитана - не пересчитываем


def test_enqueue_event_falls_back_to_50_on_scoring_failure(engine, monkeypatch):
    _drain(engine)

    def _boom(event, ctx):
        raise RuntimeError("boom")

    monkeypatch.setattr(eng_mod, "score_importance", _boom)
    engine._enqueue_event({"event_code": "OVTK"})
    evt = engine.event_queue.get_nowait()
    assert evt["importance"] == 50


def test_enqueue_event_stamps_enqueued_at(engine):
    _drain(engine)
    before = time.time()
    engine._enqueue_event({"event_code": "OVTK"})
    evt = engine.event_queue.get_nowait()
    assert evt["enqueued_at"] >= before


def test_enqueue_event_drains_by_importance_not_fifo(engine):
    _drain(engine)
    engine._enqueue_event({"event_code": "AMBIENT", "ambient": True})            # importance 20
    engine._enqueue_event({"event_code": "COLL", "priority": "critical",
                            "vehicle1_idx": 1, "vehicle2_idx": 2})                # importance 90
    first = engine.event_queue.get_nowait()
    assert first["event_code"] == "COLL"
    second = engine.event_queue.get_nowait()
    assert second["event_code"] == "AMBIENT"


# --------------------------------------------------------------------------- #
# _plan_context
# --------------------------------------------------------------------------- #

def test_plan_context_player_involved(engine):
    engine._player_car_index = 3
    ctx = engine._plan_context({"event_code": "OVTK", "overtaking_idx": 3, "being_overtaken_idx": 7})
    assert ctx.player_involved is True
    engine._player_car_index = 255


def test_plan_context_not_involved_when_other_cars(engine):
    engine._player_car_index = 9
    ctx = engine._plan_context({"event_code": "OVTK", "overtaking_idx": 3, "being_overtaken_idx": 7})
    assert ctx.player_involved is False
    engine._player_car_index = 255


def test_plan_context_battle_flag_passthrough(engine):
    ctx = engine._plan_context({"event_code": "OVTK", "battle": True})
    assert ctx.battle is True


def test_plan_context_laps_remaining(engine):
    engine._player_lap = 18
    engine._total_laps = 20
    ctx = engine._plan_context({"event_code": "OVTK"})
    assert ctx.laps_remaining == 2
    engine._player_lap = None
    engine._total_laps = None


def test_plan_context_laps_remaining_none_when_unknown(engine):
    engine._player_lap = None
    engine._total_laps = None
    ctx = engine._plan_context({"event_code": "OVTK"})
    assert ctx.laps_remaining is None


def test_plan_context_session_type_passthrough(engine):
    engine._session_type = "practice"
    ctx = engine._plan_context({"event_code": "OVTK"})
    assert ctx.session_type == "practice"
    engine._session_type = "race"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_engine_planner.py -q`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute '_enqueue_event'`

- [ ] **Step 3: `config.py` — новые константы**

Найти:

```python
LLM_MIN_INTERVAL = 8.0         # "лёгкий" throttle: мин. пауза между ambient-LLM-запросами (сек)
# Сколько последних снимков/событий гонки держим в памяти (скользящее окно).
TIMELINE_SNAPSHOTS = 15
TIMELINE_EVENTS = 15
```

Заменить на:

```python
LLM_MIN_INTERVAL = 8.0         # "лёгкий" throttle: мин. пауза между ambient-LLM-запросами (сек)
# Сколько последних снимков/событий гонки держим в памяти (скользящее окно).
TIMELINE_SNAPSHOTS = 15
TIMELINE_EVENTS = 15

# --- Comment Planner: важность события управляет порогом/очередью/гэпом/прерыванием ---
# (см. docs/superpowers/specs/2026-07-05-comment-planner-importance-design.md)
PLAN_BASE_THRESHOLD = 35.0       # порог "говорить" вне спайка (обычное затишье)
PLAN_SPIKE_THRESHOLD = 65.0      # порог сразу после озвученной фразы
PLAN_THRESHOLD_DECAY_S = 45.0    # за сколько секунд спайк линейно спадает к базе
PLAN_STALE_S = 20.0              # старше этого в очереди + importance < PLAN_STALE_IMPORTANCE -> пропуск
PLAN_STALE_IMPORTANCE = 70       # порог важности, ниже которого работает вытеснение по staleness
PLAN_GAP_SKIP_THRESHOLD = 90     # importance >= это -> MIN_COMMENT_GAP игнорируется целиком
PLAN_GAP_HALF_THRESHOLD = 80     # importance в [80, 90) -> гэп режется вдвое
PLAN_INTERRUPT_THRESHOLD = 90    # importance >= это -> voice.say(priority="critical")
```

- [ ] **Step 4: `core/engine.py` — импорты**

Найти:

```python
from commentator.brain import Commentator
from commentator.ai_provider import AIProvider
from commentator.timeline import RaceTimeline
from commentator import story as _story
```

Заменить на:

```python
from commentator.brain import Commentator
from commentator.ai_provider import AIProvider
from commentator.timeline import RaceTimeline
from commentator import story as _story
from commentator.planner import PlanContext, score_importance, build_plan
```

Найти:

```python
from core.session_guard import SessionGuard
from core.situation_dedup import SituationDedup
```

Заменить на:

```python
from core.session_guard import SessionGuard
from core.situation_dedup import SituationDedup
from core.event_queue import ImportanceQueue
```

- [ ] **Step 5: `core/engine.py` — очередь**

Найти:

```python
        self.event_queue: "queue.Queue[dict]" = queue.Queue()
```

Заменить на:

```python
        self.event_queue = ImportanceQueue()
```

- [ ] **Step 6: `core/engine.py` — `_plan_context()` и `_enqueue_event()`**

Найти конец метода `_should_commentate` (перед комментарием "Task #14"):

```python
        player_pos = self._positions.get(self._player_car_index)
        if player_pos and event.get("event_code") == "OVTK":
            for idx in (event.get("overtaking_idx"), event.get("being_overtaken_idx")):
                other_pos = self._positions.get(idx)
                if other_pos and abs(other_pos - player_pos) <= 2:
                    return True
        return False

    # ------------------------------------------------------------
    # Task #14: адаптивный ambient, cooldown, throttle (чистые методы)
    # ------------------------------------------------------------
```

Заменить на:

```python
        player_pos = self._positions.get(self._player_car_index)
        if player_pos and event.get("event_code") == "OVTK":
            for idx in (event.get("overtaking_idx"), event.get("being_overtaken_idx")):
                other_pos = self._positions.get(idx)
                if other_pos and abs(other_pos - player_pos) <= 2:
                    return True
        return False

    # ------------------------------------------------------------
    # Comment Planner: важность события -> очередь/порог/гэп/прерывание
    # (см. docs/superpowers/specs/2026-07-05-comment-planner-importance-design.md)
    # ------------------------------------------------------------

    def _plan_context(self, event: dict) -> PlanContext:
        """Срез состояния гонки для score_importance() — planner в engine-state
        напрямую не лезет, engine строит контекст по значению."""
        total_laps = getattr(self, "_total_laps", None)
        laps_remaining = (
            total_laps - self._player_lap
            if total_laps and self._player_lap is not None
            else None
        )
        return PlanContext(
            player_involved=self._event_involves(event, self._player_car_index),
            battle=bool(event.get("battle")),
            laps_remaining=laps_remaining,
            session_type=self._session_type,
        )

    def _enqueue_event(self, event: dict) -> None:
        """Единая точка входа в очередь: считает важность ОДИН раз — вызывающие
        места больше не размазывают скоринг. Сбой планировщика не должен уронить
        приложение: нейтральный дефолт 50, событие идёт по сегодняшнему пути."""
        if "importance" not in event:
            try:
                event["importance"] = score_importance(event, self._plan_context(event))
            except Exception:
                _log.warning("score_importance failed for %s",
                             event.get("event_code"), exc_info=True)
                event["importance"] = 50
        event.setdefault("enqueued_at", time.time())
        self.event_queue.put(event)

    # ------------------------------------------------------------
    # Task #14: адаптивный ambient, cooldown, throttle (чистые методы)
    # ------------------------------------------------------------
```

- [ ] **Step 7: Заменить 10 прямых `event_queue.put({...})` на `_enqueue_event({...})`**

Найти (внутри `_update_damage`):

```python
                self.event_queue.put({
                    "event_code": f"DAMAGE_{category.upper()}", "priority": "normal",
                    "phrase": _DAMAGE_PHRASES[category],
                    "color": "#F97316", "driver": ""})
```

Заменить на:

```python
                self._enqueue_event({
                    "event_code": f"DAMAGE_{category.upper()}", "priority": "normal",
                    "phrase": _DAMAGE_PHRASES[category],
                    "color": "#F97316", "driver": ""})
```

Найти (strategy_ai):

```python
                self.event_queue.put({
                    "event_code": _st_code_map.get(strategy_event.type, "STRAT_PIT"),
                    "priority": strategy_event.priority,
                    "driver": "player",
                    "color": "#38BDF8",
                    "strategy_ai_type": strategy_event.type,
                    "strategy_ai_data": {
                        **strategy_event.data,
                        "confidence": strategy_event.confidence,
                        "action": strategy_event.decision.action,
                        "reason": strategy_event.decision.reason,
                    },
                })
```

Заменить на:

```python
                self._enqueue_event({
                    "event_code": _st_code_map.get(strategy_event.type, "STRAT_PIT"),
                    "priority": strategy_event.priority,
                    "driver": "player",
                    "color": "#38BDF8",
                    "strategy_ai_type": strategy_event.type,
                    "strategy_ai_data": {
                        **strategy_event.data,
                        "confidence": strategy_event.confidence,
                        "action": strategy_event.decision.action,
                        "reason": strategy_event.decision.reason,
                    },
                })
```

Найти (race_ai):

```python
                self.event_queue.put({
                    "event_code": _code_map.get(race_event.type, "ATTACK"),
                    "priority": race_event.priority,
                    "driver": race_event.driver,
                    "color": "#E4002B",
                    "race_ai_type": race_event.type,
                    "race_ai_data": {
                        **race_event.data,
                        "confidence": race_event.confidence,
                        "track": track_ctx.to_dict() if track_ctx else None,
                    },
                })
```

Заменить на:

```python
                self._enqueue_event({
                    "event_code": _code_map.get(race_event.type, "ATTACK"),
                    "priority": race_event.priority,
                    "driver": race_event.driver,
                    "color": "#E4002B",
                    "race_ai_type": race_event.type,
                    "race_ai_data": {
                        **race_event.data,
                        "confidence": race_event.confidence,
                        "track": track_ctx.to_dict() if track_ctx else None,
                    },
                })
```

Найти (F1_BENCH):

```python
            self.event_queue.put({
                "event_code": "F1_BENCH", "priority": "normal",
                "phrase": self.f1_benchmark.pb_line(cmp, player_name),
                "color": "#34D399", "driver": ""})
```

Заменить на:

```python
            self._enqueue_event({
                "event_code": "F1_BENCH", "priority": "normal",
                "phrase": self.f1_benchmark.pb_line(cmp, player_name),
                "color": "#34D399", "driver": ""})
```

Найти (F1_SECTOR_BENCH):

```python
                self.event_queue.put({
                    "event_code": "F1_SECTOR_BENCH", "priority": "normal",
                    "phrase": self.f1_benchmark.sector_pb_line(best_n, cmp["sectors"][best_n]),
                    "color": "#34D399", "driver": ""})
```

Заменить на:

```python
                self._enqueue_event({
                    "event_code": "F1_SECTOR_BENCH", "priority": "normal",
                    "phrase": self.f1_benchmark.sector_pb_line(best_n, cmp["sectors"][best_n]),
                    "color": "#34D399", "driver": ""})
```

Найти (CAREER_PB):

```python
            self.event_queue.put({
                "event_code": "CAREER_PB", "priority": "normal",
                "phrase": self.career_memory.pb_line(cmp),
                "color": "#60A5FA", "driver": ""})
```

Заменить на:

```python
            self._enqueue_event({
                "event_code": "CAREER_PB", "priority": "normal",
                "phrase": self.career_memory.pb_line(cmp),
                "color": "#60A5FA", "driver": ""})
```

Найти (CAREER_SECTOR_PB):

```python
                self.event_queue.put({
                    "event_code": "CAREER_SECTOR_PB", "priority": "normal",
                    "phrase": self.career_memory.sector_pb_line(best_n, cmp["sectors"][best_n]),
                    "color": "#60A5FA", "driver": ""})
```

Заменить на:

```python
                self._enqueue_event({
                    "event_code": "CAREER_SECTOR_PB", "priority": "normal",
                    "phrase": self.career_memory.sector_pb_line(best_n, cmp["sectors"][best_n]),
                    "color": "#60A5FA", "driver": ""})
```

Найти (основной путь событий из `_event_loop`):

```python
            # Адаптивность/cooldown ambient: значимое событие двигает оба механизма.
            if self._is_significant_event(enriched):
                self._note_event_activity(time.time())
            self.event_queue.put(enriched)
```

Заменить на:

```python
            # Адаптивность/cooldown ambient: значимое событие двигает оба механизма.
            if self._is_significant_event(enriched):
                self._note_event_activity(time.time())
            self._enqueue_event(enriched)
```

Найти (ambient tick):

```python
            self.event_queue.put({
                "event_code": "AMBIENT", "priority": "normal",
                "color": "#9CA3AF", "driver": "", "ambient": True,
            })

    # ------------------------------------------------------------
    # Для UI
    # ------------------------------------------------------------
```

Заменить на:

```python
            self._enqueue_event({
                "event_code": "AMBIENT", "priority": "normal",
                "color": "#9CA3AF", "driver": "", "ambient": True,
            })

    # ------------------------------------------------------------
    # Для UI
    # ------------------------------------------------------------
```

Найти (ambient принудительный `fire_highlight`):

```python
        self.event_queue.put({
            "event_code": "AMBIENT", "priority": "normal",
            "color": "#9CA3AF", "driver": "", "ambient": True,
        })
        return True
```

Заменить на:

```python
        self._enqueue_event({
            "event_code": "AMBIENT", "priority": "normal",
            "color": "#9CA3AF", "driver": "", "ambient": True,
        })
        return True
```

- [ ] **Step 8: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_engine_planner.py -q`
Expected: PASS (11 passed)

- [ ] **Step 9: Regression check**

Run: `py -3.12 -m pytest tests/test_engine_damage.py tests/test_engine_f1_benchmark.py tests/test_engine_career_memory.py tests/test_engine_pit_tracking.py tests/test_flashback.py -q`
Expected: PASS, без изменений в счёте (эти тесты читают конкретные ключи события,
например `evt["event_code"]` — новый ключ `evt["importance"]` не ломает их).

- [ ] **Step 10: Checkpoint** — тесты задачи и регрессии зелёные.

---

## Task 4: `core/engine.py` — порог «говорить/молчать» + вытеснение по staleness+importance

**Files:**
- Modify: `core/engine.py`
- Modify: `tests/test_commentary_backlog.py` (переписать — семантика вытеснения меняется)
- Test: `tests/test_engine_planner.py` (дополнить)

- [ ] **Step 1: Write the failing tests**

Добавить в конец `tests/test_engine_planner.py`:

```python
import config


# --------------------------------------------------------------------------- #
# _speak_threshold: динамический порог "говорить/молчать"
# --------------------------------------------------------------------------- #

def test_speak_threshold_spikes_right_after_voicing(engine):
    engine._last_voiced_at = 1000.0
    assert engine._speak_threshold(1000.0) == config.PLAN_SPIKE_THRESHOLD


def test_speak_threshold_decays_to_base_after_full_window(engine):
    engine._last_voiced_at = 1000.0
    result = engine._speak_threshold(1000.0 + config.PLAN_THRESHOLD_DECAY_S)
    assert result == config.PLAN_BASE_THRESHOLD


def test_speak_threshold_midpoint_is_halfway(engine):
    engine._last_voiced_at = 1000.0
    half = config.PLAN_THRESHOLD_DECAY_S / 2
    expected = config.PLAN_SPIKE_THRESHOLD - (
        config.PLAN_SPIKE_THRESHOLD - config.PLAN_BASE_THRESHOLD) * 0.5
    assert engine._speak_threshold(1000.0 + half) == pytest.approx(expected)


def test_speak_threshold_base_when_never_voiced(engine):
    engine._last_voiced_at = 0.0
    assert engine._speak_threshold(time.time()) == config.PLAN_BASE_THRESHOLD
```

Переписать `tests/test_commentary_backlog.py` целиком (семантика меняется: раньше
"устарело" значило "critical vs есть что-то новее в очереди"; теперь — "недостаточно
важное И заждалось на своих собственных часах", независимо от того, что ещё в очереди):

```python
"""Анти-спам: комментатор не должен "утюжить" накопившийся бэклог событий без
пауз, догоняя уже устаревшую ситуацию (core/engine.py::_is_stale_backlog_event).

С Comment Planner (см. docs/superpowers/specs/2026-07-05-comment-planner-importance-design.md)
критерий "устарело" — важность события ниже PLAN_STALE_IMPORTANCE И событие лежит
в очереди дольше PLAN_STALE_S секунд (штамп `enqueued_at`, см. _enqueue_event()).
Раньше было "не critical И в очереди уже ждёт что-то новее" — привязка к qsize()
означала, что ОДНО-единственное событие никогда не считалось устаревшим, сколько
бы оно ни ждало; теперь у каждого события есть собственные "часы".

Bug (истрия проблемы): MIN_COMMENT_GAP=4.0 + неограниченная очередь без сброса
устаревших событий давали почти непрерывную озвучку в насыщенной гонке.
"""
import time

import pytest

import core.engine as eng_mod
from core.engine import F1Engine
import config


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def test_low_importance_event_is_stale_after_ttl(engine):
    now = 1000.0
    event = {"event_code": "OVTK", "importance": 50,
             "enqueued_at": now - config.PLAN_STALE_S - 1}
    assert engine._is_stale_backlog_event(event, now) is True


def test_low_importance_event_is_not_stale_within_ttl(engine):
    now = 1000.0
    event = {"event_code": "OVTK", "importance": 50, "enqueued_at": now - 1}
    assert engine._is_stale_backlog_event(event, now) is False


def test_high_importance_event_is_never_stale(engine):
    now = 1000.0
    event = {"event_code": "PENA", "importance": 90,
             "enqueued_at": now - config.PLAN_STALE_S - 100}
    assert engine._is_stale_backlog_event(event, now) is False


def test_importance_exactly_at_stale_threshold_is_not_stale(engine):
    now = 1000.0
    event = {"event_code": "OVTK", "importance": config.PLAN_STALE_IMPORTANCE,
             "enqueued_at": now - config.PLAN_STALE_S - 100}
    assert engine._is_stale_backlog_event(event, now) is False


def test_missing_importance_defaults_to_50_and_can_go_stale(engine):
    now = 1000.0
    event = {"event_code": "OVTK", "enqueued_at": now - config.PLAN_STALE_S - 1}
    assert engine._is_stale_backlog_event(event, now) is True


def test_missing_enqueued_at_is_treated_as_epoch_and_is_stale(engine):
    # событие без enqueued_at (не прошло через _enqueue_event) - консервативно
    # трактуем как "давно в очереди", а не как "только что положили".
    event = {"event_code": "OVTK", "importance": 50}
    assert engine._is_stale_backlog_event(event, time.time()) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_engine_planner.py tests/test_commentary_backlog.py -q`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute '_speak_threshold'`
(и `TypeError: _is_stale_backlog_event() takes 2 positional arguments but 3 were given`)

- [ ] **Step 3: Инициализация `_last_voiced_at`**

Найти:

```python
        self._recent_event_times: deque[float] = deque()  # значимые события для адаптивности
        self._last_significant_event_t: float = 0.0        # старт cooldown ambient
        self._last_ambient_llm_t: float = 0.0              # пол спейсинга ambient-LLM-запросов
        self._timing_lock = threading.Lock()              # защита деки/меток выше
```

Заменить на:

```python
        self._recent_event_times: deque[float] = deque()  # значимые события для адаптивности
        self._last_significant_event_t: float = 0.0        # старт cooldown ambient
        self._last_ambient_llm_t: float = 0.0              # пол спейсинга ambient-LLM-запросов
        self._timing_lock = threading.Lock()              # защита деки/меток выше
        # Comment Planner: момент последней ОЗВУЧЕННОЙ (не просто сгенерированной)
        # фразы -> декей порога "говорить/молчать" (_speak_threshold). Пишется в
        # Task 5, здесь только инициализация, чтобы _speak_threshold был тестируем
        # независимо (см. design spec §"Порог говорить/молчать").
        self._last_voiced_at: float = 0.0
```

- [ ] **Step 4: `_speak_threshold()` — новый метод**

Найти:

```python
    def _is_stale_backlog_event(self, event: dict) -> bool:
        """True если событие не critical и в event_queue уже ждут более свежие
        некритичные события — тогда его нужно молча пропустить, а не проговаривать
        весь накопившийся бэклог подряд без пауз (см. Фикс 1 CONTEXT.md)."""
        return event.get("priority") != "critical" and self.event_queue.qsize() > 0
```

Заменить на:

```python
    def _speak_threshold(self, now: float) -> float:
        """Динамический порог 'говорить/молчать' по важности: сразу после
        озвученной фразы подскакивает, линейно спадает к базе за
        PLAN_THRESHOLD_DECAY_S секунд. НЕ применяется к AMBIENT — у него свой
        адаптивный каданс (_ambient_loop, Task #14); второй фильтр поверх задушил
        бы его насмерть (см. design spec — сознательное исключение)."""
        elapsed = now - self._last_voiced_at
        if elapsed >= config.PLAN_THRESHOLD_DECAY_S:
            return config.PLAN_BASE_THRESHOLD
        span = config.PLAN_SPIKE_THRESHOLD - config.PLAN_BASE_THRESHOLD
        return config.PLAN_SPIKE_THRESHOLD - span * (elapsed / config.PLAN_THRESHOLD_DECAY_S)

    def _is_stale_backlog_event(self, event: dict, now: float) -> bool:
        """True если событие недостаточно важно И заждалось в очереди на СВОИХ
        собственных часах (enqueued_at) — тогда его нужно молча пропустить, а не
        проговаривать весь накопившийся бэклог подряд без пауз (см. Фикс 1
        CONTEXT.md). Важные события (>= PLAN_STALE_IMPORTANCE) не вытесняются
        никогда, сколько бы ни ждали."""
        importance = event.get("importance", 50)
        if importance >= config.PLAN_STALE_IMPORTANCE:
            return False
        age = now - event.get("enqueued_at", 0.0)
        return age > config.PLAN_STALE_S
```

- [ ] **Step 5: Порог в `_commentary_loop` (перед backlog-drop)**

Найти:

```python
    def _commentary_loop(self):
        last_speak_time = 0.0

        while True:
            event = self.event_queue.get()

            if self._is_paused():
                continue

            # ── Backlog drop: если новые некритичные события уже ждут в очереди,
            # это событие устарело — не проговариваем весь бэклог подряд без пауз,
            # а сразу переходим к самому свежему. Critical всегда проговаривается.
            if self._is_stale_backlog_event(event):
                continue
```

Заменить на:

```python
    def _commentary_loop(self):
        last_speak_time = 0.0

        while True:
            event = self.event_queue.get()

            if self._is_paused():
                continue

            now = time.time()

            # ── Порог "говорить/молчать" по важности: ниже порога вообще не
            # вызываем LLM (экономия Yandex API), только помечаем в ленте как
            # muted. AMBIENT исключён — у него свой адаптивный каданс.
            if (not event.get("ambient")
                    and event.get("importance", 50) < self._speak_threshold(now)):
                with self.state_lock:
                    self.state["feed"].insert(0, {
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "event_code": event.get("event_code", ""),
                        "phrase": event.get("description", event.get("event_code", "")),
                        "color": event.get("color", "#9CA3AF"),
                        "driver": event.get("driver", ""),
                        "muted": True,
                        "channel": "commentary",
                    })
                    self.state["feed"] = self.state["feed"][:config.MAX_FEED_ITEMS]
                continue

            # ── Backlog drop: событие недостаточно важно и заждалось в очереди —
            # не проговариваем весь накопившийся бэклог подряд без пауз, а сразу
            # переходим к самому свежему. Важные события никогда не вытесняются.
            if self._is_stale_backlog_event(event, now):
                continue
```

- [ ] **Step 6: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_engine_planner.py tests/test_commentary_backlog.py -q`
Expected: PASS (15 + 6 = 21 passed)

- [ ] **Step 7: Regression check**

Run: `py -3.12 -m pytest tests/test_flashback.py tests/test_engine_ambient.py -q`
Expected: PASS, без изменений в счёте.

- [ ] **Step 8: Checkpoint** — тесты задачи и регрессии зелёные.

---

## Task 5: `core/engine.py` — гэп и прерывание по важности

**Files:**
- Modify: `core/engine.py`

- [ ] **Step 1: Write the failing tests**

Добавить в конец `tests/test_engine_planner.py`:

```python
# --------------------------------------------------------------------------- #
# Гэп/прерывание по важности — покрыто через _speak_threshold/config константы
# напрямую (сам _commentary_loop не юнит-тестируется — бесконечный цикл с
# блокирующим get(), как и раньше в этом файле; см. Task 5 плана — код-ревью
# диффа, тот же подход, что и для SSTA-сброса в Damage plan).
# --------------------------------------------------------------------------- #

def test_gap_skip_and_interrupt_thresholds_share_same_value():
    """Design invariant: importance >= 90 должно одновременно (а) обнулять гэп и
    (б) прерывать текущую озвучку — иначе критические события сегодняшнего дня
    потеряли бы одну из двух гарантий. Обе константы обязаны совпадать."""
    assert config.PLAN_GAP_SKIP_THRESHOLD == config.PLAN_INTERRUPT_THRESHOLD == 90


def test_gap_half_threshold_is_below_skip_threshold():
    assert config.PLAN_GAP_HALF_THRESHOLD < config.PLAN_GAP_SKIP_THRESHOLD
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_engine_planner.py -q`
Expected: PASS уже сейчас (константы добавлены в Task 3) — этот шаг просто
фиксирует инвариант ДО того, как ниже меняется код, который на него полагается.
Если что-то из этого упадёт — стоп, сверить значения констант в `config.py`
перед тем, как продолжать Step 3.

- [ ] **Step 3: Implement — гэп и прерывание по важности**

Найти:

```python
            should_voice = self._should_voice(event)

            if should_voice and event.get("priority") != "critical":
                min_gap = self._get_setting("min_comment_gap", config.MIN_COMMENT_GAP)
                wait = min_gap - (time.time() - last_speak_time)
                if wait > 0:
                    time.sleep(wait)

            with self.state_lock:
                self.state["now_speaking"] = phrase if should_voice else ""
                self.state["speaking"] = should_voice
                self.state["feed"].insert(0, {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "event_code": event["event_code"],
                    "phrase": phrase,
                    "color": event.get("color", "#9CA3AF"),
                    "driver": event.get("driver", ""),
                    "muted": not should_voice,
                    "channel": channel,
                })
                self.state["feed"] = self.state["feed"][:config.MAX_FEED_ITEMS]

            if should_voice:
                priority = "critical" if event.get("priority") == "critical" else "normal"
                self.voice.say(phrase, priority=priority)

            with self.state_lock:
                self.state["speaking"] = False
                self.state["now_speaking"] = ""

            last_speak_time = time.time()
```

Заменить на:

```python
            should_voice = self._should_voice(event)
            importance = event.get("importance", 50)

            if should_voice and importance < config.PLAN_GAP_SKIP_THRESHOLD:
                min_gap = self._get_setting("min_comment_gap", config.MIN_COMMENT_GAP)
                if importance >= config.PLAN_GAP_HALF_THRESHOLD:
                    min_gap = min_gap / 2
                wait = min_gap - (time.time() - last_speak_time)
                if wait > 0:
                    time.sleep(wait)

            with self.state_lock:
                self.state["now_speaking"] = phrase if should_voice else ""
                self.state["speaking"] = should_voice
                self.state["feed"].insert(0, {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "event_code": event["event_code"],
                    "phrase": phrase,
                    "color": event.get("color", "#9CA3AF"),
                    "driver": event.get("driver", ""),
                    "muted": not should_voice,
                    "channel": channel,
                })
                self.state["feed"] = self.state["feed"][:config.MAX_FEED_ITEMS]

            if should_voice:
                voice_priority = ("critical" if importance >= config.PLAN_INTERRUPT_THRESHOLD
                                  else "normal")
                self.voice.say(phrase, priority=voice_priority)
                self._last_voiced_at = time.time()

            with self.state_lock:
                self.state["speaking"] = False
                self.state["now_speaking"] = ""

            last_speak_time = time.time()
```

**Важно (инвариант сохранения поведения):** любое событие с
`event.get("priority") == "critical"` получает `importance` не ниже 90
(`score_importance`, Task 1) и `PLAN_GAP_SKIP_THRESHOLD == PLAN_INTERRUPT_THRESHOLD
== 90` (Task 3) — то есть гэп и прерывание для сегодняшних critical-событий ведут
себя байт-в-байт так же, как до этого плана. Изменилось только то, что ТЕПЕРЬ
некритические, но важные события (например, обгон с игроком, importance 80)
тоже получают половинный гэп — то, чего раньше не было.

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_engine_planner.py -q`
Expected: PASS (17 passed)

- [ ] **Step 5: Regression check**

Run: `py -3.12 -m pytest tests/test_engine_voice.py tests/test_engine_health.py tests/test_engine_settings.py -q`
Expected: PASS, без изменений в счёте.

- [ ] **Step 6: Checkpoint** — тесты задачи и регрессии зелёные.

---

## Task 6: `commentator/brain.py` + `commentator/personas.py` — план управляет темой LLM

**Files:**
- Modify: `commentator/brain.py`
- Modify: `commentator/personas.py`
- Modify: `core/engine.py`
- Test: `tests/test_brain.py` (дополнить)
- Test: `tests/test_personas.py` (дополнить)

- [ ] **Step 1: Write the failing tests**

Добавить в конец `tests/test_brain.py`:

```python
from commentator.planner import CommentPlan


def test_plan_directive_is_composed_first_and_overrides_topic_choice():
    ai = FakeAI(result="сфокусированная фраза")
    plan = CommentPlan(focus="атака: Норрис и Пиастри", reaction="атака",
                        length="короткая ударная", emotion="на пределе",
                        importance=90, must_mention=("Норрис", "Пиастри"))
    out = Commentator(ai, "tv").create(
        {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри"},
        "СИТУАЦИЯ: старый контекст про другую драму", ai_ok=True, plan=plan)
    assert out == "сфокусированная фраза"

    composed_context = ai.calls[0][0]
    assert "ЗАДАЧА" in composed_context
    assert "атака: Норрис и Пиастри" in composed_context
    assert "Норрис" in composed_context and "Пиастри" in composed_context
    # директива обязана идти ПЕРВЫМ блоком, до старого таймлайна
    assert composed_context.index("ЗАДАЧА") < composed_context.index("старый контекст")


def test_create_without_plan_behaves_as_before():
    ai = FakeAI(result="фраза без плана")
    out = Commentator(ai, "tv").create(
        {"event_code": "OVTK", "driver": "Леклер"}, "ctx", ai_ok=True, plan=None)
    assert out == "фраза без плана"
    assert "ЗАДАЧА" not in ai.calls[0][0]


def test_plan_without_must_mention_omits_that_line():
    ai = FakeAI(result="фраза")
    plan = CommentPlan(focus="старт", reaction="старт", length="обычная",
                        emotion="оживлённо", importance=70, must_mention=())
    Commentator(ai, "tv").create({"event_code": "SSTA"}, "ctx", ai_ok=True, plan=plan)
    assert "Обязательно упомяни" not in ai.calls[0][0]
```

Добавить в конец `tests/test_personas.py`:

```python
def test_output_contract_gives_precedence_to_task_directive():
    out = system_prompt("tv")
    assert "ЗАДАЧА" in out
    assert "ПРИОРИТЕТНАЯ" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_brain.py tests/test_personas.py -q`
Expected: FAIL — `TypeError: create() got an unexpected keyword argument 'plan'`
(и `assert 'ЗАДАЧА' in out` падает — директивы в контракте ещё нет)

- [ ] **Step 3: `commentator/brain.py` — `create()`/`_compose()` принимают `plan`**

Найти:

```python
from commentator import templates
from commentator.ai_provider import AIProvider
from commentator.memory import PhraseMemory
```

Заменить на:

```python
from commentator import templates
from commentator.ai_provider import AIProvider
from commentator.memory import PhraseMemory
from commentator.planner import CommentPlan
```

Найти:

```python
    def create(self, event: dict | None, context: str = "", ai_ok: bool = True) -> str:
        """Сгенерировать реплику на событие с учётом полного контекста гонки.

        event — спровоцировавшее событие (или {'event_code': 'AMBIENT'} для тика);
        context — рендер RaceTimeline; ai_ok — здоров ли Yandex (health-monitor)."""
        code = (event or {}).get("event_code", "")
        if self.ai.available and ai_ok:
            phrase = self.ai.generate(self._compose(context, event), self.persona)
```

Заменить на:

```python
    def create(self, event: dict | None, context: str = "", ai_ok: bool = True,
               plan: CommentPlan | None = None) -> str:
        """Сгенерировать реплику на событие с учётом полного контекста гонки.

        event — спровоцировавшее событие (или {'event_code': 'AMBIENT'} для тика);
        context — рендер RaceTimeline; ai_ok — здоров ли Yandex (health-monitor);
        plan — директива Comment Planner (commentator/planner.py): ЧТО и КАК
        комментировать. При plan=None (ambient без триггера, старые вызовы) LLM
        по-прежнему сам выбирает тему — поведение байт-в-байт как раньше."""
        code = (event or {}).get("event_code", "")
        if self.ai.available and ai_ok:
            phrase = self.ai.generate(self._compose(context, event, plan), self.persona)
```

Найти:

```python
    def _compose(self, context: str, event: dict | None) -> str:
        """Собрать финальный контекст для LLM: таймлайн + GP-сверка + RAG + анти-повтор."""
        parts: list[str] = []
        if self.analytics_context:
```

Заменить на:

```python
    def _compose(self, context: str, event: dict | None,
                 plan: CommentPlan | None = None) -> str:
        """Собрать финальный контекст для LLM: план (если есть) → таймлайн →
        GP-сверка → RAG → анти-повтор. Директива плана — ПЕРВЫЙ блок: LLM должен
        увидеть ЧТО комментировать раньше, чем старый контекст таймлайна, который
        иначе перетягивает внимание на предыдущую драму (см. design spec)."""
        parts: list[str] = []
        if plan is not None:
            directive = (
                f"ЗАДАЧА: прокомментируй ИМЕННО это: {plan.focus}.\n"
                f"Тип реакции: {plan.reaction}. Стиль: {plan.length}, {plan.emotion}."
            )
            if plan.must_mention:
                directive += f"\nОбязательно упомяни: {', '.join(plan.must_mention)}."
            directive += "\nОстальной контекст ниже — только фон, НЕ пересказывай его."
            parts.append(directive)
        if self.analytics_context:
```

- [ ] **Step 4: `commentator/personas.py` — контракт уступает директиве**

Найти:

```python
_OUTPUT_CONTRACT = (
    "\n\nКАК РАБОТАТЬ:\n"
    "- Тебе дают сырой контекст гонки (ситуация, динамика, отрывы, шины, лента событий). "
    "САМ реши, что СЕЙЧАС важнее всего для пилота или зрителя, и скажи только об этом.\n"
    "- Веди репортаж как ЖИВАЯ текстовая трансляция f1news.ru: коротко, по делу, в темпе "
```

Заменить на:

```python
_OUTPUT_CONTRACT = (
    "\n\nКАК РАБОТАТЬ:\n"
    "- Если в начале контекста есть блок «ЗАДАЧА: прокомментируй ИМЕННО это: ...» — "
    "это ПРИОРИТЕТНАЯ инструкция: комментируй СТРОГО указанную тему, тип реакции и "
    "стиль из этого блока, НЕ выбирай другую тему из остального контекста (он там — "
    "только фон, не пересказывай его).\n"
    "- Если блока «ЗАДАЧА» НЕТ (например, спокойный ambient-тик без триггера) — "
    "тебе дают сырой контекст гонки (ситуация, динамика, отрывы, шины, лента событий). "
    "САМ реши, что СЕЙЧАС важнее всего для пилота или зрителя, и скажи только об этом.\n"
    "- Веди репортаж как ЖИВАЯ текстовая трансляция f1news.ru: коротко, по делу, в темпе "
```

- [ ] **Step 5: `core/engine.py` — вызов `build_plan()` на единственном реальном пути LLM**

Найти:

```python
                elif broadcast_on and event.get("race_ai_type"):
                    phrase = self.commentator.create_broadcast(
                        event, ai_ok=self._yandex_healthy)
                else:
                    phrase = self.commentator.create(
                        event, self._build_ai_context(event), ai_ok=self._yandex_healthy)
```

Заменить на:

```python
                elif broadcast_on and event.get("race_ai_type"):
                    phrase = self.commentator.create_broadcast(
                        event, ai_ok=self._yandex_healthy)
                else:
                    try:
                        plan = build_plan(event, event.get("importance", 50),
                                           self.commentator.persona)
                    except Exception:
                        _log.warning("build_plan failed for %s",
                                     event.get("event_code"), exc_info=True)
                        plan = None
                    phrase = self.commentator.create(
                        event, self._build_ai_context(event), ai_ok=self._yandex_healthy,
                        plan=plan)
```

**Примечание по покрытию тестами:** этот конкретный вызов внутри `_commentary_loop`
(бесконечный цикл с блокирующим `event_queue.get()`) в этой кодовой базе не имеет
прецедента прямого юнит-теста — как и остальные ветки того же метода (сброс на
SSTA, порядок каналов). Корректность проверяется чтением диффа при код-ревью, тем
же способом, что и раньше в этом файле; `build_plan()` и `Commentator.create(...,
plan=...)` по отдельности уже покрыты Task 1 и этим Task 6 напрямую. Try/except
вокруг `build_plan()` — та же отказоустойчивость, что и `score_importance()` в
`_enqueue_event()` (Task 3): design spec требует, чтобы сбой планировщика НИКОГДА
не ронял приложение, а деградировал до `plan=None` (LLM выбирает тему сам, как
до этого плана) — проверяется чтением диффа, не отдельным юнит-тестом на
`_commentary_loop`.

- [ ] **Step 6: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_brain.py tests/test_brain_fallback.py tests/test_personas.py -q`
Expected: PASS (все тесты обоих файлов, включая новые)

- [ ] **Step 7: Regression check**

Run: `py -3.12 -m pytest tests/test_engine_ambient.py tests/test_engine_voice.py tests/test_engine_story.py -q`
Expected: PASS, без изменений в счёте.

- [ ] **Step 8: Checkpoint** — тесты задачи и регрессии зелёные.

---

## Task 7: Полная верификация + CONTEXT.md

**Files:**
- Modify: `CONTEXT.md`

- [ ] **Step 1: Полный прогон тестов**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: все тесты проходят. Новые тесты этого плана: 24 (planner) + 6
(event_queue) + 17 (engine_planner, накопительно по Task 3/4/5) + 6
(commentary_backlog, переписан) + 3 (brain) + 1 (personas) = +57 к бейслайну
808 passed / 1 skipped на момент старта этой фичи (см. CONTEXT.md, сессия
2026-07-05 Damage/Collision). Точное итоговое число — по факту прогона, а не
арифметикой (в проекте бывают параллельные сессии, меняющие бейслайн — см.
находку в CONTEXT.md про Pit-Stop Fix). Если итоговая строка не пропечаталась —
считать через `grep -o '[.sF]' <лог> | sort | uniq -c`.

- [ ] **Step 2: Import smoke test**

Run: `py -3.12 -c "import core.engine, core.event_queue, commentator.planner, commentator.brain, commentator.personas"`
Expected: без ошибок

- [ ] **Step 3: Обновить CONTEXT.md**

Прочитать текущий `CONTEXT.md` целиком, следовать существующей структуре/конвенции
(~100-пунктовый лимит + архивация старейшей из последних трёх сессий). Добавить
запись новой сессии: что сделано (6 задач — planner, event_queue, engine-очередь,
engine-порог/staleness, engine-гэп/прерывание, brain/personas), новый
тест-бейслайн (реальное число из Step 1). Явно зафиксировать:

- Важность события (`event["importance"]`, 0-100) — новое поле, живёт РЯДОМ с
  `event["priority"]` ("critical"/"normal"), НЕ заменяет его. `priority` по-прежнему
  управляет `SituationDedup`/session guard/flashback-тишиной (не тронуты этим
  планом) — только гэп, прерывание, порог и порядок очереди теперь читают
  `importance`, а не `priority`.
- Все сегодняшние `CRITICAL_EVENTS` (`PENA`, `RTMT`, `CHQF`, `RCWN`, `COLL`)
  получают `importance` не ниже 90 (`score_importance`, `max(score, 90)` при
  `priority == "critical"`) — их гарантии (мгновенный гэп, прерывание текущей
  озвучки, иммунитет к вытеснению по staleness) сохранены байт-в-байт.
  `PLAN_GAP_SKIP_THRESHOLD == PLAN_INTERRUPT_THRESHOLD == 90` — если когда-нибудь
  захочется развести эти два порога, держать в уме, что это осознанно совпадающие
  значения ради этой гарантии, не случайность.
- `queue.Queue` заменена на `core.event_queue.ImportanceQueue` — dict-интерфейс
  (`put`/`get`/`get_nowait`/`empty`/`qsize`) идентичен снаружи, сортировка по
  важности внутри. Прямые `engine.event_queue.put({...})` в тестах (без
  `importance`) продолжают работать — дефолт 50.
- LLM больше не выбирает ТЕМУ реплики сам, если есть `CommentPlan` — Python решает
  через `build_plan()`, LLM только формулирует текст по директиве "ЗАДАЧА: ...".
  Это НЕ новый слой дедупа поверх `SituationDedup` (пользователь/CONTEXT.md
  такое запрещали) — это чинит корень (рассинхрон триггер↔фраза), `SituationDedup`
  не тронут и продолжает работать как отдельный, независимый анти-спам слой.
  `plan=None` (ambient без реального триггера, обратная совместимость) — LLM
  ведёт себя как раньше, "сам решает".
- `_is_stale_backlog_event` изменил СИГНАТУРУ (добавлен обязательный `now`) и
  СЕМАНТИКУ (важность+собственный возраст, а не "qsize() > 0") —
  `tests/test_commentary_backlog.py` переписан целиком, это осознанное решение
  из спеки, не поломанный тест.
- Следующие циклы (по спеке, НЕ в этом плане): режим последних кругов/атак,
  «гоночная память» кто-кого-атаковал, расширение phrase bank.

- [ ] **Step 4: Checkpoint** — полный прогон зелёный, CONTEXT.md обновлён.
