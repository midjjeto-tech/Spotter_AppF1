# RaceFeed — Profile header (#7) + Post screenshots (#6) (design)

## Context

Two retention amplifiers on top of the just-shipped season/championship layer,
confirmed with the user as the next work:

- **#7 Profile header** — the channel header becomes the player's identity strip
  (championship position/points, career wins/podiums, best result of the
  season). Ego hook: people return to what reflects them. Small, self-contained.
- **#6 Post screenshots** — attach a real in-game screenshot to hero-moment
  posts (overtake, collision, penalty, retirement, fastest lap, championship).
  The original spec's "Phase 3: Media". Bigger; its own module.

They are independent features sharing the RaceFeed UI. #7 ships first.

**Confirmed with the user:**
- #6 capture via `mss` (tiny ctypes lib, `mss.tools.to_png` — no Pillow), with
  **graceful degradation**: a near-black frame (fullscreen-exclusive DirectX
  capture returns black) is detected and **not saved** → the post stays
  text-only. No video/GIF, no manual re-capture, no editing.
- #6 fires only on hero events, not every post, so the feed doesn't become an
  image dump.

## Prior art reused

- `core/overlay_window.py` already locates the **game window** (hwnd + client-
  area screen rect) via a win32 window-finder, and exposes `primary_screen_
  size()`. #6 reuses this to choose a capture region.
- `pywin32` is already a dependency (used by `overlay_window.py`,
  `core/hotkeys.py`). `numpy` is already present (used for the near-black check).
- `web_server.py` already serves static assets via `static_file(...)`; #6 adds
  one more route for the screenshots folder.
- `core/season.py` + `core/career_stats.py` already compute everything #7 needs;
  the standings endpoint (`GET /api/racefeed/standings`) is already polled by the
  UI — #7 piggybacks on it rather than adding a second poll.
- RaceFeed's event→facts→post flow already carries arbitrary `extra` fields
  (see the season `CHAMPIONSHIP` work) — #6's `image` filename rides the same
  channel; `prompts._INTERNAL_ONLY_KEYS` already drops non-narrative fields so
  the LLM never verbalizes it.

---

# Feature A (#7): Profile header

## Components

- **`core/season.py`**: add `best_result(window: int = SEASON_WINDOW) -> int | None`
  — the player's best (lowest) finishing position across the window's races
  (reads the same `is_player` classification rows as `compute_standings`). `None`
  if the player isn't classified.
- **`core/racefeed/ui_bridge.py::get_standings`**: extend the returned dict with a
  `"profile"` key:
  ```python
  {
    "championship_position": <int|None>,   # from season_summary
    "championship_points": <int|None>,
    "best_result": <int|None>,             # season.best_result()
    "career": <dict|None>,                 # career_stats.compute_career_stats()
  }
  ```
  `profile` is `None` (or all-null) when there's no season store yet, so the UI
  can hide the strip. `career` is the existing `{total_races, wins, podiums,
  avg_position}` shape (or `None`).
- **Frontend**:
  - `lib/api.ts`: add `ProfileInfo` + `CareerStats` types; add `profile:
    ProfileInfo | null` to `SeasonStandingsResponse`.
  - `components/spotter/views/race-feed-channel.tsx`: a compact profile strip in
    the sticky header (below the title), e.g. `Чемпионат P2 · 40 очк ·
    3🏆 7🥉 · лучший в сезоне P1`. Rendered only when `profile` is present with
    non-null fields. `RaceFeedChannel` gains a `profile?` prop.
  - `race-feed.tsx`: pass `standings?.profile` through.

## Error handling

Every field is independently nullable; the strip renders only the parts it has.
No season store / not classified → no strip (same fail-open as the standings
table).

## Testing

- `core/season.py`: `best_result` — min player position over window, `None` when
  unclassified.
- `ui_bridge.get_standings`: `profile` present/nulled shapes.
- Frontend: `tsc --noEmit`.

---

# Feature B (#6): Post screenshots

## Components

### 1. Capture module — `core/screenshot.py` (new, isolated)

- `capture_async(path: str, region: dict | None) -> None` — spawns a daemon
  thread that grabs `region` (an `mss`-style `{left, top, width, height}`, or the
  primary monitor when `None`), runs the near-black check, and writes a PNG to
  `path` via `mss.tools.to_png`. All failures (no `mss`, capture error, encode
  error) are swallowed with a debug log — screenshots are never critical.
- `_is_near_black(rgb: bytes, size) -> bool` — mean pixel brightness below a
  threshold (numpy). True → skip the write (fullscreen-exclusive black frame).
- `mss` is imported lazily inside the worker so its absence degrades to "no
  screenshot", never an import error at startup. Add `mss` to `requirements.txt`.

### 2. Capture region — from the game window

- **`core/engine.py`**: a small helper `_capture_region() -> dict | None` reuses
  `overlay_window`'s window-finder to return the game client-area rect as an
  `mss` region; falls back to `None` (primary monitor) when the game window isn't
  found. (Reuse the existing finder; do not duplicate win32 code.)

### 3. Trigger — hero events only

- **`core/engine.py`**: at the point events are enqueued to commentary/RaceFeed,
  for a fixed set of hero codes — `{"OVTK"` (player), `"COLL"`, `"PENA"`,
  `"RTMT"`, `"FTLP"` (player), `"CHAMPIONSHIP"}` — generate `image =
  f"{uuid4().hex}.png"`, set `event["image"] = image` **synchronously** (cheap),
  and `screenshot.capture_async(<screenshots_dir>/image, self._capture_region())`
  **asynchronously**. The file lands well before the post publishes (2-35 s
  later). Gated on RaceFeed being enabled (`self._race_feed is not None`) — no
  new setting: if the feed is off there's nowhere for the image to appear, and
  reusing that switch avoids settings/UI plumbing (a dedicated screenshots
  toggle can be added later if wanted). Player-scoped codes (`OVTK`/`FTLP`) only
  capture when the event involves the player.
- Screenshots dir: `DATA_DIR/racefeed/screenshots/`.

### 4. RaceFeed passthrough

- **`core/racefeed/models.py`**: `Post` gains `image: str = ""`.
- **`core/racefeed/engine.py`**: when building the `Post` in `_publish_due`, set
  `image=(candidate.facts_snapshot or story.facts).get("image", "")`. (`image`
  already flows into `Story.facts` via `Event.extra` → `StoryBuilder`.)
- **`core/racefeed/prompts.py`**: add `"image"` to `_INTERNAL_ONLY_KEYS` so the
  filename never reaches the LLM.
- **`core/racefeed/storage.py`**: `posts` table gains an `image TEXT NOT NULL
  DEFAULT ''` column (+ the existing `ALTER TABLE` migration pattern in
  `init_db`); `save_post`/`save_publication` insert it; `get_posts` returns it
  via `SELECT *`.

### 5. Serving + UI

- **`web_server.py`**: route `GET /racefeed/media/<filename>` →
  `static_file(filename, root=<screenshots_dir>)` (filename-only, no path
  traversal — Bottle's `static_file` already guards this).
- **Frontend**:
  - `lib/api.ts`: `RaceFeedPostRow` gains `image?: string`.
  - `lib/spotter-data.ts`: `RaceFeedPost` gains `image: string`.
  - `lib/racefeed.ts`: map `image: p.image ?? ""`.
  - `components/spotter/views/race-feed-channel.tsx`: in `TelegramPost`, when
    `post.image` is non-empty, render `<img src={"/racefeed/media/" +
    post.image}>` below the text (rounded, `max-w-full`), with `onError` hiding
    the element (covers a missing/never-written file from a black-frame skip).

## Data flow (#6)

```
hero event (engine._enqueue path)
  → event["image"] = "<uuid>.png"           (sync)
  → screenshot.capture_async(dir/<uuid>.png, game_region)   (async thread; skips black frames)
  → commentary_events.publish(event)  → RaceFeed Event.extra["image"] → Story.facts
  → (2-35s later) _publish_due → Post(image=...) → storage
GET /api/racefeed        → post rows include `image`
GET /racefeed/media/<f>  → static_file(screenshot)      → <img> in the card
```

## Error handling (#6)

No `mss` / capture error / black frame → no PNG written → post publishes
text-only, `<img onError>` hides any dangling reference. Capture never runs on
the telemetry hot path (only a sync filename assignment + a spawned thread).
Off whenever RaceFeed is disabled. Orphaned PNGs (story suppressed after
capture) are harmless; a size-capped cleanup is out of scope.

## Testing (#6)

- `core/screenshot.py`: `_is_near_black` true/false on synthetic buffers;
  `capture_async` swallows a missing-`mss`/raising-grab without raising (monkeypatched);
  a black frame results in no file written.
- `core/racefeed/engine.py`: a `Post` carries `image` from story facts; storage
  round-trips the `image` column; `prompts._format_facts` omits `image`.
- `web_server` route returns the file / 404 for a missing one (light check).
- Frontend: `tsc --noEmit`.

## Out of scope

Video/GIF capture, DXGI/fullscreen-exclusive capture, manual re-shoot/edit,
screenshot thumbnails/lightbox, retention/cleanup of old PNGs, capturing for
non-hero posts.
