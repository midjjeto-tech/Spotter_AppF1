# F1 Sector Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Расширить Real-F1 Benchmark посекторным сравнением («лучшие секторы гонки» из OpenF1) — HUD-чипы, живая реплика на личном рекорде сектора, факт в Post-Race Story, бесплатно в Voice Q&A.

**Architecture:** Новый лёгкий `core/openf1_client.py` (зеркалит `JolpicaClient`) добавляет `sector_ms` к уже существующему `F1Benchmark.reference`; `compare()` расширяется полем `"sectors"` (всегда присутствует, может быть `None`); `core/engine.py::_update_f1_benchmark` (уже существующий триггер на завершённый круг) получает анти-спам логику личного рекорда по сектору; UI/Story дочитывают уже готовые данные.

**Tech Stack:** Python 3.12, стандартная библиотека (urllib/json), pytest; фронт — Next/React (`NewSpotterUI`).

> ⚠️ **Репозиторий НЕ под git** (`Is a git repository: false`). Шаги «Commit» заменены на **Checkpoint** — прогон тестов задачи. Команды тестов: `py -3.12 -m pytest ... -q`.

**Спека:** [`docs/superpowers/specs/2026-07-02-f1-sector-benchmark-design.md`](../specs/2026-07-02-f1-sector-benchmark-design.md).

---

## Файловая структура

| Файл | Действие | Ответственность |
|------|----------|-----------------|
| `config.py` | изменить | `OPENF1_*` константы (кэш, TTL, rate-limit, таймауты) |
| `core/openf1_client.py` | создать | `OpenF1Client` — session_key + лучшие секторы гонки |
| `core/f1_benchmark.py` | изменить | `_load_sectors`, `compare()["sectors"]`, `sector_pb_line`, `race_weak_sector` |
| `core/engine.py` | изменить | `_f1_best_sector_ms`, анти-спам реплика по сектору, `weak_sector_vs_f1` в Story |
| `core/race_story.py` | изменить | `facts(weak_sector_vs_f1=...)` |
| `commentator/story.py` | изменить | `_format_facts` — новая строка `weak_sector_vs_f1` |
| `NewSpotterUI/lib/api.ts` | изменить | `F1BenchmarkState.sectors` |
| `NewSpotterUI/components/spotter/views/race.tsx` | изменить | 3 чипа секторов в панели «Эталон F1» |
| `tests/test_openf1_client.py` | создать | |
| `tests/test_f1_benchmark.py` | изменить | +сектора, +`race_weak_sector` |
| `tests/test_engine_f1_benchmark.py` | изменить | `_FakeBench` получает `"sectors"`, +анти-спам тесты |
| `tests/test_story_collector.py` | изменить | +`weak_sector_vs_f1` |
| `tests/test_story_generator.py` | изменить | +строка в `_format_facts` |

---

## Task 1: `core/openf1_client.py` — клиент OpenF1

**Files:**
- Modify: `config.py`
- Create: `core/openf1_client.py`
- Test: `tests/test_openf1_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_openf1_client.py
from core.openf1_client import OpenF1Client


def _client(tmp_path):
    return OpenF1Client(cache_dir=tmp_path)


def test_get_session_key_found(tmp_path, monkeypatch):
    cl = _client(tmp_path)
    monkeypatch.setattr(cl, "_fetch", lambda path, params: [{"session_key": 9161}])
    assert cl.get_session_key(2025, "monza") == 9161


def test_get_session_key_unknown_circuit_returns_none_without_network(tmp_path, monkeypatch):
    cl = _client(tmp_path)
    calls = []
    monkeypatch.setattr(cl, "_fetch", lambda path, params: calls.append(1) or [{"session_key": 1}])
    assert cl.get_session_key(2025, "nonexistent_circuit") is None
    assert calls == []          # неизвестная трасса -> сеть не дёргаем вовсе


def test_get_session_key_empty_response_returns_none(tmp_path, monkeypatch):
    cl = _client(tmp_path)
    monkeypatch.setattr(cl, "_fetch", lambda path, params: [])
    assert cl.get_session_key(2025, "monza") is None


def test_get_best_sectors_takes_min_across_laps(tmp_path, monkeypatch):
    cl = _client(tmp_path)
    laps = [
        {"duration_sector_1": 26.966, "duration_sector_2": 38.657, "duration_sector_3": 26.12},
        {"duration_sector_1": 26.5, "duration_sector_2": 39.0, "duration_sector_3": 25.9},
    ]
    monkeypatch.setattr(cl, "_fetch", lambda path, params: laps)
    assert cl.get_best_sectors(9161) == {1: 26500, 2: 38657, 3: 25900}


def test_get_best_sectors_ignores_null_and_zero_sectors(tmp_path, monkeypatch):
    """Регресс-гард: невалидный сектор (None/0) не должен побеждать в MIN()."""
    cl = _client(tmp_path)
    laps = [
        {"duration_sector_1": None, "duration_sector_2": 0, "duration_sector_3": 26.0},
        {"duration_sector_1": 27.0, "duration_sector_2": 38.0, "duration_sector_3": 26.5},
    ]
    monkeypatch.setattr(cl, "_fetch", lambda path, params: laps)
    assert cl.get_best_sectors(9161) == {1: 27000, 2: 38000, 3: 26000}


def test_get_best_sectors_ignores_pit_out_lap(tmp_path, monkeypatch):
    cl = _client(tmp_path)
    laps = [
        {"duration_sector_1": 20.0, "duration_sector_2": 20.0, "duration_sector_3": 20.0,
         "is_pit_out_lap": True},
        {"duration_sector_1": 27.0, "duration_sector_2": 38.0, "duration_sector_3": 26.5},
    ]
    monkeypatch.setattr(cl, "_fetch", lambda path, params: laps)
    assert cl.get_best_sectors(9161) == {1: 27000, 2: 38000, 3: 26500}


def test_get_best_sectors_incomplete_data_returns_none(tmp_path, monkeypatch):
    """Если хотя бы один сектор никогда не валиден — не отдаём частичные данные."""
    cl = _client(tmp_path)
    laps = [{"duration_sector_1": 27.0, "duration_sector_2": None, "duration_sector_3": 26.5}]
    monkeypatch.setattr(cl, "_fetch", lambda path, params: laps)
    assert cl.get_best_sectors(9161) is None


def test_get_best_sectors_none_session_key_returns_none(tmp_path):
    cl = _client(tmp_path)
    assert cl.get_best_sectors(None) is None


def test_get_best_sectors_network_failure_returns_none(tmp_path, monkeypatch):
    cl = _client(tmp_path)
    monkeypatch.setattr(cl, "_fetch", lambda path, params: None)
    assert cl.get_best_sectors(9161) is None


def test_cache_hit_avoids_second_fetch(tmp_path, monkeypatch):
    cl = _client(tmp_path)
    calls = []

    def fake_fetch(path, params):
        calls.append(1)
        return [{"session_key": 9161}]

    monkeypatch.setattr(cl, "_fetch", fake_fetch)
    assert cl.get_session_key(2025, "monza") == 9161
    assert cl.get_session_key(2025, "monza") == 9161
    assert len(calls) == 1                              # второй раз — из кэша
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_openf1_client.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.openf1_client'`

- [ ] **Step 3: Add config constants**

Добавить в конец `config.py`:

```python
# --- OpenF1 (секторные эталоны реальных гонок, Real-F1 Benchmark — секторы) ---
OPENF1_CACHE_DIR = os.path.join(DATA_DIR, "openf1_cache")
OPENF1_TTL_DAYS = 3650          # практически бессрочно — завершённая гонка не меняется
OPENF1_MIN_INTERVAL = 2.0
OPENF1_MAX_RETRIES = 3
OPENF1_TIMEOUT = 8.0
```

- [ ] **Step 4: Implement `core/openf1_client.py`**

```python
"""
core/openf1_client.py
======================
Клиент OpenF1 API — секторные эталоны реальных гонок (Real-F1 Benchmark: секторы).

Ergast/Jolpica не отдаёт секторы (core/ergast_client.py) — OpenF1 отдаёт per-lap
duration_sector_1/2/3 для каждого пилота каждой гонки. Используем ТОЛЬКО «лучшие
секторы гонки» (MIN среди валидных кругов) — не пытаемся сопоставить конкретного
пилота/круг с полным-круга-эталоном Ergast (см. design spec, §2 не-цели).

Зависимостей нет: только стандартная библиотека (urllib/json/pathlib), как и
core/ergast_client.py — важно для офлайн-работы и упаковки в EXE.

Кэш практически бессрочный (OPENF1_TTL_DAYS): завершённая гонка не меняется, в
отличие от Ergast, где «текущий сезон» может обновляться.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import config

_log = logging.getLogger(__name__)

_USER_AGENT = "SpotterApp/1.0 (F1 commentator)"


class OpenF1Client:
    """Кэширующий, устойчивый к сбоям клиент OpenF1 (секторные эталоны)."""

    BASE_URL = "https://api.openf1.org/v1"

    # Ergast circuit_id (core/f1_benchmark.TRACK_ID_TO_CIRCUIT) → короткое имя
    # трассы в OpenF1 (/v1/sessions?location=...). Строки НЕ гарантированно
    # идентичны Ergast — отдельная таблица.
    CIRCUIT_ID_TO_OPENF1_LOCATION: dict[str, str] = {
        "albert_park": "Melbourne", "shanghai": "Shanghai", "bahrain": "Sakhir",
        "catalunya": "Barcelona", "monaco": "Monaco", "villeneuve": "Montreal",
        "silverstone": "Silverstone", "hungaroring": "Budapest", "spa": "Spa-Francorchamps",
        "monza": "Monza", "marina_bay": "Singapore", "suzuka": "Suzuka",
        "yas_marina": "Yas Marina Circuit", "americas": "Austin", "interlagos": "Sao Paulo",
        "red_bull_ring": "Spielberg", "rodriguez": "Mexico City", "baku": "Baku",
        "zandvoort": "Zandvoort", "imola": "Imola", "jeddah": "Jeddah", "miami": "Miami",
        "vegas": "Las Vegas", "losail": "Lusail",
    }

    def __init__(self, cache_dir: str | Path | None = None):
        self.cache_dir = Path(cache_dir or config.OPENF1_CACHE_DIR)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # noqa: BLE001 — кэш не критичен, продолжаем без него
            _log.warning("OpenF1 cache dir unavailable (%s): %s", self.cache_dir, exc)
        self._rate_lock = threading.Lock()
        self._last_request_t = 0.0

    # ------------------------------------------------------------------ #
    # Низкий уровень: кэш + сеть
    # ------------------------------------------------------------------ #

    def _cache_path(self, key: str) -> Path:
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _read_cache(self, key: str) -> tuple[list | None, bool]:
        """Вернуть (data, fresh). fresh=False, если кэша нет или он протух."""
        cp = self._cache_path(key)
        if not cp.exists():
            return None, False
        try:
            payload = json.loads(cp.read_text(encoding="utf-8"))
            ts = float(payload.get("ts", 0))
            data = payload.get("data")
        except (OSError, ValueError, TypeError):
            return None, False
        fresh = (time.time() - ts) < (config.OPENF1_TTL_DAYS * 86400.0)
        return data, fresh

    def _write_cache(self, key: str, data) -> None:
        cp = self._cache_path(key)
        try:
            tmp = cp.with_suffix(".tmp")
            tmp.write_text(json.dumps({"ts": time.time(), "data": data},
                                      ensure_ascii=False), encoding="utf-8")
            tmp.replace(cp)
        except OSError as exc:  # noqa: BLE001
            _log.debug("OpenF1 cache write failed (%s): %s", cp, exc)

    def _respect_rate_limit(self) -> None:
        with self._rate_lock:
            wait = config.OPENF1_MIN_INTERVAL - (time.time() - self._last_request_t)
            if wait > 0:
                time.sleep(wait)
            self._last_request_t = time.time()

    def _fetch(self, path: str, params: dict) -> list | None:
        """Один сетевой запрос с retry/backoff. None при неустранимом сбое.
        OpenF1 возвращает JSON-массив записей, не объект."""
        url = f"{self.BASE_URL}/{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        last_err: str | None = None
        for attempt in range(config.OPENF1_MAX_RETRIES):
            self._respect_rate_limit()
            try:
                with urllib.request.urlopen(req, timeout=config.OPENF1_TIMEOUT) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    _log.info("OpenF1 404 for %s — no data", path)
                    return None
                if exc.code not in (429, 500, 502, 503, 504):
                    _log.warning("OpenF1 HTTP %s for %s", exc.code, path)
                    return None
                last_err = f"HTTP {exc.code}"
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_err = str(exc)
            _log.debug("OpenF1 attempt %d/%d failed for %s: %s",
                       attempt + 1, config.OPENF1_MAX_RETRIES, path, last_err)
            if attempt < config.OPENF1_MAX_RETRIES - 1:
                time.sleep(0.5 * (2 ** attempt))
        _log.warning("OpenF1 unreachable for %s after %d attempts: %s",
                     path, config.OPENF1_MAX_RETRIES, last_err)
        return None

    def _get(self, path: str, params: dict) -> list | None:
        """Кэш → (если протух/нет) сеть. При сбое сети отдаём устаревший кэш."""
        key = f"{path}?{urllib.parse.urlencode(sorted(params.items()))}"
        cached, fresh = self._read_cache(key)
        if fresh and cached is not None:
            _log.info("OpenF1 cache hit: %s", key)
            return cached
        data = self._fetch(path, params)
        if data is not None:
            self._write_cache(key, data)
            return data
        if cached is not None:
            _log.info("OpenF1 offline — serving stale cache for %s", key)
            return cached
        return None

    # ------------------------------------------------------------------ #
    # Высокий уровень: session_key + лучшие секторы
    # ------------------------------------------------------------------ #

    def get_session_key(self, year: int, circuit_id: str) -> int | None:
        """Трасса+год → session_key гонки (Race). None — нет в таблице/нет данных."""
        location = self.CIRCUIT_ID_TO_OPENF1_LOCATION.get(circuit_id)
        if not location:
            _log.warning("OpenF1: no session_key mapping for %s/%s", year, circuit_id)
            return None
        sessions = self._get("sessions", {"year": year, "location": location,
                                          "session_name": "Race"})
        if not sessions:
            return None
        return sessions[0].get("session_key")

    def get_best_sectors(self, session_key: int | None) -> dict[int, int] | None:
        """MIN(duration_sector_N) среди валидных кругов гонки. None — нет данных
        ИЛИ хотя бы один сектор ни разу не был валиден (не отдаём частичные данные)."""
        if session_key is None:
            return None
        laps = self._get("laps", {"session_key": session_key})
        if not laps:
            return None
        best: dict[int, float] = {}
        for lap in laps:
            if lap.get("is_pit_out_lap"):
                continue
            for n in (1, 2, 3):
                dur = lap.get(f"duration_sector_{n}")
                if not dur:            # None или 0 — невалидный сектор
                    continue
                if n not in best or dur < best[n]:
                    best[n] = dur
        if len(best) != 3:
            return None
        result = {n: round(ms * 1000) for n, ms in best.items()}
        _log.info("OpenF1 OK: session=%s sectors=%s", session_key, result)
        return result
```

- [ ] **Step 5: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_openf1_client.py -q`
Expected: PASS (10 passed)

- [ ] **Step 6: Checkpoint** — тесты задачи зелёные.

---

## Task 2: Расширение `core/f1_benchmark.py` — секторы + `race_weak_sector`

**Files:**
- Modify: `core/f1_benchmark.py`
- Modify: `tests/test_f1_benchmark.py`

- [ ] **Step 1: Write the failing tests**

Заменить весь файл `tests/test_f1_benchmark.py` на:

```python
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


_UNSET = object()   # отличает «sectors не передан» (дефолт) от явного sectors=None


class _OpenF1:
    def __init__(self, session_key=9161, sectors=_UNSET):
        self._session_key = session_key
        self._sectors = {1: 27000, 2: 38000, 3: 26000} if sectors is _UNSET else sectors
        self.session_calls, self.sector_calls = [], []

    def get_session_key(self, year, circuit):
        self.session_calls.append((year, circuit))
        return self._session_key

    def get_best_sectors(self, session_key):
        self.sector_calls.append(session_key)
        return self._sectors


def test_load_reference_from_fastest_lap_maps_latin_to_ru():
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1())
    assert b.load(11, 2025) is True               # Monza
    assert b.ready
    assert b.reference["driver"] == "Ферстаппен"  # латиница → кириллица
    assert b.reference["source"] == "fastest_lap"
    assert b.reference["event"] == "Italian Grand Prix"


def test_load_falls_back_to_pole_after_trying_both_years():
    c = _Client(fl=None, pole={"driver": "Leclerc", "time_ms": 79800})
    b = F1Benchmark(client=c, openf1_client=_OpenF1())
    assert b.load(11, 2025) is True
    assert b.reference["source"] == "pole"
    assert b.reference["driver"] == "Леклер"
    assert c.fl_calls == [(2025, "monza"), (2024, "monza")]   # fastest пробован за оба года


def test_load_unknown_track_returns_false():
    b = F1Benchmark(client=_Client(fl={"driver": "X", "time_ms": 1}), openf1_client=_OpenF1())
    assert b.load(999, 2025) is False
    assert not b.ready


def test_load_fetches_sectors_after_finding_reference():
    """load() дополнительно тянет OpenF1-секторы после нахождения эталона."""
    openf1 = _OpenF1(session_key=9161, sectors={1: 27000, 2: 38000, 3: 26000})
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=openf1)
    b.load(11, 2025)
    assert b.reference["sector_ms"] == {1: 27000, 2: 38000, 3: 26000}
    assert openf1.session_calls == [(2025, "monza")]
    assert openf1.sector_calls == [9161]


def test_load_sectors_none_does_not_fail_load():
    """OpenF1 не находит данные -> sector_ms=None, но load() всё равно True
    (полный-круга-эталон не зависит от OpenF1)."""
    openf1 = _OpenF1(session_key=None, sectors=None)
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=openf1)
    assert b.load(11, 2025) is True
    assert b.reference["sector_ms"] is None


def test_compare_computes_gap():
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1())
    b.load(11, 2025)
    cmp = b.compare([{"lap": 5, "last_lap_ms": 81346}, {"lap": 6, "last_lap_ms": 0}])
    assert cmp["gap_ms"] == 1500
    assert cmp["player_best_ms"] == 81346
    assert cmp["f1_driver"] == "Ферстаппен"


def test_compare_none_when_not_ready_or_no_laps():
    b = F1Benchmark(client=_Client(fl={"driver": "X", "time_ms": 1}), openf1_client=_OpenF1())
    assert b.compare([{"last_lap_ms": 1000}]) is None      # не загружен
    b.load(11, 2025)
    assert b.compare([]) is None
    assert b.compare([{"last_lap_ms": 0}]) is None


def test_compare_always_has_sectors_key():
    """compare() ВСЕГДА возвращает ключ "sectors" (словарь либо None) — контракт
    для HUD/Voice/Story, без hasattr-проверок у потребителей."""
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1(sectors=None))
    b.load(11, 2025)
    cmp = b.compare([{"lap": 5, "last_lap_ms": 81346}])
    assert "sectors" in cmp
    assert cmp["sectors"] is None


def test_compare_sectors_gap_uses_player_best_lap():
    """Секторный гэп берётся из ТОГО ЖЕ круга, что дал player_best_ms."""
    openf1 = _OpenF1(sectors={1: 27000, 2: 38000, 3: 26000})
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=openf1)
    b.load(11, 2025)
    cmp = b.compare([
        {"lap": 5, "last_lap_ms": 81346, "s1_ms": 27200, "s2_ms": 37800, "s3_ms": 26346},
        {"lap": 6, "last_lap_ms": 90000, "s1_ms": 30000, "s2_ms": 40000, "s3_ms": 20000},
    ])
    assert cmp["player_best_lap"] == 5
    assert cmp["sectors"] == {
        1: {"player_ms": 27200, "gap_ms": 200},
        2: {"player_ms": 37800, "gap_ms": -200},
        3: {"player_ms": 26346, "gap_ms": 346},
    }


def test_compare_sectors_none_when_best_lap_missing_sector_data():
    """Лучший круг без валидных s1/s2/s3 (например, из телеметрии с 0) -> sectors=None,
    полный-круга-гэп при этом считается как обычно."""
    openf1 = _OpenF1(sectors={1: 27000, 2: 38000, 3: 26000})
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=openf1)
    b.load(11, 2025)
    cmp = b.compare([{"lap": 5, "last_lap_ms": 81346, "s1_ms": 0, "s2_ms": 0, "s3_ms": 0}])
    assert cmp["gap_ms"] == 1500
    assert cmp["sectors"] is None


def test_lines_use_genitive_and_source_word():
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1())
    b.load(11, 2025)
    cmp = b.compare([{"lap": 5, "last_lap_ms": 81346}])
    assert "Ферстаппена" in b.context_line(cmp) and "быстрейший круг" in b.context_line(cmp)
    assert "Ферстаппена" in b.pb_line(cmp) and "рекорд" in b.pb_line(cmp).lower()


def test_pole_source_changes_wording():
    b = F1Benchmark(client=_Client(fl=None, pole={"driver": "Leclerc", "time_ms": 79800}),
                    openf1_client=_OpenF1())
    b.load(11, 2025)
    cmp = b.compare([{"lap": 3, "last_lap_ms": 80000}])
    assert "поул" in b.context_line(cmp)


def test_reset_clears():
    b = F1Benchmark(client=_Client(fl={"driver": "X", "time_ms": 1}), openf1_client=_OpenF1())
    b.load(11, 2025)
    b.reset()
    assert not b.ready


def test_sector_pb_line_faster_than_reference():
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1())
    b.load(11, 2025)
    line = b.sector_pb_line(2, {"player_ms": 37800, "gap_ms": -200})
    assert "Сектор 2" in line and "быстрее" in line.lower()


def test_sector_pb_line_slower_than_reference():
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1())
    b.load(11, 2025)
    line = b.sector_pb_line(1, {"player_ms": 27200, "gap_ms": 200})
    assert "Сектор 1" in line and "отставание" in line.lower()


def test_race_weak_sector_picks_largest_average_gap():
    openf1 = _OpenF1(sectors={1: 27000, 2: 38000, 3: 26000})
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=openf1)
    b.load(11, 2025)
    laps = [
        {"s1_ms": 27100, "s2_ms": 39500, "s3_ms": 26050},   # s2 гэп +1500
        {"s1_ms": 27050, "s2_ms": 39000, "s3_ms": 26100},   # s2 гэп +1000
    ]
    assert b.race_weak_sector(laps) == 2


def test_race_weak_sector_none_without_reference_sectors():
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1(sectors=None))
    b.load(11, 2025)
    assert b.race_weak_sector([{"s1_ms": 27000, "s2_ms": 38000, "s3_ms": 26000}]) is None


def test_race_weak_sector_none_without_valid_laps():
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1())
    b.load(11, 2025)
    assert b.race_weak_sector([{"s1_ms": 0, "s2_ms": 0, "s3_ms": 0}]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_f1_benchmark.py -q`
Expected: FAIL — `TypeError: F1Benchmark.__init__() got an unexpected keyword argument 'openf1_client'`

- [ ] **Step 3: Implement**

Заменить весь файл `core/f1_benchmark.py` на:

```python
"""
core/f1_benchmark.py
====================
Живой бенчмарк темпа игрока против РЕАЛЬНОГО F1 (killer-фича #2).

Эталон — быстрейший круг реального GP этой трассы из Jolpica (фолбэк — поул).
Сравнение по ВРЕМЕНИ КРУГА (Ergast не отдаёт сектора). Секторный эталон — ОТДЕЛЬНО,
из OpenF1 («лучшие секторы гонки», не привязаны к тому же пилоту/кругу, что и
полный-круга-эталон — см. design spec docs/superpowers/specs/2026-07-02-f1-sector-benchmark-design.md).
Чистый юнит: хранит эталон и считает гэп; сеть только в `load` (engine зовёт её в фоновом потоке).

Ergast отдаёт ЛАТИНСКИЕ фамилии — мапим в кириллицу (_LATIN_TO_RU) перед склонением
через core.ru_names, иначе TTS произнесёт латиницу и без падежа.
"""
from __future__ import annotations

import logging

from analytics.loader import TRACK_ID_TO_GP
from core.ergast_client import JolpicaClient
from core.ru_names import decline

_log = logging.getLogger(__name__)

# track_id (m_trackId, фиксированный enum игры — см. analytics/loader.TRACK_ID_TO_GP)
# → ergast circuitId. Только текущий календарь; legacy-трассы (Paul Ricard/Hockenheim/
# Sochi/Hanoi/short-варианты) сюда не включены — load() для них корректно вернёт False.
TRACK_ID_TO_CIRCUIT: dict[int, str] = {
    0: "albert_park", 2: "shanghai", 3: "bahrain", 4: "catalunya", 5: "monaco",
    6: "villeneuve", 7: "silverstone", 9: "hungaroring", 10: "spa", 11: "monza",
    12: "marina_bay", 13: "suzuka", 14: "yas_marina", 15: "americas",
    16: "interlagos", 17: "red_bull_ring", 19: "rodriguez", 20: "baku",
    26: "zandvoort", 27: "imola", 29: "jeddah", 30: "miami", 31: "vegas",
    32: "losail",
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
    def __init__(self, client=None, openf1_client=None):
        self._client = client
        self._openf1_client = openf1_client
        self.reference: dict | None = None

    @property
    def _c(self):
        if self._client is None:
            self._client = JolpicaClient()
        return self._client

    @property
    def _openf1(self):
        if self._openf1_client is None:
            from core.openf1_client import OpenF1Client
            self._openf1_client = OpenF1Client()
        return self._openf1_client

    @property
    def ready(self) -> bool:
        return self.reference is not None

    def reset(self) -> None:
        self.reference = None

    def load(self, track_id: int, year: int) -> bool:
        """Загрузить эталон трассы: fastest lap (year, year-1), иначе поул. True если найден.
        Дополнительно (не критично для основного результата) тянет секторный эталон
        из OpenF1 — сбой не влияет на возврат True/False (см. _load_sectors)."""
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
                self._load_sectors(circuit, y)
                return True
        for y in years:
            pole = self._c.get_circuit_pole(y, circuit)
            if pole:
                self.reference = {"driver": _ru_driver(pole["driver"]), "time_ms": pole["time_ms"],
                                  "year": y, "event": event, "source": "pole"}
                self._load_sectors(circuit, y)
                return True
        return False

    def _load_sectors(self, circuit: str, year: int) -> None:
        """Секторный эталон OpenF1 — надстройка поверх основного эталона.
        OpenF1Client сам гасит сетевые сбои (возвращает None) — здесь просто трансляция
        в self.reference["sector_ms"]."""
        session_key = self._openf1.get_session_key(year, circuit)
        self.reference["sector_ms"] = self._openf1.get_best_sectors(session_key)

    def compare(self, player_laps: list[dict]) -> dict | None:
        """Гэп лучшего круга игрока к эталону. None если не готов / нет валидных кругов.
        Ключ "sectors" присутствует ВСЕГДА (словарь либо None) — контракт для
        HUD/Voice/Story, чтобы не делать hasattr-проверки у потребителей."""
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
            "sectors": self._sector_gaps(best, ref.get("sector_ms")),
        }

    def _sector_gaps(self, best_lap: dict, ref_sectors: dict[int, int] | None) -> dict | None:
        """Посекторный гэп ЛУЧШЕГО круга игрока (тот же круг, что дал player_best_ms)
        к эталонным секторам. None — эталонных секторов нет ИЛИ у лучшего круга
        игрока нет валидных s1/s2/s3 (не отдаём частичные/вводящие в заблуждение данные)."""
        if not ref_sectors:
            return None
        player = {1: best_lap.get("s1_ms"), 2: best_lap.get("s2_ms"), 3: best_lap.get("s3_ms")}
        if any(not player[n] for n in (1, 2, 3)):
            return None
        return {n: {"player_ms": player[n], "gap_ms": player[n] - ref_sectors[n]}
                for n in (1, 2, 3)}

    def race_weak_sector(self, player_laps: list[dict]) -> int | None:
        """Сектор с наибольшим СРЕДНИМ гэпом к эталону среди кругов гонки (для
        Post-Race Story: weak_sector_vs_f1 — НЕ то же самое, что coach_ai.weak_sector,
        который про собственный темп игрока, а не про реальный F1). None — эталонных
        секторов нет ИЛИ ни один круг не дал валидных s1/s2/s3."""
        ref_sectors = (self.reference or {}).get("sector_ms")
        if not ref_sectors:
            return None
        totals = {1: 0, 2: 0, 3: 0}
        counts = {1: 0, 2: 0, 3: 0}
        for lap in player_laps:
            for n in (1, 2, 3):
                v = lap.get(f"s{n}_ms")
                if v:
                    totals[n] += v - ref_sectors[n]
                    counts[n] += 1
        if not all(counts.values()):
            return None
        avg_gap = {n: totals[n] / counts[n] for n in (1, 2, 3)}
        return max(avg_gap, key=lambda n: avg_gap[n])

    def _ref_word(self) -> str:
        return "поул" if (self.reference or {}).get("source") == "pole" else "быстрейший круг"

    def context_line(self, cmp: dict) -> str:
        """Строка-сверка для контекста LLM (не озвучивается напрямую)."""
        drv = decline(cmp["f1_driver"], "gen")
        return (f"Эталон трассы — {self._ref_word()} {drv} {_fmt_lap(cmp['f1_time_ms'])} "
                f"({cmp['event']}). Твой лучший {_fmt_lap(cmp['player_best_ms'])}, "
                f"отставание {cmp['gap_ms'] / 1000.0:.1f}с.")

    def pb_line(self, cmp: dict) -> str:
        """Озвучиваемая реплика на личном рекорде круга (гэп словами, без сырого времени круга)."""
        drv = decline(cmp["f1_driver"], "gen")
        gap = cmp["gap_ms"] / 1000.0
        if gap >= 0:
            return f"Личный рекорд круга! Отставание {gap:.1f} секунды от {self._ref_word()} {drv}."
        return f"Личный рекорд круга! Ты быстрее {self._ref_word()} {drv} на {abs(gap):.1f} секунды!"

    def sector_pb_line(self, sector_n: int, sector_cmp: dict) -> str:
        """Озвучиваемая реплика на личном рекорде СЕКТОРА (не путать с pb_line — там полный круг)."""
        gap = sector_cmp["gap_ms"] / 1000.0
        if gap >= 0:
            return (f"Сектор {sector_n} — твой лучший в сессии, "
                    f"отставание {gap:.1f} секунды от эталона гонки.")
        return (f"Сектор {sector_n} — твой лучший в сессии, "
                f"ты быстрее эталона гонки на {abs(gap):.1f} секунды!")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_f1_benchmark.py -q`
Expected: PASS (18 passed)

- [ ] **Step 5: Checkpoint** — тесты задачи зелёные.

---

## Task 3: `core/engine.py` — анти-спам реплика по сектору

**Files:**
- Modify: `core/engine.py`
- Modify: `tests/test_engine_f1_benchmark.py`

- [ ] **Step 1: Write the failing tests**

Заменить весь файл `tests/test_engine_f1_benchmark.py` на:

```python
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

    def __init__(self, sectors=None):
        self._sectors = sectors

    def compare(self, laps):
        return {"gap_ms": 1500, "player_best_ms": 81346, "player_best_lap": 5,
                "f1_time_ms": 79846, "f1_driver": "Ферстаппен",
                "event": "Italian Grand Prix", "year": 2025, "source": "fastest_lap",
                "sectors": self._sectors}

    def context_line(self, cmp):
        return "Эталон трассы — быстрейший круг Ферстаппена 1:19.846."

    def pb_line(self, cmp):
        return "Личный рекорд круга! Отставание полторы секунды от быстрейшего круга Ферстаппена."

    def sector_pb_line(self, n, s):
        return f"Сектор {n} — твой лучший в сессии."


def _drain(engine):
    events = []
    while not engine.event_queue.empty():
        events.append(engine.event_queue.get_nowait())
    return events


def test_f1_bench_event_routes_to_commentary():
    assert route_event({"event_code": "F1_BENCH"}, "race") == CHANNEL_COMMENTARY


def test_f1_sector_bench_event_routes_to_commentary():
    assert route_event({"event_code": "F1_SECTOR_BENCH"}, "race") == CHANNEL_COMMENTARY


def test_update_sets_hud_context_and_pb_event(engine):
    engine.f1_benchmark = _FakeBench()
    engine._f1_best_ms = None
    engine._f1_best_sector_ms = {}
    _drain(engine)
    engine._update_f1_benchmark()
    hud = engine.get_state().get("f1_benchmark")
    assert hud is not None and hud["gap_ms"] == 1500 and hud["f1_driver"] == "Ферстаппен"
    assert hud["sectors"] is None                            # без секторов в этой фикстуре
    assert engine.commentator.analytics_context              # контекст обновлён
    evt = engine.event_queue.get_nowait()                    # PB-событие (полный круг)
    assert evt["event_code"] == "F1_BENCH" and evt["phrase"]


def test_no_double_pb_when_not_improved(engine):
    engine.f1_benchmark = _FakeBench()
    engine._f1_best_ms = 81346                                # тот же best уже зафиксирован
    engine._f1_best_sector_ms = {}
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


def test_sector_pb_fires_on_first_improvement(engine):
    """Холодный старт: первый круг сессии — все секторы считаются PB."""
    sectors = {1: {"player_ms": 27000, "gap_ms": -200}, 2: {"player_ms": 38000, "gap_ms": 100},
               3: {"player_ms": 26000, "gap_ms": 50}}
    engine.f1_benchmark = _FakeBench(sectors=sectors)
    engine._f1_best_ms = None
    engine._f1_best_sector_ms = {}
    _drain(engine)
    engine._update_f1_benchmark()
    events = _drain(engine)
    sector_events = [e for e in events if e["event_code"] == "F1_SECTOR_BENCH"]
    assert len(sector_events) == 1
    assert engine._f1_best_sector_ms == {1: 27000, 2: 38000, 3: 26000}


def test_sector_pb_picks_smallest_gap_when_multiple_improve(engine):
    """Несколько PB-секторов в одном круге -> ОДНА реплика, про наименьший gap_ms
    (ближе всего к/лучше реального F1 — самое впечатляющее достижение)."""
    sectors = {1: {"player_ms": 27000, "gap_ms": 500}, 2: {"player_ms": 38000, "gap_ms": -300},
               3: {"player_ms": 26000, "gap_ms": 200}}
    engine.f1_benchmark = _FakeBench(sectors=sectors)
    engine._f1_best_ms = None
    engine._f1_best_sector_ms = {}
    _drain(engine)
    engine._update_f1_benchmark()
    events = _drain(engine)
    sector_events = [e for e in events if e["event_code"] == "F1_SECTOR_BENCH"]
    assert len(sector_events) == 1
    assert "Сектор 2" in sector_events[0]["phrase"]        # наименьший gap_ms (-300)


def test_sector_pb_silent_when_not_improved(engine):
    sectors = {1: {"player_ms": 27000, "gap_ms": 500}, 2: {"player_ms": 38000, "gap_ms": -300},
               3: {"player_ms": 26000, "gap_ms": 200}}
    engine.f1_benchmark = _FakeBench(sectors=sectors)
    engine._f1_best_ms = 81346
    engine._f1_best_sector_ms = {1: 27000, 2: 38000, 3: 26000}   # уже лучшие — не улучшены
    _drain(engine)
    engine._update_f1_benchmark()
    assert engine.event_queue.empty()


def test_sector_pb_absent_when_sectors_none(engine):
    """compare()["sectors"] is None -> без секторной реплики, полный бенчмарк не трогаем."""
    engine.f1_benchmark = _FakeBench(sectors=None)
    engine._f1_best_ms = None
    engine._f1_best_sector_ms = {}
    _drain(engine)
    engine._update_f1_benchmark()
    events = _drain(engine)
    assert all(e["event_code"] != "F1_SECTOR_BENCH" for e in events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_engine_f1_benchmark.py -q`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute '_f1_best_sector_ms'`

- [ ] **Step 3: Implement — add `_f1_best_sector_ms` state**

В `core/engine.py`, найти:

```python
        # Real-F1 Benchmark (live)
        self.f1_benchmark = F1Benchmark()
        self._f1_best_ms: int | None = None
```

Заменить на:

```python
        # Real-F1 Benchmark (live)
        self.f1_benchmark = F1Benchmark()
        self._f1_best_ms: int | None = None
        self._f1_best_sector_ms: dict[int, int] = {}
```

- [ ] **Step 4: Implement — reset on track change**

Найти:

```python
                    self._track_manager = TrackManager(track_info) if track_info else None
                    self.f1_benchmark.reset()
                    self._f1_best_ms = None
                    self._start_f1_benchmark_load(new_tid)
```

Заменить на:

```python
                    self._track_manager = TrackManager(track_info) if track_info else None
                    self.f1_benchmark.reset()
                    self._f1_best_ms = None
                    self._f1_best_sector_ms = {}
                    self._start_f1_benchmark_load(new_tid)
```

- [ ] **Step 5: Implement — reset on SSTA**

Найти:

```python
                self.story_collector.reset()
                self._story_fired = False
                self._f1_best_ms = None
                with self.state_lock:
                    self.state["race_story"] = None
```

Заменить на:

```python
                self.story_collector.reset()
                self._story_fired = False
                self._f1_best_ms = None
                self._f1_best_sector_ms = {}
                with self.state_lock:
                    self.state["race_story"] = None
```

- [ ] **Step 6: Implement — extend `_update_f1_benchmark`**

Найти весь метод:

```python
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

Заменить на:

```python
    def _update_f1_benchmark(self) -> None:
        """Каждый завершённый круг: гэп к эталону → HUD + контекст; на личном рекорде —
        озвучка. Секторы (cmp["sectors"]) — независимая надстройка, может быть None."""
        if not self.f1_benchmark.ready:
            return
        cmp = self.f1_benchmark.compare(self.recorder.laps())
        if cmp is None:
            return
        with self.state_lock:
            self.state["f1_benchmark"] = {
                "gap_ms": cmp["gap_ms"], "f1_driver": cmp["f1_driver"],
                "f1_time_ms": cmp["f1_time_ms"], "player_best_ms": cmp["player_best_ms"],
                "event": cmp["event"], "year": cmp["year"], "source": cmp["source"],
                "sectors": cmp["sectors"]}
        self.set_analytics_context(self.f1_benchmark.context_line(cmp))
        if self._f1_best_ms is None or cmp["player_best_ms"] < self._f1_best_ms:
            self._f1_best_ms = cmp["player_best_ms"]
            self.event_queue.put({
                "event_code": "F1_BENCH", "priority": "normal",
                "phrase": self.f1_benchmark.pb_line(cmp),
                "color": "#34D399", "driver": ""})
        if cmp["sectors"] is not None:
            improved: list[int] = []
            for n, s in cmp["sectors"].items():
                best_so_far = self._f1_best_sector_ms.get(n)
                if best_so_far is None or s["player_ms"] < best_so_far:
                    self._f1_best_sector_ms[n] = s["player_ms"]
                    improved.append(n)
            if improved:
                # несколько PB-секторов в одном круге -> говорим ОДИН раз, про сектор
                # с наименьшим gap_ms (самое впечатляющее достижение относительно
                # реального F1, а не просто самый большой числовой прогресс)
                best_n = min(improved, key=lambda n: cmp["sectors"][n]["gap_ms"])
                self.event_queue.put({
                    "event_code": "F1_SECTOR_BENCH", "priority": "normal",
                    "phrase": self.f1_benchmark.sector_pb_line(best_n, cmp["sectors"][best_n]),
                    "color": "#34D399", "driver": ""})
```

- [ ] **Step 7: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_engine_f1_benchmark.py -q`
Expected: PASS (9 passed)

- [ ] **Step 8: Regression check**

Run: `py -3.12 -m pytest tests/test_engine_story.py tests/test_engine_ambient.py tests/test_engine_health.py tests/test_engine_voice.py tests/test_engine_settings.py -q`
Expected: PASS (без изменений в счёте)

- [ ] **Step 9: Checkpoint** — тесты задачи и регрессии зелёные.

---

## Task 4: Post-Race Story — `weak_sector_vs_f1`

**Files:**
- Modify: `core/race_story.py`
- Modify: `commentator/story.py`
- Modify: `core/engine.py`
- Modify: `tests/test_story_collector.py`
- Modify: `tests/test_story_generator.py`

- [ ] **Step 1: Write the failing tests**

Добавить в конец `tests/test_story_collector.py`:

```python
def test_facts_includes_weak_sector_vs_f1():
    from core.race_story import RaceStoryCollector
    c = RaceStoryCollector()
    facts = c.facts(final_position=4, laps=[], weak_sector_vs_f1=2)
    assert facts["weak_sector_vs_f1"] == 2


def test_facts_weak_sector_vs_f1_defaults_to_none():
    from core.race_story import RaceStoryCollector
    c = RaceStoryCollector()
    facts = c.facts(final_position=4, laps=[])
    assert facts["weak_sector_vs_f1"] is None
```

Добавить в конец `tests/test_story_generator.py`:

```python
def test_format_facts_includes_weak_sector_vs_f1():
    from commentator.story import build_prompt
    facts = {"weak_sector_vs_f1": 3}
    prompt = build_prompt(facts, "tv")
    assert "S3" in prompt and "эталона F1" in prompt


def test_format_facts_omits_weak_sector_vs_f1_when_none():
    from commentator.story import build_prompt
    facts = {"weak_sector_vs_f1": None}
    prompt = build_prompt(facts, "tv")
    assert "эталона F1" not in prompt
```

**Примечание:** если существующие тесты в `tests/test_story_collector.py`/`tests/test_story_generator.py`
уже вызывают `RaceStoryCollector.facts(...)`/`build_prompt(...)` без `weak_sector_vs_f1` — они НЕ
должны сломаться (новый параметр опциональный, дефолт `None`). Прочитать оба файла целиком перед
правкой, чтобы не продублировать существующие тестовые классы/фикстуры.

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_story_collector.py tests/test_story_generator.py -q`
Expected: FAIL — `TypeError: facts() got an unexpected keyword argument 'weak_sector_vs_f1'`

- [ ] **Step 3: Implement `core/race_story.py`**

Найти сигнатуру и конец метода `facts`:

```python
    def facts(self, *, final_position: int | None, laps: list[dict],
              coach_state: dict | None = None, leader_name: str | None = None,
              total_laps: int | None = None, track: str | None = None) -> dict:
        """Свести накопленное + финальные данные в плоский факт-блок для LLM."""
```

Заменить на:

```python
    def facts(self, *, final_position: int | None, laps: list[dict],
              coach_state: dict | None = None, leader_name: str | None = None,
              total_laps: int | None = None, track: str | None = None,
              weak_sector_vs_f1: int | None = None) -> dict:
        """Свести накопленное + финальные данные в плоский факт-блок для LLM."""
```

Найти строку возврата:

```python
            "weak_sector": coach.get("weak_sector"),
            "consistency": coach.get("consistency_score"),
```

Заменить на:

```python
            "weak_sector": coach.get("weak_sector"),
            "weak_sector_vs_f1": weak_sector_vs_f1,
            "consistency": coach.get("consistency_score"),
```

- [ ] **Step 4: Implement `commentator/story.py`**

Найти:

```python
    if facts.get("weak_sector"):
        L.append(f"- Слабый сектор: S{facts['weak_sector']}")
```

Заменить на:

```python
    if facts.get("weak_sector"):
        L.append(f"- Слабый сектор: S{facts['weak_sector']}")
    if facts.get("weak_sector_vs_f1"):
        L.append(f"- Слабее эталона F1 в секторе: S{facts['weak_sector_vs_f1']}")
```

- [ ] **Step 5: Implement `core/engine.py` — прокинуть в `_generate_story`**

Найти в `_generate_story`:

```python
            track = TRACK_ID_TO_GP.get(self._track_id, ("Unknown",))[0]
            facts = self.story_collector.facts(
                final_position=final_pos, laps=self.recorder.laps(),
                coach_state=coach, leader_name=self._leader_name,
                total_laps=getattr(self, "_total_laps", None), track=track)
```

Заменить на:

```python
            track = TRACK_ID_TO_GP.get(self._track_id, ("Unknown",))[0]
            weak_sector_vs_f1 = self.f1_benchmark.race_weak_sector(self.recorder.laps())
            facts = self.story_collector.facts(
                final_position=final_pos, laps=self.recorder.laps(),
                coach_state=coach, leader_name=self._leader_name,
                total_laps=getattr(self, "_total_laps", None), track=track,
                weak_sector_vs_f1=weak_sector_vs_f1)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_story_collector.py tests/test_story_generator.py -q`
Expected: PASS (все тесты файлов, включая новые)

- [ ] **Step 7: Regression check**

Run: `py -3.12 -m pytest tests/test_engine_story.py -q`
Expected: PASS (без изменений в счёте — `f1_benchmark.race_weak_sector` на дефолтном
`F1Benchmark()` без загруженного эталона просто вернёт `None`, как и раньше без этого поля)

- [ ] **Step 8: Checkpoint** — тесты задачи и регрессии зелёные.

---

## Task 5: UI — секторные чипы в HUD

**Files:**
- Modify: `NewSpotterUI/lib/api.ts`
- Modify: `NewSpotterUI/components/spotter/views/race.tsx`

- [ ] **Step 1: `lib/api.ts` — расширить тип**

**Важно:** `cmp["sectors"]` в Python — словарь с INT-ключами (`{1: {...}, 2: {...}, 3: {...}}`),
но `json.dumps`/HTTP-ответ сериализует ключи словаря в СТРОКИ (`{"1": {...}, "2": {...}, "3": {...}}`).
Поэтому тип на фронте — `Record<"1"|"2"|"3", ...>`, не `Record<1|2|3, ...>`; обращение к
`sectors["1"]`, а не `sectors[1]` (последнее в рантайме тоже сработает благодаря JS coercion, но
тип объявлен строковыми литералами для честности с реальным JSON).

Найти:

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

Заменить на:

```typescript
export type F1SectorGap = { player_ms: number; gap_ms: number }

export type F1BenchmarkState = {
  gap_ms: number
  f1_driver: string
  f1_time_ms: number
  player_best_ms: number
  event: string | null
  year: number | null
  source: "fastest_lap" | "pole"
  sectors: Record<"1" | "2" | "3", F1SectorGap> | null
}
```

- [ ] **Step 2: `race.tsx` — производное значение**

Найти:

```tsx
  const bench = state?.f1_benchmark ?? null
```

Заменить на:

```tsx
  const bench = state?.f1_benchmark ?? null
  const sectors = bench?.sectors ?? null
```

- [ ] **Step 3: `race.tsx` — чипы секторов**

Найти:

```tsx
                  <p className={cn(
                    "font-heading text-lg font-bold tabular",
                    bench.gap_ms <= 0 ? "text-success" : "text-foreground",
                  )}>
                    {bench.gap_ms <= 0 ? "−" : "+"}
                    {(Math.abs(bench.gap_ms) / 1000).toFixed(1)}с
                  </p>
                </div>
```

Заменить на:

```tsx
                  <p className={cn(
                    "font-heading text-lg font-bold tabular",
                    bench.gap_ms <= 0 ? "text-success" : "text-foreground",
                  )}>
                    {bench.gap_ms <= 0 ? "−" : "+"}
                    {(Math.abs(bench.gap_ms) / 1000).toFixed(1)}с
                  </p>
                  {sectors && (
                    <div className="mt-2 flex gap-1.5">
                      {(["1", "2", "3"] as const).map((n) => {
                        const s = sectors[n]
                        return (
                          <div
                            key={n}
                            className={cn(
                              "flex-1 rounded px-1.5 py-1 text-center",
                              s.gap_ms <= 0
                                ? "bg-success/15 text-success"
                                : "bg-secondary/60 text-muted-foreground",
                            )}
                          >
                            <p className="font-mono text-[9px]">S{n}</p>
                            <p className="text-[11px] font-semibold tabular">
                              {s.gap_ms <= 0 ? "−" : "+"}
                              {(Math.abs(s.gap_ms) / 1000).toFixed(2)}
                            </p>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
```

- [ ] **Step 4: Typecheck**

Run: `cd NewSpotterUI && npx tsc --noEmit`
Expected: без ошибок типов

- [ ] **Step 5: Checkpoint** — tsc чист.

---

## Task 6: Полная верификация + CONTEXT.md

**Files:**
- Modify: `CONTEXT.md`

- [ ] **Step 1: Полный прогон тестов**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: все тесты проходят (текущий бейслайн 671 + новые из Tasks 1–4: 10 openf1_client +
8 новых/расширенных f1_benchmark + 5 новых engine_f1_benchmark + 4 story ≈ +27, точное число —
по факту прогона). **Если итоговая строка не пропечаталась (Windows-гочта, см. CONTEXT.md) —
считать через `grep -o '[.sF]' <лог> | sort | uniq -c`.**

- [ ] **Step 2: Полный typecheck**

Run: `cd NewSpotterUI && npx tsc --noEmit`
Expected: чисто

- [ ] **Step 3: Import smoke**

Run: `py -3.12 -c "import core.engine, core.openf1_client, core.f1_benchmark, core.race_story, commentator.story"`
Expected: без ошибок

- [ ] **Step 4: Обновить CONTEXT.md**

В раздел «На чём остановились» дописать новую сессию: что сделано (6 задач, файлы), новый
тест-бейслайн (671 → N), явно отметить — секторный эталон OpenF1 независим от полного-круга
эталона Ergast/Jolpica (не тот же пилот/круг, осознанное решение), анти-спам реплики по сектору
(как и у pb_line — только на личном рекорде), `weak_sector_vs_f1` НЕ путать с `weak_sector`
(coach_ai). Обновить счётчик задач сессии.

- [ ] **Step 5: Checkpoint** — полный прогон зелёный, CONTEXT.md обновлён.
