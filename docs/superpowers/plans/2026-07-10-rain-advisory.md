# Дождь через N минут — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Однократный heads-up «дождь через N минут» голосом инженера, когда
прогноз показывает дождь в пределах 30 минут. Не гейтован по session_type
(в отличие от гэп-дайджеста), без эскалации (в отличие от box-вызова).

**Architecture:** `RainAdvisoryTracker` (armed-once, по образцу
`BoxCallTracker`, но без тиров) в `core/strategy_ai/weather_advisory.py`.
Проводка через существующий блок `PACKET_SESSION` в `_update_telemetry`
(рядом с `track_id`/`session_type`). Преднабранная фраза + `speaker=engineer`
+ `bypass_speak_threshold` — тот же короткий путь, что `ENGINEER_GAP_DIGEST`.

**Tech Stack:** Python 3.12, pytest. Проект НЕ под git — без commit-шагов.

**Спека:** `docs/superpowers/specs/2026-07-10-rain-advisory-design.md`.

---

### Task 1: `RainAdvisoryTracker`

**Files:**
- Create: `core/strategy_ai/weather_advisory.py`
- Create: `tests/test_weather_advisory.py`

- [ ] **Step 1: Написать падающие тесты**

```python
# tests/test_weather_advisory.py
"""RainAdvisoryTracker — однократный heads-up "дождь через N минут".
См. docs/superpowers/specs/2026-07-10-rain-advisory-design.md.
"""
from core.strategy_ai.weather_advisory import (
    RAIN_ADVISORY_HORIZON_MIN, RainAdvisoryTracker,
)


def test_rain_in_horizon_announces_once():
    t = RainAdvisoryTracker()
    phrase = t.check({"minutes": 15, "rain_pct": 60, "weather": 3})
    assert phrase is not None
    assert "15" in phrase


def test_does_not_repeat_same_episode():
    t = RainAdvisoryTracker()
    t.check({"minutes": 15, "rain_pct": 60, "weather": 3})
    phrase2 = t.check({"minutes": 14, "rain_pct": 60, "weather": 3})
    assert phrase2 is None


def test_no_forecast_returns_none_and_resets():
    t = RainAdvisoryTracker()
    t.check({"minutes": 15, "rain_pct": 60, "weather": 3})
    phrase = t.check(None)
    assert phrase is None


def test_new_episode_after_dry_gap_announces_again():
    t = RainAdvisoryTracker()
    t.check({"minutes": 15, "rain_pct": 60, "weather": 3})
    t.check(None)                                       # прогноз стал сухим
    phrase = t.check({"minutes": 20, "rain_pct": 70, "weather": 4})
    assert phrase is not None


def test_beyond_horizon_does_not_announce():
    t = RainAdvisoryTracker()
    phrase = t.check({"minutes": RAIN_ADVISORY_HORIZON_MIN + 1, "rain_pct": 80, "weather": 4})
    assert phrase is None


def test_exactly_at_horizon_announces():
    t = RainAdvisoryTracker()
    phrase = t.check({"minutes": RAIN_ADVISORY_HORIZON_MIN, "rain_pct": 80, "weather": 4})
    assert phrase is not None


def test_leaving_horizon_resets_for_new_episode():
    t = RainAdvisoryTracker()
    t.check({"minutes": 15, "rain_pct": 60, "weather": 3})
    t.check({"minutes": RAIN_ADVISORY_HORIZON_MIN + 5, "rain_pct": 60, "weather": 3})  # ушёл за горизонт
    phrase = t.check({"minutes": 25, "rain_pct": 60, "weather": 3})  # снова в горизонте
    assert phrase is not None


def test_manual_reset():
    t = RainAdvisoryTracker()
    t.check({"minutes": 15, "rain_pct": 60, "weather": 3})
    t.reset()
    phrase = t.check({"minutes": 15, "rain_pct": 60, "weather": 3})
    assert phrase is not None


def test_urgent_phrasing_when_five_minutes_or_less():
    t = RainAdvisoryTracker()
    phrase = t.check({"minutes": 5, "rain_pct": 90, "weather": 4})
    assert "интермедиейты" in phrase.lower()
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `py -3.12 -u -m pytest tests/test_weather_advisory.py -q`
Expected: `ModuleNotFoundError: No module named 'core.strategy_ai.weather_advisory'`

- [ ] **Step 3: Реализовать**

```python
# core/strategy_ai/weather_advisory.py
"""
core/strategy_ai/weather_advisory.py
======================================
Однократный heads-up "дождь через N минут" — детерминированный, без LLM,
armed-once (без эскалации, в отличие от box_call.py). См.
docs/superpowers/specs/2026-07-10-rain-advisory-design.md.
"""
from __future__ import annotations

RAIN_ADVISORY_HORIZON_MIN = 30


class RainAdvisoryTracker:
    """Однократный heads-up «дождь через N минут» — armed once, без
    эскалации. Сброс, когда дождь уходит из горизонта или прогноз становится
    сухим — следующее появление снова объявляется."""

    def __init__(self) -> None:
        self._armed = False

    def check(self, rain_forecast: dict | None) -> str | None:
        """rain_forecast: {"minutes", "rain_pct", "weather"} или None.
        Возвращает готовую фразу один раз за эпизод, либо None."""
        if rain_forecast is None or rain_forecast["minutes"] > RAIN_ADVISORY_HORIZON_MIN:
            self._armed = False
            return None
        if self._armed:
            return None
        self._armed = True
        return _phrase(rain_forecast["minutes"], rain_forecast["rain_pct"])

    def reset(self) -> None:
        self._armed = False


def _phrase(minutes: int, rain_pct: int) -> str:
    if minutes <= 5:
        return f"Дождь через {minutes} минут, вероятность {rain_pct} процентов. Готовь интермедиейты."
    return f"Дождь ожидается через {minutes} минут, вероятность {rain_pct} процентов."
```

- [ ] **Step 4: Прогнать тесты, зелёные**

Run: `py -3.12 -u -m pytest tests/test_weather_advisory.py -q`
Expected: `9 passed`

---

### Task 2: Проводка в `core/engine.py`

**Files:**
- Modify: `core/engine.py`
- Modify: `tests/test_engine_planner.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `tests/test_engine_planner.py`:

`_update_telemetry(self, header: dict, packet_id: int, data: bytes)` (строка
816) — `header.get("player_car_index", 255)`/`header.get("game_year", 0)`
безопасны с дефолтами при отсутствии ключей в `header`. `event_queue` —
`ImportanceQueue` (`core/event_queue.py`), публичный интерфейс только
`put`/`get`/`get_nowait`/`empty` (нет `.queue`) — дренировать циклом
`get_nowait()`, как везде в этом файле (`_drain`):

```python
def test_rain_advisory_enqueues_on_session_packet(engine, monkeypatch):
    _drain(engine)
    engine._rain_advisory.reset()

    monkeypatch.setattr(
        "core.engine.parse_session",
        lambda data: {"total_laps": 0, "track_id": -1, "session_type": "unknown",
                       "rain_forecast": {"minutes": 15, "rain_pct": 60, "weather": 3}})
    engine._update_telemetry({"packet_id": 1}, 1, b"\x00" * 40)

    drained = []
    while not engine.event_queue.empty():
        drained.append(engine.event_queue.get_nowait())
    found = [e for e in drained if e["event_code"] == "ENGINEER_RAIN_ADVISORY"]
    assert len(found) == 1
    assert found[0]["speaker"] == "engineer"
    assert found[0]["bypass_speak_threshold"] is True
    assert "15" in found[0]["phrase"]

    engine._rain_advisory.reset()
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `py -3.12 -u -m pytest tests/test_engine_planner.py -k rain_advisory -q`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute '_rain_advisory'`.

- [ ] **Step 3: Импорт + инициализация**

В `core/engine.py`, рядом с существующим импортом `BoxCallTracker`/
`GapDigestTracker`:
```python
from core.strategy_ai.weather_advisory import RainAdvisoryTracker
```

В `__init__`, рядом с `self._track_id: int = -1`:
```python
        self._rain_forecast: dict | None = None
        self._rain_advisory = RainAdvisoryTracker()
```

- [ ] **Step 4: Проводка в `_update_telemetry`**

Найти блок `if packet_id == PACKET_SESSION:` (начинается с
`session = parse_session(data)`). Сразу после этой строки добавить:
```python
            self._rain_forecast = session.get("rain_forecast")
            _rain_phrase = self._rain_advisory.check(self._rain_forecast)
            if _rain_phrase is not None:
                self._enqueue_event({
                    "event_code": "ENGINEER_RAIN_ADVISORY", "priority": "normal",
                    "phrase": _rain_phrase, "speaker": SPEAKER_ENGINEER,
                    "driver": "", "color": "#38BDF8",
                    "bypass_speak_threshold": True,
                })
```
Не трогать остальную логику блока (обработка `total_laps`/`track_id`/
`session_type` ниже — эти строки читают `session.get(...)` независимо, порядок
не важен, просто не удалять/не переставлять существующий код).

- [ ] **Step 5: Сброс на SSTA**

В блоке `if code == "SSTA":`, рядом с `self._gap_digest.reset()`:
```python
                self._rain_advisory.reset()
```

- [ ] **Step 6: Прогнать, зелёные**

Run: `py -3.12 -u -m pytest tests/test_engine_planner.py -q`
Expected: все тесты файла зелёные (существующие + 1 новый).

---

### Task 3: Полный прогон + CONTEXT.md

- [ ] **Step 1:** `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q` — 0 failed.
- [ ] **Step 2:** CONTEXT.md — сессия закрыта, Фаза 4 (погода) полностью
  готова (парсинг + advisory); напомнить про висящую живую сверку прогноза
  из шага 1 (целый-сэмпл сдвиг — единственный незакрытый кодом риск).

---

## Верификация (сквозная)

- `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q` — весь набор зелёный.
- Точечно: `pytest tests/test_weather_advisory.py tests/test_engine_planner.py -q`.
- Живая проверка (звучит ли фраза адекватно) — у пользователя.
