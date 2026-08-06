# Real-F1 Benchmark (live) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Во время гонки сравнивать темп игрока с реальным F1 (эталон из Jolpica), обновляя HUD и контекст комментатора каждый круг и озвучивая реплику на личном рекорде.

**Architecture:** новый метод в `JolpicaClient` тянет быстрейший круг GP (фолбэк — поул); чистый юнит `core/f1_benchmark.py` хранит эталон и считает гэп по времени круга; engine фоном грузит эталон на смене трассы и на каждом завершённом круге обновляет `state["f1_benchmark"]` + `analytics_context`, на личном рекорде кладёт preset-phrase событие; UI рисует реадаут в Race-view.

**Tech Stack:** Python 3.12, существующий `JolpicaClient` (stdlib urllib, кэш/offline), pytest; фронт Next/React, Bottle `/api/state`.

> ⚠️ **Репозиторий НЕ под git.** Шаги «Commit» заменены на **Checkpoint** — прогон тестов задачи.
> Ergast отдаёт ЛАТИНСКИЕ фамилии → `F1Benchmark` мапит их в кириллицу (`_LATIN_TO_RU`) перед склонением.

---

## Файловая структура

| Файл | Действие | Ответственность |
|------|----------|-----------------|
| `core/ergast_client.py` | изменить | `_laptime_to_ms` + `get_circuit_fastest_lap` + `get_circuit_pole` |
| `core/f1_benchmark.py` | создать | `F1Benchmark` (load/compare/context_line/pb_line) + карты circuit/имён |
| `core/engine.py` | изменить | фон-загрузка на смене трассы, обновление HUD+контекста на круге, PB-триггер, preset-phrase passthrough, сброс на SSTA |
| `NewSpotterUI/lib/api.ts` | изменить | тип `F1BenchmarkState` + поле `f1_benchmark?` |
| `NewSpotterUI/components/spotter/views/race.tsx` | изменить | реадаут «Эталон F1» в панели «Лидер гонки» |
| `tests/test_ergast_fastest_lap.py` | создать | парсинг времени + fastest lap + pole |
| `tests/test_f1_benchmark.py` | создать | load/fallback/compare/строки/reset |
| `tests/test_engine_f1_benchmark.py` | создать | HUD-обновление, PB-триггер, роутинг F1_BENCH |

---

## Task 1: Jolpica — быстрейший круг и поул

**Files:**
- Modify: `core/ergast_client.py`
- Test: `tests/test_ergast_fastest_lap.py` (создать)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ergast_fastest_lap.py
from core.ergast_client import JolpicaClient, _laptime_to_ms


def test_laptime_to_ms():
    assert _laptime_to_ms("1:21.046") == 81046
    assert _laptime_to_ms("58.4") == 58400
    assert _laptime_to_ms(None) is None
    assert _laptime_to_ms("garbage") is None


class _FakeClient(JolpicaClient):
    def __init__(self, payload):           # без super().__init__ — сеть/кэш не нужны
        self._payload = payload

    def get_json(self, path):
        return self._payload


def _results(*entries):
    return {"MRData": {"RaceTable": {"Races": [{"Results": list(entries)}]}}}


def test_fastest_lap_picks_rank_1():
    payload = _results(
        {"Driver": {"familyName": "Norris"},
         "FastestLap": {"rank": "2", "Time": {"time": "1:22.000"}}},
        {"Driver": {"familyName": "Verstappen"},
         "FastestLap": {"rank": "1", "Time": {"time": "1:21.046"}}},
    )
    assert _FakeClient(payload).get_circuit_fastest_lap(2025, "monza") == \
        {"driver": "Verstappen", "time_ms": 81046}


def test_fastest_lap_none_when_no_data():
    assert _FakeClient({"MRData": {"RaceTable": {"Races": []}}}).get_circuit_fastest_lap(2025, "monza") is None
    assert _FakeClient({}).get_circuit_fastest_lap(2025, "") is None


def test_pole_picks_best_quali_time():
    payload = {"MRData": {"RaceTable": {"Races": [{"QualifyingResults": [
        {"position": "1", "Driver": {"familyName": "Leclerc"},
         "Q1": "1:20.5", "Q2": "1:20.1", "Q3": "1:19.8"},
    ]}]}}}
    assert _FakeClient(payload).get_circuit_pole(2025, "monza") == \
        {"driver": "Leclerc", "time_ms": 79800}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_ergast_fastest_lap.py -q`
Expected: FAIL — `ImportError: cannot import name '_laptime_to_ms'`

- [ ] **Step 3: Implement** — добавить в `core/ergast_client.py`.

Модульный helper (после `_USER_AGENT`):

```python
def _laptime_to_ms(t: str | None) -> int | None:
    """«1:21.046» → 81046, «58.4» → 58400. Мусор/None → None."""
    if not t:
        return None
    try:
        t = t.strip()
        if ":" in t:
            mm, ss = t.split(":", 1)
            return int(mm) * 60000 + round(float(ss) * 1000)
        return round(float(t) * 1000)
    except (ValueError, TypeError):
        return None
```

Методы класса `JolpicaClient` (после `get_constructors`):

```python
    def get_circuit_fastest_lap(self, year, circuit_id: str) -> dict | None:
        """Быстрейший круг гонки на трассе: {"driver": familyName, "time_ms": int} | None."""
        if not circuit_id:
            return None
        data = self.get_json(f"{year}/circuits/{circuit_id}/results.json")
        try:
            races = data["MRData"]["RaceTable"]["Races"]  # type: ignore[index]
        except (KeyError, TypeError):
            return None
        if not races:
            return None
        best: dict | None = None
        for r in races[0].get("Results", []):
            fl = r.get("FastestLap") or {}
            ms = _laptime_to_ms((fl.get("Time") or {}).get("time"))
            if ms is None:
                continue
            surname = (r.get("Driver") or {}).get("familyName")
            if str(fl.get("rank")) == "1":
                return {"driver": surname, "time_ms": ms}
            if best is None or ms < best["time_ms"]:
                best = {"driver": surname, "time_ms": ms}
        return best

    def get_circuit_pole(self, year, circuit_id: str) -> dict | None:
        """Фолбэк: поул-тайм (лучшее из Q3→Q2→Q1 у P1). {"driver","time_ms"} | None."""
        if not circuit_id:
            return None
        data = self.get_json(f"{year}/circuits/{circuit_id}/qualifying.json")
        try:
            races = data["MRData"]["RaceTable"]["Races"]  # type: ignore[index]
        except (KeyError, TypeError):
            return None
        if not races:
            return None
        for q in races[0].get("QualifyingResults", []):
            if str(q.get("position")) == "1":
                for k in ("Q3", "Q2", "Q1"):
                    ms = _laptime_to_ms(q.get(k))
                    if ms is not None:
                        return {"driver": (q.get("Driver") or {}).get("familyName"),
                                "time_ms": ms}
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_ergast_fastest_lap.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Checkpoint** — тесты задачи зелёные.

---

## Task 2: `F1Benchmark`

**Files:**
- Create: `core/f1_benchmark.py`
- Test: `tests/test_f1_benchmark.py` (создать)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_f1_benchmark.py
from core.f1_benchmark import F1Benchmark


class _Client:
    def __init__(self, fl=None, pole=None):
        self._fl, self._pole = fl, pole
        self.fl_calls, self.pole_calls = [], []

    def get_circuit_fastest_lap(self, year, circuit):
        self.fl_calls.append((year, circuit))
        return self._fl

    def get_circuit_pole(self, year, circuit):
        self.pole_calls.append((year, circuit))
        return self._pole


def test_load_reference_from_fastest_lap_maps_latin_to_ru():
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}))
    assert b.load(15, 2025) is True               # Monza
    assert b.ready
    assert b.reference["driver"] == "Ферстаппен"  # латиница → кириллица
    assert b.reference["source"] == "fastest_lap"
    assert b.reference["event"] == "Italian Grand Prix"


def test_load_falls_back_to_pole_after_trying_both_years():
    c = _Client(fl=None, pole={"driver": "Leclerc", "time_ms": 79800})
    b = F1Benchmark(client=c)
    assert b.load(15, 2025) is True
    assert b.reference["source"] == "pole"
    assert b.reference["driver"] == "Леклер"
    assert c.fl_calls == [(2025, "monza"), (2024, "monza")]   # fastest пробован за оба года


def test_load_unknown_track_returns_false():
    b = F1Benchmark(client=_Client(fl={"driver": "X", "time_ms": 1}))
    assert b.load(999, 2025) is False
    assert not b.ready


def test_compare_computes_gap():
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}))
    b.load(15, 2025)
    cmp = b.compare([{"lap": 5, "last_lap_ms": 81346}, {"lap": 6, "last_lap_ms": 0}])
    assert cmp["gap_ms"] == 1500
    assert cmp["player_best_ms"] == 81346
    assert cmp["f1_driver"] == "Ферстаппен"


def test_compare_none_when_not_ready_or_no_laps():
    b = F1Benchmark(client=_Client(fl={"driver": "X", "time_ms": 1}))
    assert b.compare([{"last_lap_ms": 1000}]) is None      # не загружен
    b.load(15, 2025)
    assert b.compare([]) is None
    assert b.compare([{"last_lap_ms": 0}]) is None


def test_lines_use_genitive_and_source_word():
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}))
    b.load(15, 2025)
    cmp = b.compare([{"lap": 5, "last_lap_ms": 81346}])
    assert "Ферстаппена" in b.context_line(cmp) and "быстрейший круг" in b.context_line(cmp)
    assert "Ферстаппена" in b.pb_line(cmp) and "рекорд" in b.pb_line(cmp).lower()


def test_pole_source_changes_wording():
    b = F1Benchmark(client=_Client(fl=None, pole={"driver": "Leclerc", "time_ms": 79800}))
    b.load(15, 2025)
    cmp = b.compare([{"lap": 3, "last_lap_ms": 80000}])
    assert "поул" in b.context_line(cmp)


def test_reset_clears():
    b = F1Benchmark(client=_Client(fl={"driver": "X", "time_ms": 1}))
    b.load(15, 2025)
    b.reset()
    assert not b.ready
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_f1_benchmark.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.f1_benchmark'`

- [ ] **Step 3: Implement**

```python
# core/f1_benchmark.py
"""
core/f1_benchmark.py
====================
Живой бенчмарк темпа игрока против РЕАЛЬНОГО F1 (killer-фича #2).

Эталон — быстрейший круг реального GP этой трассы из Jolpica (фолбэк — поул).
Сравнение по ВРЕМЕНИ КРУГА (Ergast не отдаёт сектора). Чистый юнит: хранит эталон
и считает гэп; сеть только в `load` (engine зовёт её в фоновом потоке).

Ergast отдаёт ЛАТИНСКИЕ фамилии — мапим в кириллицу (_LATIN_TO_RU) перед склонением
через core.ru_names, иначе TTS произнесёт латиницу и без падежа.
"""
from __future__ import annotations

import logging

from analytics.loader import TRACK_ID_TO_GP
from core.ergast_client import JolpicaClient
from core.ru_names import decline

_log = logging.getLogger(__name__)

# track_id (F1 25) → ergast circuitId.
TRACK_ID_TO_CIRCUIT: dict[int, str] = {
    0: "albert_park", 1: "shanghai", 2: "suzuka", 3: "bahrain", 4: "jeddah",
    5: "miami", 6: "imola", 7: "monaco", 8: "catalunya", 9: "villeneuve",
    10: "red_bull_ring", 11: "silverstone", 12: "spa", 13: "hungaroring",
    14: "zandvoort", 15: "monza", 16: "baku", 17: "marina_bay", 18: "americas",
    19: "rodriguez", 20: "interlagos", 21: "vegas", 22: "losail", 23: "yas_marina",
}

# Латинская фамилия (Ergast) → русская (ключи как в core/ru_names._FORMS).
_LATIN_TO_RU: dict[str, str] = {
    "Verstappen": "Ферстаппен", "Norris": "Норрис", "Leclerc": "Леклер",
    "Piastri": "Пиастри", "Sainz": "Сайнс", "Hamilton": "Хэмилтон",
    "Russell": "Расселл", "Alonso": "Алонсо", "Stroll": "Стролл",
    "Gasly": "Гасли", "Ocon": "Окон", "Albon": "Албон", "Tsunoda": "Цунода",
    "Hulkenberg": "Хюлькенберг", "Hülkenberg": "Хюлькенберг",
    "Antonelli": "Антонелли", "Colapinto": "Колапинто", "Bearman": "Бирман",
    "Hadjar": "Хаджар", "Lawson": "Лоусон", "Bortoleto": "Бортолето",
    "Doohan": "Дун",
}


def _ru_driver(latin: str | None) -> str:
    if not latin:
        return ""
    return _LATIN_TO_RU.get(latin, latin)   # неизвестное имя → как есть (латиница, без падежа)


def _fmt_lap(ms: int | None) -> str:
    if not ms or ms <= 0:
        return "—"
    total = ms / 1000.0
    m = int(total // 60)
    s = total - m * 60
    return f"{m}:{s:06.3f}" if m else f"{s:.1f}"


class F1Benchmark:
    def __init__(self, client=None):
        self._client = client
        self.reference: dict | None = None

    @property
    def _c(self):
        if self._client is None:
            self._client = JolpicaClient()
        return self._client

    @property
    def ready(self) -> bool:
        return self.reference is not None

    def reset(self) -> None:
        self.reference = None

    def load(self, track_id: int, year: int) -> bool:
        """Загрузить эталон трассы: fastest lap (year, year-1), иначе поул. True если найден."""
        circuit = TRACK_ID_TO_CIRCUIT.get(track_id)
        if not circuit:
            return False
        event = TRACK_ID_TO_GP.get(track_id, ("", ""))[1]
        years = [year, year - 1] if year > 2024 else [year]
        for y in years:
            fl = self._c.get_circuit_fastest_lap(y, circuit)
            if fl:
                self.reference = {"driver": _ru_driver(fl["driver"]), "time_ms": fl["time_ms"],
                                  "year": y, "event": event, "source": "fastest_lap"}
                return True
        for y in years:
            pole = self._c.get_circuit_pole(y, circuit)
            if pole:
                self.reference = {"driver": _ru_driver(pole["driver"]), "time_ms": pole["time_ms"],
                                  "year": y, "event": event, "source": "pole"}
                return True
        return False

    def compare(self, player_laps: list[dict]) -> dict | None:
        """Гэп лучшего круга игрока к эталону. None если не готов / нет валидных кругов."""
        if not self.ready:
            return None
        valid = [l for l in player_laps if (l.get("last_lap_ms") or 0) > 0]
        if not valid:
            return None
        best = min(valid, key=lambda l: l["last_lap_ms"])
        ref = self.reference
        return {
            "gap_ms": best["last_lap_ms"] - ref["time_ms"],
            "player_best_ms": best["last_lap_ms"],
            "player_best_lap": best.get("lap"),
            "f1_time_ms": ref["time_ms"],
            "f1_driver": ref["driver"],
            "event": ref["event"],
            "year": ref["year"],
            "source": ref["source"],
        }

    def _ref_word(self) -> str:
        return "поул" if (self.reference or {}).get("source") == "pole" else "быстрейший круг"

    def context_line(self, cmp: dict) -> str:
        """Строка-сверка для контекста LLM (не озвучивается напрямую)."""
        drv = decline(cmp["f1_driver"], "gen")
        return (f"Эталон трассы — {self._ref_word()} {drv} {_fmt_lap(cmp['f1_time_ms'])} "
                f"({cmp['event']}). Твой лучший {_fmt_lap(cmp['player_best_ms'])}, "
                f"отставание {cmp['gap_ms'] / 1000.0:.1f}с.")

    def pb_line(self, cmp: dict) -> str:
        """Озвучиваемая реплика на личном рекорде (гэп словами, без сырого времени круга)."""
        drv = decline(cmp["f1_driver"], "gen")
        gap = cmp["gap_ms"] / 1000.0
        if gap >= 0:
            return f"Личный рекорд круга! Отставание {gap:.1f} секунды от {self._ref_word()} {drv}."
        return f"Личный рекорд круга! Ты быстрее {self._ref_word()} {drv} на {abs(gap):.1f} секунды!"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_f1_benchmark.py -q`
Expected: PASS (8 passed)

- [ ] **Step 5: Checkpoint** — тесты задачи зелёные.

---

## Task 3: Engine — оркестрация

**Files:**
- Modify: `core/engine.py`
- Test: `tests/test_engine_f1_benchmark.py` (создать)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_engine_f1_benchmark.py
import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from commentator.channel_router import route_event, CHANNEL_COMMENTARY


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


class _FakeBench:
    ready = True

    def compare(self, laps):
        return {"gap_ms": 1500, "player_best_ms": 81346, "player_best_lap": 5,
                "f1_time_ms": 79846, "f1_driver": "Ферстаппен",
                "event": "Italian Grand Prix", "year": 2025, "source": "fastest_lap"}

    def context_line(self, cmp):
        return "Эталон трассы — быстрейший круг Ферстаппена 1:19.846."

    def pb_line(self, cmp):
        return "Личный рекорд круга! Отставание полторы секунды от быстрейшего круга Ферстаппена."


def _drain(engine):
    while not engine.event_queue.empty():
        engine.event_queue.get_nowait()


def test_f1_bench_event_routes_to_commentary():
    assert route_event({"event_code": "F1_BENCH"}, "race") == CHANNEL_COMMENTARY


def test_update_sets_hud_context_and_pb_event(engine):
    engine.f1_benchmark = _FakeBench()
    engine._f1_best_ms = None
    _drain(engine)
    engine._update_f1_benchmark()
    hud = engine.get_state().get("f1_benchmark")
    assert hud is not None and hud["gap_ms"] == 1500 and hud["f1_driver"] == "Ферстаппен"
    assert engine.commentator.analytics_context              # контекст обновлён
    evt = engine.event_queue.get_nowait()                    # PB-событие
    assert evt["event_code"] == "F1_BENCH" and evt["phrase"]


def test_no_double_pb_when_not_improved(engine):
    engine.f1_benchmark = _FakeBench()
    engine._f1_best_ms = 81346                                # тот же best уже зафиксирован
    _drain(engine)
    engine._update_f1_benchmark()
    assert engine.event_queue.empty()                        # не улучшил → без озвучки


def test_update_noop_when_not_ready(engine):
    class _NotReady:
        ready = False
    engine.f1_benchmark = _NotReady()
    _drain(engine)
    engine._update_f1_benchmark()                            # без исключений, без событий
    assert engine.event_queue.empty()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_engine_f1_benchmark.py -q`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute '_update_f1_benchmark'`

- [ ] **Step 3a: Import** — рядом с `from core.race_story import RaceStoryCollector`:

```python
from core.f1_benchmark import F1Benchmark
```

- [ ] **Step 3b: `__init__`** — после блока Post-Race Story Mode:

```python
        # Real-F1 Benchmark (live)
        self.f1_benchmark = F1Benchmark()
        self._f1_best_ms: int | None = None
```

В `self.state = {...}` после `"race_story": None,`:

```python
            "f1_benchmark": None,
```

- [ ] **Step 3c: фон-загрузка на смене трассы** — в `_update_telemetry`, ветка SESSION, после
`self._track_manager = TrackManager(track_info) if track_info else None` добавить:

```python
                    self.f1_benchmark.reset()
                    self._f1_best_ms = None
                    self._start_f1_benchmark_load(new_tid)
```

- [ ] **Step 3d: обновление на завершённом круге** — в `_update_telemetry`, сразу после вызова
`self.driver_coach.add_lap(...)` (внутри `if cur > self._prev_lap ...`), добавить:

```python
                        self._update_f1_benchmark()
```

- [ ] **Step 3e: сброс на SSTA** — в `_telemetry_loop`, блок `if code == "SSTA":`, в существующий
`with self.state_lock:` (где `self.state["race_story"] = None`) добавить и обнулить best:

```python
                self._f1_best_ms = None
                with self.state_lock:
                    self.state["race_story"] = None
                    self.state["f1_benchmark"] = None
```

(заменив прежний одиночный `with self.state_lock: self.state["race_story"] = None`).

- [ ] **Step 3f: preset-phrase passthrough** — в `_commentary_loop`, блок генерации фразы заменить:

```python
            # ── Phrase generation ────────────────────────────────────────────
            phrase = ""
            if channel == CHANNEL_RADIO:
                phrase = get_radio_line(event["event_code"]) or ""
```

на:

```python
            # ── Phrase generation ────────────────────────────────────────────
            phrase = event.get("phrase") or ""    # preset (напр. F1_BENCH) — короткозамыкает
            if not phrase and channel == CHANNEL_RADIO:
                phrase = get_radio_line(event["event_code"]) or ""
```

- [ ] **Step 3g: методы** — добавить в класс `F1Engine` (рядом с `_generate_story`):

```python
    def _start_f1_benchmark_load(self, track_id: int) -> None:
        """Фоновая загрузка эталона трассы из Jolpica (сеть — только тут, не из потока телеметрии)."""
        def _run() -> None:
            try:
                self.f1_benchmark.load(track_id, int(config.F1_SEASON))
            except Exception as exc:  # noqa: BLE001
                _log.warning("F1 benchmark load failed: %s", exc)
        threading.Thread(target=_run, daemon=True, name="f1-benchmark-load").start()

    def _update_f1_benchmark(self) -> None:
        """Каждый завершённый круг: гэп к эталону → HUD + контекст; на личном рекорде — озвучка."""
        if not self.f1_benchmark.ready:
            return
        cmp = self.f1_benchmark.compare(self.recorder.laps())
        if cmp is None:
            return
        with self.state_lock:
            self.state["f1_benchmark"] = {
                "gap_ms": cmp["gap_ms"], "f1_driver": cmp["f1_driver"],
                "f1_time_ms": cmp["f1_time_ms"], "player_best_ms": cmp["player_best_ms"],
                "event": cmp["event"], "year": cmp["year"], "source": cmp["source"]}
        self.set_analytics_context(self.f1_benchmark.context_line(cmp))
        if self._f1_best_ms is None or cmp["player_best_ms"] < self._f1_best_ms:
            self._f1_best_ms = cmp["player_best_ms"]
            self.event_queue.put({
                "event_code": "F1_BENCH", "priority": "normal",
                "phrase": self.f1_benchmark.pb_line(cmp),
                "color": "#34D399", "driver": ""})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_engine_f1_benchmark.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Checkpoint** — тесты задачи зелёные.

---

## Task 4: UI — тип и поле состояния

**Files:**
- Modify: `NewSpotterUI/lib/api.ts`

- [ ] **Step 1: Implement** — добавить тип перед `export type RaceStory = {`:

```typescript
export type F1BenchmarkState = {
  gap_ms: number
  f1_driver: string
  f1_time_ms: number
  player_best_ms: number
  event: string | null
  year: number | null
  source: "fastest_lap" | "pole"
}
```

Добавить поле в `SpotterState` после `race_story?: RaceStory | null`:

```typescript
  f1_benchmark?: F1BenchmarkState | null
```

- [ ] **Step 2: Type-check**

Run: `cd NewSpotterUI; npx tsc --noEmit`
Expected: без новых ошибок

- [ ] **Step 3: Checkpoint** — типы компилируются.

---

## Task 5: UI — реадаут в Race-view

**Files:**
- Modify: `NewSpotterUI/components/spotter/views/race.tsx`

- [ ] **Step 1: Implement** — внутри `RaceView`, после `const playerLap = state?.telemetry?.lap` добавить:

```typescript
  const bench = state?.f1_benchmark ?? null
```

Заменить в панели «Лидер гонки» заглушку-подсказку:

```tsx
              <p className="mt-3 text-[11px] text-muted-foreground">
                Шины, отрыв и карта трассы появятся при расширении телеметрии.
              </p>
```

на блок эталона (показывается, когда есть данные):

```tsx
              {bench ? (
                <div className="mt-3 rounded-md bg-secondary/60 p-3">
                  <p className="font-mono text-[10px] text-muted-foreground">
                    ЭТАЛОН F1 · {bench.source === "pole" ? "ПОУЛ" : "БЫСТРЕЙШИЙ КРУГ"} · {bench.f1_driver}
                  </p>
                  <p className={cn(
                    "font-heading text-lg font-bold tabular",
                    bench.gap_ms <= 0 ? "text-success" : "text-foreground",
                  )}>
                    {bench.gap_ms <= 0 ? "−" : "+"}
                    {(Math.abs(bench.gap_ms) / 1000).toFixed(1)}с
                  </p>
                </div>
              ) : (
                <p className="mt-3 text-[11px] text-muted-foreground">
                  Эталон реального GP подгрузится после первого круга.
                </p>
              )}
```

- [ ] **Step 2: Type-check**

Run: `cd NewSpotterUI; npx tsc --noEmit`
Expected: без новых ошибок (если `text-success` отсутствует в теме — заменить на `text-primary`)

- [ ] **Step 3: Checkpoint** — компонент компилируется.

---

## Task 6: Полная верификация

- [ ] **Step 1: Полный прогон Python-тестов**

Run: `py -3.12 -m pytest --ignore=tests/test_gpt.py -q`
Expected: прошлые + новые зелёные (~612 + 16 новых), 1 skipped.

- [ ] **Step 2: Импорт-смоук**

Run: `py -3.12 -c "import core.engine, core.f1_benchmark, core.ergast_client, web_server; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Обновить CONTEXT.md** — раздел Real-F1 Benchmark: из «спека утверждена, план/код pending»
→ «завершено ✅» (файлы, поведение, тест-бейслайн); счётчик задач по правилу проекта.

- [ ] **Step 4: Checkpoint** — фича готова, тесты зелёные, документация обновлена.

---

## Self-Review (выполнено при написании плана)

- **Покрытие спеки:** Jolpica fastest+pole (T1), F1Benchmark load/fallback/compare/строки (T2),
  engine фон-загрузка+HUD+контекст+PB+passthrough+SSTA (T3), UI тип (T4) и реадаут (T5),
  graceful-off (T2 unknown track / T3 not-ready), Latin→RU имена (T2). ✓
- **Типы/сигнатуры согласованы:** `get_circuit_fastest_lap/get_circuit_pole(year, circuit_id)` (T1↔T2);
  `compare(player_laps)` ключи (T2↔T3 `_FakeBench` зеркалит); `state["f1_benchmark"]` форма (T3↔T4↔T5);
  `F1_BENCH` код + preset `phrase` (T3 passthrough + router default commentary, проверено). ✓
- **Без плейсхолдеров:** весь код дословно. ✓
- **No-git:** «Commit» → «Checkpoint». ✓
- **Имена:** Ergast латиница → `_LATIN_TO_RU` → `ru_names.decline` (родительный) — закрывает риск коверканья. ✓
