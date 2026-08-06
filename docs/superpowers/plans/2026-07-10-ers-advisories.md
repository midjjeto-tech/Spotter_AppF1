# ERS-подсказки инженера — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Три ERS-подсказки инженера: экономия при низком заряде, «жми
овертейк» при близком сопернике, и % заряда в гэп-дайджесте. Детерминированно,
голосом инженера, только в гонке.

**Architecture:** Две новые чистые функции в `analysis.py` → две ветки в
`StrategyAnalyzer` (наследуют голос инженера/шаблоны/cooldown через `STRAT_*`)
→ фразы в `strategist.py`, race-gate в `session_guard.py`. Плюс опциональная
строка «Батарея N%» в `GapDigestTracker.build()`. Плюс проброс
`ers_percent`/`ers_deploy_mode` через engine-state в snapshot/дайджест.

**Tech Stack:** Python 3.12, pytest. Проект НЕ под git — без commit-шагов.

**Спека:** `docs/superpowers/specs/2026-07-10-ers-advisories-design.md`
(пороги приняты автономно, помечены как требующие живой проверки).

---

### Task 1: `analysis.py` — две чистые функции

**Files:**
- Modify: `core/strategy_ai/analysis.py`
- Modify: `tests/test_strategy_ai.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в `tests/test_strategy_ai.py`, после `test_fuel_save_ok` (импорт
пополнить: `from core.strategy_ai.analysis import pace_mode,
fuel_save_recommended, ers_save_recommended, ers_overtake_recommended`):

```python
def test_ers_save_low_battery():
    ok, conf = ers_save_recommended(ers_percent=5.0)
    assert ok is True
    assert conf > 0.6


def test_ers_save_ok_when_charged():
    ok, _ = ers_save_recommended(ers_percent=60.0)
    assert ok is False


def test_ers_save_none_safe():
    assert ers_save_recommended(ers_percent=None) == (False, 0.0)


def test_ers_overtake_when_charged_and_close():
    ok, conf = ers_overtake_recommended(
        ers_percent=70.0, ers_deploy_mode=1, gap_front_ms=800)
    assert ok is True
    assert conf > 0.6


def test_ers_overtake_suppressed_when_already_overtake_mode():
    ok, _ = ers_overtake_recommended(
        ers_percent=70.0, ers_deploy_mode=2, gap_front_ms=800)
    assert ok is False


def test_ers_overtake_suppressed_when_low_battery():
    ok, _ = ers_overtake_recommended(
        ers_percent=30.0, ers_deploy_mode=1, gap_front_ms=800)
    assert ok is False


def test_ers_overtake_suppressed_when_gap_large():
    ok, _ = ers_overtake_recommended(
        ers_percent=70.0, ers_deploy_mode=1, gap_front_ms=5000)
    assert ok is False


def test_ers_overtake_none_safe():
    assert ers_overtake_recommended(None, None, None) == (False, 0.0)
```

- [ ] **Step 2: Прогнать, убедиться что падают**

Run: `py -3.12 -u -m pytest tests/test_strategy_ai.py -k ers -q`
Expected: FAIL — `ImportError` (функций ещё нет).

- [ ] **Step 3: Добавить функции в `core/strategy_ai/analysis.py`**

После `FUEL_LOW_KG = 2.0` (блок констант вверху) добавить:
```python
ERS_LOW_PERCENT = 12.0
ERS_OVERTAKE_MIN_PERCENT = 50.0
ERS_OVERTAKE_GAP_MS = 1200
```

В конец файла (после `fuel_save_recommended`) добавить:
```python
def ers_save_recommended(ers_percent: float | None) -> tuple[bool, float]:
    """Заряд ERS почти исчерпан — беречь деплой."""
    if ers_percent is None or ers_percent >= ERS_LOW_PERCENT:
        return False, 0.0
    conf = 0.6 + (ERS_LOW_PERCENT - ers_percent) / ERS_LOW_PERCENT * 0.25
    return True, min(conf, 0.85)


def ers_overtake_recommended(
    ers_percent: float | None,
    ers_deploy_mode: int | None,
    gap_front_ms: int | None,
) -> tuple[bool, float]:
    """Есть заряд + близкий соперник впереди + ещё не в overtake-режиме."""
    if ers_percent is None or gap_front_ms is None:
        return False, 0.0
    if ers_deploy_mode == 2:            # уже overtake — не советуем повторно
        return False, 0.0
    if ers_percent < ERS_OVERTAKE_MIN_PERCENT or gap_front_ms > ERS_OVERTAKE_GAP_MS:
        return False, 0.0
    conf = 0.6 + (ERS_OVERTAKE_GAP_MS - gap_front_ms) / ERS_OVERTAKE_GAP_MS * 0.25
    return True, min(conf, 0.85)
```

- [ ] **Step 4: Прогнать, зелёные**

Run: `py -3.12 -u -m pytest tests/test_strategy_ai.py -k ers -q`
Expected: `8 passed`.

---

### Task 2: `gap_digest.py` — строка «Батарея N%»

**Files:**
- Modify: `core/strategy_ai/gap_digest.py`
- Modify: `tests/test_gap_digest.py`

- [ ] **Step 1: Написать падающие тесты**

Добавить в `tests/test_gap_digest.py`:
```python
def test_ers_percent_appended_when_gap_present():
    t = GapDigestTracker()
    out = t.build(gap_front_ms=1800, gap_behind_ms=None, ers_percent=62.5)
    assert out == "Отрыв впереди: 1.8. Батарея 62%."


def test_ers_percent_none_not_appended():
    t = GapDigestTracker()
    out = t.build(gap_front_ms=1800, gap_behind_ms=None, ers_percent=None)
    assert out == "Отрыв впереди: 1.8."


def test_ers_percent_alone_does_not_trigger_digest():
    """Батарея без гэпов НЕ запускает дайджест (анти-болтливость, spec п.3)."""
    t = GapDigestTracker()
    out = t.build(gap_front_ms=None, gap_behind_ms=None, ers_percent=62.0)
    assert out is None
```

- [ ] **Step 2: Прогнать, убедиться что падают**

Run: `py -3.12 -u -m pytest tests/test_gap_digest.py -k ers -q`
Expected: FAIL — `TypeError` (нет параметра `ers_percent`).

- [ ] **Step 3: Расширить `build()` в `core/strategy_ai/gap_digest.py`**

Текущий (после Фазы 2):
```python
    def build(self, gap_front_ms: int | None, gap_behind_ms: int | None) -> str | None:
        """Возвращает готовую фразу, либо None (нечего сказать)."""
        parts: list[str] = []
        if gap_front_ms is not None and gap_front_ms > 0:
            parts.append(_gap_phrase("впереди", gap_front_ms, self._prev_front_ms))
        if gap_behind_ms is not None and gap_behind_ms > 0:
            parts.append(_gap_phrase("сзади", gap_behind_ms, self._prev_behind_ms))
        # ... нормализация prev ...
        self._prev_front_ms = gap_front_ms if gap_front_ms else None
        self._prev_behind_ms = gap_behind_ms if gap_behind_ms else None
        return " ".join(parts) if parts else None
```
Заменить сигнатуру и добавить хвост про батарею (НЕ трогая нормализацию prev):
```python
    def build(self, gap_front_ms: int | None, gap_behind_ms: int | None,
              ers_percent: float | None = None) -> str | None:
        """Возвращает готовую фразу, либо None (нечего сказать). Батарея —
        только ДОПОЛНЕНИЕ к гэп-части, одна дайджест не запускает (spec п.3)."""
        parts: list[str] = []
        if gap_front_ms is not None and gap_front_ms > 0:
            parts.append(_gap_phrase("впереди", gap_front_ms, self._prev_front_ms))
        if gap_behind_ms is not None and gap_behind_ms > 0:
            parts.append(_gap_phrase("сзади", gap_behind_ms, self._prev_behind_ms))
        self._prev_front_ms = gap_front_ms if gap_front_ms else None
        self._prev_behind_ms = gap_behind_ms if gap_behind_ms else None
        if not parts:
            return None
        if ers_percent is not None:
            parts.append(f"Батарея {round(ers_percent)}%.")
        return " ".join(parts)
```

- [ ] **Step 4: Прогнать, зелёные**

Run: `py -3.12 -u -m pytest tests/test_gap_digest.py -q`
Expected: все тесты файла зелёные (существующие + 3 новых).

---

### Task 3: `strategy.py` ветки + `strategist.py` фразы + `session_guard.py`

**Files:**
- Modify: `core/strategy_ai/strategy.py`
- Modify: `commentator/strategist.py`
- Modify: `core/session_guard.py`
- Modify: `tests/test_strategy_ai.py`, `tests/test_strategist.py`, `tests/test_session_guard.py`

- [ ] **Step 1: Написать падающие тесты**

В `tests/test_strategy_ai.py` (использует хелпер `_snapshot`):
```python
def test_analyzer_ers_overtake_event():
    sa = StrategyAnalyzer()
    event = sa.update(_snapshot(
        gap_front_ms=800, ers_percent=70.0, ers_deploy_mode=1,
        tyre_age=8, tyre_wear=20.0))
    assert event is not None
    assert event.type == "ers_overtake"


def test_analyzer_ers_save_event():
    sa = StrategyAnalyzer()
    event = sa.update(_snapshot(
        gap_front_ms=8000, gap_behind_ms=8000, ers_percent=4.0,
        tyre_age=8, tyre_wear=20.0))
    assert event is not None
    assert event.type == "ers_save"
```

В `tests/test_strategist.py` (импортировать `_MESSAGES` для проверки членства,
как надёжнее эвристик по подстроке — get_message на неизвестный ключ молча
падает в `stable`, членство в пуле это ловит):
```python
from commentator.strategist import get_message, _MESSAGES


def test_ers_save_message_from_pool():
    assert get_message("ers_save") in _MESSAGES["ers_save"]


def test_ers_overtake_message_from_pool():
    assert get_message("ers_overtake") in _MESSAGES["ers_overtake"]
```
(если в файле уже есть `from commentator.strategist import get_message` —
дополнить импорт `_MESSAGES`, не дублировать строку.)

В `tests/test_session_guard.py` (добавить к тестам практики — сначала
прочитать файл, найти как проверяется `_PRACTICE_SUPPRESS`, повторить
паттерн; ниже — типовой вид, СВЕРИТЬ с существующим стилем файла):
```python
def test_ers_advisories_suppressed_in_practice():
    g = SessionGuard()
    g.set_session_type("practice")
    assert g.should_emit({"event_code": "STRAT_ERS_SAVE"}) is False
    assert g.should_emit({"event_code": "STRAT_ERS_OVERTAKE"}) is False
```

- [ ] **Step 2: Прогнать, убедиться что падают**

Run: `py -3.12 -u -m pytest tests/test_strategy_ai.py tests/test_strategist.py tests/test_session_guard.py -k "ers" -q`
Expected: FAIL (событий/фраз/suppress ещё нет).

- [ ] **Step 3a: `core/strategy_ai/strategy.py` — импорт + snapshot + ветки**

Импорт (строки ~10-16, к существующим `fuel_save_recommended, pace_mode`):
```python
from core.strategy_ai.analysis import (
    FuelTracker,
    LapRecord,
    PaceTracker,
    ers_overtake_recommended,
    ers_save_recommended,
    fuel_save_recommended,
    pace_mode,
)
```

В `update()`, где читается snapshot (после `fuel = snapshot.get("fuel")`):
```python
        ers_percent = snapshot.get("ers_percent")
        ers_deploy_mode = snapshot.get("ers_deploy_mode")
```

Новые ветки МЕЖДУ «Priority 5: Fuel save» и «Priority 6: Pace mode». Найти
конец блока fuel_save (`event = StrategyEvent(type="fuel_save", ...)` внутри
`if fuel_ok:`) и ПЕРЕД комментарием `# Priority 6: Pace mode` вставить:
```python
        # Priority 5a: ERS overtake (близкий соперник + есть заряд)
        if not event:
            ok, conf = ers_overtake_recommended(ers_percent, ers_deploy_mode, gap_front)
            if ok:
                decision = StrategyDecision(
                    action="push",
                    confidence=conf,
                    reason="ers_overtake",
                    data={"ers_percent": ers_percent,
                          "gap_front_s": round(gap_front / 1000.0, 2) if gap_front else None},
                )
                event = StrategyEvent(
                    type="ers_overtake",
                    priority="medium",
                    confidence=conf,
                    decision=decision,
                    data=dict(decision.data),
                )

        # Priority 5b: ERS save (низкий заряд)
        if not event:
            ok, conf = ers_save_recommended(ers_percent)
            if ok:
                decision = StrategyDecision(
                    action="save",
                    confidence=conf,
                    reason="ers_save",
                    data={"ers_percent": ers_percent},
                )
                event = StrategyEvent(
                    type="ers_save",
                    priority="low",
                    confidence=conf,
                    decision=decision,
                    data=dict(decision.data),
                )
```

В `_ADVICE_RU` (словарь вверху strategy.py) добавить:
```python
    "ers_overtake":       "Есть заряд — атакуй, режим овертейк.",
    "ers_save":           "Береги заряд батареи.",
```

- [ ] **Step 3b: `commentator/strategist.py` — фразы**

В `_MESSAGES`, после `"fuel_save": [...]` (перед `"stable"`):
```python
    "ers_save": [
        "Заряд батареи на исходе — береги деплой.",
        "Мало энергии Э-эр-эс. Экономь на выходах из поворотов.",
    ],
    "ers_overtake": [
        "Заряд есть — жми овертейк, атакуй сейчас.",
        "Полная батарея, соперник близко — режим атаки, вперёд.",
    ],
```

- [ ] **Step 3c: `core/engine.py` — `_st_code_map`**

В `_st_code_map` (в `_maybe_snapshot`, рядом с `"fuel_save": "STRAT_FUEL"`):
```python
                    "ers_save":     "STRAT_ERS_SAVE",
                    "ers_overtake": "STRAT_ERS_OVERTAKE",
```

- [ ] **Step 3d: `commentator/templates.py` — `_STRATEGY_AI_CODES`**

В `_STRATEGY_AI_CODES` добавить (чтобы `templates.render` маршрутизировал их
в strategist, как сиблингов):
```python
    "STRAT_ERS_SAVE":     "ers_save",
    "STRAT_ERS_OVERTAKE": "ers_overtake",
```

- [ ] **Step 3e: `core/session_guard.py` — `_PRACTICE_SUPPRESS`**

Добавить `"STRAT_ERS_SAVE", "STRAT_ERS_OVERTAKE"` во frozenset
`_PRACTICE_SUPPRESS`.

- [ ] **Step 4: Прогнать, зелёные**

Run: `py -3.12 -u -m pytest tests/test_strategy_ai.py tests/test_strategist.py tests/test_session_guard.py tests/test_templates.py -q`
Expected: все зелёные.

---

### Task 4: `core/engine.py` — проброс телеметрии

**Files:**
- Modify: `core/engine.py`
- Modify: `tests/test_engine_planner.py`

- [ ] **Step 1: Написать падающий тест**

В `tests/test_engine_planner.py`:
```python
def test_gap_digest_includes_battery_when_ers_present(engine):
    _drain(engine)
    engine._gap_digest.reset()
    engine._session_type = "race"
    engine._player_gap_front = 1800
    engine._player_gap_behind = None
    engine._player_ers_percent = 60.0
    engine._last_significant_event_t = 0.0
    engine.state["connected"] = True

    engine._maybe_emit_gap_digest(time.time())
    evt = engine.event_queue.get_nowait()
    assert "Батарея 60%." in evt["phrase"]

    engine._gap_digest.reset()
    engine._session_type = "unknown"
    engine._player_gap_front = None
    engine._player_ers_percent = None
    engine.state["connected"] = False
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `py -3.12 -u -m pytest tests/test_engine_planner.py -k battery -q`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute '_player_ers_percent'`.

- [ ] **Step 3: Проводка в `core/engine.py`**

3a. `__init__` (рядом с `self._player_fuel`... найти где инициализируются
`_player_*` поля телеметрии, напр. рядом с `_player_tyre_wear`):
```python
        self._player_ers_percent: float | None = None
        self._player_ers_deploy_mode: int | None = None
```

3b. `_update_telemetry`, после блока `if telem.get("tyre_age") is not None:`:
```python
            if telem.get("ers_percent") is not None:
                self._player_ers_percent = telem["ers_percent"]
            if telem.get("ers_deploy_mode") is not None:
                self._player_ers_deploy_mode = telem["ers_deploy_mode"]
```

3c. `_maybe_snapshot`, в `st_snapshot` (после `"fuel": self._player_fuel,`):
```python
            "ers_percent": self._player_ers_percent,
            "ers_deploy_mode": self._player_ers_deploy_mode,
```

3d. `_maybe_emit_gap_digest`, вызов `build`:
```python
        phrase = self._gap_digest.build(
            self._player_gap_front, self._player_gap_behind,
            ers_percent=self._player_ers_percent)
```

- [ ] **Step 4: Прогнать, зелёные**

Run: `py -3.12 -u -m pytest tests/test_engine_planner.py -q`
Expected: все зелёные.

---

### Task 5: Полный прогон + CONTEXT.md

- [ ] **Step 1: Полный прогон**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: 0 failed.

- [ ] **Step 2: CONTEXT.md**

Добавить: Фаза 3 шаг 2/3 — три ERS-подсказки. Пороги приняты автономно
(ERS_LOW_PERCENT=12, ERS_OVERTAKE_MIN_PERCENT=50, ERS_OVERTAKE_GAP_MS=1200) —
нужна живая проверка на слух. Отметить, что офсеты парсинга уже подтверждены
статически (шаг 1). Открыто: нет тумблера ERS-подсказок (как и у дайджеста).

---

## Верификация (сквозная)

- `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q` — весь набор зелёный.
- Точечно: `pytest tests/test_strategy_ai.py tests/test_gap_digest.py tests/test_strategist.py tests/test_session_guard.py tests/test_engine_planner.py tests/test_templates.py -q`.
- Живая проверка порогов (звучат ли советы в нужные моменты) — у пользователя.
