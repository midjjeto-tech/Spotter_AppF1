# Career Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сравнение игрока с СОБСТВЕННОЙ историей на трассе — HUD-панель «Личный рекорд трассы», голосовые реплики на новом личном рекорде (круг+сектор), факт «прогресс с прошлого визита» в Post-Race Story.

**Architecture:** Новый `core/career_memory.py` (зеркалит `core/f1_benchmark.py` по форме, источник — локальный архив `analytics/archive.py`, без сети/кэша). Две независимые метрики: `best_ever` (фиксированная цель для HUD/голоса) и `last_visit` (для Story-нарратива «прогресс с прошлого раза»). Те же триггеры, что у Real-F1 Benchmark (смена трассы → фоновая загрузка; завершённый круг → сравнение).

**Tech Stack:** Python 3.12, стандартная библиотека (только диск, никакой сети), pytest; фронт — Next/React (`NewSpotterUI`).

> ⚠️ **Репозиторий НЕ под git** (`Is a git repository: false`). Шаги «Commit» заменены на **Checkpoint** — прогон тестов задачи. Команды тестов: `py -3.12 -m pytest ... -q`.

**Спека:** [`docs/superpowers/specs/2026-07-03-career-memory-design.md`](../specs/2026-07-03-career-memory-design.md).

---

## Файловая структура

| Файл | Действие | Ответственность |
|------|----------|-----------------|
| `analytics/archive.py` | изменить | `list_game_sessions()` — добавить `track_id` в сводку |
| `core/career_memory.py` | создать | `CareerMemory` — `load`/`compare`/`pb_line`/`sector_pb_line`/`story_facts`/`context_line` |
| `core/engine.py` | изменить | `career_memory`, анти-спам PB (круг+сектор), объединение `analytics_context` (F1+Career), `vs_last_visit` в Story |
| `core/race_story.py` | изменить | `facts(vs_last_visit=...)` |
| `commentator/story.py` | изменить | `_format_facts` — новая строка `vs_last_visit` |
| `NewSpotterUI/lib/api.ts` | изменить | `CareerMemoryState` |
| `NewSpotterUI/components/spotter/views/race.tsx` | изменить | панель «Личный рекорд трассы» |
| `tests/test_archive_sessions.py` | изменить | +тест `track_id` в сводке |
| `tests/test_career_memory.py` | создать | |
| `tests/test_engine_career_memory.py` | создать | |
| `tests/test_story_collector.py` | изменить | +`vs_last_visit` |
| `tests/test_story_generator.py` | изменить | +строка в `_format_facts` |

---

## Task 1: `analytics/archive.py` — `track_id` в сводке сессий

**Files:**
- Modify: `analytics/archive.py`
- Modify: `tests/test_archive_sessions.py`

- [ ] **Step 1: Write the failing test**

Добавить в конец `tests/test_archive_sessions.py`:

```python
def test_list_includes_track_id(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    archive._atomic_write(tmp_path / "a.json",
                          {"track_name": "Monza", "track_id": 11, "session_type": "race"})
    archive._atomic_write(tmp_path / "b.json",
                          {"track_name": "NoId", "session_type": "race"})   # старая запись без track_id
    out = {s["track_name"]: s["track_id"] for s in archive.list_game_sessions()}
    assert out["Monza"] == 11
    assert out["NoId"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_archive_sessions.py -q`
Expected: FAIL — `KeyError: 'track_id'`

- [ ] **Step 3: Implement**

В `analytics/archive.py`, найти в `list_game_sessions()`:

```python
        result.append({
            "path": str(f),
            "track_name": d.get("track_name"),
            "timestamp": d.get("timestamp"),
            "final_position": d.get("final_position"),
            "game_year": d.get("game_year"),
            "session_type": _normalize_session_type(d.get("session_type")),
        })
```

Заменить на:

```python
        result.append({
            "path": str(f),
            "track_name": d.get("track_name"),
            "track_id": d.get("track_id"),
            "timestamp": d.get("timestamp"),
            "final_position": d.get("final_position"),
            "game_year": d.get("game_year"),
            "session_type": _normalize_session_type(d.get("session_type")),
        })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_archive_sessions.py -q`
Expected: PASS (все тесты файла, включая новый)

- [ ] **Step 5: Checkpoint** — тесты задачи зелёные.

---

## Task 2: `core/career_memory.py` — `CareerMemory`

**Files:**
- Create: `core/career_memory.py`
- Test: `tests/test_career_memory.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_career_memory.py
from analytics import archive
from core.career_memory import CareerMemory


def _write_session(tmp_path, name, *, track_id, session_type="race",
                   final_position=None, timestamp=None, player_laps=None):
    archive._atomic_write(tmp_path / name, {
        "track_id": track_id, "session_type": session_type,
        "final_position": final_position, "timestamp": timestamp,
        "player_laps": player_laps or [],
    })


def test_load_no_history_returns_false(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    cm = CareerMemory()
    assert cm.load(11) is False
    assert not cm.ready


def test_load_ignores_other_tracks(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    _write_session(tmp_path, "a.json", track_id=99, final_position=1,
                   timestamp="2026-01-01T10:00:00",
                   player_laps=[{"lap": 1, "last_lap_ms": 70000}])
    cm = CareerMemory()
    assert cm.load(11) is False


def test_load_ignores_non_race_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    _write_session(tmp_path, "a.json", track_id=11, session_type="practice",
                   final_position=1, timestamp="2026-01-01T10:00:00",
                   player_laps=[{"lap": 1, "last_lap_ms": 70000}])
    cm = CareerMemory()
    assert cm.load(11) is False


def test_load_best_ever_is_global_minimum_across_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    _write_session(tmp_path, "1_old.json", track_id=11, final_position=5,
                   timestamp="2026-01-01T10:00:00",
                   player_laps=[{"lap": 1, "last_lap_ms": 81000,
                                "s1_ms": 27000, "s2_ms": 28000, "s3_ms": 26000}])
    _write_session(tmp_path, "2_new.json", track_id=11, final_position=3,
                   timestamp="2026-02-01T10:00:00",
                   player_laps=[{"lap": 1, "last_lap_ms": 80000,
                                "s1_ms": 26500, "s2_ms": 27500, "s3_ms": 26000}])
    cm = CareerMemory()
    assert cm.load(11) is True
    assert cm.reference["best_ever"]["lap_ms"] == 80000
    assert cm.reference["best_ever"]["sector_ms"] == {1: 26500, 2: 27500, 3: 26000}


def test_load_last_visit_is_most_recent_not_fastest(tmp_path, monkeypatch):
    """last_visit — САМАЯ НОВАЯ сессия, даже если она была МЕДЛЕННЕЕ старой."""
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    _write_session(tmp_path, "1_old_fast.json", track_id=11, final_position=2,
                   timestamp="2026-01-01T10:00:00",
                   player_laps=[{"lap": 1, "last_lap_ms": 79000}])
    _write_session(tmp_path, "2_new_slow.json", track_id=11, final_position=7,
                   timestamp="2026-02-01T10:00:00",
                   player_laps=[{"lap": 1, "last_lap_ms": 85000}])
    cm = CareerMemory()
    cm.load(11)
    assert cm.reference["last_visit"]["best_lap_ms"] == 85000
    assert cm.reference["last_visit"]["final_position"] == 7
    assert cm.reference["best_ever"]["lap_ms"] == 79000


def test_load_best_ever_sector_ms_none_when_fastest_lap_missing_sectors(tmp_path, monkeypatch):
    """Лучший ИСТОРИЧЕСКИЙ круг может быть без валидных s1/s2/s3 (старый формат сессии
    / телеметрия оборвалась) — sector_ms деградирует в None, а не в частичный словарь."""
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    _write_session(tmp_path, "a.json", track_id=11, final_position=1,
                   timestamp="2026-01-01T10:00:00",
                   player_laps=[{"lap": 1, "last_lap_ms": 80000}])   # без s1/s2/s3
    cm = CareerMemory()
    assert cm.load(11) is True
    assert cm.reference["best_ever"]["lap_ms"] == 80000
    assert cm.reference["best_ever"]["sector_ms"] is None


def test_load_skips_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    (tmp_path / "corrupt.json").write_text("NOT JSON", encoding="utf-8")
    _write_session(tmp_path, "good.json", track_id=11, final_position=1,
                   timestamp="2026-01-01T10:00:00",
                   player_laps=[{"lap": 1, "last_lap_ms": 80000}])
    cm = CareerMemory()
    assert cm.load(11) is True
    assert cm.reference["best_ever"]["lap_ms"] == 80000


def test_compare_always_has_sectors_key():
    cm = CareerMemory()
    cm.reference = {"best_ever": {"lap_ms": 80000, "sector_ms": None, "date": "2026-01-01"},
                    "last_visit": {"best_lap_ms": 80000, "final_position": 1, "date": "2026-01-01"}}
    cmp = cm.compare([{"lap": 1, "last_lap_ms": 81000}])
    assert "sectors" in cmp and cmp["sectors"] is None


def test_compare_none_when_not_ready():
    cm = CareerMemory()
    assert cm.compare([{"last_lap_ms": 1000}]) is None


def test_compare_computes_gap_and_sectors():
    cm = CareerMemory()
    cm.reference = {"best_ever": {"lap_ms": 80000, "sector_ms": {1: 26500, 2: 27500, 3: 26000},
                                  "date": "2026-01-01"},
                    "last_visit": {"best_lap_ms": 80000, "final_position": 1, "date": "2026-01-01"}}
    cmp = cm.compare([{"lap": 1, "last_lap_ms": 79500,
                       "s1_ms": 26400, "s2_ms": 27400, "s3_ms": 25700}])
    assert cmp["gap_ms"] == -500
    assert cmp["sectors"] == {
        1: {"player_ms": 26400, "gap_ms": -100},
        2: {"player_ms": 27400, "gap_ms": -100},
        3: {"player_ms": 25700, "gap_ms": -300},
    }


def test_compare_sectors_none_when_current_best_lap_missing_sectors():
    """Эталон ИМЕЕТ секторы, но текущий лучший круг — нет (та же all-or-nothing
    деградация, что и в load()): "sectors" всё равно None, а не KeyError/частичное."""
    cm = CareerMemory()
    cm.reference = {"best_ever": {"lap_ms": 80000, "sector_ms": {1: 26500, 2: 27500, 3: 26000},
                                  "date": "2026-01-01"},
                    "last_visit": {"best_lap_ms": 80000, "final_position": 1, "date": "2026-01-01"}}
    cmp = cm.compare([{"lap": 1, "last_lap_ms": 79500}])   # без s1/s2/s3
    assert cmp["gap_ms"] == -500
    assert cmp["sectors"] is None


def test_context_line_mentions_gap():
    cm = CareerMemory()
    line_ahead = cm.context_line({"gap_ms": -500, "player_best_ms": 79500,
                                  "best_ever_ms": 80000, "best_ever_date": "2026-01-01",
                                  "sectors": None})
    line_behind = cm.context_line({"gap_ms": 500, "player_best_ms": 80500,
                                   "best_ever_ms": 80000, "best_ever_date": "2026-01-01",
                                   "sectors": None})
    assert "0.5" in line_ahead and "быстрее" in line_ahead.lower()
    assert "0.5" in line_behind and "отставание" in line_behind.lower()


def test_story_facts_signs():
    """laptime_delta_ms<0 = быстрее прошлого визита; position_delta>0 = финиш выше."""
    cm = CareerMemory()
    cm.reference = {"best_ever": {"lap_ms": 80000, "sector_ms": None, "date": "2026-01-01"},
                    "last_visit": {"best_lap_ms": 82000, "final_position": 8,
                                   "date": "2026-01-01T10:00:00"}}
    facts = cm.story_facts(final_position=5, player_laps=[{"last_lap_ms": 81000}])
    vlv = facts["vs_last_visit"]
    assert vlv["laptime_delta_ms"] == -1000
    assert vlv["position_delta"] == 3
    assert vlv["last_visit_date"] == "2026-01-01T10:00:00"


def test_story_facts_none_without_last_visit():
    cm = CareerMemory()
    assert cm.story_facts(final_position=5, player_laps=[])["vs_last_visit"] is None


def test_story_facts_none_when_reference_set_but_last_visit_incomplete():
    """Защитный путь из §6 спеки: best_ever есть, а last_visit неполный (не должно
    происходить на практике — оба считаются из одного набора файлов, — но
    story_facts() обязан молча вернуть None, а не упасть)."""
    cm = CareerMemory()
    cm.reference = {"best_ever": {"lap_ms": 80000, "sector_ms": None, "date": "2026-01-01"},
                    "last_visit": {"best_lap_ms": None, "final_position": None, "date": None}}
    facts = cm.story_facts(final_position=5, player_laps=[{"last_lap_ms": 81000}])
    assert facts["vs_last_visit"] is None


def test_pb_line_beat_history():
    cm = CareerMemory()
    line = cm.pb_line({"gap_ms": -500, "player_best_ms": 79500})
    assert "рекорд" in line.lower() and "быстрее" in line.lower()


def test_pb_line_session_best_still_behind_history():
    cm = CareerMemory()
    line = cm.pb_line({"gap_ms": 500, "player_best_ms": 80500})
    assert "лучший круг" in line.lower()


def test_sector_pb_line_beat_history():
    cm = CareerMemory()
    line = cm.sector_pb_line(2, {"gap_ms": -100, "player_ms": 27400})
    assert "Сектор 2" in line and "рекорд" in line.lower()


def test_sector_pb_line_session_best_still_behind():
    cm = CareerMemory()
    line = cm.sector_pb_line(1, {"gap_ms": 100, "player_ms": 26600})
    assert "Сектор 1" in line
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_career_memory.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.career_memory'`

- [ ] **Step 3: Implement `core/career_memory.py`**

```python
"""
core/career_memory.py
======================
Личная память игрока по трассе — сравнение с СОБСТВЕННОЙ историей (не с реальным
F1 — это core/f1_benchmark.py, независимая фича). Источник — уже сохранённый архив
игровых сессий (analytics/archive.py, DATA_DIR/game_sessions/*.json), без сети.

Две независимые метрики (см. design spec, §2):
- best_ever — лучший круг+секторы за ВСЮ историю трассы (фиксированная цель, как
  у F1Benchmark). Питает HUD и голосовые PB-реплики.
- last_visit — данные САМОЙ ПОСЛЕДНЕЙ прошлой сессии на трассе (лучший круг +
  финишная позиция). Питает ТОЛЬКО факт Post-Race Story (прогресс с прошлого раза,
  НЕ рекорд).

Скоуп — только session_type == "race" (практика/квалификация не сравнимы по темпу).
Фильтр по track_id (надёжный числовой enum), не track_name (см. CONTEXT.md — баг
"Unknown" был из-за строкового маппинга трасс).
"""
from __future__ import annotations

import logging

from analytics import archive

_log = logging.getLogger(__name__)


class CareerMemory:
    def __init__(self):
        self.reference: dict | None = None

    @property
    def ready(self) -> bool:
        return self.reference is not None

    def reset(self) -> None:
        self.reference = None

    def load(self, track_id: int) -> bool:
        """Просканировать архив на предмет прошлых RACE-сессий на этой трассе.
        True, если найдена хотя бы одна. best_ever — глобальный минимум круга
        среди ВСЕХ совпадающих сессий; last_visit — САМАЯ НОВАЯ (список от
        list_game_sessions() уже отсортирован новыми-сначала — первое совпадение
        и есть last_visit, без доп. сортировки)."""
        matches = [s for s in archive.list_game_sessions()
                  if s.get("track_id") == track_id and s.get("session_type") == "race"]
        if not matches:
            return False

        best_ms: int | None = None
        best_sectors: dict[int, int] | None = None
        last_visit: dict | None = None

        for summary in matches:
            data = archive.load_game_session(summary["path"])
            if data is None:
                continue
            laps = data.get("player_laps") or []
            valid = [lap for lap in laps if (lap.get("last_lap_ms") or 0) > 0]
            if valid:
                session_best = min(valid, key=lambda lap: lap["last_lap_ms"])
                if best_ms is None or session_best["last_lap_ms"] < best_ms:
                    best_ms = session_best["last_lap_ms"]
                    s1 = session_best.get("s1_ms")
                    s2 = session_best.get("s2_ms")
                    s3 = session_best.get("s3_ms")
                    best_sectors = {1: s1, 2: s2, 3: s3} if s1 and s2 and s3 else None
            if last_visit is None:   # первое совпадение в списке = самое новое
                last_visit = {
                    "best_lap_ms": min((lap["last_lap_ms"] for lap in valid), default=None),
                    "final_position": data.get("final_position"),
                    "date": data.get("timestamp"),
                }

        if best_ms is None:
            return False

        self.reference = {
            "best_ever": {"lap_ms": best_ms, "sector_ms": best_sectors,
                         "date": last_visit["date"] if last_visit else None},
            "last_visit": last_visit,
        }
        return True

    def compare(self, player_laps: list[dict]) -> dict | None:
        """Гэп ЛУЧШЕГО круга текущей гонки к best_ever. Ключ "sectors" присутствует
        ВСЕГДА (словарь либо None) — тот же контракт, что у F1Benchmark.compare()."""
        if not self.ready:
            return None
        valid = [lap for lap in player_laps if (lap.get("last_lap_ms") or 0) > 0]
        if not valid:
            return None
        best = min(valid, key=lambda lap: lap["last_lap_ms"])
        best_ever = self.reference["best_ever"]
        return {
            "gap_ms": best["last_lap_ms"] - best_ever["lap_ms"],
            "player_best_ms": best["last_lap_ms"],
            "best_ever_ms": best_ever["lap_ms"],
            "best_ever_date": best_ever["date"],
            "sectors": self._sector_gaps(best, best_ever.get("sector_ms")),
        }

    def _sector_gaps(self, best_lap: dict, ref_sectors: dict[int, int] | None) -> dict | None:
        """Посекторный гэп ЛУЧШЕГО круга к best_ever-секторам. None — эталонных
        секторов нет ИЛИ у лучшего круга нет валидных s1/s2/s3."""
        if not ref_sectors:
            return None
        player = {1: best_lap.get("s1_ms"), 2: best_lap.get("s2_ms"), 3: best_lap.get("s3_ms")}
        if any(not player[n] for n in (1, 2, 3)):
            return None
        return {n: {"player_ms": player[n], "gap_ms": player[n] - ref_sectors[n]}
                for n in (1, 2, 3)}

    def story_facts(self, final_position: int | None, player_laps: list[dict]) -> dict:
        """Сравнение ТЕКУЩЕГО финиша с last_visit (НЕ с best_ever!) для Post-Race
        Story. Знаки: laptime_delta_ms < 0 = быстрее прошлого визита; position_delta
        > 0 = финиш выше, чем в прошлый раз."""
        last_visit = (self.reference or {}).get("last_visit")
        if (not last_visit or last_visit.get("best_lap_ms") is None
                or last_visit.get("final_position") is None):
            return {"vs_last_visit": None}
        valid = [lap for lap in player_laps if (lap.get("last_lap_ms") or 0) > 0]
        if not valid or final_position is None:
            return {"vs_last_visit": None}
        current_best_ms = min(lap["last_lap_ms"] for lap in valid)
        return {"vs_last_visit": {
            "laptime_delta_ms": current_best_ms - last_visit["best_lap_ms"],
            "position_delta": last_visit["final_position"] - final_position,
            "last_visit_date": last_visit["date"],
        }}

    def context_line(self, cmp: dict) -> str:
        """Строка-сверка для контекста LLM (Voice Q&A через analytics_context)."""
        gap = cmp["gap_ms"] / 1000.0
        word = "отставание" if gap >= 0 else "быстрее рекорда на"
        return (f"Твой личный рекорд трассы. Сейчас лучший круг отличается: "
                f"{word} {abs(gap):.1f}с.")

    def pb_line(self, cmp: dict) -> str:
        """Реплика на новом ЛИЧНОМ РЕКОРДЕ КРУГА ЭТОЙ СЕССИИ (зеркалит
        F1Benchmark.pb_line — фиксирует сам факт улучшения в рамках текущей гонки;
        gap_ms<=0 значит этот круг ЕЩЁ И побил исторический best_ever)."""
        gap = cmp["gap_ms"] / 1000.0
        if gap <= 0:
            return f"Новый личный рекорд трассы! Быстрее прежнего рекорда на {abs(gap):.1f} секунды!"
        return f"Лучший круг в этой гонке! Отставание {gap:.1f} секунды от личного рекорда трассы."

    def sector_pb_line(self, sector_n: int, sector_cmp: dict) -> str:
        """Реплика на новом личном рекорде СЕКТОРА этой сессии (не путать с
        F1Benchmark.sector_pb_line — эталон СВОЙ, не реальный F1)."""
        gap = sector_cmp["gap_ms"] / 1000.0
        if gap <= 0:
            return (f"Сектор {sector_n} — новый личный рекорд трассы, "
                    f"быстрее прежнего на {abs(gap):.1f} секунды!")
        return f"Сектор {sector_n} — твой лучший в этой гонке."
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_career_memory.py -q`
Expected: PASS (19 passed)

- [ ] **Step 5: Checkpoint** — тесты задачи зелёные.

---

## Task 3: `core/engine.py` — HUD + анти-спам PB (круг+сектор)

**Files:**
- Modify: `core/engine.py`
- Test: `tests/test_engine_career_memory.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_engine_career_memory.py
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


class _FakeCareer:
    ready = True

    def __init__(self, sectors=None):
        self._sectors = sectors

    def compare(self, laps):
        return {"gap_ms": -500, "player_best_ms": 79500, "best_ever_ms": 80000,
                "best_ever_date": "2026-01-01", "sectors": self._sectors}

    def context_line(self, cmp):
        return "личный рекорд трассы — контекст"

    def pb_line(self, cmp):
        return "Новый личный рекорд трассы! Быстрее прежнего на 0.5 секунды!"

    def sector_pb_line(self, n, s):
        return f"Сектор {n} — новый личный рекорд трассы!"


def _drain(engine):
    events = []
    while not engine.event_queue.empty():
        events.append(engine.event_queue.get_nowait())
    return events


def test_career_pb_event_routes_to_commentary():
    assert route_event({"event_code": "CAREER_PB"}, "race") == CHANNEL_COMMENTARY


def test_career_sector_pb_event_routes_to_commentary():
    assert route_event({"event_code": "CAREER_SECTOR_PB"}, "race") == CHANNEL_COMMENTARY


def test_update_sets_hud_and_pb_event(engine):
    engine.career_memory = _FakeCareer()
    engine._career_best_ms = None
    engine._career_best_sector_ms = {}
    _drain(engine)
    engine._update_career_memory()
    hud = engine.get_state().get("career_memory")
    assert hud is not None and hud["gap_ms"] == -500
    assert hud["sectors"] is None
    evt = engine.event_queue.get_nowait()
    assert evt["event_code"] == "CAREER_PB" and evt["phrase"]


def test_no_double_pb_when_not_improved(engine):
    engine.career_memory = _FakeCareer()
    engine._career_best_ms = 79500
    engine._career_best_sector_ms = {}
    _drain(engine)
    engine._update_career_memory()
    assert engine.event_queue.empty()


def test_update_noop_when_not_ready(engine):
    class _NotReady:
        ready = False
    engine.career_memory = _NotReady()
    _drain(engine)
    engine._update_career_memory()
    assert engine.event_queue.empty()


def test_sector_pb_fires_on_first_improvement(engine):
    sectors = {1: {"player_ms": 26400, "gap_ms": -100}, 2: {"player_ms": 27400, "gap_ms": -100},
               3: {"player_ms": 25700, "gap_ms": -300}}
    engine.career_memory = _FakeCareer(sectors=sectors)
    engine._career_best_ms = None
    engine._career_best_sector_ms = {}
    _drain(engine)
    engine._update_career_memory()
    events = _drain(engine)
    sector_events = [e for e in events if e["event_code"] == "CAREER_SECTOR_PB"]
    assert len(sector_events) == 1
    assert engine._career_best_sector_ms == {1: 26400, 2: 27400, 3: 25700}


def test_sector_pb_picks_smallest_gap_when_multiple_improve(engine):
    sectors = {1: {"player_ms": 26400, "gap_ms": 500}, 2: {"player_ms": 27400, "gap_ms": -300},
               3: {"player_ms": 25700, "gap_ms": 200}}
    engine.career_memory = _FakeCareer(sectors=sectors)
    engine._career_best_ms = None
    engine._career_best_sector_ms = {}
    _drain(engine)
    engine._update_career_memory()
    events = _drain(engine)
    sector_events = [e for e in events if e["event_code"] == "CAREER_SECTOR_PB"]
    assert len(sector_events) == 1
    assert "Сектор 2" in sector_events[0]["phrase"]


def test_sector_pb_silent_when_not_improved(engine):
    sectors = {1: {"player_ms": 26400, "gap_ms": 500}, 2: {"player_ms": 27400, "gap_ms": -300},
               3: {"player_ms": 25700, "gap_ms": 200}}
    engine.career_memory = _FakeCareer(sectors=sectors)
    engine._career_best_ms = 79500
    engine._career_best_sector_ms = {1: 26400, 2: 27400, 3: 25700}
    _drain(engine)
    engine._update_career_memory()
    assert engine.event_queue.empty()


def test_sector_pb_absent_when_sectors_none(engine):
    engine.career_memory = _FakeCareer(sectors=None)
    engine._career_best_ms = None
    engine._career_best_sector_ms = {}
    _drain(engine)
    engine._update_career_memory()
    events = _drain(engine)
    assert all(e["event_code"] != "CAREER_SECTOR_PB" for e in events)


def test_update_sets_analytics_context(engine):
    engine._f1_context_line = None    # изолируемся от состояния других тестов модуля
    engine._career_context_line = None
    engine.career_memory = _FakeCareer()
    engine._career_best_ms = None
    engine._career_best_sector_ms = {}
    _drain(engine)
    engine._update_career_memory()
    assert engine.commentator.analytics_context == engine.career_memory.context_line(
        engine.career_memory.compare([]))


def test_analytics_context_combines_f1_and_career_without_clobbering(engine):
    """Регрессия: до фикса Career Memory затирала F1 Benchmark в analytics_context,
    т.к. обе фичи вызывали set_analytics_context() напрямую с перезаписью (см. Step 9
    плана). Обе части должны присутствовать ОДНОВРЕМЕННО."""
    engine._f1_context_line = "F1-КОНТЕКСТ-МАРКЕР"
    engine._career_context_line = None
    engine._refresh_analytics_context()
    engine.career_memory = _FakeCareer()
    engine._career_best_ms = None
    engine._career_best_sector_ms = {}
    _drain(engine)
    engine._update_career_memory()
    assert "F1-КОНТЕКСТ-МАРКЕР" in engine.commentator.analytics_context
    assert engine.career_memory.context_line(
        engine.career_memory.compare([])) in engine.commentator.analytics_context


def test_reset_clears_both_context_lines_and_analytics_context(engine):
    engine._f1_context_line = "старый F1 контекст"
    engine._career_context_line = "старый career контекст"
    engine._refresh_analytics_context()
    assert engine.commentator.analytics_context
    engine._f1_context_line = None
    engine._career_context_line = None
    engine._refresh_analytics_context()
    assert engine.commentator.analytics_context is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_engine_career_memory.py -q`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute 'career_memory'`

- [ ] **Step 3: Add imports**

В `core/engine.py`, найти:

```python
from core.f1_benchmark import F1Benchmark
```

Заменить на:

```python
from core.f1_benchmark import F1Benchmark
from core.career_memory import CareerMemory
```

- [ ] **Step 4: Init state**

Найти:

```python
        # Real-F1 Benchmark (live)
        self.f1_benchmark = F1Benchmark()
        self._f1_best_ms: int | None = None
        self._f1_best_sector_ms: dict[int, int] = {}
```

Заменить на:

```python
        # Real-F1 Benchmark (live)
        self.f1_benchmark = F1Benchmark()
        self._f1_best_ms: int | None = None
        self._f1_best_sector_ms: dict[int, int] = {}
        self._f1_context_line: str | None = None

        # Career Memory (личная история игрока по трассе, независимо от реального F1)
        self.career_memory = CareerMemory()
        self._career_best_ms: int | None = None
        self._career_best_sector_ms: dict[int, int] = {}
        self._career_context_line: str | None = None
```

**Важно (найдено при самопроверке плана):** `self.commentator.analytics_context` —
ОДНА строка (`commentator/brain.py:56`), не список/словарь. Сейчас
`_update_f1_benchmark()` вызывает `self.set_analytics_context(self.f1_benchmark.context_line(cmp))`
(`core/engine.py:1095`) — прямая перезапись. Если `_update_career_memory()` тоже
независимо вызовет `set_analytics_context(...)`, он молча затрёт контекст F1
Benchmark на каждом круге (Career Memory обновляется ПОСЛЕ F1 Benchmark в
`_telemetry_loop`, см. Step 10 — значит F1-контекст был бы потерян навсегда, как
только у игрока появится история хотя бы на одной трассе). Поля
`_f1_context_line`/`_career_context_line` + `_refresh_analytics_context()` (Step 8a)
существуют, чтобы оба источника СОСУЩЕСТВОВАЛИ в одной строке, а не затирали друг
друга.

- [ ] **Step 5: Reset on track change**

Найти:

```python
                    self.f1_benchmark.reset()
                    self._f1_best_ms = None
                    self._f1_best_sector_ms = {}
                    self._start_f1_benchmark_load(new_tid)
```

Заменить на:

```python
                    self.f1_benchmark.reset()
                    self._f1_best_ms = None
                    self._f1_best_sector_ms = {}
                    self._f1_context_line = None
                    self._start_f1_benchmark_load(new_tid)
                    self.career_memory.reset()
                    self._career_best_ms = None
                    self._career_best_sector_ms = {}
                    self._career_context_line = None
                    self._start_career_memory_load(new_tid)
                    self._refresh_analytics_context()
```

- [ ] **Step 6: Reset on SSTA**

Найти:

```python
                self._story_fired = False
                self._f1_best_ms = None
                self._f1_best_sector_ms = {}
                with self.state_lock:
                    self.state["race_story"] = None
                    self.state["f1_benchmark"] = None
```

Заменить на:

```python
                self._story_fired = False
                self._f1_best_ms = None
                self._f1_best_sector_ms = {}
                self._f1_context_line = None
                self._career_best_ms = None
                self._career_best_sector_ms = {}
                self._career_context_line = None
                self._refresh_analytics_context()
                with self.state_lock:
                    self.state["race_story"] = None
                    self.state["f1_benchmark"] = None
                    self.state["career_memory"] = None
```

- [ ] **Step 7: Init `state["career_memory"]` in `self.state` dict**

Найти (в конструкторе `self.state = {...}`):

```python
            "f1_benchmark": None,
```

Заменить на:

```python
            "f1_benchmark": None,
            "career_memory": None,
```

- [ ] **Step 8: `_start_career_memory_load` + `_update_career_memory`**

Найти:

```python
    def _start_f1_benchmark_load(self, track_id: int) -> None:
        """Фоновая загрузка эталона трассы из Jolpica (сеть — только тут, не из потока телеметрии)."""
        def _run() -> None:
            try:
                self.f1_benchmark.load(track_id, int(config.F1_SEASON))
            except Exception as exc:  # noqa: BLE001
                _log.warning("F1 benchmark load failed: %s", exc)
        threading.Thread(target=_run, daemon=True, name="f1-benchmark-load").start()
```

Заменить на (добавляем 2 новых метода ПОСЛЕ существующего, сам существующий не трогаем):

```python
    def _start_f1_benchmark_load(self, track_id: int) -> None:
        """Фоновая загрузка эталона трассы из Jolpica (сеть — только тут, не из потока телеметрии)."""
        def _run() -> None:
            try:
                self.f1_benchmark.load(track_id, int(config.F1_SEASON))
            except Exception as exc:  # noqa: BLE001
                _log.warning("F1 benchmark load failed: %s", exc)
        threading.Thread(target=_run, daemon=True, name="f1-benchmark-load").start()

    def _start_career_memory_load(self, track_id: int) -> None:
        """Фоновая загрузка личной истории трассы из архива (диск, не сеть — но
        всё равно фоновый поток, чтобы не блокировать телеметрию на I/O)."""
        def _run() -> None:
            try:
                self.career_memory.load(track_id)
            except Exception as exc:  # noqa: BLE001
                _log.warning("Career memory load failed: %s", exc)
        threading.Thread(target=_run, daemon=True, name="career-memory-load").start()
```

- [ ] **Step 9: `_refresh_analytics_context()` — объединить оба источника контекста LLM**

`analytics_context` — одна строка (см. примечание в Step 4). F1 Benchmark и Career
Memory оба должны в неё попадать, не затирая друг друга.

Найти в `core/engine.py`:

```python
        self.set_analytics_context(self.f1_benchmark.context_line(cmp))
        if self._f1_best_ms is None or cmp["player_best_ms"] < self._f1_best_ms:
```

Заменить на:

```python
        self._f1_context_line = self.f1_benchmark.context_line(cmp)
        self._refresh_analytics_context()
        if self._f1_best_ms is None or cmp["player_best_ms"] < self._f1_best_ms:
```

Найти метод `set_analytics_context`:

```python
    def set_analytics_context(self, context: str | None) -> None:
        self.commentator.analytics_context = context
```

Заменить на (добавляем новый метод СРАЗУ ПОСЛЕ, сам `set_analytics_context` не трогаем):

```python
    def set_analytics_context(self, context: str | None) -> None:
        self.commentator.analytics_context = context

    def _refresh_analytics_context(self) -> None:
        """F1 Benchmark и Career Memory — независимые источники контекста для LLM,
        но `analytics_context` — одна строка. Собираем обе непустые части вместе,
        чтобы каждое новое сравнение не затирало предыдущее (баг, найденный при
        самопроверке плана — см. Step 4)."""
        parts = [p for p in (self._f1_context_line, self._career_context_line) if p]
        self.set_analytics_context(" ".join(parts) if parts else None)
```

- [ ] **Step 10: `_update_career_memory` — сразу после `_update_f1_benchmark`**

Найти конец метода `_update_f1_benchmark` (последние строки):

```python
            if improved:
                # несколько PB-секторов в одном круге -> говорим ОДИН раз, про сектор
                # с наименьшим gap_ms (самое впечатляющее достижение относительно
                # реального F1, а не просто самый большой числовой прогресс)
                best_n = min(improved, key=lambda n: cmp["sectors"][n]["gap_ms"])
                self.event_queue.put({
                    "event_code": "F1_SECTOR_BENCH", "priority": "normal",
                    "phrase": self.f1_benchmark.sector_pb_line(best_n, cmp["sectors"][best_n]),
                    "color": "#34D399", "driver": ""})

    def _telemetry_loop(self):
```

Заменить на:

```python
            if improved:
                # несколько PB-секторов в одном круге -> говорим ОДИН раз, про сектор
                # с наименьшим gap_ms (самое впечатляющее достижение относительно
                # реального F1, а не просто самый большой числовой прогресс)
                best_n = min(improved, key=lambda n: cmp["sectors"][n]["gap_ms"])
                self.event_queue.put({
                    "event_code": "F1_SECTOR_BENCH", "priority": "normal",
                    "phrase": self.f1_benchmark.sector_pb_line(best_n, cmp["sectors"][best_n]),
                    "color": "#34D399", "driver": ""})

    def _update_career_memory(self) -> None:
        """Каждый завершённый круг: гэп к ЛИЧНОМУ рекорду трассы → HUD; на новом
        личном рекорде (полный круг ИЛИ сектор) — озвучка. Независимая надстройка
        от _update_f1_benchmark — разные эталоны (свой архив vs реальный F1),
        разные события (CAREER_PB/CAREER_SECTOR_PB vs F1_BENCH/F1_SECTOR_BENCH)."""
        if not self.career_memory.ready:
            return
        cmp = self.career_memory.compare(self.recorder.laps())
        if cmp is None:
            return
        with self.state_lock:
            self.state["career_memory"] = {
                "gap_ms": cmp["gap_ms"], "player_best_ms": cmp["player_best_ms"],
                "best_ever_ms": cmp["best_ever_ms"], "best_ever_date": cmp["best_ever_date"],
                "sectors": cmp["sectors"]}
        self._career_context_line = self.career_memory.context_line(cmp)
        self._refresh_analytics_context()
        if self._career_best_ms is None or cmp["player_best_ms"] < self._career_best_ms:
            self._career_best_ms = cmp["player_best_ms"]
            self.event_queue.put({
                "event_code": "CAREER_PB", "priority": "normal",
                "phrase": self.career_memory.pb_line(cmp),
                "color": "#60A5FA", "driver": ""})
        if cmp["sectors"] is not None:
            improved: list[int] = []
            for n, s in cmp["sectors"].items():
                best_so_far = self._career_best_sector_ms.get(n)
                if best_so_far is None or s["player_ms"] < best_so_far:
                    self._career_best_sector_ms[n] = s["player_ms"]
                    improved.append(n)
            if improved:
                best_n = min(improved, key=lambda n: cmp["sectors"][n]["gap_ms"])
                self.event_queue.put({
                    "event_code": "CAREER_SECTOR_PB", "priority": "normal",
                    "phrase": self.career_memory.sector_pb_line(best_n, cmp["sectors"][best_n]),
                    "color": "#60A5FA", "driver": ""})

    def _telemetry_loop(self):
```

- [ ] **Step 11: Вызов `_update_career_memory()` рядом с `_update_f1_benchmark()`**

Найти (внутри `_telemetry_loop`, после завершения круга):

```python
                        self._update_f1_benchmark()
```

Заменить на:

```python
                        self._update_f1_benchmark()
                        self._update_career_memory()
```

**Важно:** если это ровно ОДНО вхождение — замена безопасна. Если `_update_f1_benchmark()` вызывается более одного раза в файле (проверить `grep -n "_update_f1_benchmark()" core/engine.py` перед правкой), использовать только тот вызов, что стоит в `_telemetry_loop` сразу после `self.driver_coach.add_lap(...)` и `self._update_f1_benchmark()` в блоке `if cur > self._prev_lap ...` (там же, где раньше `_update_f1_benchmark()` был добавлен для F1 Sector Benchmark).

- [ ] **Step 12: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_engine_career_memory.py -q`
Expected: PASS (12 passed)

- [ ] **Step 13: Regression check**

Run: `py -3.12 -m pytest tests/test_engine_f1_benchmark.py tests/test_engine_story.py tests/test_engine_ambient.py tests/test_engine_health.py tests/test_engine_voice.py -q`
Expected: PASS (без изменений в счёте — особенно `test_engine_f1_benchmark.py::
test_update_sets_hud_context_and_pb_event`, которая проверяет
`engine.commentator.analytics_context` truthy: F1-контекст по-прежнему долетает,
просто теперь потенциально как часть объединённой строки, а не единственная часть)

- [ ] **Step 14: Checkpoint** — тесты задачи и регрессии зелёные.

---

## Task 4: Post-Race Story — факт `vs_last_visit`

**Files:**
- Modify: `core/race_story.py`
- Modify: `commentator/story.py`
- Modify: `core/engine.py`
- Modify: `tests/test_story_collector.py`
- Modify: `tests/test_story_generator.py`

- [ ] **Step 1: Read existing test files first**

Прочитать `tests/test_story_collector.py` и `tests/test_story_generator.py` целиком —
файлы уже расширялись для `weak_sector_vs_f1` (F1 Sector Benchmark), новые тесты
должны следовать той же конвенции (без фикстур, прямой вызов), не дублировать
существующие имена тестов.

- [ ] **Step 2: Write the failing tests**

Добавить в конец `tests/test_story_collector.py`:

```python
def test_facts_includes_vs_last_visit():
    from core.race_story import RaceStoryCollector
    c = RaceStoryCollector()
    vlv = {"laptime_delta_ms": -500, "position_delta": 2, "last_visit_date": "2026-01-01"}
    facts = c.facts(final_position=4, laps=[], vs_last_visit=vlv)
    assert facts["vs_last_visit"] == vlv


def test_facts_vs_last_visit_defaults_to_none():
    from core.race_story import RaceStoryCollector
    c = RaceStoryCollector()
    facts = c.facts(final_position=4, laps=[])
    assert facts["vs_last_visit"] is None
```

Добавить в конец `tests/test_story_generator.py`:

```python
def test_format_facts_includes_vs_last_visit_faster_and_higher():
    from commentator.story import build_prompt
    facts = {"vs_last_visit": {"laptime_delta_ms": -1500, "position_delta": 3,
                               "last_visit_date": "2026-01-01T10:00:00"}}
    prompt = build_prompt(facts, "tv")
    assert "прошлого визита" in prompt
    assert "быстрее на 1.5с" in prompt
    assert "выше на 3" in prompt


def test_format_facts_includes_vs_last_visit_slower_and_lower():
    from commentator.story import build_prompt
    facts = {"vs_last_visit": {"laptime_delta_ms": 800, "position_delta": -2,
                               "last_visit_date": "2026-01-01T10:00:00"}}
    prompt = build_prompt(facts, "tv")
    assert "медленнее на 0.8с" in prompt
    assert "ниже на 2" in prompt


def test_format_facts_omits_vs_last_visit_when_none():
    from commentator.story import build_prompt
    facts = {"vs_last_visit": None}
    prompt = build_prompt(facts, "tv")
    assert "прошлого визита" not in prompt


def test_weak_sector_vs_f1_and_vs_last_visit_coexist():
    """Ещё одна проверка независимости фактов (F1 Sector Benchmark и Career Memory
    не пересекаются) — оба должны появиться, не подменяя друг друга."""
    from commentator.story import build_prompt
    facts = {"weak_sector_vs_f1": 2,
            "vs_last_visit": {"laptime_delta_ms": -500, "position_delta": 1,
                              "last_visit_date": "2026-01-01T10:00:00"}}
    prompt = build_prompt(facts, "tv")
    assert "Слабее эталона F1 в секторе: S2" in prompt
    assert "прошлого визита" in prompt
```

- [ ] **Step 3: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_story_collector.py tests/test_story_generator.py -q`
Expected: FAIL — `TypeError: facts() got an unexpected keyword argument 'vs_last_visit'`

- [ ] **Step 4: Implement `core/race_story.py`**

Найти сигнатуру:

```python
    def facts(self, *, final_position: int | None, laps: list[dict],
              coach_state: dict | None = None, leader_name: str | None = None,
              total_laps: int | None = None, track: str | None = None,
              weak_sector_vs_f1: int | None = None) -> dict:
```

Заменить на:

```python
    def facts(self, *, final_position: int | None, laps: list[dict],
              coach_state: dict | None = None, leader_name: str | None = None,
              total_laps: int | None = None, track: str | None = None,
              weak_sector_vs_f1: int | None = None,
              vs_last_visit: dict | None = None) -> dict:
```

Найти конец возвращаемого словаря:

```python
            "weak_sector": coach.get("weak_sector"),
            "weak_sector_vs_f1": weak_sector_vs_f1,
            "consistency": coach.get("consistency_score"),
            "leader": leader_name,
        }
```

Заменить на:

```python
            "weak_sector": coach.get("weak_sector"),
            "weak_sector_vs_f1": weak_sector_vs_f1,
            "vs_last_visit": vs_last_visit,
            "consistency": coach.get("consistency_score"),
            "leader": leader_name,
        }
```

- [ ] **Step 5: Implement `commentator/story.py`**

Найти:

```python
    if facts.get("weak_sector_vs_f1"):
        L.append(f"- Слабее эталона F1 в секторе: S{facts['weak_sector_vs_f1']}")
    c = facts.get("consistency")
```

Заменить на:

```python
    if facts.get("weak_sector_vs_f1"):
        L.append(f"- Слабее эталона F1 в секторе: S{facts['weak_sector_vs_f1']}")
    vlv = facts.get("vs_last_visit")
    if vlv:
        date = (vlv.get("last_visit_date") or "").split("T")[0]
        dt_ms = vlv["laptime_delta_ms"]
        pd = vlv["position_delta"]
        speed = (f"быстрее на {abs(dt_ms) / 1000.0:.1f}с" if dt_ms < 0
                else f"медленнее на {abs(dt_ms) / 1000.0:.1f}с")
        if pd > 0:
            pos = f"финиш выше на {pd}"
        elif pd < 0:
            pos = f"финиш ниже на {abs(pd)}"
        else:
            pos = "та же позиция на финише"
        suffix = f" ({date})" if date else ""
        L.append(f"- С прошлого визита сюда{suffix}: {speed}, {pos}")
    c = facts.get("consistency")
```

- [ ] **Step 6: Implement `core/engine.py` — прокинуть в `_generate_story`**

Найти:

```python
            laps = self.recorder.laps()
            # Средний гэп по сектору за ВСЮ гонку к реальному F1 (Post-Race Story),
            # отдельно от per-lap sector-PB логики в _update_f1_benchmark (Task 3).
            weak_sector_vs_f1 = self.f1_benchmark.race_weak_sector(laps)
            facts = self.story_collector.facts(
                final_position=final_pos, laps=laps,
                coach_state=coach, leader_name=self._leader_name,
                total_laps=getattr(self, "_total_laps", None), track=track,
                weak_sector_vs_f1=weak_sector_vs_f1)
```

Заменить на:

```python
            laps = self.recorder.laps()
            # Средний гэп по сектору за ВСЮ гонку к реальному F1 (Post-Race Story),
            # отдельно от per-lap sector-PB логики в _update_f1_benchmark (Task 3).
            weak_sector_vs_f1 = self.f1_benchmark.race_weak_sector(laps)
            # Прогресс с прошлого визита на эту трассу (Career Memory) — НЕ путать
            # с best_ever/личным рекордом из _update_career_memory.
            vs_last_visit = self.career_memory.story_facts(final_pos, laps)["vs_last_visit"]
            facts = self.story_collector.facts(
                final_position=final_pos, laps=laps,
                coach_state=coach, leader_name=self._leader_name,
                total_laps=getattr(self, "_total_laps", None), track=track,
                weak_sector_vs_f1=weak_sector_vs_f1,
                vs_last_visit=vs_last_visit)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_story_collector.py tests/test_story_generator.py -q`
Expected: PASS (все тесты файлов, включая новые)

- [ ] **Step 8: Regression check**

Run: `py -3.12 -m pytest tests/test_engine_story.py -q`
Expected: PASS (без изменений в счёте — `career_memory.story_facts()` на дефолтном
`CareerMemory()` без загруженной истории вернёт `{"vs_last_visit": None}` — как и
`race_weak_sector` на дефолтном `F1Benchmark()`)

- [ ] **Step 9: Checkpoint** — тесты задачи и регрессии зелёные.

---

## Task 5: UI — панель «Личный рекорд трассы»

**Files:**
- Modify: `NewSpotterUI/lib/api.ts`
- Modify: `NewSpotterUI/components/spotter/views/race.tsx`

- [ ] **Step 1: `lib/api.ts` — новый тип**

Найти:

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

export type CareerMemoryState = {
  gap_ms: number
  player_best_ms: number
  best_ever_ms: number
  best_ever_date: string | null
  sectors: Record<"1" | "2" | "3", F1SectorGap> | null
}
```

- [ ] **Step 2: `lib/api.ts` — поле в `SpotterState`**

Найти:

```typescript
  f1_benchmark?: F1BenchmarkState | null
  voice_query?: VoiceQuery | null
}
```

Заменить на:

```typescript
  f1_benchmark?: F1BenchmarkState | null
  career_memory?: CareerMemoryState | null
  voice_query?: VoiceQuery | null
}
```

- [ ] **Step 3: `race.tsx` — производные значения**

Найти:

```tsx
  const bench = state?.f1_benchmark ?? null
  const sectors = bench?.sectors ?? null
```

Заменить на:

```tsx
  const bench = state?.f1_benchmark ?? null
  const sectors = bench?.sectors ?? null
  const career = state?.career_memory ?? null
  const careerSectors = career?.sectors ?? null
```

- [ ] **Step 4: `race.tsx` — новая панель**

Найти (закрытие Panel «Лидер гонки», перед Panel «Голосовой вопрос»):

```tsx
              ) : (
                <p className="mt-3 text-[11px] text-muted-foreground">
                  Эталон реального GP подгрузится после первого круга.
                </p>
              )}
            </Panel>
            <Panel label="Голосовой вопрос">
```

Заменить на:

```tsx
              ) : (
                <p className="mt-3 text-[11px] text-muted-foreground">
                  Эталон реального GP подгрузится после первого круга.
                </p>
              )}
            </Panel>
            <Panel label="Личный рекорд трассы">
              {career ? (
                <div className="rounded-md bg-secondary/60 p-3">
                  <p className="font-mono text-[10px] text-muted-foreground">
                    ЛИЧНЫЙ РЕКОРД ТРАССЫ
                  </p>
                  <p className={cn(
                    "font-heading text-lg font-bold tabular",
                    career.gap_ms <= 0 ? "text-success" : "text-foreground",
                  )}>
                    {career.gap_ms <= 0 ? "−" : "+"}
                    {(Math.abs(career.gap_ms) / 1000).toFixed(1)}с
                  </p>
                  {careerSectors && (
                    <div className="mt-2 flex gap-1.5">
                      {(["1", "2", "3"] as const).map((n) => {
                        const s = careerSectors[n]
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
              ) : (
                <p className="text-[11px] text-muted-foreground">
                  Личный рекорд появится после первого визита на эту трассу.
                </p>
              )}
            </Panel>
            <Panel label="Голосовой вопрос">
```

- [ ] **Step 5: Typecheck**

Run: `cd NewSpotterUI && npx tsc --noEmit`
Expected: без ошибок типов

- [ ] **Step 6: Checkpoint** — tsc чист.

---

## Task 6: Полная верификация + CONTEXT.md

**Files:**
- Modify: `CONTEXT.md`

- [ ] **Step 1: Полный прогон тестов**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: все тесты проходят (бейслайн 704 + новые из Tasks 1-4: 1 archive + 19
career_memory + 12 engine_career_memory + 6 story = +38, итого 742). Если итоговая
строка не пропечаталась (Windows-гочта) — считать через
`grep -o '[.sF]' <лог> | sort | uniq -c`.

- [ ] **Step 2: Полный typecheck**

Run: `cd NewSpotterUI && npx tsc --noEmit`
Expected: чисто

- [ ] **Step 3: Import smoke**

Run: `py -3.12 -c "import core.engine, core.career_memory, core.race_story, commentator.story, analytics.archive"`
Expected: без ошибок

- [ ] **Step 4: Обновить CONTEXT.md**

В раздел «На чём остановились» дописать новую сессию: что сделано (6 задач, файлы),
новый тест-бейслайн, явно отметить — `best_ever` (фиксированная цель, HUD/голос) и
`last_visit` (для Story-нарратива) две РАЗНЫЕ метрики, не путать; `CAREER_PB`/
`CAREER_SECTOR_PB` — свои события, отдельные от `F1_BENCH`/`F1_SECTOR_BENCH`;
`vs_last_visit` — свой факт Story, отдельный от `weak_sector`/`weak_sector_vs_f1`.
Обновить счётчик задач сессии.

- [ ] **Step 5: Checkpoint** — полный прогон зелёный, CONTEXT.md обновлён.
