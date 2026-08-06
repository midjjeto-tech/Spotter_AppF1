# Career Stats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a cross-track career statistics aggregate (total races, wins, podiums, average finish position) computed once at race end, surfaced as a Post-Race Story fact and a Voice Q&A context line — closing the "cross-race career memory" backlog item.

**Architecture:** A new pure-function module `core/career_stats.py` aggregates over `analytics/archive.py::list_game_sessions()` (already-available lightweight summaries, no new I/O). The result threads through the existing `RaceStoryCollector.facts()` → `commentator/story.py::_format_facts()` pipeline (same pattern as the existing `vs_last_visit`/`weak_sector_vs_f1` facts) and separately feeds a new context-line attribute that joins the existing `_refresh_analytics_context()` aggregation in `core/engine.py`.

**Tech Stack:** Python 3.12, pytest. No new dependencies.

**Design doc:** `docs/superpowers/specs/2026-07-08-career-stats-design.md`

**Note on git:** this project is not under version control. No `git commit` steps — each task ends with a verification checkpoint instead.

---

### Task 1: `core/career_stats.py` — compute + context line

**Files:**
- Create: `core/career_stats.py`
- Test: `tests/test_career_stats.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_career_stats.py`:

```python
from analytics import archive
from core.career_stats import compute_career_stats, context_line


def _write_session(tmp_path, name, *, session_type="race", final_position=None):
    archive._atomic_write(tmp_path / name, {
        "track_id": 11, "session_type": session_type,
        "final_position": final_position, "timestamp": "2026-01-01T10:00:00",
    })


def test_no_sessions_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    assert compute_career_stats() is None


def test_ignores_non_race_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    _write_session(tmp_path, "a.json", session_type="practice", final_position=1)
    assert compute_career_stats() is None


def test_ignores_races_without_final_position(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    _write_session(tmp_path, "a.json", final_position=None)
    assert compute_career_stats() is None


def test_computes_wins_podiums_avg(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    _write_session(tmp_path, "1.json", final_position=1)
    _write_session(tmp_path, "2.json", final_position=3)
    _write_session(tmp_path, "3.json", final_position=8)
    stats = compute_career_stats()
    assert stats["total_races"] == 3
    assert stats["wins"] == 1
    assert stats["podiums"] == 2
    assert stats["avg_position"] == (1 + 3 + 8) / 3


def test_podiums_include_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    _write_session(tmp_path, "1.json", final_position=1)
    stats = compute_career_stats()
    assert stats["wins"] == 1
    assert stats["podiums"] == 1


def test_context_line_formats_all_fields():
    line = context_line({"total_races": 15, "wins": 2, "podiums": 5, "avg_position": 6.333})
    assert "15" in line
    assert "2" in line and "побед" in line
    assert "5" in line and "подиумов" in line
    assert "6.3" in line
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_career_stats.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.career_stats'`

- [ ] **Step 3: Implement**

Create `core/career_stats.py`:

```python
"""
core/career_stats.py
=====================
Карьерная статистика игрока — агрегат по ВСЕМ гоночным сессиям в архиве,
независимо от трассы (в отличие от core/career_memory.py, который сравнивает
только визиты на ОДНУ И ТУ ЖЕ трассу). Источник — analytics/archive.py
(DATA_DIR/game_sessions/*.json), без сети.

Чистая функция, не класс: в отличие от CareerMemory (live-обновление каждый
круг во время гонки), карьерная статистика считается ОДИН РАЗ, в момент
финиша — состояние между вызовами не нужно.
"""
from __future__ import annotations

from analytics import archive


def compute_career_stats() -> dict | None:
    """Агрегат по всем гонкам с известным final_position. None, если таких
    гонок нет (архив пуст / ни одна гонка не имеет зафиксированного
    результата) — тот же паттерн, что CareerMemory.load() -> False."""
    races = [s for s in archive.list_game_sessions()
             if s.get("session_type") == "race" and s.get("final_position") is not None]
    if not races:
        return None
    positions = [s["final_position"] for s in races]
    total = len(positions)
    return {
        "total_races": total,
        "wins": sum(1 for p in positions if p == 1),
        "podiums": sum(1 for p in positions if p <= 3),
        "avg_position": sum(positions) / total,
    }


def context_line(stats: dict) -> str:
    """Строка-сверка для контекста LLM (Voice Q&A через analytics_context,
    по аналогии с core/career_memory.py::context_line)."""
    return (f"Карьерная статистика игрока: {stats['total_races']} гонок, "
            f"{stats['wins']} побед, {stats['podiums']} подиумов, "
            f"средняя финишная позиция {stats['avg_position']:.1f}.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_career_stats.py -v`
Expected: all PASS

- [ ] **Step 5: Checkpoint**

Confirm all 6 tests pass. No git commit needed (project has no git repo). Move to Task 2.

---

### Task 2: `core/race_story.py` — thread `career_stats` through `facts()`

**Files:**
- Modify: `core/race_story.py:45-81` (`RaceStoryCollector.facts`)
- Test: `tests/test_story_collector.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_story_collector.py`, near the existing `test_facts_includes_vs_last_visit`/`test_facts_vs_last_visit_defaults_to_none` tests:

```python
def test_facts_includes_career_stats():
    from core.race_story import RaceStoryCollector
    c = RaceStoryCollector()
    cs = {"total_races": 10, "wins": 1, "podiums": 3, "avg_position": 7.5}
    facts = c.facts(final_position=4, laps=[], career_stats=cs)
    assert facts["career_stats"] == cs


def test_facts_career_stats_defaults_to_none():
    from core.race_story import RaceStoryCollector
    c = RaceStoryCollector()
    facts = c.facts(final_position=4, laps=[])
    assert facts["career_stats"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_story_collector.py::test_facts_includes_career_stats -v`
Expected: FAIL with `TypeError: facts() got an unexpected keyword argument 'career_stats'`

- [ ] **Step 3: Implement**

In `core/race_story.py`, change the `facts()` signature and return dict:

```python
    def facts(self, *, final_position: int | None, laps: list[dict],
              coach_state: dict | None = None, leader_name: str | None = None,
              total_laps: int | None = None, track: str | None = None,
              weak_sector_vs_f1: int | None = None,
              vs_last_visit: dict | None = None,
              career_stats: dict | None = None) -> dict:
        """Свести накопленное + финальные данные в плоский факт-блок для LLM."""
        best_ms: int | None = None
        best_lap: int | None = None
        for lp in laps:
            ms = lp.get("last_lap_ms") or 0
            if ms > 0 and (best_ms is None or ms < best_ms):
                best_ms, best_lap = ms, lp.get("lap")

        overtakes = [{"lap": e["lap"], "target": e["target"]}
                     for e in self._events if e["code"] == "OVTK" and e.get("target")]
        incidents = [{"lap": e["lap"], "code": e["code"], "driver": e.get("driver")}
                     for e in self._events if e["code"] in ("PENA", "RTMT")]
        gained = (self._start_position - final_position
                  if self._start_position and final_position else None)
        coach = coach_state or {}
        return {
            "track": track,
            "start_position": self._start_position,
            "final_position": final_position,
            "positions_gained": gained,
            "total_laps": total_laps,
            "best_lap_ms": best_ms,
            "best_lap_number": best_lap,
            "overtakes": overtakes,
            "incidents": incidents,
            "fastest_lap_flag": any(e["code"] == "FTLP" for e in self._events),
            "weak_sector": coach.get("weak_sector"),
            "weak_sector_vs_f1": weak_sector_vs_f1,
            "vs_last_visit": vs_last_visit,
            "career_stats": career_stats,
            "consistency": coach.get("consistency_score"),
            "leader": leader_name,
        }
```

Only the new `career_stats` parameter and the `"career_stats": career_stats,` line are additions — everything else in the method body is unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_story_collector.py -v`
Expected: all PASS

- [ ] **Step 5: Checkpoint**

Move to Task 3.

---

### Task 3: `commentator/story.py` — career stats bullet in `_format_facts`

**Files:**
- Modify: `commentator/story.py:39-86` (`_format_facts`)
- Test: `tests/test_story_generator.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_story_generator.py`, near the existing `test_format_facts_includes_vs_last_visit_*`/`test_weak_sector_vs_f1_and_vs_last_visit_coexist` tests:

```python
def test_format_facts_includes_career_stats():
    from commentator.story import build_prompt
    facts = {"career_stats": {"total_races": 10, "wins": 2, "podiums": 4, "avg_position": 5.5}}
    prompt = build_prompt(facts, "tv")
    assert "Карьера: гонка №10" in prompt
    assert "побед 2" in prompt
    assert "подиумов 4" in prompt
    assert "средняя позиция 5.5" in prompt


def test_format_facts_omits_career_stats_when_none():
    from commentator.story import build_prompt
    facts = {"career_stats": None}
    prompt = build_prompt(facts, "tv")
    assert "Карьера:" not in prompt


def test_career_stats_and_vs_last_visit_coexist():
    """Sanity check that the new career-wide fact and the existing per-track
    vs_last_visit fact don't interfere — both should appear, neither replacing
    the other."""
    from commentator.story import build_prompt
    facts = {"career_stats": {"total_races": 10, "wins": 2, "podiums": 4, "avg_position": 5.5},
            "vs_last_visit": {"laptime_delta_ms": -500, "position_delta": 1,
                              "last_visit_date": "2026-01-01T10:00:00"}}
    prompt = build_prompt(facts, "tv")
    assert "Карьера: гонка №10" in prompt
    assert "прошлого визита" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_story_generator.py::test_format_facts_includes_career_stats -v`
Expected: FAIL — `"Карьера: гонка №10" not in prompt`

- [ ] **Step 3: Implement**

In `commentator/story.py`, inside `_format_facts()`, add a new block right after the existing `vs_last_visit` block (after the line `L.append(f"- С прошлого визита сюда{suffix}: {speed}, {pos}")`) and before the `consistency` block:

```python
    cs = facts.get("career_stats")
    if cs:
        L.append(f"- Карьера: гонка №{cs['total_races']}, побед {cs['wins']}, "
                 f"подиумов {cs['podiums']}, средняя позиция {cs['avg_position']:.1f}")
```

Do not touch `render_fallback()` — the offline deterministic fallback intentionally does not cover `vs_last_visit`/`weak_sector_vs_f1` either, and `career_stats` follows the same LLM-only-fact convention.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_story_generator.py -v`
Expected: all PASS

- [ ] **Step 5: Checkpoint**

Move to Task 4.

---

### Task 4: `core/engine.py` — wiring

**Files:**
- Modify: `core/engine.py:64` (imports)
- Modify: `core/engine.py:185` (`__init__`)
- Modify: `core/engine.py:1495` (SSTA reset block)
- Modify: `core/engine.py:1149-1197` (`_generate_story`)
- Modify: `core/engine.py:1811-1816` (`_refresh_analytics_context`)
- Test: `tests/test_engine_story.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_engine_story.py`:

```python
def test_generate_story_includes_career_stats_in_context(engine, tmp_path, monkeypatch):
    import analytics.archive as archive_mod
    monkeypatch.setattr(archive_mod, "_GAME_SESSIONS", tmp_path)
    archive_mod._atomic_write(tmp_path / "1.json", {
        "track_id": 11, "session_type": "race", "final_position": 3,
        "timestamp": "2026-01-01T10:00:00",
    })
    engine.settings["autovoice_enabled"] = False
    engine.story_collector.reset()
    engine.story_collector.note_start_position(6)
    engine._player_pos = 4
    engine._generate_story(None)
    assert engine._career_stats_context_line is not None
    assert "Карьерная статистика" in engine._career_stats_context_line
    assert engine._career_stats_context_line in (engine.commentator.analytics_context or "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_engine_story.py::test_generate_story_includes_career_stats_in_context -v`
Expected: FAIL with `AttributeError: 'F1Engine' object has no attribute '_career_stats_context_line'`

- [ ] **Step 3: Implement.** Four small, surgical edits to `core/engine.py`:

**3a. Import** — find the line `from core.career_memory import CareerMemory` (line 64) and add a new import line right after it:

```python
from core.career_memory import CareerMemory
import core.career_stats as career_stats_mod
```

**3b. `__init__`** — find the block (around line 181-185):

```python
        # Career Memory (личная история игрока по трассе, независимо от реального F1)
        self.career_memory = CareerMemory()
        self._career_best_ms: int | None = None
        self._career_best_sector_ms: dict[int, int] = {}
        self._career_context_line: str | None = None
```

Add one new line right after it:

```python
        # Career Memory (личная история игрока по трассе, независимо от реального F1)
        self.career_memory = CareerMemory()
        self._career_best_ms: int | None = None
        self._career_best_sector_ms: dict[int, int] = {}
        self._career_context_line: str | None = None

        # Career Stats (кросс-трековый агрегат: всего гонок/побед/подиумов/средняя
        # позиция) — НЕ путать с career_memory выше, которая привязана к трассе.
        self._career_stats_context_line: str | None = None
```

**3c. SSTA reset block** — find the block inside the `elif code == "SSTA":` handling (around line 1490-1500) that resets `self._career_context_line = None` among other resets:

```python
                self._career_best_ms = None
                self._career_best_sector_ms = {}
                self._career_context_line = None
```

Add one new line right after it:

```python
                self._career_best_ms = None
                self._career_best_sector_ms = {}
                self._career_context_line = None
                self._career_stats_context_line = None
```

Do NOT add this reset to the OTHER block that resets `self._career_context_line = None` on track change (search for `self._start_career_memory_load(new_tid)` — that's a different, per-track reset a few hundred lines earlier). Career stats is track-independent, so it must NOT be cleared just because the player changed tracks — only on a fresh race start (`SSTA`), matching the design doc's explicit "reset on SSTA" decision.

**3d. `_generate_story`** — find the method (search for `def _generate_story`). The current body has this sequence:

```python
            vs_last_visit = self.career_memory.story_facts(final_pos, laps)["vs_last_visit"]
            facts = self.story_collector.facts(
                final_position=final_pos, laps=laps,
                coach_state=coach, leader_name=self._leader_name,
                total_laps=getattr(self, "_total_laps", None), track=track,
                weak_sector_vs_f1=weak_sector_vs_f1,
                vs_last_visit=vs_last_visit)
```

Replace it with:

```python
            vs_last_visit = self.career_memory.story_facts(final_pos, laps)["vs_last_visit"]
            career_stats = career_stats_mod.compute_career_stats()
            self._career_stats_context_line = (
                career_stats_mod.context_line(career_stats) if career_stats else None)
            self._refresh_analytics_context()
            facts = self.story_collector.facts(
                final_position=final_pos, laps=laps,
                coach_state=coach, leader_name=self._leader_name,
                total_laps=getattr(self, "_total_laps", None), track=track,
                weak_sector_vs_f1=weak_sector_vs_f1,
                vs_last_visit=vs_last_visit,
                career_stats=career_stats)
```

**3e. `_refresh_analytics_context`** — find the method:

```python
    def _refresh_analytics_context(self) -> None:
        """F1 Benchmark и Career Memory — независимые источники контекста для LLM,
        но `analytics_context` — одна строка. Собираем обе непустые части вместе,
        чтобы каждое новое сравнение не затирало предыдущее."""
        parts = [p for p in (self._f1_context_line, self._career_context_line) if p]
        self.set_analytics_context(" ".join(parts) if parts else None)
```

Replace with:

```python
    def _refresh_analytics_context(self) -> None:
        """F1 Benchmark, Career Memory и Career Stats — независимые источники
        контекста для LLM, но `analytics_context` — одна строка. Собираем все
        непустые части вместе, чтобы каждое новое сравнение не затирало
        предыдущее."""
        parts = [p for p in (self._f1_context_line, self._career_context_line,
                             self._career_stats_context_line) if p]
        self.set_analytics_context(" ".join(parts) if parts else None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_engine_story.py -v`
Expected: all PASS (including the pre-existing `test_generate_story_sets_state` — this project's dev `DATA_DIR/game_sessions/` is empty, so `compute_career_stats()` returns `None` for that test and doesn't change its behavior)

- [ ] **Step 5: Checkpoint**

Run the broader regression: `py -3.12 -m pytest tests/test_career_memory.py tests/test_engine_career_memory.py tests/test_engine_f1_benchmark.py -v` — expected all PASS unchanged (confirms the SSTA reset edit and `_refresh_analytics_context` edit didn't disturb the sibling `career_memory`/`f1_benchmark` context-line logic they share the block with). No git commit needed (project has no git repo). Move to Task 5.

---

### Task 5: Full regression + `CONTEXT.md` session note

**Files:**
- Modify: `CONTEXT.md`
- No code changes

- [ ] **Step 1: Run the full test suite**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: 0 failed. Note the exact "N passed, M skipped" line (baseline before this feature was 1011 passed, 1 skipped) — call this count `<TOTAL>` below.

- [ ] **Step 2: Import smoke test**

Run: `py -3.12 -c "import core.career_stats, core.race_story, commentator.story, core.engine"`
Expected: no output, exit code 0

- [ ] **Step 3: Add a new session section to `CONTEXT.md`**

Read the current `CONTEXT.md` first (it changes between sessions). Insert a new session section directly above the current newest session entry (following this file's convention of newest-session-on-top, right after the "На чём остановились" block), and update "На чём остановились" to point at this closure. Use this template, filling in the real `<TOTAL>` from Step 1:

```markdown
## Сессия 2026-07-08 — Карьерная статистика (кросс-трековый агрегат), 5/5 ✅

Закрывает пункт бэклога «кросс-гоночная карьерная память» — `core/career_memory.py`
сравнивает игрока с его историей только НА ОДНОЙ И ТОЙ ЖЕ трассе; кросс-трековый
агрегат (сколько гонок всего, побед, подиумов, средняя позиция) design-спека
`2026-07-03-career-memory-design.md` явно относила к «вне рамок». План:
`docs/superpowers/plans/2026-07-08-career-stats.md`, спека:
`docs/superpowers/specs/2026-07-08-career-stats-design.md`.

- **`core/career_stats.py`** (новый) — чистая функция `compute_career_stats()`
  (не класс, в отличие от `CareerMemory` — считается один раз в момент финиша,
  не live во время гонки), агрегирует по `analytics/archive.py::list_game_sessions()`
  без доп. I/O. `total_races` считается по гонкам С известным `final_position`
  (иначе разойдётся с wins/podiums/avg). `podiums` включает победы.
- **Поверхности — ТОЛЬКО Post-Race Story факт + Voice Q&A контекст** (решение
  пользователя) — никакой UI-панели, никакой отдельной голосовой реплики.
  `core/race_story.py::facts()` получил kwarg `career_stats`;
  `commentator/story.py::_format_facts()` — новая строка-буллет в факт-лист
  LLM (офлайн-фолбэк `render_fallback()` не тронут — тот же принцип, что у
  `vs_last_visit`/`weak_sector_vs_f1`).
- **`core/engine.py`** — `_generate_story` считает `career_stats` сразу после
  `finalize()` (только что завершённая гонка уже на диске — попадает в
  подсчёт без искусственного +1); новый `_career_stats_context_line`
  подмешивается в `_refresh_analytics_context()` наравне с
  `_f1_context_line`/`_career_context_line`. Сбрасывается на `SSTA` — но НЕ на
  смене трассы (в отличие от `_career_context_line`), т.к. это глобальная, не
  трековая статистика.

**Верификация:** `tests/test_career_stats.py` (6 тестов, новый),
`tests/test_story_collector.py`/`tests/test_story_generator.py` (расширены),
`tests/test_engine_story.py` (расширен, 1 новый интеграционный тест сквозь
весь путь архив→контекст). Полный прогон
`py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q` — **<TOTAL>** (было 1011
passed, 1 skipped). Импорт-смоук — без ошибок.
```

Replace `<TOTAL>` with the actual line from Step 1.

- [ ] **Step 4: Checkpoint (final)**

Confirm `CONTEXT.md` renders correctly (no broken markdown), full suite green, import smoke clean. Feature complete.

---

## Plan Self-Review Notes

- **Spec coverage:** all 4 design sections (`core/career_stats.py`, `race_story.py`
  kwarg, `story.py` bullet, `engine.py` orchestration) map 1:1 to Tasks 1-4. The
  "reset on SSTA, not on track change" nuance from the design is called out
  explicitly in Task 4 Step 3c to prevent an implementer from copy-pasting the
  reset into the wrong block (there are two similar-looking reset sites in
  `engine.py` for `_career_context_line` — only one is correct for this new field).
- **No engine-level test for the `career_stats=career_stats` kwarg threading into
  `facts()` in isolation** — intentional. It's a one-line addition inside a method
  already covered by `test_generate_story_sets_state`, and the more meaningful
  integration point (does the archive scan actually reach `analytics_context`) IS
  covered by Task 4's new test. Matches the precedent set by prior plans in this
  project for low-risk glue code.
- **No reset-on-SSTA test added** — also intentional, matching existing project
  restraint: there is no existing test that verifies `_career_context_line`
  resets to `None` on `SSTA` either, so adding one only for the new field would
  be inconsistent test coverage for no real risk reduction (single-line reset,
  same shape as its untested siblings).
- **Type/signature consistency check:** `compute_career_stats() -> dict | None`,
  `context_line(stats: dict) -> str`, `RaceStoryCollector.facts(..., career_stats:
  dict | None = None)`, `facts()["career_stats"]`, `commentator.story._format_facts`
  reading `facts.get("career_stats")` — same names used consistently across
  Tasks 1-4 and their tests.
