# RaceFeed Season / Championship Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give RaceFeed a persistent, sliding-window championship — a real standings table (player + rivals), a recurring rival, a post-race narrative post with a cliffhanger, and a pinned standings card — so the player has a reason to come back.

**Architecture:** On the Final Classification packet, the engine records every driver's game-awarded `points` into a dedicated season store. A pure `core/season.py` computes standings/rival/summary from the last ~22 race records. Race finish publishes a `CHAMPIONSHIP` RaceFeed event (new `championship_desk` reporter) and a new `GET /api/racefeed/standings` endpoint feeds a pinned table in the channel UI.

**Tech Stack:** Python 3.12 (backend, pytest), Bottle (web routes), Next.js/React + TypeScript (frontend). Spec: `docs/superpowers/specs/2026-07-25-racefeed-season-championship-design.md`.

**Project note:** This repo is **not** under git. Ignore any "commit" convention — the per-task checkpoint is running that task's tests green. Backend tests run with `py -3.12 -m pytest ...`; frontend verification is `node_modules/.bin/tsc --noEmit -p tsconfig.json` from `NewSpotterUI/`.

---

## File Structure

- Create `core/season.py` — pure standings/rival/summary + `build_classification` helper.
- Create `tests/test_season.py`, `tests/test_archive_season.py`.
- Modify `analytics/archive.py` — `save_season_result` / `list_season_results` + `_SEASON` folder.
- Modify `core/racefeed/engine.py` — `StoryBuilder._PLAYER_ONLY_CODES` gains `CHAMPIONSHIP`.
- Modify `core/racefeed/reporters.py` — `ChampionshipReporter` + `CHAMPIONSHIP_CATEGORIES` + `REPORTERS`.
- Modify `core/racefeed/prompts.py` — `championship_desk` system prompt.
- Modify `core/racefeed/ui_bridge.py` — `get_standings()`.
- Modify `core/engine.py` — `_maybe_record_championship()` at the packet-8 site, `_championship_recorded` flag + SSTA reset, `get_season_standings()`.
- Modify `web_server.py` — `GET /api/racefeed/standings`.
- Modify `NewSpotterUI/lib/api.ts` — `StandingsRow`, `SeasonStandingsResponse`, `getSeasonStandings`.
- Modify `NewSpotterUI/lib/use-racefeed.ts` — `useSeasonStandings` hook.
- Modify `NewSpotterUI/components/spotter/views/race-feed-channel.tsx` — `ChampionshipStandings` card + `standings` prop.
- Modify `NewSpotterUI/components/spotter/views/race-feed.tsx` — wire the hook.
- Modify test files under `tests/racefeed/` for the new category/reporter/endpoint.

---

## Task 1: Season results store (`analytics/archive.py`)

**Files:**
- Modify: `analytics/archive.py`
- Test: `tests/test_archive_season.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_archive_season.py
import analytics.archive as archive


def test_season_result_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_SEASON", tmp_path / "season")
    archive.save_season_result({"track_id": 1, "classification": [{"driver": "Max", "points": 25}]})
    out = archive.list_season_results()
    assert len(out) == 1
    assert out[0]["classification"][0]["driver"] == "Max"


def test_season_results_newest_first_and_limited(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(archive, "_SEASON", tmp_path / "season")
    for i in range(3):
        archive.save_season_result({"track_id": i})
        time.sleep(0.01)  # distinct timestamped filenames
    out = archive.list_season_results(limit=2)
    assert [d["track_id"] for d in out] == [2, 1]  # newest-first, truncated


def test_list_season_results_empty_when_no_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_SEASON", tmp_path / "nope")
    assert archive.list_season_results() == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `py -3.12 -m pytest tests/test_archive_season.py -v`
Expected: FAIL (`AttributeError: module 'analytics.archive' has no attribute '_SEASON'`).

- [ ] **Step 3: Implement**

In `analytics/archive.py`, after the line `_RACE_ARCHIVE = _DATA / "race_archive"` (~line 16) add:

```python
_SEASON = _DATA / "season"
```

Then, after `get_last_race()` (~line 102) add:

```python
# --- Season championship results (one JSON per finished race, points included) ---

def save_season_result(data: dict) -> Path:
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
    path = _SEASON / f"{ts}.json"
    _atomic_write(path, data)
    return path


def list_season_results(limit: int | None = None) -> list[dict]:
    """Full race records, newest-first, optionally truncated to `limit`."""
    if not _SEASON.exists():
        return []
    files = sorted(_SEASON.glob("*.json"), reverse=True)
    if limit is not None:
        files = files[:limit]
    result: list[dict] = []
    for f in files:
        try:
            d = _load(f)
        except (OSError, json.JSONDecodeError):
            _log.warning("Skipping corrupt season file: %s", f)
            continue
        if d is not None:
            result.append(d)
    return result
```

- [ ] **Step 4: Run to verify it passes**

Run: `py -3.12 -m pytest tests/test_archive_season.py -v`
Expected: PASS (3 tests).

---

## Task 2: Standings computation (`core/season.py`)

**Files:**
- Create: `core/season.py`
- Test: `tests/test_season.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_season.py
import core.season as season


def _race(rows):
    return {"classification": rows}


def _driver_lookup(table):
    return lambda idx: table.get(idx, {"name": "гонщик", "team": "", "color": "#9CA3AF"})


def test_build_classification_flags_player_and_reads_points():
    grid = [
        {"vehicle_idx": 0, "position": 1, "points": 25},
        {"vehicle_idx": 4, "position": 2, "points": 18},
    ]
    lookup = _driver_lookup({0: {"name": "Max", "team": "Red Bull", "color": "#3671C6"},
                             4: {"name": "Norris", "team": "McLaren", "color": "#FF8000"}})
    rows = season.build_classification(grid, lookup, player_idx=4)
    assert rows[0] == {"position": 1, "points": 25, "driver": "Max",
                       "team": "Red Bull", "color": "#3671C6", "is_player": False}
    assert rows[1]["is_player"] is True


def test_compute_standings_sums_points_by_driver(monkeypatch):
    monkeypatch.setattr(season.archive, "list_season_results", lambda limit=None: [
        _race([{"driver": "Max", "points": 25, "team": "Red Bull", "position": 1, "is_player": False},
               {"driver": "You", "points": 18, "team": "Ferrari", "position": 2, "is_player": True}]),
        _race([{"driver": "Max", "points": 18, "team": "Red Bull", "position": 2, "is_player": False},
               {"driver": "You", "points": 25, "team": "Ferrari", "position": 1, "is_player": True}]),
    ])
    result = season.compute_standings()
    assert result["races_counted"] == 2
    table = result["standings"]
    assert [r["driver"] for r in table] == ["Max", "You"]  # 43 vs 43 -> tie broken by wins? both 1 win -> name
    assert table[0]["points"] == 43 and table[1]["points"] == 43
    assert table[0]["position"] == 1 and table[1]["position"] == 2
    assert any(r["is_player"] for r in table)


def test_compute_standings_none_when_store_empty(monkeypatch):
    monkeypatch.setattr(season.archive, "list_season_results", lambda limit=None: [])
    assert season.compute_standings() is None


def test_pick_rival_returns_driver_ahead():
    table = [{"driver": "Max", "points": 50, "is_player": False, "position": 1},
             {"driver": "You", "points": 40, "is_player": True, "position": 2},
             {"driver": "Norris", "points": 30, "is_player": False, "position": 3}]
    assert season.pick_rival(table)["driver"] == "Max"


def test_pick_rival_when_player_leads_returns_driver_behind():
    table = [{"driver": "You", "points": 50, "is_player": True, "position": 1},
             {"driver": "Max", "points": 40, "is_player": False, "position": 2}]
    assert season.pick_rival(table)["driver"] == "Max"


def test_pick_rival_none_when_player_alone():
    assert season.pick_rival([{"driver": "You", "points": 10, "is_player": True, "position": 1}]) is None


def test_season_summary_shape(monkeypatch):
    monkeypatch.setattr(season.archive, "list_season_results", lambda limit=None: [
        _race([{"driver": "Max", "points": 50, "team": "Red Bull", "position": 1, "is_player": False},
               {"driver": "You", "points": 40, "team": "Ferrari", "position": 2, "is_player": True}]),
    ])
    summary = season.season_summary(race_points=18)
    assert summary["player_points"] == 40
    assert summary["player_position"] == 2
    assert summary["rival"] == "Max"
    assert summary["gap_to_rival"] == 10
    assert summary["race_points"] == 18
    assert summary["races_counted"] == 1


def test_season_summary_none_when_player_not_classified(monkeypatch):
    monkeypatch.setattr(season.archive, "list_season_results", lambda limit=None: [
        _race([{"driver": "Max", "points": 25, "team": "Red Bull", "position": 1, "is_player": False}]),
    ])
    assert season.season_summary() is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `py -3.12 -m pytest tests/test_season.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'core.season'`).

- [ ] **Step 3: Implement**

```python
# core/season.py
"""
core/season.py
==============
Sliding-window championship over the season store (analytics/archive.py::
list_season_results). Pure functions, no state, no network — computed on demand,
same pattern as core/career_stats.py. "Season" = the last SEASON_WINDOW races
(a form championship; the telemetry has no round/season id — see design doc).
"""
from __future__ import annotations

from analytics import archive

SEASON_WINDOW = 22


def build_classification(grid: list[dict], driver_lookup, player_idx: int) -> list[dict]:
    """Turn raw final-classification entries into store rows.

    grid: entries with position/points/vehicle_idx (parse_final_classification_grid).
    driver_lookup: callable vehicle_idx -> {"name","team","color"} (race_state.driver).
    """
    rows: list[dict] = []
    for entry in grid:
        idx = entry.get("vehicle_idx")
        ident = driver_lookup(idx)
        rows.append({
            "position": entry.get("position"),
            "points": int(entry.get("points") or 0),
            "driver": ident.get("name"),
            "team": ident.get("team"),
            "color": ident.get("color"),
            "is_player": idx == player_idx,
        })
    return rows


def compute_standings(window: int = SEASON_WINDOW) -> dict | None:
    """Championship table over the last `window` recorded races, newest-first.
    None if the season store is empty (no classified race yet)."""
    races = archive.list_season_results(limit=window)
    if not races:
        return None
    totals: dict[str, dict] = {}
    for race in races:  # newest-first: first sighting of a driver = latest team
        for entry in race.get("classification", []):
            driver = entry.get("driver")
            if not driver:
                continue
            row = totals.setdefault(driver, {
                "driver": driver, "points": 0, "wins": 0,
                "team": entry.get("team"), "color": entry.get("color"),
                "is_player": False,
            })
            row["points"] += int(entry.get("points") or 0)
            if entry.get("position") == 1:
                row["wins"] += 1
            if entry.get("is_player"):
                row["is_player"] = True
    standings = sorted(
        totals.values(), key=lambda r: (-r["points"], -r["wins"], r["driver"])
    )
    for position, row in enumerate(standings, start=1):
        row["position"] = position
    return {"standings": standings, "races_counted": len(races)}


def pick_rival(standings: list[dict]) -> dict | None:
    """Driver adjacent to the player: the one directly ahead by points, or
    directly behind if the player leads. None if the player isn't in the table
    or is the only entry."""
    idx = next((i for i, r in enumerate(standings) if r.get("is_player")), None)
    if idx is None or len(standings) < 2:
        return None
    return standings[1] if idx == 0 else standings[idx - 1]


def season_summary(window: int = SEASON_WINDOW,
                   race_points: int | None = None) -> dict | None:
    """Fact set for the CHAMPIONSHIP RaceFeed event. None when there's no
    season store yet or the player isn't classified in the window."""
    result = compute_standings(window)
    if result is None:
        return None
    standings = result["standings"]
    player = next((r for r in standings if r.get("is_player")), None)
    if player is None:
        return None
    summary = {
        "player_points": player["points"],
        "player_position": player["position"],
        "races_counted": result["races_counted"],
    }
    if race_points is not None:
        summary["race_points"] = race_points
    rival = pick_rival(standings)
    if rival is not None:
        summary["rival"] = rival["driver"]
        summary["rival_points"] = rival["points"]
        summary["gap_to_rival"] = abs(player["points"] - rival["points"])
    return summary
```

- [ ] **Step 4: Run to verify it passes**

Run: `py -3.12 -m pytest tests/test_season.py -v`
Expected: PASS (8 tests).

---

## Task 3: RaceFeed championship category + reporter + prompt

**Files:**
- Modify: `core/racefeed/engine.py` (StoryBuilder map)
- Modify: `core/racefeed/reporters.py`
- Modify: `core/racefeed/prompts.py`
- Test: `tests/racefeed/test_story_builder.py`, `tests/racefeed/test_reporters.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/racefeed/test_reporters.py`:

```python
def test_championship_reporter_covers_only_championship_in_race():
    from core.racefeed.reporters import ChampionshipReporter
    r = ChampionshipReporter()
    assert r.covers(_story("championship", session_type="race")) is True
    assert r.covers(_story("championship", session_type="qualifying")) is False
    assert r.covers(_story("penalty", session_type="race")) is False


def test_championship_reporter_propose_priority_and_id():
    from core.racefeed.reporters import ChampionshipReporter
    candidate = ChampionshipReporter().propose(
        _story("championship", {"importance": 85}, session_type="race"))
    assert candidate is not None
    assert candidate.reporter_id == "championship_desk"
    assert candidate.priority == "analysis"
    assert candidate.update_policy == "supersede"
```

Update the roster test in `tests/racefeed/test_reporters.py`:

```python
def test_reporters_list_has_one_of_each_with_unique_ids():
    from core.racefeed.reporters import REPORTERS
    assert len(REPORTERS) == 5
    ids = [r.id for r in REPORTERS]
    assert len(ids) == len(set(ids))
    assert set(ids) == {
        "race_control", "spotter_analytics", "players_garage",
        "qualifying_control", "championship_desk",
    }
```

Append to `tests/racefeed/test_story_builder.py` (follow that file's existing helper style for building an `Event` and calling `StoryBuilder.from_event`):

```python
def test_championship_code_maps_to_championship_category():
    from core.racefeed.editor import StoryMemory
    from core.racefeed.engine import StoryBuilder
    from core.racefeed.models import Event
    builder = StoryBuilder(StoryMemory())
    event = Event(
        event_code="CHAMPIONSHIP", session_type="race", driver="", team=None,
        vehicle_idx=4, is_player=True, importance=85, laps_remaining=None,
        description="", extra={"player_points": 40, "rival": "Max"},
        enqueued_at=0.0,
    )
    story = builder.from_event(event)
    assert story is not None
    assert story.category == "championship"
```

- [ ] **Step 2: Run to verify they fail**

Run: `py -3.12 -m pytest tests/racefeed/test_reporters.py tests/racefeed/test_story_builder.py -v`
Expected: FAIL (`ImportError: cannot import name 'ChampionshipReporter'`, category `None`).

- [ ] **Step 3: Implement**

In `core/racefeed/engine.py`, add `CHAMPIONSHIP` to `_PLAYER_ONLY_CODES`:

```python
_PLAYER_ONLY_CODES: dict[str, str] = {
    "PIT_EXIT": "player_pit_stop",
    "OVTK": "player_overtake",
    "FTLP": "player_fastest_lap",
    "CAREER_PB": "player_progression",
    "CAREER_SECTOR_PB": "player_progression",
    "CAREER_RECAP": "player_progression",
    "CHAMPIONSHIP": "championship",
}
```

In `core/racefeed/reporters.py`, after `QUALIFYING_CATEGORIES` add:

```python
CHAMPIONSHIP_CATEGORIES = {
    "championship": ("analysis", "supersede"),  # one evolving title-fight story
}
```

After `QualifyingReporter`, before `REPORTERS`, add:

```python
class ChampionshipReporter:
    id = "championship_desk"

    def covers(self, story: Story) -> bool:
        return (story.session_type == "race"
                and story.category in CHAMPIONSHIP_CATEGORIES)

    def propose(self, story: Story) -> Candidate | None:
        if not self.covers(story):
            return None
        priority, update_policy = CHAMPIONSHIP_CATEGORIES[story.category]
        base_importance = int(story.facts.get("importance", 70))
        return _make_candidate(story, self.id, priority, update_policy, base_importance)
```

And extend `REPORTERS`:

```python
REPORTERS = [RaceControlReporter(), SpotterAnalyticsReporter(),
             PlayersGarageReporter(), QualifyingReporter(),
             ChampionshipReporter()]
```

In `core/racefeed/prompts.py`, add to `SYSTEM_PROMPTS`:

```python
    "championship_desk": (
        "Ты — чемпионатная редакция сезона. По итогам гонки коротко подводишь "
        "положение игрока в борьбе за титул: набранные очки, место в таблице, "
        "разрыв до соперника. Заверши ставкой в борьбе за титул (сколько очков "
        "до соперника). Строго по фактам, по-русски, один короткий абзац."
    ),
```

- [ ] **Step 4: Run to verify they pass**

Run: `py -3.12 -m pytest tests/racefeed/test_reporters.py tests/racefeed/test_story_builder.py tests/racefeed/test_prompts.py -v`
Expected: PASS (includes `test_every_reporter_has_a_system_prompt` now covering `championship_desk`).

---

## Task 4: Publish a CHAMPIONSHIP post from a race finish (RaceFeed engine test)

**Files:**
- Test: `tests/racefeed/test_race_feed_engine.py`

This verifies the whole RaceFeed side end-to-end with a hand-built event, so the engine glue in Task 5 only has to produce that event.

- [ ] **Step 1: Write the failing test**

Append to `tests/racefeed/test_race_feed_engine.py`:

```python
def test_championship_event_is_published_by_the_championship_desk(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                         data_dir=str(tmp_path))
    rf.reset()

    from core.racefeed.models import Event
    rf.ingest(Event(
        event_code="CHAMPIONSHIP", session_type="race", driver="", team=None,
        vehicle_idx=4, is_player=True, importance=85, laps_remaining=None,
        description="", extra={"player_points": 40, "player_position": 2,
                               "rival": "Max", "gap_to_rival": 10},
        enqueued_at=time.time(),
    ))
    rf._drain_queue()

    fake_now = [time.time() + 40]  # past the "analysis" delay (25-35s)
    import core.racefeed.engine as engine_mod
    monkeypatch.setattr(engine_mod.time, "time", lambda: fake_now[0])
    rf._publish_due()

    from core.racefeed import storage
    posts = storage.get_posts(rf.current_db_path())
    assert len(posts) == 1
    assert posts[0]["reporter_id"] == "championship_desk"
    assert posts[0]["is_player_story"] == 1
```

- [ ] **Step 2: Run to verify it fails then passes**

Run: `py -3.12 -m pytest tests/racefeed/test_race_feed_engine.py::test_championship_event_is_published_by_the_championship_desk -v`
Expected: With Task 3 done, this should PASS immediately (the pipeline already handles the new code/category/reporter). If it FAILS, fix Task 3 wiring before proceeding. No new production code in this task — it is a guard test.

---

## Task 5: Engine capture + publish + standings accessor (`core/engine.py`)

**Files:**
- Modify: `core/engine.py`

- [ ] **Step 1: Add the import and the reset flag**

Near the other `import core.*` lines (~line 81-82) add:

```python
import core.season as season_mod
```

In `__init__`, next to `self._career_pb_this_race: bool = False` (~line 310) add:

```python
        self._championship_recorded: bool = False
```

In the `SSTA` reset block, next to `self._career_pb_this_race = False` (~line 2235) add:

```python
            self._championship_recorded = False
```

- [ ] **Step 2: Hook capture into the Final Classification packet**

In `_update_final_classification_grid()`, immediately after `self._final_classification_grid = list(parsed)` (~line 816) add:

```python
        self._maybe_record_championship(parsed)
```

- [ ] **Step 3: Implement `_maybe_record_championship` and `get_season_standings`**

Add these methods to `F1Engine` (place `_maybe_record_championship` right after `_update_final_classification_grid`, and `get_season_standings` next to `get_racefeed_stats`):

```python
    def _maybe_record_championship(self, grid: list[dict]) -> None:
        """On the authoritative Final Classification (points included), append
        this race to the season store and publish a CHAMPIONSHIP RaceFeed event.
        Once per race (flag reset at SSTA); races only; F1 only."""
        if (self._session_type != "race" or self._championship_recorded
                or self._telemetry_source != "f1" or not grid):
            return
        self._championship_recorded = True
        classification = season_mod.build_classification(
            grid, self.race_state.driver, self._player_car_index)
        player_points = next(
            (row["points"] for row in classification if row["is_player"]), None)
        try:
            _archive.save_season_result({
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "track_id": self._track_id,
                "game_year": self._game_year or None,
                "classification": classification,
            })
        except Exception:
            _log.warning("Season result save failed", exc_info=True)
            return
        summary = season_mod.season_summary(race_points=player_points)
        if summary is None:
            return
        if summary.get("player_position") == 1:
            importance = 85
        elif player_points:
            importance = 70
        else:
            importance = 55
        self._commentary_events.publish({
            "event_code": "CHAMPIONSHIP", "priority": "normal",
            "driver": "", "color": "#FBBF24",
            "vehicle_idx": self._player_car_index,
            "importance": importance,
            **summary,
        })

    def get_season_standings(self) -> dict:
        from core.racefeed import ui_bridge
        return ui_bridge.get_standings(self._race_feed)
```

- [ ] **Step 4: Verify the module imports cleanly**

Run: `py -3.12 -c "import core.engine; import core.season; print('ok')"`
Expected: prints `ok` (ignore any unrelated iRacing/pyirsdk warning line).

Note: `get_season_standings` depends on `ui_bridge.get_standings` (Task 6). If running this step before Task 6, temporarily expect an `AttributeError` only when the route is called, not at import — imports still succeed.

---

## Task 6: Standings read API (`ui_bridge` + route) and pinned UI card

**Files:**
- Modify: `core/racefeed/ui_bridge.py`
- Modify: `web_server.py`
- Modify: `NewSpotterUI/lib/api.ts`, `NewSpotterUI/lib/use-racefeed.ts`
- Modify: `NewSpotterUI/components/spotter/views/race-feed-channel.tsx`, `race-feed.tsx`
- Test: `tests/racefeed/test_ui_bridge.py`

- [ ] **Step 1: Write the failing backend test**

Append to `tests/racefeed/test_ui_bridge.py`:

```python
def test_get_standings_disabled_when_engine_is_none():
    assert ui_bridge.get_standings(None) == {
        "enabled": False, "standings": [], "races_counted": 0}


def test_get_standings_returns_table(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=lambda: {},
                         data_dir=str(tmp_path))
    import core.season as season
    monkeypatch.setattr(season, "compute_standings", lambda window=22: {
        "standings": [{"driver": "You", "points": 40, "team": "Ferrari",
                       "color": "#E8002D", "position": 1, "is_player": True}],
        "races_counted": 3,
    })
    out = ui_bridge.get_standings(rf)
    assert out["enabled"] is True
    assert out["races_counted"] == 3
    assert out["standings"][0]["driver"] == "You"


def test_get_standings_empty_before_any_race(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=lambda: {},
                         data_dir=str(tmp_path))
    import core.season as season
    monkeypatch.setattr(season, "compute_standings", lambda window=22: None)
    assert ui_bridge.get_standings(rf) == {
        "enabled": True, "standings": [], "races_counted": 0}
```

- [ ] **Step 2: Run to verify it fails**

Run: `py -3.12 -m pytest tests/racefeed/test_ui_bridge.py -v -k standings`
Expected: FAIL (`AttributeError: module has no attribute 'get_standings'`).

- [ ] **Step 3: Implement backend**

In `core/racefeed/ui_bridge.py`, append:

```python
def get_standings(race_feed: "RaceFeedEngine | None") -> dict:
    """Sliding-window championship table for the pinned UI card. Independent of
    the posts feed (shows even with an empty channel). Empty until the first
    finished race is recorded in the season store."""
    if race_feed is None:
        return {"enabled": False, "standings": [], "races_counted": 0}
    import core.season as season
    result = season.compute_standings()
    if result is None:
        return {"enabled": True, "standings": [], "races_counted": 0}
    return {"enabled": True, "standings": result["standings"],
            "races_counted": result["races_counted"]}
```

In `web_server.py`, after the `@app.route("/api/racefeed/stats")` block add:

```python
    @app.route("/api/racefeed/standings")
    def api_racefeed_standings():
        return _json(engine.get_season_standings())
```

- [ ] **Step 4: Run backend tests**

Run: `py -3.12 -m pytest tests/racefeed/ tests/test_season.py tests/test_archive_season.py -q`
Expected: PASS (all green).

- [ ] **Step 5: Frontend types + fetch (`lib/api.ts`)**

After the `RaceFeedResponse` type add:

```typescript
export type StandingsRow = {
  driver: string
  team: string | null
  color: string | null
  points: number
  position: number
  is_player: boolean
}

export type SeasonStandingsResponse = {
  enabled: boolean
  standings: StandingsRow[]
  races_counted: number
}
```

Near `getRaceFeed` (~line 426) add:

```typescript
export const getSeasonStandings = () =>
  fetch("/api/racefeed/standings").then((r) => asJson<SeasonStandingsResponse>(r))
```

- [ ] **Step 6: Standings hook (`lib/use-racefeed.ts`)**

Append a sibling hook (same self-rescheduling pattern as `useRaceFeed`):

```typescript
import { getRaceFeed, getSeasonStandings, type RaceFeedResponse, type SeasonStandingsResponse } from "./api"

// (adjust the existing import line above to include getSeasonStandings + type)

export function useSeasonStandings(intervalMs = 5000) {
  const [data, setData] = useState<SeasonStandingsResponse | null>(null)

  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const tick = async () => {
      try {
        const d = await getSeasonStandings()
        if (alive) setData(d)
      } catch {
        /* leave last-known standings on a transient error */
      } finally {
        if (alive) timer = setTimeout(tick, intervalMs)
      }
    }
    tick()
    return () => {
      alive = false
      if (timer) clearTimeout(timer)
    }
  }, [intervalMs])

  return data
}
```

- [ ] **Step 7: Pinned standings card (`race-feed-channel.tsx`)**

Add the import at the top:

```typescript
import type { RaceFeedComment, RaceFeedPost } from "@/lib/spotter-data"
import type { StandingsRow } from "@/lib/api"
```

Add this component above `RaceFeedChannel`:

```tsx
function ChampionshipStandings({ standings }: { standings: StandingsRow[] }) {
  if (standings.length === 0) return null
  return (
    <div className="mb-1 rounded-2xl border border-amber-400/15 bg-amber-400/[0.04] p-3">
      <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-amber-300/90">
        <span>🏆 Чемпионат сезона</span>
      </div>
      <div className="space-y-1">
        {standings.slice(0, 10).map((row) => (
          <div
            key={row.driver}
            className={`flex items-center gap-2 rounded-lg px-2 py-1 text-[12px] ${
              row.is_player ? "bg-amber-400/[0.12] font-semibold text-amber-100" : "text-zinc-300"
            }`}
          >
            <span className="w-5 shrink-0 tabular-nums text-zinc-500">{row.position}</span>
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: row.color ?? "#9CA3AF" }} />
            <span className="min-w-0 flex-1 truncate">{row.driver}</span>
            <span className="shrink-0 tabular-nums text-zinc-400">{row.points}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
```

Change the `RaceFeedChannel` signature to accept standings and render the card at the top of the post stream:

```tsx
export function RaceFeedChannel({ posts, status, standings = [] }: {
  posts: RaceFeedPost[]
  status: RaceFeedChannelStatus
  standings?: StandingsRow[]
}) {
```

Inside the `status === "ready"` branch, render the card just before the "Текущий Гран-при" pill:

```tsx
          {status === "ready" ? (
            <>
              <ChampionshipStandings standings={standings} />
              <div className="mx-auto w-fit rounded-full bg-black/35 px-3 py-1 text-[10px] text-zinc-400">Текущий Гран-при</div>
```

- [ ] **Step 8: Wire the hook (`race-feed.tsx`)**

```tsx
import { useRaceFeed } from "@/lib/use-racefeed"
import { useSeasonStandings } from "@/lib/use-racefeed"
import { toRaceFeedPosts } from "@/lib/racefeed"
import { RaceFeedChannel, type RaceFeedChannelStatus } from "./race-feed-channel"

export function RaceFeedView() {
  const { data, error } = useRaceFeed()
  const standings = useSeasonStandings()
  const posts = data ? toRaceFeedPosts(data) : []
  let status: RaceFeedChannelStatus = "loading"
  if (error) status = "error"
  else if (data && !data.enabled) status = "disabled"
  else if (data && posts.length === 0) status = "waiting"
  else if (posts.length > 0) status = "ready"

  return <RaceFeedChannel posts={posts} status={status} standings={standings?.standings ?? []} />
}
```

(Consolidate the two `use-racefeed` imports into one line.)

- [ ] **Step 9: Typecheck the frontend**

Run (from `NewSpotterUI/`): `node_modules/.bin/tsc --noEmit -p tsconfig.json`
Expected: exit 0, no output.

---

## Task 7: Full verification + docs

- [ ] **Step 1: Full RaceFeed + season backend suite**

Run: `py -3.12 -m pytest tests/racefeed/ tests/test_engine_racefeed.py tests/test_season.py tests/test_archive_season.py -q`
Expected: all PASS.

- [ ] **Step 2: Import smoke**

Run: `py -3.12 -c "import web_server, core.engine, core.season; from core.racefeed import ui_bridge; print(hasattr(ui_bridge,'get_standings'))"`
Expected: prints `True`.

- [ ] **Step 3: Update CONTEXT.md**

Add a session entry under "На чём остановились" summarizing: season store (`analytics/archive.py`), `core/season.py` sliding-window standings, `CHAMPIONSHIP` event/category/`championship_desk` reporter, capture at the Final Classification packet, `GET /api/racefeed/standings`, pinned UI card. Note the open items: live verification needs a real race finish in F1 25; team names in the standings still degrade to "Команда #N" for unmapped team_ids (separate known bug); no calendar/round/sprint/constructors modelling (deferred).

---

## Self-review notes (verify during execution)

- **Spec coverage:** Task 1 = season store; Task 2 = standings/rival/summary; Task 3 = category+reporter+prompt; Task 4 = post pipeline guard; Task 5 = capture+publish+accessor; Task 6 = read API + pinned card; Task 7 = verification/docs. All spec components mapped.
- **Type consistency:** `compute_standings` returns `{"standings": [...], "races_counted": N}`; `pick_rival`/`season_summary` consume the inner list / dict; `ui_bridge.get_standings` and the `SeasonStandingsResponse` type both expose `{enabled, standings, races_counted}`; `StandingsRow` fields (`driver/team/color/points/position/is_player`) match the rows `compute_standings` produces.
- **Ordering:** capture + publish both hang off `_update_final_classification_grid` (points available), not `finalize` (too early). `save_season_result` runs before `season_summary` so the just-finished race is included.
