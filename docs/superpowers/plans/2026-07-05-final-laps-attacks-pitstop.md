# Final Laps / Attacks / Pit-Exit Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make final-lap moments and battles-for-position sound short, dense, and urgent regardless of their raw importance score, and give the commentator a real voice line when the player exits the pits (something F1 25 doesn't send as a discrete event today).

**Architecture:** One shared "force urgent style" check inside `commentator/planner.py::build_plan()` — reused by both the final-laps case (`event["laps_remaining"] <= 3`, the same threshold already used for scoring) and the battle case (`event.get("battle")`) — forces short length + top-tier emotion before the persona shift is applied, and folds an explicit phase marker into the LLM directive text. `core/engine.py::_enqueue_event()` gains one more stashed field (`laps_remaining`) alongside the existing `importance`/`enqueued_at`, computed once and read by `build_plan()` later. A new edge-triggered detector (`_maybe_announce_pit_exit`) watches the existing `pit_status` telemetry field for a 1/2→0 transition during a race and fires a new `PIT_EXIT` event through the existing `_enqueue_event()` funnel — same pattern already used for `DAMAGE_*`.

**Tech Stack:** Python 3.12, standard library, pytest. No frontend changes in this plan.

> ⚠️ **Репозиторий НЕ под git** (`Is a git repository: false`). Шаги «Commit» заменены на **Checkpoint** — прогон тестов задачи. Команды тестов: `py -3.12 -m pytest ... -q`.

**Спека:** [`docs/superpowers/specs/2026-07-05-final-laps-attacks-pitstop-design.md`](../specs/2026-07-05-final-laps-attacks-pitstop-design.md).

---

## Файловая структура

| Файл | Действие | Ответственность |
|------|----------|-----------------|
| `commentator/planner.py` | изменить | `build_plan()` — принудительная краткость/эмоция для финальных кругов и атак; `_BASE_IMPORTANCE`/`_REACTION_BY_CODE` — запись `PIT_EXIT` |
| `core/engine.py` | изменить | `_enqueue_event()` — проставляет `laps_remaining`; новый `_maybe_announce_pit_exit()` + вызов из `_telemetry_loop` |
| `tests/test_planner.py` | изменить | тесты на forced-urgent + `PIT_EXIT` reaction/focus |
| `tests/test_engine_planner.py` | изменить | тесты на проставление `laps_remaining` |
| `tests/test_engine_pit_exit.py` | создать | детекция `PIT_EXIT`: переход, фильтр по сессии, без повторов |
| `CONTEXT.md` | изменить | запись новой сессии |

---

## Task 1: `commentator/planner.py` — принудительная краткость/эмоция + `PIT_EXIT`

**Files:**
- Modify: `commentator/planner.py`
- Modify: `tests/test_planner.py`

- [ ] **Step 1: Write the failing tests**

Добавить в конец `tests/test_planner.py`:

```python
# --------------------------------------------------------------------------- #
# build_plan: принудительная краткость/эмоция (последние круги / атака)
# --------------------------------------------------------------------------- #

def test_build_plan_final_laps_forces_short_length_even_at_low_importance():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б", "laps_remaining": 2}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.length == "короткая ударная"
    assert plan.emotion == "на пределе"


def test_build_plan_battle_forces_short_length_even_at_low_importance():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б", "battle": True}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.length == "короткая ударная"
    assert plan.emotion == "на пределе"


def test_build_plan_final_laps_and_battle_both_still_force_urgent():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б",
             "laps_remaining": 1, "battle": True}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.length == "короткая ударная"
    assert plan.emotion == "на пределе"


def test_build_plan_neither_final_laps_nor_battle_uses_normal_scale():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б", "laps_remaining": 10}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.length == "обычная"
    assert plan.emotion == "оживлённо"


def test_build_plan_final_laps_marker_in_focus_not_in_reaction_field():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри", "laps_remaining": 2}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака (последние 2 круга гонки): Норрис и Пиастри"
    assert plan.reaction == "атака"          # категория остаётся чистой, без маркера


def test_build_plan_battle_without_final_laps_has_no_marker_in_focus():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри", "battle": True}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака: Норрис и Пиастри"     # без маркера кругов


def test_build_plan_forced_urgent_calm_persona_never_reaches_top_emotion():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б", "battle": True}
    plan = build_plan(event, importance=50, persona="calm")
    assert plan.emotion == "оживлённо"     # -1 от "на пределе", не доходит до максимума


def test_build_plan_forced_urgent_hype_persona_stays_at_top():
    event = {"event_code": "OVTK", "driver": "А", "target": "Б", "battle": True}
    plan = build_plan(event, importance=50, persona="hype")
    assert plan.emotion == "на пределе"    # уже на верху, +1 не уходит за пределы


def test_build_plan_final_laps_does_not_force_urgent_above_threshold():
    """laps_remaining=4 не должен срабатывать — порог тот же, что и в
    score_importance (<=3), не отдельная константа."""
    event = {"event_code": "OVTK", "driver": "А", "target": "Б", "laps_remaining": 4}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.length == "обычная"
    assert "последние" not in plan.focus


# --------------------------------------------------------------------------- #
# build_plan: PIT_EXIT
# --------------------------------------------------------------------------- #

def test_build_plan_pit_exit_focus_with_tyre_compound():
    event = {"event_code": "PIT_EXIT", "tyre_compound": "M"}
    plan = build_plan(event, importance=60, persona="tv")
    assert plan.focus == "выезд из боксов: свежий комплект M"
    assert plan.reaction == "выезд из боксов"
    assert plan.must_mention == ()


def test_build_plan_pit_exit_focus_without_tyre_compound():
    event = {"event_code": "PIT_EXIT", "tyre_compound": None}
    plan = build_plan(event, importance=60, persona="tv")
    assert plan.focus == "выезд из боксов"


def test_build_plan_pit_exit_in_final_laps_gets_marker_too():
    """PIT_EXIT не обходит общий механизм срочности стороной — focus_reaction
    общий для всех веток построения focus, включая tyre_compound-ветку."""
    event = {"event_code": "PIT_EXIT", "tyre_compound": "S", "laps_remaining": 1}
    plan = build_plan(event, importance=60, persona="tv")
    assert plan.focus == "выезд из боксов (последние 1 круга гонки): свежий комплект S"
    assert plan.length == "короткая ударная"


def test_score_base_table_pit_exit():
    assert score_importance({"event_code": "PIT_EXIT"}, _CTX) == 60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_planner.py -q`
Expected: FAIL — `AssertionError` на всех новых тестах (текущий `build_plan()` не
знает про `laps_remaining`/`tyre_compound`, `PIT_EXIT` нет в таблицах)

- [ ] **Step 3: `_BASE_IMPORTANCE`/`_REACTION_BY_CODE` — запись `PIT_EXIT`**

Найти:

```python
    "FLBK": 25,
    "AMBIENT": 20,
}
_DEFAULT_IMPORTANCE = 50
```

Заменить на:

```python
    "FLBK": 25,
    "AMBIENT": 20,
    "PIT_EXIT": 60,
}
_DEFAULT_IMPORTANCE = 50
```

Найти:

```python
    "FLBK": "ремарка",
    "AMBIENT": "разбор",
}
_DEFAULT_REACTION = "ремарка"
```

Заменить на:

```python
    "FLBK": "ремарка",
    "AMBIENT": "разбор",
    "PIT_EXIT": "выезд из боксов",
}
_DEFAULT_REACTION = "ремарка"
```

- [ ] **Step 4: `build_plan()` — принудительная краткость/эмоция + `PIT_EXIT` focus**

Найти:

```python
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

Заменить на:

```python
def build_plan(event: dict, importance: int, persona: str) -> CommentPlan:
    """Строит директиву для LLM. Вызывать ПОСЛЕ entity resolution — driver/target
    в event должны быть уже резолвнутыми именами (см. _commentary_loop в
    core/engine.py: entity resolution идёт раньше build_plan() в пайплайне).

    Последние круги (laps_remaining <= _FINAL_LAPS_THRESHOLD, ТОТ ЖЕ порог, что
    и в score_importance — не отдельная константа) и борьба за позицию (battle)
    принудительно делают реплику короткой и эмоциональной НЕЗАВИСИМО от того,
    что дала бы числовая шкала важности — см. design spec
    2026-07-05-final-laps-attacks-pitstop."""
    code = event.get("event_code", "")
    driver = event.get("driver") or ""
    target = event.get("target") or ""
    reaction = _REACTION_BY_CODE.get(code, _DEFAULT_REACTION)
    battle = bool(event.get("battle"))
    laps_remaining = event.get("laps_remaining")
    final_laps = laps_remaining is not None and laps_remaining <= _FINAL_LAPS_THRESHOLD
    force_urgent = final_laps or battle

    # focus_reaction — ЧАСТЬ focus (описательный текст), НЕ plan.reaction
    # (короткая категория для строки "Тип реакции: ..." в brain.py._compose()).
    focus_reaction = reaction
    if final_laps:
        focus_reaction = f"{reaction} (последние {laps_remaining} круга гонки)"

    # tyre_compound — только у PIT_EXIT; идёт первой веткой без риска конфликта
    # с driver/target (PIT_EXIT никогда их не несёт, событие всегда про игрока).
    tyre_compound = event.get("tyre_compound")
    if tyre_compound:
        focus = f"{focus_reaction}: свежий комплект {tyre_compound}"
    elif target:
        focus = f"{focus_reaction}: {driver} и {target}".strip()
    elif driver:
        focus = f"{focus_reaction}: {driver}".strip()
    else:
        focus = focus_reaction

    if force_urgent:
        length = _LENGTH_SHORT
        emotion = _shift_emotion(_EMOTION_LADDER[2], persona)
    else:
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

- [ ] **Step 5: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_planner.py -q`
Expected: PASS (40 passed — 27 из ядра Comment Planner + 13 новых)

- [ ] **Step 6: Checkpoint** — тесты задачи зелёные.

---

## Task 2: `core/engine.py` — `laps_remaining` на событии + детекция `PIT_EXIT`

**Files:**
- Modify: `core/engine.py`
- Modify: `tests/test_engine_planner.py`
- Test: `tests/test_engine_pit_exit.py` (новый)

- [ ] **Step 1: Write the failing tests**

Добавить в конец `tests/test_engine_planner.py`:

```python
def test_enqueue_event_stamps_laps_remaining(engine):
    _drain(engine)
    engine._player_lap = 18
    engine._total_laps = 20
    engine._enqueue_event({"event_code": "OVTK"})
    evt = engine.event_queue.get_nowait()
    assert evt["laps_remaining"] == 2
    engine._player_lap = None
    engine._total_laps = None


def test_enqueue_event_laps_remaining_none_when_unknown(engine):
    _drain(engine)
    engine._player_lap = None
    engine._total_laps = None
    engine._enqueue_event({"event_code": "OVTK"})
    evt = engine.event_queue.get_nowait()
    assert evt["laps_remaining"] is None


def test_enqueue_event_stamps_laps_remaining_even_with_precomputed_importance(engine):
    _drain(engine)
    engine._player_lap = 19
    engine._total_laps = 20
    engine._enqueue_event({"event_code": "OVTK", "importance": 99})
    evt = engine.event_queue.get_nowait()
    assert evt["laps_remaining"] == 1
    assert evt["importance"] == 99
    engine._player_lap = None
    engine._total_laps = None


def test_enqueue_event_falls_back_when_plan_context_fails(engine, monkeypatch):
    _drain(engine)

    def _boom(event):
        raise RuntimeError("boom")

    monkeypatch.setattr(engine, "_plan_context", _boom)
    engine._enqueue_event({"event_code": "OVTK"})
    evt = engine.event_queue.get_nowait()
    assert evt["importance"] == 50
    assert evt["laps_remaining"] is None
```

Создать `tests/test_engine_pit_exit.py`:

```python
"""Выезд из боксов — новое синтетическое событие PIT_EXIT (см. design spec
2026-07-05-final-laps-attacks-pitstop-design.md). Едж-детект перехода
pit_status 1/2 -> 0, только в гонке, без повторного срабатывания — тот же
паттерн проверки, что и в tests/test_engine_damage.py.
"""
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


def test_pit_exit_fires_on_transition_to_zero_in_race(engine):
    _drain(engine)
    engine._session_type = "race"
    engine._player_tyre_compound = "M"
    engine._maybe_announce_pit_exit(1, 0)
    evt = engine.event_queue.get_nowait()
    assert evt["event_code"] == "PIT_EXIT"
    assert evt["tyre_compound"] == "M"


def test_pit_exit_fires_from_either_pit_status_value(engine):
    _drain(engine)
    engine._session_type = "race"
    engine._maybe_announce_pit_exit(2, 0)
    evt = engine.event_queue.get_nowait()
    assert evt["event_code"] == "PIT_EXIT"


def test_pit_exit_does_not_fire_on_entry(engine):
    _drain(engine)
    engine._session_type = "race"
    engine._maybe_announce_pit_exit(0, 1)
    assert engine.event_queue.empty()


def test_pit_exit_does_not_fire_while_already_out(engine):
    _drain(engine)
    engine._session_type = "race"
    engine._maybe_announce_pit_exit(0, 0)
    assert engine.event_queue.empty()


def test_pit_exit_does_not_fire_outside_race(engine):
    _drain(engine)
    engine._session_type = "practice"
    engine._maybe_announce_pit_exit(1, 0)
    assert engine.event_queue.empty()
    engine._session_type = "race"


def test_pit_exit_does_not_refire_without_new_stop(engine):
    _drain(engine)
    engine._session_type = "race"
    engine._maybe_announce_pit_exit(1, 0)
    assert not engine.event_queue.empty()
    _drain(engine)
    engine._maybe_announce_pit_exit(0, 0)
    assert engine.event_queue.empty()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_engine_planner.py tests/test_engine_pit_exit.py -q`
Expected: FAIL — новые тесты `test_enqueue_event_stamps_laps_remaining*`/
`test_enqueue_event_falls_back_when_plan_context_fails` падают (`KeyError:
'laps_remaining'`), весь `tests/test_engine_pit_exit.py` падает —
`AttributeError: 'F1Engine' object has no attribute '_maybe_announce_pit_exit'`

- [ ] **Step 3: `_enqueue_event()` — проставить `laps_remaining`**

Найти:

```python
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
```

Заменить на:

```python
    def _enqueue_event(self, event: dict) -> None:
        """Единая точка входа в очередь: считает важность и laps_remaining ОДИН
        раз — вызывающие места больше не размазывают скоринг. laps_remaining
        нужен build_plan() для режима последних кругов (design spec
        2026-07-05-final-laps-attacks-pitstop). Сбой планировщика не должен
        уронить приложение: нейтральные дефолты, событие идёт по сегодняшнему пути."""
        try:
            ctx = self._plan_context(event)
            event["laps_remaining"] = ctx.laps_remaining
            if "importance" not in event:
                event["importance"] = score_importance(event, ctx)
        except Exception:
            _log.warning("planner failed for %s",
                         event.get("event_code"), exc_info=True)
            event.setdefault("laps_remaining", None)
            event.setdefault("importance", 50)
        event.setdefault("enqueued_at", time.time())
        self.event_queue.put(event)
```

- [ ] **Step 4: `_maybe_announce_pit_exit()` — новый метод**

Найти:

```python
        for category, severity in categories.items():
            if severity >= _DAMAGE_NOTICEABLE_THRESHOLD and not self._damage_announced[category]:
                self._damage_announced[category] = True
                self._enqueue_event({
                    "event_code": f"DAMAGE_{category.upper()}", "priority": "normal",
                    "phrase": _DAMAGE_PHRASES[category],
                    "color": "#F97316", "driver": ""})
            elif severity < _DAMAGE_NOTICEABLE_THRESHOLD:
                self._damage_announced[category] = False

    def _should_commentate(self, event: dict) -> bool:
```

Заменить на:

```python
        for category, severity in categories.items():
            if severity >= _DAMAGE_NOTICEABLE_THRESHOLD and not self._damage_announced[category]:
                self._damage_announced[category] = True
                self._enqueue_event({
                    "event_code": f"DAMAGE_{category.upper()}", "priority": "normal",
                    "phrase": _DAMAGE_PHRASES[category],
                    "color": "#F97316", "driver": ""})
            elif severity < _DAMAGE_NOTICEABLE_THRESHOLD:
                self._damage_announced[category] = False

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
            self._enqueue_event({
                "event_code": "PIT_EXIT", "priority": "normal",
                "driver": "", "color": "#38BDF8",
                "tyre_compound": self._player_tyre_compound,
            })

    def _should_commentate(self, event: dict) -> bool:
```

- [ ] **Step 5: Вызов `_maybe_announce_pit_exit()` из `_telemetry_loop`**

Найти:

```python
                # Отрывы: к машине впереди и к лидеру — из пакета игрока;
                # к машине сзади — gap_front той машины, что на позицию ниже.
                self._player_gap_front = pl.get("gap_front_ms")
                self._player_gap_leader = pl.get("gap_leader_ms")
                self._player_pit_status = pl.get("pit_status")
                if pl.get("pit_status"):
                    self._current_lap_pit = True
```

Заменить на:

```python
                # Отрывы: к машине впереди и к лидеру — из пакета игрока;
                # к машине сзади — gap_front той машины, что на позицию ниже.
                self._player_gap_front = pl.get("gap_front_ms")
                self._player_gap_leader = pl.get("gap_leader_ms")
                _prev_pit_status = self._player_pit_status
                self._player_pit_status = pl.get("pit_status")
                self._maybe_announce_pit_exit(_prev_pit_status, self._player_pit_status)
                if pl.get("pit_status"):
                    self._current_lap_pit = True
```

- [ ] **Step 6: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_engine_planner.py tests/test_engine_pit_exit.py -q`
Expected: PASS (21 passed в test_engine_planner.py — 17 + 4 новых + 6 passed в
test_engine_pit_exit.py = 27 всего)

- [ ] **Step 7: Regression check**

Run: `py -3.12 -m pytest tests/test_engine_damage.py tests/test_engine_pit_tracking.py tests/test_commentary_backlog.py tests/test_flashback.py -q`
Expected: PASS, без изменений в счёте (эти тесты не читают `laps_remaining` —
новый ключ на событии их не ломает; `_prev_pit_status` — новая локальная
переменная в `_telemetry_loop`, не пересекается с существующими атрибутами).

- [ ] **Step 8: Checkpoint** — тесты задачи и регрессии зелёные.

---

## Task 3: Полная верификация + CONTEXT.md

**Files:**
- Modify: `CONTEXT.md`

- [ ] **Step 1: Полный прогон тестов**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: все тесты проходят. Новые тесты этого плана: 13 (planner) + 4
(engine_planner) + 6 (engine_pit_exit) = +23 к бейслайну 865 passed / 1 skipped
на момент старта этой фичи (см. CONTEXT.md, сессия Comment Planner 2026-07-05).
Точное итоговое число — по факту прогона, а не арифметикой (см. документированную
в CONTEXT.md находку про параллельные сессии, меняющие бейслайн). Если итоговая
строка не пропечаталась — считать через `grep -o '[.sF]' <лог> | sort | uniq -c`.

- [ ] **Step 2: Import smoke test**

Run: `py -3.12 -c "import core.engine, commentator.planner"`
Expected: без ошибок

- [ ] **Step 3: Обновить CONTEXT.md**

Прочитать текущий `CONTEXT.md` целиком, следовать существующей структуре/конвенции
(~100-пунктовый лимит, ~3 последние сессии целиком, архивация старейшей из них в
`docs/CONTEXT_ARCHIVE.md` при добавлении новой). Добавить запись новой сессии
(2 задачи — planner.py, engine.py), реальный тест-бейслайн из Step 1. Явно
зафиксировать:

- Финальные круги и атаки используют ОДИН механизм в `build_plan()`
  (`force_urgent`), не два параллельных — оба принудительно дают короткую
  длину и топ эмоции ДО сдвига персоны; `calm` поэтому никогда не доходит до
  «на пределе», даже в решающий момент гонки — это характер персоны, не баг.
- `_FINAL_LAPS_THRESHOLD` (=3) — ОДНА константа на весь Comment Planner
  (уже использовалась в `score_importance`, теперь читается и в `build_plan()`
  через `event["laps_remaining"]`) — специально НЕ заведена вторая одноимённая
  константа с другим порогом.
- `PIT_EXIT` — новое синтетическое событие (как `DAMAGE_*`), детектится
  переходом `pit_status` 1/2→0, только в гонке, без анти-спам флага (edge-detect
  физически не может повториться без нового заезда). Озвучивается ТОЛЬКО выезд,
  не заезд — сознательное сужение объёма.
- Следующие циклы (по спеке, НЕ в этом плане): «гоночная память» кто-кого-атаковал,
  расширение phrase bank; `race_ai` ATTACK/BATTLE (Broadcast Overlay Mode) и заезд
  в боксы — сознательно не тронуты.

- [ ] **Step 4: Checkpoint** — полный прогон зелёный, CONTEXT.md обновлён.
