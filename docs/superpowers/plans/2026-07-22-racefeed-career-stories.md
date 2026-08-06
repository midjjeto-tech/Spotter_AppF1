# RaceFeed Career Stories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the player's existing per-track personal records and
all-time career stats through RaceFeed — mid-race "personal best beaten"
posts, and a race-finish recap post — reusing data this codebase already
computes, through the existing (previously dead) `player_progression`
category.

**Architecture:** Two new event types flow through the app's single existing
telemetry-event pipeline (`CommentaryEvents.publish()`), exactly like every
other RaceFeed-visible event. `CAREER_PB`/`CAREER_SECTOR_PB` already exist
and already reach RaceFeed's ingest queue today — they're enriched with a
`vehicle_idx` (fixing a real bug where they're currently invisible to the
player-involvement check) and raw comparison numbers. A new `CAREER_RECAP`
event is published once, at race finish, from a new small method with its
own importance scoring so routine finishes don't spam a post. `StoryBuilder`
gets 3 new code-to-category mappings, all pointing at the existing, unused
`player_progression` category — no reporter or prompt changes needed.

**Tech Stack:** Python 3.12, pytest, existing `CommentaryEvents`/`RaceFeedEngine`
infrastructure (all pre-existing, built across earlier plans).

**Note on commits:** This repo has no git — every task ends with a
Checkpoint step (mark done, no commit), not `git commit`.

**Coordination note:** Per `CODEX_CLAUDE_HANDOFF.md`'s protocol, claim
ownership of `core/engine.py`, `core/racefeed/engine.py`, and the listed test
files in that file's "Активная работа" section before starting Task 1, and
mark them unlocked again after Task 5.

---

## Task 1: Enrich `CAREER_PB`/`CAREER_SECTOR_PB` + add the PB-this-race flag

**Files:**
- Modify: `core/engine.py`
- Test: `tests/test_engine_career_memory.py`

This fixes a real, verified bug: these two events currently reach
`CommentaryEvents.publish()` with no `vehicle_idx` key and `"driver": ""`.
`_event_involves()` (`core/engine.py:662-672`) only checks `vehicle_idx`,
`overtaking_idx`, `being_overtaken_idx`, `vehicle1_idx`, `vehicle2_idx` — it
never looks at `driver`. With none of those keys present,
`context.player_involved` resolves to `False` today, which means even after
Task 3 adds a `StoryBuilder` category mapping for these codes, they'd still
be silently dropped (`StoryBuilder.from_event()`'s gate is `if category is
None and (event.is_player or event.is_player_team):`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine_career_memory.py` (reuses the existing
`_FakeCareer` class and `_drain`/`engine` fixture already in this file —
don't redefine them):

```python
def test_pb_event_carries_vehicle_idx_and_raw_comparison_fields(engine):
    engine.career_memory = _FakeCareer()
    engine._career_comparison_progress.best_lap_ms = None
    engine._career_comparison_progress.best_sector_ms = {}
    _drain(engine)
    engine._update_career_memory()
    evt = engine._commentary_events.get_nowait()
    assert evt["vehicle_idx"] == engine._player_car_index
    assert evt["gap_ms"] == -500
    assert evt["player_best_ms"] == 79500
    assert evt["best_ever_ms"] == 80000
    assert evt["best_ever_date"] == "2026-01-01"


def test_sector_pb_event_carries_vehicle_idx(engine):
    sectors = {1: {"player_ms": 26400, "gap_ms": -100}, 2: {"player_ms": 27400, "gap_ms": -100},
               3: {"player_ms": 25700, "gap_ms": -300}}
    engine.career_memory = _FakeCareer(sectors=sectors)
    engine._career_comparison_progress.best_lap_ms = None
    engine._career_comparison_progress.best_sector_ms = {}
    _drain(engine)
    engine._update_career_memory()
    events = _drain(engine)
    sector_events = [e for e in events if e["event_code"] == "CAREER_SECTOR_PB"]
    assert len(sector_events) == 1
    assert sector_events[0]["vehicle_idx"] == engine._player_car_index


def test_lap_pb_sets_career_pb_this_race_flag(engine):
    engine.career_memory = _FakeCareer()
    engine._career_comparison_progress.best_lap_ms = None
    engine._career_comparison_progress.best_sector_ms = {}
    engine._career_pb_this_race = False
    _drain(engine)
    engine._update_career_memory()
    assert engine._career_pb_this_race is True


def test_sector_pb_sets_career_pb_this_race_flag(engine):
    sectors = {1: {"player_ms": 26400, "gap_ms": -100}, 2: {"player_ms": 27400, "gap_ms": -100},
               3: {"player_ms": 25700, "gap_ms": -300}}
    engine.career_memory = _FakeCareer(sectors=sectors)
    engine._career_comparison_progress.best_lap_ms = None
    engine._career_comparison_progress.best_sector_ms = {}
    engine._career_pb_this_race = False
    _drain(engine)
    engine._update_career_memory()
    assert engine._career_pb_this_race is True


def test_no_pb_does_not_set_career_pb_this_race_flag(engine):
    engine.career_memory = _FakeCareer()
    engine._career_comparison_progress.best_lap_ms = 79500
    engine._career_comparison_progress.best_sector_ms = {1: 26400, 2: 27400, 3: 25700}
    engine._career_pb_this_race = False
    _drain(engine)
    engine._update_career_memory()
    assert engine._career_pb_this_race is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -u -m pytest tests/test_engine_career_memory.py -v -k "vehicle_idx or career_pb_this_race"`
Expected: FAIL — `KeyError: 'vehicle_idx'` on the first two, `AttributeError:
'F1Engine' object has no attribute '_career_pb_this_race'` on the rest.

- [ ] **Step 3: Add the `_career_pb_this_race` attribute**

In `core/engine.py`, find:
```python
        # Career Stats (кросс-трековый агрегат: всего гонок/побед/подиумов/средняя
        # позиция) — НЕ путать с career_memory выше, которая привязана к трассе.
        self._career_stats_context_line: str | None = None
```
Add immediately after it:
```python

        # True если в ЭТОЙ гонке уже был побит личный рекорд (круг или сектор) —
        # используется _publish_career_recap() (Task 2) как один из сигналов
        # "improvement" для важности карьерного recap-поста на финише.
        self._career_pb_this_race: bool = False
```

- [ ] **Step 4: Enrich the CAREER_PB/CAREER_SECTOR_PB draft dicts and set the flag**

In `core/engine.py`, find (inside `_update_career_memory`):
```python
        milestones = self._career_comparison_progress.observe(cmp)
        if milestones.lap_improved:
            self._commentary_events.publish({
                "event_code": "CAREER_PB", "priority": "normal",
                "phrase": self.career_memory.pb_line(cmp),
                "color": "#60A5FA", "driver": ""})
        if milestones.sector_improved is not None:
            best_n = milestones.sector_improved
            self._commentary_events.publish({
                "event_code": "CAREER_SECTOR_PB", "priority": "normal",
                "phrase": self.career_memory.sector_pb_line(best_n, cmp["sectors"][best_n]),
                "color": "#60A5FA", "driver": ""})
```
Replace with:
```python
        milestones = self._career_comparison_progress.observe(cmp)
        if milestones.lap_improved:
            self._career_pb_this_race = True
            self._commentary_events.publish({
                "event_code": "CAREER_PB", "priority": "normal",
                "phrase": self.career_memory.pb_line(cmp),
                "color": "#60A5FA", "driver": "",
                "vehicle_idx": self._player_car_index,
                "gap_ms": cmp["gap_ms"], "player_best_ms": cmp["player_best_ms"],
                "best_ever_ms": cmp["best_ever_ms"], "best_ever_date": cmp["best_ever_date"]})
        if milestones.sector_improved is not None:
            best_n = milestones.sector_improved
            self._career_pb_this_race = True
            self._commentary_events.publish({
                "event_code": "CAREER_SECTOR_PB", "priority": "normal",
                "phrase": self.career_memory.sector_pb_line(best_n, cmp["sectors"][best_n]),
                "color": "#60A5FA", "driver": "",
                "vehicle_idx": self._player_car_index,
                "sector": best_n, "sector_gap_ms": cmp["sectors"][best_n]["gap_ms"]})
```

- [ ] **Step 5: Reset the flag on SSTA**

In `core/engine.py`, find (inside the `if code == "SSTA":` block):
```python
            self._career_comparison_progress.reset()
            self._career_context_line = None
```
Add immediately after it:
```python
            self._career_pb_this_race = False
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `py -3.12 -u -m pytest tests/test_engine_career_memory.py -v`
Expected: PASS (all tests in the file, including the 5 new ones).

- [ ] **Step 7: Run the full test suite to confirm no regression**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: no new failures.

- [ ] **Step 8: Checkpoint** — Task 1 done, no git commit (see note above).

---

## Task 2: New `_publish_career_recap()` + race-finish call site

**Files:**
- Modify: `core/engine.py`
- Test: `tests/test_engine_career_memory.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engine_career_memory.py`:

```python
def test_career_recap_podium_gets_high_importance(engine):
    engine._career_pb_this_race = False
    _drain(engine)
    engine._publish_career_recap(
        vs_last_visit={"laptime_delta_ms": 500, "position_delta": -2, "last_visit_date": "2026-01-01"},
        career_stats={"total_races": 10, "wins": 1, "podiums": 3, "avg_position": 5.0},
        final_pos=2,
    )
    evt = engine._commentary_events.get_nowait()
    assert evt["event_code"] == "CAREER_RECAP"
    assert evt["importance"] == 90
    assert evt["vehicle_idx"] == engine._player_car_index


def test_career_recap_improved_position_gets_medium_importance(engine):
    engine._career_pb_this_race = False
    _drain(engine)
    engine._publish_career_recap(
        vs_last_visit={"laptime_delta_ms": 500, "position_delta": 3, "last_visit_date": "2026-01-01"},
        career_stats={"total_races": 10, "wins": 0, "podiums": 0, "avg_position": 8.0},
        final_pos=7,
    )
    evt = engine._commentary_events.get_nowait()
    assert evt["importance"] == 70


def test_career_recap_faster_lap_gets_medium_importance(engine):
    engine._career_pb_this_race = False
    _drain(engine)
    engine._publish_career_recap(
        vs_last_visit={"laptime_delta_ms": -250, "position_delta": -1, "last_visit_date": "2026-01-01"},
        career_stats={"total_races": 10, "wins": 0, "podiums": 0, "avg_position": 8.0},
        final_pos=9,
    )
    evt = engine._commentary_events.get_nowait()
    assert evt["importance"] == 70


def test_career_recap_pb_this_race_gets_medium_importance_even_if_vs_last_visit_none(engine):
    engine._career_pb_this_race = True
    _drain(engine)
    engine._publish_career_recap(
        vs_last_visit=None,
        career_stats={"total_races": 1, "wins": 0, "podiums": 0, "avg_position": 9.0},
        final_pos=9,
    )
    evt = engine._commentary_events.get_nowait()
    assert evt["importance"] == 70


def test_career_recap_routine_finish_gets_low_importance(engine):
    engine._career_pb_this_race = False
    _drain(engine)
    engine._publish_career_recap(
        vs_last_visit={"laptime_delta_ms": 300, "position_delta": -1, "last_visit_date": "2026-01-01"},
        career_stats={"total_races": 10, "wins": 0, "podiums": 0, "avg_position": 8.0},
        final_pos=9,
    )
    evt = engine._commentary_events.get_nowait()
    assert evt["importance"] == 40


def test_career_recap_handles_none_vs_last_visit_without_crashing(engine):
    engine._career_pb_this_race = False
    _drain(engine)
    engine._publish_career_recap(
        vs_last_visit=None,
        career_stats={"total_races": 1, "wins": 0, "podiums": 0, "avg_position": 9.0},
        final_pos=9,
    )
    evt = engine._commentary_events.get_nowait()
    assert evt["importance"] == 40


def test_career_recap_carries_facts_for_racefeed(engine):
    vs_last_visit = {"laptime_delta_ms": 500, "position_delta": -2, "last_visit_date": "2026-01-01"}
    career_stats = {"total_races": 10, "wins": 1, "podiums": 3, "avg_position": 5.0}
    engine._career_pb_this_race = False
    _drain(engine)
    engine._publish_career_recap(vs_last_visit=vs_last_visit, career_stats=career_stats, final_pos=2)
    evt = engine._commentary_events.get_nowait()
    assert evt["vs_last_visit"] == vs_last_visit
    assert evt["career_stats"] == career_stats
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -u -m pytest tests/test_engine_career_memory.py -v -k career_recap`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute '_publish_career_recap'`

- [ ] **Step 3: Write `_publish_career_recap`**

In `core/engine.py`, add this new method immediately after `_update_career_memory`
(right after the method whose body ends with the `CAREER_SECTOR_PB` publish
call from Task 1, Step 4):

```python
    def _publish_career_recap(self, vs_last_visit: dict | None, career_stats: dict,
                               final_pos: int | None) -> None:
        """Race-finish career recap for RaceFeed (player_progression category,
        Player's Garage reporter) — reuses facts already computed for Post-Race
        Story (see _generate_story), adding an importance score so the Editor
        can decide whether this finish is actually worth a post. Signs per
        core/career_memory.py::story_facts(): position_delta > 0 = better
        finish than last visit; laptime_delta_ms < 0 = faster than last visit."""
        is_podium = final_pos is not None and final_pos <= 3
        improved = self._career_pb_this_race or (
            vs_last_visit is not None
            and (vs_last_visit["position_delta"] > 0 or vs_last_visit["laptime_delta_ms"] < 0)
        )
        if is_podium:
            importance = 90
        elif improved:
            importance = 70
        else:
            importance = 40
        self._commentary_events.publish({
            "event_code": "CAREER_RECAP", "priority": "normal",
            "driver": "", "color": "#60A5FA",
            "vehicle_idx": self._player_car_index,
            "importance": importance,
            "vs_last_visit": vs_last_visit,
            "career_stats": career_stats,
        })
```

- [ ] **Step 4: Wire the call site in `_generate_story`**

In `core/engine.py`, find (inside `_generate_story`):
```python
            vs_last_visit = self.career_memory.story_facts(final_pos, laps)["vs_last_visit"]
            career_stats = career_stats_mod.compute_career_stats()
            self._career_stats_context_line = (
                career_stats_mod.context_line(career_stats) if career_stats else None)
```
Add immediately after it:
```python
            self._publish_career_recap(vs_last_visit, career_stats, final_pos)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -3.12 -u -m pytest tests/test_engine_career_memory.py -v`
Expected: PASS (all tests, including the 7 new ones).

- [ ] **Step 6: Run the full test suite to confirm no regression**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: no new failures.

- [ ] **Step 7: Checkpoint** — Task 2 done.

---

## Task 3: StoryBuilder category mappings

**Files:**
- Modify: `core/racefeed/engine.py`
- Test: `tests/racefeed/test_story_builder.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/racefeed/test_story_builder.py` (reuses the existing
`_event()` helper already in this file):

```python
def test_from_event_maps_career_pb_codes_to_player_progression():
    builder = StoryBuilder(StoryMemory())
    story = builder.from_event(_event("CAREER_PB", is_player=True))
    assert story is not None
    assert story.category == "player_progression"


def test_from_event_maps_career_sector_pb_to_player_progression():
    builder = StoryBuilder(StoryMemory())
    story = builder.from_event(_event("CAREER_SECTOR_PB", is_player=True))
    assert story is not None
    assert story.category == "player_progression"


def test_from_event_maps_career_recap_to_player_progression():
    builder = StoryBuilder(StoryMemory())
    story = builder.from_event(_event("CAREER_RECAP", is_player=True))
    assert story is not None
    assert story.category == "player_progression"


def test_from_event_ignores_career_codes_when_not_player():
    builder = StoryBuilder(StoryMemory())
    assert builder.from_event(_event("CAREER_PB", is_player=False)) is None
    assert builder.from_event(_event("CAREER_SECTOR_PB", is_player=False)) is None
    assert builder.from_event(_event("CAREER_RECAP", is_player=False)) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -u -m pytest tests/racefeed/test_story_builder.py -v -k career`
Expected: FAIL — `assert story is not None` fails (`story` is `None`) since
these codes aren't mapped yet.

- [ ] **Step 3: Add the mappings**

In `core/racefeed/engine.py`, find:
```python
_PLAYER_ONLY_CODES: dict[str, str] = {
    "PIT_EXIT": "player_pit_stop",
    "OVTK": "player_overtake",
    "FTLP": "player_fastest_lap",
}
```
Replace with:
```python
_PLAYER_ONLY_CODES: dict[str, str] = {
    "PIT_EXIT": "player_pit_stop",
    "OVTK": "player_overtake",
    "FTLP": "player_fastest_lap",
    "CAREER_PB": "player_progression",
    "CAREER_SECTOR_PB": "player_progression",
    "CAREER_RECAP": "player_progression",
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -u -m pytest tests/racefeed/test_story_builder.py -v`
Expected: PASS (all tests in the file, including the 4 new ones).

- [ ] **Step 5: Run the full racefeed suite**

Run: `py -3.12 -u -m pytest tests/racefeed -v`
Expected: PASS, no regressions.

- [ ] **Step 6: Checkpoint** — Task 3 done.

---

## Task 4: Integration test — full career-recap flow, 3 scenarios

**Files:**
- Test: `tests/racefeed/test_career_recap_integration.py`

This proves the whole chain works end to end through the REAL pipeline
(StoryBuilder → Reporter → Editor), not just each piece in isolation — the
thing that actually matters is that a routine finish gets suppressed while a
podium or improvement publishes.

- [ ] **Step 1: Write the test**

`tests/racefeed/test_career_recap_integration.py`:
```python
import time

from core.racefeed.editor import Editor, StoryMemory
from core.racefeed.engine import StoryBuilder
from core.racefeed.models import Event
from core.racefeed.reporters import REPORTERS


def _career_recap_event(importance: int) -> Event:
    return Event(
        event_code="CAREER_RECAP", session_type="race", driver=None, team=None,
        vehicle_idx=4, is_player=True, importance=importance, laps_remaining=0,
        description="career recap", extra={
            "vs_last_visit": {"laptime_delta_ms": -200, "position_delta": 2,
                              "last_visit_date": "2026-01-01"},
            "career_stats": {"total_races": 10, "wins": 1, "podiums": 3, "avg_position": 5.0},
        },
        enqueued_at=time.time(),
    )


def _propose_and_evaluate(story):
    """Mirrors RaceFeedEngine._propose_and_schedule for a single story, without
    needing a running worker thread — returns the Editor's decision, or None if
    no reporter covers the story at all."""
    editor = Editor()
    for reporter in REPORTERS:
        candidate = reporter.propose(story)
        if candidate is None:
            continue
        return editor.evaluate(candidate, story)
    return None


def test_podium_recap_publishes():
    builder = StoryBuilder(StoryMemory())
    story = builder.from_event(_career_recap_event(importance=90))
    assert _propose_and_evaluate(story) == "new"


def test_improved_recap_publishes():
    builder = StoryBuilder(StoryMemory())
    story = builder.from_event(_career_recap_event(importance=70))
    assert _propose_and_evaluate(story) == "new"


def test_routine_recap_is_suppressed():
    builder = StoryBuilder(StoryMemory())
    story = builder.from_event(_career_recap_event(importance=40))
    assert _propose_and_evaluate(story) == "suppress"
```

- [ ] **Step 2: Run the test**

Run: `py -3.12 -u -m pytest tests/racefeed/test_career_recap_integration.py -v`
Expected: PASS (3 passed). If `test_routine_recap_is_suppressed` fails
(publishes when it shouldn't), check `core/racefeed/editor.py::PUBLISH_THRESHOLD`
(should be `60`) — importance `40` must be below it.

- [ ] **Step 3: Run the full racefeed suite one more time**

Run: `py -3.12 -u -m pytest tests/racefeed -v`
Expected: PASS, no regressions.

- [ ] **Step 4: Checkpoint** — Task 4 done.

---

## Task 5: Full regression + manual verification + handoff

**Files:** none — verification and coordination, not code changes.

- [ ] **Step 1: Full backend test suite**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: 0 failures.

- [ ] **Step 2: Live verification (requires F1 25 running, RaceFeed enabled)**

Two things to confirm once telemetry is flowing:
1. Beat a personal best (lap or sector) at a track you've raced before —
   confirm a RaceFeed post appears referencing it (not just the voiced
   commentary phrase — RaceFeed's post should read differently, per Player's
   Garage's "don't repeat engineer radio verbatim" rule).
2. Finish a race. If it was a podium, or faster/better than your last visit
   to that track, confirm a recap post appears. If it was a routine finish
   with no improvement, confirm no recap post appears (check
   `/api/racefeed` or the RaceFeed UI tab shows nothing new for that story).

- [ ] **Step 3: Update `CODEX_CLAUDE_HANDOFF.md`**

Mark this task's files unlocked (`core/engine.py`, `core/racefeed/engine.py`,
the 3 test files), record the new `CAREER_PB`/`CAREER_SECTOR_PB`/
`CAREER_RECAP` contract (event shapes, the `_career_pb_this_race` flag, the
importance thresholds) for Codex's awareness, and note the still-open,
deliberately-deferred `F1_BENCH`/`F1_SECTOR_BENCH` `vehicle_idx` bug found
along the way (same root cause, different event codes, not fixed here).

- [ ] **Step 4: Checkpoint** — Task 5 done. Career stories complete.

---

## Self-review notes

**Spec coverage:** Both career moments from the spec are covered — Task 1
(mid-race PB enrichment + bug fix), Task 2 (race-finish recap + importance
scoring), Task 3 (category wiring). The spec's testing section maps to Task
1/2's unit tests, Task 3's mapping tests, and Task 4's integration test:
"career_memory not ready" is already covered by the pre-existing
`test_update_noop_when_not_ready` test in `tests/test_engine_career_memory.py`
(confirmed present before writing this plan) — `_publish_career_recap` itself
doesn't need its own separate "not ready" test since it's called with
already-computed `vs_last_visit`/`career_stats` values (the readiness gate
lives upstream, in `_update_career_memory` and the existing race-finish
computation block that already tolerates `vs_last_visit is None`).

**Placeholder scan:** No TBD/TODO; every step has complete code grounded in
the actual current file contents, verified by direct reads (not assumed)
immediately before writing this plan, including two real corrections
(`position_delta` sign convention, `vs_last_visit` nullability) caught by
reading `core/career_memory.py` directly rather than trusting an earlier
research summary.

**Type consistency:** `_publish_career_recap(vs_last_visit: dict | None,
career_stats: dict, final_pos: int | None)` (Task 2) matches the call site
added in `_generate_story` (Task 2, Step 4), which passes the exact same
`vs_last_visit`/`career_stats`/`final_pos` local variables already computed
a few lines above it. `"CAREER_PB"`/`"CAREER_SECTOR_PB"`/`"CAREER_RECAP"`
(Task 1/2's event_code strings) match exactly what Task 3's
`_PLAYER_ONLY_CODES` keys expect.
