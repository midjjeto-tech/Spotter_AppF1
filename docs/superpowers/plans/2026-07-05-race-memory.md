# Race Memory (v1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire two facts that already exist in the codebase but never reach the commentator — how many times a pair of drivers has traded overtakes (`RaceState`), and a rival's pace-trend style (`RivalTracker`) — into `build_plan()`'s directive for `OVTK` events, so a real battle can sound like "3rd attempt" and a fading/charging rival gets described as such.

**Architecture:** `RaceState.is_battle()` keeps its exact existing bool contract (zero risk to existing callers), backed internally by a new `_count_recent_overtakes()` that `enrich()` also exposes as `event["battle_count"]`. `RivalTracker` gets one new read-only accessor, `get_style(vehicle_idx)`. `core/engine.py` attaches `driver_style`/`target_style` to `OVTK` events right after `enrich()`. `commentator/planner.py::build_plan()` folds both into `focus` as composable markers/suffixes — no changes to `score_importance()`, this is purely descriptive text for the LLM directive.

**Tech Stack:** Python 3.12, standard library, pytest. No frontend changes in this plan.

> ⚠️ **Репозиторий НЕ под git** (`Is a git repository: false`). Шаги «Commit» заменены на **Checkpoint** — прогон тестов задачи. Команды тестов: `py -3.12 -m pytest ... -q`.

**Спека:** [`docs/superpowers/specs/2026-07-05-race-memory-design.md`](../specs/2026-07-05-race-memory-design.md).

---

## Файловая структура

| Файл | Действие | Ответственность |
|------|----------|-----------------|
| `core/race_state.py` | изменить | `_count_recent_overtakes()` (новый), `is_battle()` — тонкая обёртка (контракт не меняется), `enrich()` — `battle_count` на `OVTK` |
| `core/rivals/tracker.py` | изменить | `get_style()` — новый аксессор |
| `commentator/planner.py` | изменить | `build_plan()` — маркеры (`focus_reaction`) + суффиксы стиля в `focus` |
| `core/engine.py` | изменить | проводка `driver_style`/`target_style` для `OVTK` сразу после `enrich()` |
| `tests/test_race_state.py` | изменить | тесты на `battle_count`, `is_battle()` неизменное поведение |
| `tests/test_rivals.py` | изменить | тесты на `get_style()` |
| `tests/test_planner.py` | изменить | тесты на маркеры/суффиксы |
| `CONTEXT.md` | изменить | запись новой сессии |

---

## Task 1: `core/race_state.py` — счётчик попыток обгона

**Files:**
- Modify: `core/race_state.py`
- Modify: `tests/test_race_state.py`

- [ ] **Step 1: Write the failing tests**

Добавить в конец `tests/test_race_state.py`:

```python
def test_count_recent_overtakes_zero_when_no_history():
    s = _make_state()
    assert s._count_recent_overtakes(3, 7) == 0


def test_count_recent_overtakes_counts_both_directions():
    """Обгон в любую сторону между той же парой считается — пара сравнивается
    как frozenset, направление не важно для счётчика затяжной борьбы."""
    s = _make_state()
    s.record_event({"event_code": "OVTK", "overtaking_idx": 3, "being_overtaken_idx": 7})
    s.record_event({"event_code": "OVTK", "overtaking_idx": 7, "being_overtaken_idx": 3})
    assert s._count_recent_overtakes(3, 7) == 2


def test_count_recent_overtakes_ignores_other_pairs():
    s = _make_state()
    s.record_event({"event_code": "OVTK", "overtaking_idx": 3, "being_overtaken_idx": 7})
    s.record_event({"event_code": "OVTK", "overtaking_idx": 1, "being_overtaken_idx": 2})
    assert s._count_recent_overtakes(3, 7) == 1


def test_is_battle_unchanged_behavior_below_threshold():
    """is_battle() сохраняет свой прежний контракт (bool, порог BATTLE_THRESHOLD=2)
    — это не должно измениться этим планом."""
    s = _make_state()
    s.record_event({"event_code": "OVTK", "overtaking_idx": 3, "being_overtaken_idx": 7})
    assert s.is_battle(3, 7) is False


def test_is_battle_unchanged_behavior_at_threshold():
    s = _make_state()
    s.record_event({"event_code": "OVTK", "overtaking_idx": 3, "being_overtaken_idx": 7})
    s.record_event({"event_code": "OVTK", "overtaking_idx": 7, "being_overtaken_idx": 3})
    assert s.is_battle(3, 7) is True


def test_enrich_overtake_event_includes_battle_count():
    """В реальном _event_loop (core/engine.py) enrich() вызывается ДО
    record_event() для ТЕКУЩЕГО события — то есть battle_count всегда считает
    только ПРЕДЫДУЩИЕ обгоны той же пары, никогда не включает текущий вызов.
    Здесь имитируем это: один прошлый обгон уже записан в history, затем
    enrich() вызывается на "втором" (текущем) обгоне той же пары."""
    s = _make_state()
    s.record_event({"event_code": "OVTK", "overtaking_idx": 3, "being_overtaken_idx": 7})
    out = s.enrich({"event_code": "OVTK", "overtaking_idx": 3, "being_overtaken_idx": 7})
    assert out["battle_count"] == 1


def test_enrich_overtake_event_battle_count_zero_when_no_prior_history():
    s = _make_state()
    out = s.enrich({"event_code": "OVTK", "overtaking_idx": 3, "being_overtaken_idx": 7})
    assert out["battle_count"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_race_state.py -q`
Expected: FAIL — `AttributeError: 'RaceState' object has no attribute '_count_recent_overtakes'`
(и `KeyError: 'battle_count'` на enrich-тестах)

- [ ] **Step 3: Implement `_count_recent_overtakes()` + `is_battle()` обёртка**

Найти:

```python
    def is_battle(self, vehicle_a: int, vehicle_b: int) -> bool:
        """Были ли недавно повторяющиеся обгоны между этими двумя пилотами."""
        pair = frozenset((vehicle_a, vehicle_b))
        count = 0
        for past in self.history:
            if past.get("event_code") != "OVTK":
                continue
            past_pair = frozenset((past.get("overtaking_idx"), past.get("being_overtaken_idx")))
            if past_pair == pair:
                count += 1
        return count >= BATTLE_THRESHOLD
```

Заменить на:

```python
    def _count_recent_overtakes(self, vehicle_a: int, vehicle_b: int) -> int:
        """Сколько раз эта пара пилотов обгоняла друг друга за последние
        HISTORY_SIZE событий (переиспользуется is_battle() и enrich()'ом для
        build_plan() — см. design spec 2026-07-05-race-memory)."""
        pair = frozenset((vehicle_a, vehicle_b))
        count = 0
        for past in self.history:
            if past.get("event_code") != "OVTK":
                continue
            past_pair = frozenset((past.get("overtaking_idx"), past.get("being_overtaken_idx")))
            if past_pair == pair:
                count += 1
        return count

    def is_battle(self, vehicle_a: int, vehicle_b: int) -> bool:
        """Были ли недавно повторяющиеся обгоны между этими двумя пилотами.
        Контракт (bool, порог BATTLE_THRESHOLD) НЕ меняется этим планом —
        подсчёт лишь вынесен в переиспользуемый _count_recent_overtakes()."""
        return self._count_recent_overtakes(vehicle_a, vehicle_b) >= BATTLE_THRESHOLD
```

- [ ] **Step 4: `enrich()` — добавить `battle_count`**

Найти:

```python
        if "overtaking_idx" in event:
            a = self.driver(event["overtaking_idx"])
            b = self.driver(event["being_overtaken_idx"])
            enriched["driver"] = a["name"]
            enriched["team"] = a["team"]
            enriched["color"] = a["color"]
            enriched["target"] = b["name"]
            enriched["target_team"] = b["team"]
            enriched["battle"] = self.is_battle(
                event["overtaking_idx"], event["being_overtaken_idx"]
            )
```

Заменить на:

```python
        if "overtaking_idx" in event:
            a = self.driver(event["overtaking_idx"])
            b = self.driver(event["being_overtaken_idx"])
            enriched["driver"] = a["name"]
            enriched["team"] = a["team"]
            enriched["color"] = a["color"]
            enriched["target"] = b["name"]
            enriched["target_team"] = b["team"]
            enriched["battle_count"] = self._count_recent_overtakes(
                event["overtaking_idx"], event["being_overtaken_idx"]
            )
            enriched["battle"] = enriched["battle_count"] >= BATTLE_THRESHOLD
```

**Важно:** `enriched["battle"]` теперь читает уже посчитанный `battle_count`
вместо повторного вызова `is_battle()` — тот же результат (`is_battle()` сама
делает `_count_recent_overtakes(...) >= BATTLE_THRESHOLD`), но без пересчёта
истории дважды за один `enrich()`.

- [ ] **Step 5: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_race_state.py -q`
Expected: PASS (12 passed — 5 существующих + 7 новых)

- [ ] **Step 6: Checkpoint** — тесты задачи зелёные.

---

## Task 2: `core/rivals/tracker.py` — аксессор стиля соперника

**Files:**
- Modify: `core/rivals/tracker.py`
- Modify: `tests/test_rivals.py`

- [ ] **Step 1: Write the failing tests**

Добавить в конец `tests/test_rivals.py`:

```python
def test_get_style_returns_known_rival_style():
    t = RivalTracker()
    grid = _grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz"))
    t.update(grid, player_vehicle_idx=0)
    assert t.get_style(1) == "consistent"     # дефолт при малой истории (см. _classify_style)


def test_get_style_returns_none_for_unknown_vehicle():
    t = RivalTracker()
    grid = _grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz"))
    t.update(grid, player_vehicle_idx=0)
    assert t.get_style(99) is None


def test_get_style_returns_none_for_player():
    """RivalTracker никогда не профилирует игрока (update() пропускает его
    целиком) — get_style() для игрока всегда None, без специальной проверки."""
    t = RivalTracker()
    grid = _grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz"))
    t.update(grid, player_vehicle_idx=0)
    assert t.get_style(0) is None


def test_get_style_returns_none_for_none_vehicle_idx():
    t = RivalTracker()
    assert t.get_style(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_rivals.py -q`
Expected: FAIL — `AttributeError: 'RivalTracker' object has no attribute 'get_style'`

- [ ] **Step 3: Implement `get_style()`**

Найти:

```python
    def get_state(self) -> dict:
```

Заменить на:

```python
    def get_style(self, vehicle_idx: int | None) -> str | None:
        """Стиль соперника по vehicle_idx, если он уже профилирован (см. update()).
        None — игрок (RivalTracker профилирует всех, КРОМЕ игрока, по конструкции
        update()) или машина ещё не встречалась в этой сессии."""
        if vehicle_idx is None:
            return None
        profile = self._profiles.get(vehicle_idx)
        return profile.style if profile else None

    def get_state(self) -> dict:
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_rivals.py -q`
Expected: PASS (все тесты файла, включая 4 новых)

- [ ] **Step 5: Checkpoint** — тесты задачи зелёные.

---

## Task 3: `commentator/planner.py` — маркеры и суффиксы стиля в `focus`

**Files:**
- Modify: `commentator/planner.py`
- Modify: `tests/test_planner.py`

- [ ] **Step 1: Write the failing tests**

Добавить в конец `tests/test_planner.py`:

```python
# --------------------------------------------------------------------------- #
# build_plan: battle_count и rival style в focus (Race Memory v1)
# --------------------------------------------------------------------------- #

def test_build_plan_battle_count_marker_when_battle_true():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "battle": True, "battle_count": 3}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака (3-я попытка обгона): Норрис и Пиастри"


def test_build_plan_no_battle_count_marker_when_battle_false():
    """battle_count может присутствовать (например 1 — первая попытка, ещё не
    battle), но маркер появляется только когда battle уже True — не дублируем
    порог BATTLE_THRESHOLD внутри planner.py."""
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "battle": False, "battle_count": 1}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака: Норрис и Пиастри"


def test_build_plan_final_laps_and_battle_count_markers_combine():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "battle": True, "battle_count": 3, "laps_remaining": 2}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == ("атака (последние 2 круга гонки, 3-я попытка обгона): "
                          "Норрис и Пиастри")


def test_build_plan_driver_style_suffix():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "driver_style": "charging"}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака: Норрис (в ударе) и Пиастри"


def test_build_plan_target_style_suffix():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "target_style": "fading"}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака: Норрис и Пиастри (теряет темп)"


def test_build_plan_both_style_suffixes_together():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "driver_style": "aggressive", "target_style": "fading"}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака: Норрис (агрессивен) и Пиастри (теряет темп)"


def test_build_plan_consistent_style_produces_no_suffix():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "driver_style": "consistent"}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака: Норрис и Пиастри"


def test_build_plan_missing_style_fields_unaffected():
    """Событие без driver_style/target_style/battle_count (сегодняшний путь —
    DAMAGE_*, PIT_EXIT, и т.п.) ведёт себя как раньше."""
    event = {"event_code": "PIT_EXIT", "tyre_compound": "M"}
    plan = build_plan(event, importance=60, persona="tv")
    assert plan.focus == "выезд из боксов: свежий комплект M"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_planner.py -q`
Expected: FAIL — `AssertionError` на всех 8 новых тестах (текущий `build_plan()`
не знает про `battle_count`/`driver_style`/`target_style`)

- [ ] **Step 3: `build_plan()` — маркеры + суффиксы**

Найти:

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
    2026-07-05-final-laps-attacks-pitstop.

    Race Memory (design spec 2026-07-05-race-memory): battle_count (сколько раз
    эта пара уже обгоняла друг друга) и driver_style/target_style (тренд темпа
    соперника из RivalTracker) — чисто описательные добавки в focus, НЕ новые
    модификаторы важности (score_importance() не меняется)."""
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
    # markers — список фрагментов маркера фазы/истории, объединяются одной парой
    # скобок через запятую (а не (...)(...)), см. design spec.
    markers: list[str] = []
    if final_laps:
        markers.append(f"последние {laps_remaining} круга гонки")
    battle_count = event.get("battle_count", 0)
    if battle and battle_count:   # battle УЖЕ порогует по BATTLE_THRESHOLD — не дублируем здесь
        markers.append(f"{battle_count}-я попытка обгона")
    focus_reaction = f"{reaction} ({', '.join(markers)})" if markers else reaction

    # Суффиксы стиля соперника — привязаны к конкретному имени, не к focus_reaction.
    # "consistent" НАМЕРЕННО отсутствует в _STYLE_PHRASES — незаметный дефолт, не
    # повод для реплики (см. design spec).
    driver_style = event.get("driver_style")
    target_style = event.get("target_style")
    driver_suffix = f" ({_STYLE_PHRASES[driver_style]})" if driver_style in _STYLE_PHRASES else ""
    target_suffix = f" ({_STYLE_PHRASES[target_style]})" if target_style in _STYLE_PHRASES else ""

    # tyre_compound — только у PIT_EXIT; идёт первой веткой без риска конфликта
    # с driver/target (PIT_EXIT никогда их не несёт, событие всегда про игрока).
    tyre_compound = event.get("tyre_compound")
    if tyre_compound:
        focus = f"{focus_reaction}: свежий комплект {tyre_compound}"
    elif target:
        focus = f"{focus_reaction}: {driver}{driver_suffix} и {target}{target_suffix}".strip()
    elif driver:
        focus = f"{focus_reaction}: {driver}{driver_suffix}".strip()
    else:
        focus = focus_reaction
```

- [ ] **Step 4: `_STYLE_PHRASES` — новая таблица**

Найти:

```python
_DEFAULT_REACTION = "ремарка"
```

Заменить на:

```python
_DEFAULT_REACTION = "ремарка"

# Стиль соперника (RivalTracker._classify_style) -> русская фраза-суффикс в
# focus. "consistent" намеренно отсутствует — незаметный дефолт, не повод для
# реплики (design spec 2026-07-05-race-memory).
_STYLE_PHRASES: dict[str, str] = {
    "aggressive": "агрессивен",
    "charging": "в ударе",
    "fading": "теряет темп",
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_planner.py -q`
Expected: PASS (48 passed — 40 из предыдущих циклов + 8 новых)

- [ ] **Step 6: Checkpoint** — тесты задачи зелёные.

---

## Task 4: `core/engine.py` — проводка `driver_style`/`target_style`

**Files:**
- Modify: `core/engine.py`

- [ ] **Step 1: Implement**

Найти:

```python
            enriched = self.race_state.enrich(event)
            self.race_state.record_event(event)
            self._note_story_event(event, enriched)
```

Заменить на:

```python
            enriched = self.race_state.enrich(event)
            if enriched.get("event_code") == "OVTK":
                enriched["driver_style"] = self.rival_tracker.get_style(
                    enriched.get("overtaking_idx"))
                enriched["target_style"] = self.rival_tracker.get_style(
                    enriched.get("being_overtaken_idx"))
            self.race_state.record_event(event)
            self._note_story_event(event, enriched)
```

**Примечание по покрытию тестами:** этот вызов внутри `_event_loop` (там же,
где происходит `enrich()`/`record_event()`/`_note_story_event()`) не имеет
прецедента прямого юнит-теста в этой кодовой базе — корректность уже
подтверждена по отдельности: `RivalTracker.get_style()` (Task 2) и
`build_plan()`'s чтение `driver_style`/`target_style` (Task 3) оба протестированы
изолированно. Соответствие проверяется чтением диффа при код-ревью — тот же
подход, что и для аналогичного одностроч­ного вызова `build_plan()` в
`_commentary_loop` из прошлого цикла.

- [ ] **Step 2: Regression check**

Run: `py -3.12 -m pytest tests/test_race_state.py tests/test_rivals.py tests/test_planner.py tests/test_engine_ambient.py tests/test_flashback.py -q`
Expected: PASS, без изменений в счёте (никакой новый тест этой задачи не
добавляется — только регрессия существующих файлов, чувствительных к
`_event_loop`/`RivalTracker`/`RaceState`).

- [ ] **Step 3: Checkpoint** — регрессия зелёная.

---

## Task 5: Полная верификация + CONTEXT.md

**Files:**
- Modify: `CONTEXT.md`

- [ ] **Step 1: Полный прогон тестов**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: все тесты проходят. Новые тесты этого плана: 7 (race_state) + 4
(rivals) + 8 (planner) = +19 к бейслайну 888 passed / 1 skipped на момент старта
этой фичи (см. CONTEXT.md, сессия «Режим последних кругов/атак/пит-стопов»,
2026-07-05). Точное итоговое число — по факту прогона, а не арифметикой. Если
итоговая строка не пропечаталась — считать через
`grep -o '[.sF]' <лог> | sort | uniq -c`.

- [ ] **Step 2: Import smoke test**

Run: `py -3.12 -c "import core.engine, core.race_state, core.rivals.tracker, commentator.planner"`
Expected: без ошибок

- [ ] **Step 3: Обновить CONTEXT.md**

Прочитать текущий `CONTEXT.md` целиком, следовать существующей структуре/конвенции
(~100-пунктовый лимит, ~3 последние сессии целиком, архивация старейшей из них в
`docs/CONTEXT_ARCHIVE.md` при добавлении новой — только если это реально
понадобится, свериться с фактическим числом полных секций `## Сессия` перед тем
как что-то архивировать, а не по арифметике из этого пункта плана). Добавить
запись новой сессии (4 задачи — race_state, rivals, planner, engine), реальный
тест-бейслайн из Step 1. Явно зафиксировать:

- `is_battle()` сохранил свой публичный контракт (bool, тот же порог) — подсчёт
  вынесен в `_count_recent_overtakes()`, `battle_count` — НОВОЕ отдельное поле
  события, не замена `battle` (bool). `focus`-маркер "N-я попытка" появляется
  ТОЛЬКО когда `battle` уже True — порог `BATTLE_THRESHOLD` не задублирован
  внутри `commentator/planner.py`.
- `RivalTracker.get_style()` возвращает `None` для игрока (трекер и раньше не
  профилировал игрока — это не новое поведение) и для ещё непрофилированных
  машин — оба случая просто не дают суффикса в `focus`, без явных проверок на
  стороне `build_plan()`.
- `"consistent"` (стиль по умолчанию/незаметный) сознательно НЕ входит в
  `_STYLE_PHRASES` — не каждый стиль стоит озвучивать.
- `score_importance()` НЕ изменился в этом плане — `battle_count`/
  `driver_style`/`target_style` влияют только на текст директивы (`focus`), не
  на числовую важность.
- Сознательно НЕ в этом цикле (по design-спеке): «недавняя ошибка» и «свежая
  резина соперника» — оба требуют парсинга телеметрии ЧУЖИХ машин, которого
  сейчас нет вообще (только машина игрока).

- [ ] **Step 4: Checkpoint** — полный прогон зелёный, CONTEXT.md обновлён.
