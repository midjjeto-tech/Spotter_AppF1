# RaceFeed Profile Header (#7) + Post Screenshots (#6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the RaceFeed channel header into the player's identity strip (#7) and attach real in-game screenshots to hero-moment posts (#6), degrading gracefully when capture isn't possible.

**Architecture:** #7 piggybacks on the already-polled `/api/racefeed/standings` with a `profile` block from `season`/`career_stats`. #6 captures via `mss` on a background thread at the moment of a hero event (through a new `media_hook` in `CommentaryEvents.publish`), skips near-black frames, rides the image filename through the existing event→facts→post flow, and serves the PNG via a new static route.

**Tech Stack:** Python 3.12 (pytest), Bottle, `mss` (new, tiny), `numpy` + `pywin32` (already present), Next.js/React + TypeScript. Spec: `docs/superpowers/specs/2026-07-25-racefeed-media-and-profile-design.md`.

**Project note:** Repo is **not** under git — ignore "commit" conventions; each task's checkpoint is green tests. Backend: `py -3.12 -m pytest ...`. Frontend: `node_modules/.bin/tsc --noEmit -p tsconfig.json` from `NewSpotterUI/`. `mss` need not be installed for tests (all capture code is behind injectable seams / lazy imports); install it (`py -3.12 -m pip install mss`) only to see real screenshots.

---

## File Structure

Feature A (#7):
- Modify `core/season.py` — `best_result()`.
- Modify `core/racefeed/ui_bridge.py` — `profile` block in `get_standings`.
- Modify `NewSpotterUI/lib/api.ts`, `.../components/spotter/views/race-feed-channel.tsx`, `.../race-feed.tsx`.

Feature B (#6):
- Create `core/screenshot.py` — capture + near-black skip.
- Modify `core/overlay_window.py` — `game_window_region()`.
- Modify `core/commentary_events.py` — `media_hook` callback.
- Modify `core/engine.py` — hero-capture hook + screenshots dir + region helper.
- Modify `core/racefeed/models.py` (`Post.image`), `core/racefeed/engine.py` (set image), `core/racefeed/prompts.py` (`_INTERNAL_ONLY_KEYS`), `core/racefeed/storage.py` (column).
- Modify `web_server.py` — `/racefeed/media/<filename>` route.
- Modify `NewSpotterUI/lib/api.ts`, `lib/spotter-data.ts`, `lib/racefeed.ts`, `race-feed-channel.tsx`.
- Add `mss` to `requirements.txt`.
- Tests: `tests/test_season.py`, `tests/racefeed/test_ui_bridge.py`, `tests/test_screenshot.py`, `tests/test_overlay_window.py` (if present, else new), `tests/racefeed/test_race_feed_engine.py`, `tests/racefeed/test_storage.py`, `tests/racefeed/test_prompts.py`, `tests/test_commentary_events.py`.

---

# FEATURE A (#7): Profile header

## Task 1: `season.best_result`

**Files:**
- Modify: `core/season.py`
- Test: `tests/test_season.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_season.py`)

```python
def test_best_result_is_players_lowest_position(monkeypatch):
    monkeypatch.setattr(season.archive, "list_season_results", lambda limit=None: [
        _race([{"driver": "You", "points": 25, "position": 1, "is_player": True}]),
        _race([{"driver": "You", "points": 12, "position": 6, "is_player": True}]),
    ])
    assert season.best_result() == 1


def test_best_result_none_when_player_never_classified(monkeypatch):
    monkeypatch.setattr(season.archive, "list_season_results", lambda limit=None: [
        _race([{"driver": "Max", "points": 25, "position": 1, "is_player": False}]),
    ])
    assert season.best_result() is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `py -3.12 -m pytest tests/test_season.py -k best_result -v`
Expected: FAIL (`AttributeError: module 'core.season' has no attribute 'best_result'`).

- [ ] **Step 3: Implement** (add to `core/season.py`, after `compute_standings`)

```python
def best_result(window: int = SEASON_WINDOW) -> int | None:
    """The player's best (lowest) finishing position across the window, or None
    if the player isn't classified in any recorded race."""
    positions = [
        entry["position"]
        for race in archive.list_season_results(limit=window)
        for entry in race.get("classification", [])
        if entry.get("is_player") and entry.get("position") is not None
    ]
    return min(positions) if positions else None
```

- [ ] **Step 4: Run to verify it passes**

Run: `py -3.12 -m pytest tests/test_season.py -k best_result -v`
Expected: PASS (2 tests).

---

## Task 2: `profile` block in `get_standings`

**Files:**
- Modify: `core/racefeed/ui_bridge.py`
- Test: `tests/racefeed/test_ui_bridge.py`

- [ ] **Step 1: Write the failing test** (append to `tests/racefeed/test_ui_bridge.py`)

```python
def test_get_standings_includes_profile(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=lambda: {},
                         data_dir=str(tmp_path))
    import core.season as season
    import core.career_stats as career_stats
    monkeypatch.setattr(season, "compute_standings", lambda window=22: {
        "standings": [{"driver": "You", "points": 40, "team": "Ferrari",
                       "color": "#E8002D", "position": 2, "is_player": True}],
        "races_counted": 3})
    monkeypatch.setattr(season, "season_summary", lambda **k: {
        "player_position": 2, "player_points": 40})
    monkeypatch.setattr(season, "best_result", lambda window=22: 1)
    monkeypatch.setattr(career_stats, "compute_career_stats", lambda: {
        "total_races": 12, "wins": 3, "podiums": 7, "avg_position": 4.2})
    out = ui_bridge.get_standings(rf)
    assert out["profile"]["championship_position"] == 2
    assert out["profile"]["championship_points"] == 40
    assert out["profile"]["best_result"] == 1
    assert out["profile"]["career"]["wins"] == 3


def test_get_standings_profile_null_when_no_season(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=lambda: {},
                         data_dir=str(tmp_path))
    import core.season as season
    monkeypatch.setattr(season, "compute_standings", lambda window=22: None)
    out = ui_bridge.get_standings(rf)
    assert out["profile"] is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `py -3.12 -m pytest tests/racefeed/test_ui_bridge.py -k profile -v`
Expected: FAIL (`KeyError: 'profile'`).

- [ ] **Step 3: Implement** — replace the body of `get_standings` in `core/racefeed/ui_bridge.py` with:

```python
def get_standings(race_feed: "RaceFeedEngine | None") -> dict:
    """Sliding-window championship table + player profile for the pinned UI card
    and header strip. Independent of the posts feed. Empty/None until the first
    finished race is recorded in the season store."""
    if race_feed is None:
        return {"enabled": False, "standings": [], "races_counted": 0, "profile": None}
    import core.season as season
    import core.career_stats as career_stats
    result = season.compute_standings()
    if result is None:
        return {"enabled": True, "standings": [], "races_counted": 0, "profile": None}
    summary = season.season_summary()
    profile = {
        "championship_position": (summary or {}).get("player_position"),
        "championship_points": (summary or {}).get("player_points"),
        "best_result": season.best_result(),
        "career": career_stats.compute_career_stats(),
    }
    return {"enabled": True, "standings": result["standings"],
            "races_counted": result["races_counted"], "profile": profile}
```

- [ ] **Step 4: Run to verify it passes**

Run: `py -3.12 -m pytest tests/racefeed/test_ui_bridge.py -k "standings or profile" -v`
Expected: PASS (existing standings tests + 2 new). Note: the earlier `test_get_standings_empty_before_any_race` and `test_get_standings_returns_table` must still pass — they don't assert on `profile`, and the added key doesn't break them; if either used `==` on the whole dict, update its expected dict to include `"profile": None` / `"profile": <...>`. (As written in the season plan they assert on individual keys, so no change needed.)

---

## Task 3: Profile strip UI

**Files:**
- Modify: `NewSpotterUI/lib/api.ts`
- Modify: `NewSpotterUI/components/spotter/views/race-feed-channel.tsx`
- Modify: `NewSpotterUI/components/spotter/views/race-feed.tsx`

- [ ] **Step 1: Types** — in `lib/api.ts`, after `SeasonStandingsResponse`, add and extend:

```typescript
export type CareerStats = {
  total_races: number
  wins: number
  podiums: number
  avg_position: number
}

export type ProfileInfo = {
  championship_position: number | null
  championship_points: number | null
  best_result: number | null
  career: CareerStats | null
}
```

And add `profile: ProfileInfo | null` to `SeasonStandingsResponse`:

```typescript
export type SeasonStandingsResponse = {
  enabled: boolean
  standings: StandingsRow[]
  races_counted: number
  profile: ProfileInfo | null
}
```

- [ ] **Step 2: Header strip** — in `race-feed-channel.tsx`, add the import:

```typescript
import type { ProfileInfo, StandingsRow } from "@/lib/api"
```

Add this component above `RaceFeedChannel`:

```tsx
function ProfileStrip({ profile }: { profile: ProfileInfo | null }) {
  if (!profile) return null
  const parts: string[] = []
  if (profile.championship_position != null)
    parts.push(`Чемпионат P${profile.championship_position}${profile.championship_points != null ? ` · ${profile.championship_points} очк` : ""}`)
  if (profile.career)
    parts.push(`${profile.career.wins}🏆 ${profile.career.podiums}🥉`)
  if (profile.best_result != null)
    parts.push(`лучший в сезоне P${profile.best_result}`)
  if (parts.length === 0) return null
  return <p className="mt-0.5 truncate text-[10px] text-amber-300/80">{parts.join(" · ")}</p>
}
```

Change the `RaceFeedChannel` signature to accept `profile` and render the strip in the header (just after `<EditorialTeam />`):

```tsx
export function RaceFeedChannel({ posts, status, standings = [], profile = null }: {
  posts: RaceFeedPost[]
  status: RaceFeedChannelStatus
  standings?: StandingsRow[]
  profile?: ProfileInfo | null
}) {
```

In the header block, immediately after `<EditorialTeam />`:

```tsx
            <EditorialTeam />
            <ProfileStrip profile={profile} />
```

- [ ] **Step 3: Wire it** — in `race-feed.tsx`, pass profile:

```tsx
  return <RaceFeedChannel posts={posts} status={status} standings={standings?.standings ?? []} profile={standings?.profile ?? null} />
```

- [ ] **Step 4: Typecheck**

Run (from `NewSpotterUI/`): `node_modules/.bin/tsc --noEmit -p tsconfig.json`
Expected: exit 0.

---

# FEATURE B (#6): Post screenshots

## Task 4: Capture module `core/screenshot.py`

**Files:**
- Create: `core/screenshot.py`
- Modify: `requirements.txt`
- Test: `tests/test_screenshot.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_screenshot.py
import core.screenshot as screenshot


class _Shot:
    def __init__(self, rgb, size):
        self.rgb = rgb
        self.size = size


def test_is_near_black_true_for_dark_and_false_for_bright():
    assert screenshot._is_near_black(b"\x00" * 300) is True
    assert screenshot._is_near_black(b"\xff" * 300) is False
    assert screenshot._is_near_black(b"") is True


def test_capture_to_writes_when_frame_is_bright(tmp_path):
    calls = {}
    def fake_write(rgb, size, path):
        calls["path"] = path
    ok = screenshot.capture_to(
        str(tmp_path / "x.png"), region=None,
        grab=lambda region: _Shot(b"\xff" * 300, (10, 10)),
        write=fake_write)
    assert ok is True
    assert calls["path"].endswith("x.png")


def test_capture_to_skips_black_frame(tmp_path):
    calls = {}
    ok = screenshot.capture_to(
        str(tmp_path / "x.png"), region=None,
        grab=lambda region: _Shot(b"\x00" * 300, (10, 10)),
        write=lambda *a: calls.setdefault("wrote", True))
    assert ok is False
    assert "wrote" not in calls


def test_capture_to_never_raises_on_grab_error(tmp_path):
    def boom(region):
        raise RuntimeError("no display")
    assert screenshot.capture_to(str(tmp_path / "x.png"), region=None,
                                 grab=boom, write=lambda *a: None) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `py -3.12 -m pytest tests/test_screenshot.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'core.screenshot'`).

- [ ] **Step 3: Implement**

```python
# core/screenshot.py
"""
core/screenshot.py
==================
Best-effort game screenshot for RaceFeed hero posts. Uses `mss` (lazy import)
to grab a region and write a PNG; a near-black frame (fullscreen-exclusive
DirectX capture returns black) is detected and skipped. Everything degrades
silently — a screenshot is never critical. All heavy work runs off the caller's
thread via capture_async.
"""
from __future__ import annotations

import logging
import threading

_log = logging.getLogger(__name__)

# Mean 0-255 brightness below this => treat the frame as a black capture failure.
_NEAR_BLACK_THRESHOLD = 12.0


def _is_near_black(rgb: bytes) -> bool:
    import numpy as np
    arr = np.frombuffer(rgb, dtype=np.uint8)
    if arr.size == 0:
        return True
    return float(arr.mean()) < _NEAR_BLACK_THRESHOLD


def _default_grab(region):
    import mss
    with mss.mss() as sct:
        return sct.grab(region or sct.monitors[1])  # monitors[1] = primary


def _default_write(rgb, size, path):
    import mss.tools
    mss.tools.to_png(rgb, size, output=path)


def capture_to(path: str, region: dict | None,
               grab=_default_grab, write=_default_write, is_black=_is_near_black) -> bool:
    """Grab `region` (primary monitor if None), skip near-black, write a PNG.
    Returns True iff a file was written. Never raises."""
    try:
        shot = grab(region)
        if shot is None or is_black(shot.rgb):
            return False
        write(shot.rgb, shot.size, path)
        return True
    except Exception:
        _log.debug("screenshot capture failed for %s", path, exc_info=True)
        return False


def capture_async(path: str, region: dict | None = None) -> None:
    """Fire-and-forget capture on a daemon thread (never blocks the caller)."""
    threading.Thread(target=capture_to, args=(path, region),
                     daemon=True, name="racefeed-shot").start()
```

Add to `requirements.txt` (near the other optional integrations):

```
mss>=9.0  # RaceFeed hero-post screenshots (optional; degrades if absent)
```

- [ ] **Step 4: Run to verify it passes**

Run: `py -3.12 -m pytest tests/test_screenshot.py -v`
Expected: PASS (4 tests). No `mss` install required — tests inject `grab`/`write`.

---

## Task 5: Game-window region helper

**Files:**
- Modify: `core/overlay_window.py`
- Test: `tests/test_overlay_window.py` (create if absent)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_overlay_window.py  (append if the file already exists)
import core.overlay_window as ow


def test_game_window_region_maps_rect(monkeypatch):
    monkeypatch.setattr(ow._Win32OverlayBackend, "find_game_window",
                        lambda self: ow.GameWindow(hwnd=1, left=10, top=20, width=800, height=600))
    assert ow.game_window_region() == {"left": 10, "top": 20, "width": 800, "height": 600}


def test_game_window_region_none_when_no_window(monkeypatch):
    monkeypatch.setattr(ow._Win32OverlayBackend, "find_game_window", lambda self: None)
    assert ow.game_window_region() is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `py -3.12 -m pytest tests/test_overlay_window.py -k region -v`
Expected: FAIL (`AttributeError: module 'core.overlay_window' has no attribute 'game_window_region'`).

- [ ] **Step 3: Implement** — in `core/overlay_window.py`, after `primary_screen_size()` add:

```python
def game_window_region() -> dict | None:
    """The game window's client area as an mss-style region, or None when the
    game window can't be found (mss then falls back to the primary monitor)."""
    win = _Win32OverlayBackend().find_game_window()
    if win is None or win.width <= 0 or win.height <= 0:
        return None
    return {"left": win.left, "top": win.top, "width": win.width, "height": win.height}
```

- [ ] **Step 4: Run to verify it passes**

Run: `py -3.12 -m pytest tests/test_overlay_window.py -k region -v`
Expected: PASS (2 tests).

---

## Task 6: `media_hook` in CommentaryEvents + engine hero-capture

**Files:**
- Modify: `core/commentary_events.py`
- Modify: `core/engine.py`
- Test: `tests/test_commentary_events.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_commentary_events.py`; mirror that file's existing construction of `CommentaryEvents` — it needs a `context_provider`; reuse the file's existing helper/fixture if present, otherwise the inline one below)

```python
def test_media_hook_runs_before_fanout_and_can_mutate_values():
    from core.commentary_events import CommentaryEvents
    from core.commentary.planner import PlanContext  # adjust import to match file's existing one

    seen = {}
    def ctx(values):
        return PlanContext(player_involved=True, battle=False,
                           laps_remaining=None, session_type="race")
    def media_hook(values, context):
        seen["code"] = values.get("event_code")
        seen["player"] = context.player_involved
        values["image"] = "shot.png"

    class _RF:
        def __init__(self): self.got = None
        def ingest(self, event): self.got = event
    rf = _RF()

    events = CommentaryEvents(ctx, race_feed_provider=lambda: rf, media_hook=media_hook)
    events.publish({"event_code": "OVTK", "importance": 90})

    assert seen == {"code": "OVTK", "player": True}
    assert rf.got.extra.get("image") == "shot.png"  # image reached the RaceFeed event
```

(If the existing `PlanContext` import path in `tests/test_commentary_events.py` differs, use that file's import. The RaceFeed event's passthrough field is `extra` — see `core/racefeed/models.py::Event.from_engine_dict`, which routes unknown keys into `extra`.)

- [ ] **Step 2: Run to verify it fails**

Run: `py -3.12 -m pytest tests/test_commentary_events.py -k media_hook -v`
Expected: FAIL (`TypeError: __init__() got an unexpected keyword argument 'media_hook'`).

- [ ] **Step 3: Implement — `core/commentary_events.py`**

Add the param to `__init__` (after `player_team_provider`):

```python
        player_team_provider: Callable[[], str | None] = lambda: None,
        media_hook: Callable[[dict, "PlanContext"], None] = lambda values, context: None,
```

Store it: `self._media_hook = media_hook` (next to `self._player_team_provider = ...`).

In `publish`, call it just before `event = CommentaryEvent.from_mapping(values)`:

```python
        values.setdefault("enqueued_at", self._clock())
        try:
            self._media_hook(values, context)
        except Exception:  # noqa: BLE001 - media is never critical
            _log.debug("media_hook failed for %s", values.get("event_code"), exc_info=True)
        event = CommentaryEvent.from_mapping(values)
```

- [ ] **Step 4: Implement — `core/engine.py`**

Add imports near the other `import core.*`:

```python
import core.screenshot as screenshot_mod
import core.overlay_window as overlay_window
```

Add a module-level constant near the top of the file (after the imports):

```python
_HERO_SCREENSHOT_CODES = frozenset({"OVTK", "COLL", "PENA", "RTMT", "FTLP", "CHAMPIONSHIP"})
```

At the `CommentaryEvents(...)` construction (where `race_feed_provider=lambda: self._race_feed` is passed), add the hook argument:

```python
            media_hook=self._capture_hero_screenshot,
```

Add the method and helper to `F1Engine` (place near `get_racefeed_state`):

```python
    def _screenshots_dir(self) -> Path:
        d = Path(config.DATA_DIR) / "racefeed" / "screenshots"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _capture_hero_screenshot(self, values: dict, context) -> None:
        """Attach a screenshot to hero-moment player events. Sets values["image"]
        synchronously (cheap) and captures asynchronously so the file lands well
        before the post publishes. Only when RaceFeed is on and the player is
        involved."""
        if self._race_feed is None:
            return
        if values.get("event_code") not in _HERO_SCREENSHOT_CODES or not context.player_involved:
            return
        image = f"{uuid.uuid4().hex}.png"
        values["image"] = image
        try:
            region = overlay_window.game_window_region()
            screenshot_mod.capture_async(str(self._screenshots_dir() / image), region)
        except Exception:  # noqa: BLE001 - never let capture break publishing
            _log.debug("hero screenshot dispatch failed", exc_info=True)
```

(Confirm `import uuid`, `from pathlib import Path`, and `import config` are present at the top of `core/engine.py`; add any that are missing.)

- [ ] **Step 5: Run to verify it passes**

Run: `py -3.12 -m pytest tests/test_commentary_events.py -k media_hook -v`
Expected: PASS.

---

## Task 7: RaceFeed `Post.image` passthrough + storage

**Files:**
- Modify: `core/racefeed/models.py`
- Modify: `core/racefeed/engine.py`
- Modify: `core/racefeed/prompts.py`
- Modify: `core/racefeed/storage.py`
- Test: `tests/racefeed/test_storage.py`, `tests/racefeed/test_prompts.py`, `tests/racefeed/test_race_feed_engine.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/racefeed/test_storage.py` (mirror that file's existing `Post`/`save_post`/`get_posts` usage):

```python
def test_post_image_round_trips(tmp_path):
    from core.racefeed import storage
    from core.racefeed.models import Post
    db = str(tmp_path / "s.sqlite3")
    storage.init_db(db)
    storage.save_post(db, Post(
        id="p1", session_id="s", story_id="st", reporter_id="race_control",
        category="incident", text="x", created_at=1.0, published_at=2.0,
        driver="Norris", is_player_story=True, image="shot.png"))
    rows = storage.get_posts(db)
    assert rows[0]["image"] == "shot.png"
```

Append to `tests/racefeed/test_prompts.py`:

```python
def test_image_filename_never_reaches_the_prompt():
    story = Story(id="s", story_key=("x",), category="player_overtake",
                   session_type="race", facts={"driver": "Макс", "image": "shot.png"})
    ctx = build_context(story, _candidate(story))
    assert "shot.png" not in ctx and "image" not in ctx
```

Append to `tests/racefeed/test_race_feed_engine.py`:

```python
def test_post_carries_image_from_story_facts(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                         data_dir=str(tmp_path))
    rf.reset()
    from core.racefeed.models import Event
    rf.ingest(Event(
        event_code="OVTK", session_type="race", driver="You", team="Ferrari",
        vehicle_idx=4, is_player=True, importance=90, laps_remaining=None,
        description="overtake", extra={"image": "shot.png"}, enqueued_at=time.time()))
    rf._drain_queue()
    fake_now = [time.time() + 30]
    import core.racefeed.engine as engine_mod
    monkeypatch.setattr(engine_mod.time, "time", lambda: fake_now[0])
    rf._publish_due()
    from core.racefeed import storage
    posts = storage.get_posts(rf.current_db_path())
    assert posts[0]["image"] == "shot.png"
```

- [ ] **Step 2: Run to verify they fail**

Run: `py -3.12 -m pytest tests/racefeed/test_storage.py tests/racefeed/test_prompts.py tests/racefeed/test_race_feed_engine.py -k "image" -v`
Expected: FAIL (`TypeError: Post got unexpected keyword 'image'` / missing column / filename present).

- [ ] **Step 3: Implement — `core/racefeed/models.py`**

Add to `Post` (after `claim_fingerprint: str = ""`, before `comments`):

```python
    image: str = ""
```

- [ ] **Step 4: Implement — `core/racefeed/prompts.py`**

Add `"image"` to `_INTERNAL_ONLY_KEYS` (the existing set that already holds `"team_id"`, `"color"`, etc.).

- [ ] **Step 5: Implement — `core/racefeed/engine.py`**

In `_publish_due`, where the `Post(...)` is constructed, add the `image` field sourced from the same facts as `driver`/`is_player_story`:

```python
                is_player_story=bool(
                    (candidate.facts_snapshot or story.facts).get("is_player", False)
                ),
                image=(candidate.facts_snapshot or story.facts).get("image", ""),
                story_stage=story.stage,
```

- [ ] **Step 6: Implement — `core/racefeed/storage.py`**

In `_SCHEMA`'s `posts` table, add the column (e.g. after `claim_fingerprint`):

```sql
    image TEXT NOT NULL DEFAULT '',
```

In `init_db`, add a migration alongside the existing `ALTER TABLE` guards:

```python
        if "image" not in columns:
            con.execute("ALTER TABLE posts ADD COLUMN image TEXT NOT NULL DEFAULT ''")
```

In BOTH `save_post` and `save_publication`, add `image` to the posts `INSERT` column list and a matching `?`, and `post.image` to the values tuple. (Both INSERTs list the same columns — keep them identical.)

- [ ] **Step 7: Run to verify they pass**

Run: `py -3.12 -m pytest tests/racefeed/ -k "image" -v`
Expected: PASS (3 tests).

---

## Task 8: Serve + render screenshots

**Files:**
- Modify: `web_server.py`
- Modify: `NewSpotterUI/lib/api.ts`, `lib/spotter-data.ts`, `lib/racefeed.ts`
- Modify: `NewSpotterUI/components/spotter/views/race-feed-channel.tsx`

- [ ] **Step 1: Media route** — in `web_server.py`, after the `/api/racefeed/standings` route add:

```python
    @app.route("/racefeed/media/<filename>")
    def api_racefeed_media(filename):
        import config
        from pathlib import Path
        root = str(Path(config.DATA_DIR) / "racefeed" / "screenshots")
        return static_file(filename, root=root)
```

(`static_file` already blocks path traversal, so the `<filename>` wildcard — not `<path:path>` — is safe.)

- [ ] **Step 2: Frontend types** — `lib/api.ts`: add `image?: string` to `RaceFeedPostRow`. `lib/spotter-data.ts`: add `image: string` to `RaceFeedPost`.

- [ ] **Step 3: Map it** — `lib/racefeed.ts`, in the `toRaceFeedPosts` map, add:

```typescript
      image: p.image ?? "",
```

- [ ] **Step 4: Render it** — in `race-feed-channel.tsx`'s `TelegramPost`, after the text `<p>` and before the reactions row, add:

```tsx
      {post.image ? (
        <img
          src={`/racefeed/media/${post.image}`}
          alt=""
          className="mt-2.5 max-h-72 w-full rounded-xl border border-white/[0.06] object-cover"
          onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none" }}
        />
      ) : null}
```

- [ ] **Step 5: Typecheck**

Run (from `NewSpotterUI/`): `node_modules/.bin/tsc --noEmit -p tsconfig.json`
Expected: exit 0.

---

## Task 9: Full verification + docs

- [ ] **Step 1: Backend suites**

Run: `py -3.12 -m pytest tests/racefeed/ tests/test_engine_racefeed.py tests/test_season.py tests/test_archive_season.py tests/test_screenshot.py tests/test_overlay_window.py tests/test_commentary_events.py -q`
Expected: all PASS.

- [ ] **Step 2: Import smoke**

Run: `py -3.12 -c "import web_server, core.engine, core.screenshot, core.overlay_window; print('ok')"`
Expected: prints `ok` (ignore unrelated iRacing/pyirsdk warning).

- [ ] **Step 3: Frontend typecheck** (from `NewSpotterUI/`)

Run: `node_modules/.bin/tsc --noEmit -p tsconfig.json`
Expected: exit 0.

- [ ] **Step 4: Update CONTEXT.md**

Add a session entry under "На чём остановились": #7 profile strip (season/career via `/api/racefeed/standings` `profile`), #6 screenshots (`core/screenshot.py` via `mss` with near-black skip, `media_hook` in CommentaryEvents, hero-code+player gate, `Post.image` + storage column + `/racefeed/media/<file>` route + `<img>` in the card). Note open items: live verification needs a real race in **borderless/windowed** (fullscreen-exclusive → black frame skipped, text-only post); `mss` must be installed for real capture (`pip install mss`), tests don't need it; no cleanup of old PNGs.

---

## Self-review notes

- **Spec coverage:** #7 → Tasks 1-3 (best_result, profile block, strip). #6 → Task 4 (capture+black-skip), Task 5 (region), Task 6 (media_hook+hero gate), Task 7 (Post.image passthrough+prompt drop+storage), Task 8 (route+render), Task 9 (verify/docs). All spec components mapped.
- **Type/consistency:** `profile` block keys (`championship_position/points`, `best_result`, `career`) match `ProfileInfo`; `capture_to(path, region, grab, write, is_black)` seams are the same names used in tests; `Post.image` flows models→engine→storage→ui_bridge(SELECT *)→api row `image?`→`RaceFeedPost.image`→`<img>`; `media_hook(values, context)` signature matches both the CommentaryEvents call site and the engine method.
- **Gate refinement vs spec:** capture fires on hero code AND `context.player_involved` (simpler and more relevant than per-code player-scoping; CHAMPIONSHIP is player-involved by construction).
- **mss-free tests:** every capture test injects `grab`/`write`; `mss` is imported only inside `_default_grab`/`_default_write`.
