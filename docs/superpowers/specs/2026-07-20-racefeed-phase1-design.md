# RaceFeed — Phase 1: Core Pipeline (design)

## Context

RaceFeed is a new subsystem: an AI-powered "living paddock feed" that turns
telemetry-driven race events into journalism-style posts (per-reporter
personalities, editorial curation, publication timing, eventually media and
fake community engagement) instead of a raw event log. Full spec supplied by
the user (see chat history) describes ~13 modules across 5 conceptual areas:
core editorial pipeline, world/season persistence, media (screenshots), fake
community (comments/reactions), and a dedicated UI.

This is too large for one plan. It is decomposed into phases, each an
independent design → plan → build cycle:

1. **Phase 1 (this doc)** — core pipeline: events → stories → editorial
   curation → scheduled, LLM-rendered posts → minimal text-only UI.
2. Phase 2 — World/season persistence (`World/career_x/...`, cross-race
   archive, revisit old races).
3. Phase 3 — Media: async screenshot capture attached to posts.
4. Phase 4 — Fake community: views/likes/reactions/AI-generated comments.
5. Phase 5 — Full reporter roster (remaining team garages, Paddock Insider,
   Meme Department), personalized player stories, UI polish (filters, pins,
   search, breaking news).

Phase 1's goal is narrower than "build RaceFeed": prove that the editorial
loop actually turns ~100 telemetry events into 15-25 posts that read like
journalism, with real anti-repetition and story evolution — the part of the
spec explicitly called out as "the most important part." Everything else is
easier once this loop is proven.

## Prior art in this codebase (reused, not reinvented)

- `core/engine.py::_enqueue_event()` is the single choke point where every
  event dict is queued today (already computes `importance`/`laps_remaining`
  once). RaceFeed taps this exact point as a second, non-blocking consumer —
  no changes to any tracker.
- `core/broadcast/` already does "telemetry event → LLM rewrite → styled
  message" for spoken commentary, gated by a `broadcast_mode_enabled`
  setting read directly off `self.state`. RaceFeed's `racefeed_enabled`
  setting follows the same flat-boolean, `apply_settings()`-driven
  convention — except RaceFeed also owns a background worker thread, so
  toggling it must actually start/stop that thread (hot start/stop, no
  restart required), not just flip a bool that call sites check.
- This project's own history includes a documented bug class: letting the
  LLM decide "is this the same story as before" caused it to re-narrate the
  dominant drama on every trigger (`core/situation_dedup.py` exists because
  of it). RaceFeed's Editor is therefore **deterministic** — the LLM is only
  ever asked to render already-approved facts into prose, never to decide
  what's worth publishing or whether something was already said.

## Package layout

New, isolated package `core/racefeed/`. Phase 1 creates only the files it
needs; the rest of the spec's file list is created in later phases when
there's real content to put in them (no empty stubs):

| File | Phase 1 responsibility |
|---|---|
| `models.py` | `Event`, `Story`, `Candidate`, `Post` dataclasses |
| `engine.py` | `RaceFeedEngine` — ingest queue, worker thread, `start()`/`stop()` |
| `reporters.py` | Reporter definitions: coverage filter + `propose(story) -> Candidate` |
| `editor.py` | Scoring, Story Memory, new/update/suppress decision |
| `scheduler.py` | Delay queue (heap by `publish_at`), `update_policy` handling |
| `generators.py` | `render(candidate, story)` — builds prompt, calls LLM, returns text |
| `storage.py` | SQLite persistence (`stories`, `posts` tables) |
| `prompts.py` | Per-reporter system prompts + fact-only context builder |
| `ui_bridge.py` | Read API consumed by `web_server.py` |

Deferred to later phases: `media.py` (Phase 3), `comments.py` (Phase 4),
`templates.py` (not needed — see Error handling), `world.py` (Phase 2).

## Pipeline

```
Event (from engine._enqueue_event fan-out, or periodic tick)
    ↓
StoryBuilder (inside engine.py's worker loop)
    ↓ upserts
Story  (held in Story Memory, owned by editor.py)
    ↓
Reporter.propose(story) → Candidate      [cheap: coverage filter, no LLM]
    ↓
Editor.evaluate(candidate) → new | update | suppress
    ↓ (if not suppressed)
Scheduler.schedule(candidate)             [heap by publish_at, applies update_policy]
    ↓ (at publish time)
Generator.render(candidate, story) → LLM → text → Post
    ↓
Storage.save(post)  →  ui_bridge  →  /api/racefeed
```

The LLM is called only once per *actually published* post, at the last
possible moment (publish time), not at proposal time. This lets a better
Candidate for the same story arrive later and cancel/replace a still-pending
one (`update_policy="supersede"`) without ever paying for the LLM call that
would have been thrown away.

**Why StoryBuilder is separate from Reporter:** some stories aggregate
multiple events over time (undercut succeeding, a pace trend over 5 laps),
not a single discrete event. StoryBuilder's job is turning raw signal into
"what is currently true" (a `Story` with facts); Reporter's job is only "how
would my journalist voice tell this," never "where did this come from."

**Why Editor sits before Generator, not after:** Editor's decision (publish
new / publish update / suppress) is what actually enforces "100 events → 15-
25 posts" and "never say the same thing twice." Putting it before the LLM
call keeps that guarantee deterministic and cheap to test (see Testing).

## Event source & session scope

Single hook: `core/engine.py::_enqueue_event()` gets one added line —
non-blocking fan-out into `RaceFeedEngine.ingest()` (`put_nowait`, own
bounded queue) when `racefeed_enabled` is on. No existing tracker changes.

Periodic/analytical stories (gap trends, tyre-life/fuel/ERS reads for
Spotter Analytics) aren't triggered by discrete events. `RaceFeedEngine`
owns its own ~20s ticker and pulls a state snapshot via a `state_provider()`
closure passed in at construction (reads `engine.state` under
`state_lock`). RaceFeed never reaches back into engine internals beyond this
one pull callback plus the ingest queue — the subsystem stays isolated in
both directions.

Every `Event`/`Story` carries `session_type`. The editor stays generic and
does not special-case "race" — only the reporter/coverage layer decides
which categories apply per session type. Phase 1 only wires reporters that
recognize `session_type="race"`; qualifying/practice reporters are a later
phase's addition, not a rewrite of the editor. Session/story identifiers are
chosen so they don't preclude later grouping under a Race Weekend (Practice
→ Qualifying → Sprint → Race) once Phase 2 designs `World/` — Phase 1 does
not implement weekend grouping.

## Enable/disable

New setting `racefeed_enabled: bool`, default `False` (flat boolean,
consistent with `broadcast_mode_enabled`/`engineer_chatter_enabled`; future
sub-toggles like a hypothetical `racefeed_comments_enabled` follow the same
flat convention rather than nesting).

`F1Engine.apply_settings()` gets a new branch: on `"racefeed_enabled" in
settings`, start or stop `RaceFeedEngine` (construct + `.start()` the first
time it's turned on; `.stop()` signals the worker thread to exit and joins
it when turned off). While disabled: the fan-out branch in `_enqueue_event`
is never entered (no subscription), no worker thread exists, no ticker
runs, no LLM calls happen. Toggling is live — no app restart needed, same
as every other `apply_settings()`-driven setting.

`stop()` lets any render currently in flight finish (so storage never sees
a half-written post), then exits without publishing candidates still
sitting in the scheduler heap — they're simply dropped, same as if the
session had ended. Story Memory for that session is discarded; nothing is
half-persisted.

## Data model

```python
@dataclass
class Event:
    event_code: str
    session_type: str
    driver: str | None
    team: str | None
    vehicle_idx: int | None
    is_player: bool
    importance: int          # already computed by engine._enqueue_event
    laps_remaining: int | None
    description: str
    extra: dict               # passthrough of remaining engine-provided fields
    enqueued_at: float

@dataclass
class Story:
    id: str
    story_key: tuple           # e.g. ("pit_strategy", driver_id) or ("safety_car",)
    category: str              # one of the spec's Story Categories
    session_type: str
    stage: int                 # evolution counter, 0 = first mention
    facts: dict                # current facts
    history: list[dict]        # prior fact snapshots — LLM continuity + future timeline UI
    created_at: float
    last_update: float         # last time StoryBuilder touched facts
    last_publish: float | None
    status: str                 # "developing" | "published"  (Phase 1: no stale/closed state machine)
    post_ids: list[str]

@dataclass
class Candidate:
    story_id: str
    story_key: tuple
    category: str
    reporter_id: str
    decision: str                # "new" | "update" — set by Editor
    base_importance: int
    priority: str                 # "incident"|"pit_stop"|"statistics"|"analysis"|"default"
    publish_after: tuple[float, float]   # delay range resolved from priority
    expires_at: float             # drop if not published by this time (avoid stale "breaking news")
    update_policy: str            # "supersede" | "append" | "ignore_if_pending"

@dataclass
class Post:
    id: str
    session_id: str
    story_id: str
    reporter_id: str
    category: str
    text: str
    created_at: float
    published_at: float
    driver: str | None
    is_player_story: bool
```

## Editor algorithm (deterministic)

1. Each reporter's `propose(story)` returns a `Candidate` only if it covers
   that story's category (and, for Player's Garage, the story is tied to the
   player or player's team).
2. Editor looks up `story.id` (via `story_key`) in Story Memory:
   - Not seen before, `base_importance >= PUBLISH_THRESHOLD` → `decision="new"`.
   - Seen before, facts changed materially (gap moved beyond a noise
     threshold, weather stage changed, etc.) → `decision="update"`
     (`stage += 1`), carrying prior `facts`/`history` forward so the
     Generator's prompt can produce continuity ("Lap 10: rain expected" →
     "Lap 16: rain begins").
   - Seen before, nothing material changed, or below threshold → suppressed,
     Story Memory untouched.
3. `update_policy` governs what happens if a Candidate is scheduled but not
   yet published when a newer Candidate for the same story arrives:
   - `"supersede"` (incidents, pit stops): cancel the pending one, schedule
     the new one instead.
   - `"append"` (distinct stages worth their own post, e.g. SC deployed vs.
     SC ending): both get published.
   - `"ignore_if_pending"` (statistics/analysis ticks): drop the new one
     silently if something is already queued for this story.
4. The 15-25-posts-per-race target is not an artificial cap — it falls out
   of (a) each reporter only proposing for its narrow category list, and
   (b) suppression of non-material updates. `PUBLISH_THRESHOLD` and the
   per-category "material change" noise thresholds are tunable constants,
   not fixed by this design — they get set empirically against the
   integration test's synthetic race (see Testing) and adjusted during
   Phase 1's own live-verification pass, the same way this codebase already
   tunes `MIN_COMMENT_GAP`/cooldown constants elsewhere.

## Scheduler & storage

Single background worker thread inside `RaceFeedEngine`:
1. Drain the ingest queue non-blockingly → StoryBuilder → Reporter →
   Editor → push accepted candidates onto a `heapq` keyed by `publish_at`
   (`created_at + random.uniform(*publish_after)`), applying `update_policy`
   against anything already in the heap for the same `story_id`.
2. Pop everything from the heap whose `publish_at <= now` (and not past
   `expires_at`) → `Generator.render()` → `Post` → `storage.save_post()`.
3. Short sleep (~0.5s), repeat.

Default delay ranges (seconds), per spec:

```python
PUBLISH_DELAY_S = {
    "incident":   (2, 5),
    "pit_stop":   (5, 10),
    "statistics": (15, 25),
    "analysis":   (25, 35),
    "default":    (5, 10),
}
```

**Storage: SQLite**, `DATA_DIR/racefeed/<session_id>.sqlite3` — one file per
session for Phase 1 (path scheme forward-compatible with Phase 2's
`World/career_x/feed.db`/`posts.db`, which the original spec already named
with `.db` extensions). No existing session-identifier concept exists
elsewhere in the codebase to reuse — `session_id` is a timestamp
(`%Y%m%d_%H%M%S`) that `RaceFeedEngine` generates itself the moment it sees
the start of a new race session (an `SSTA`-type event, or the first
`session_type="race"` event after none was active).

```sql
CREATE TABLE stories (
    id TEXT PRIMARY KEY, story_key TEXT, category TEXT, session_type TEXT,
    stage INTEGER, facts TEXT, history TEXT,
    created_at REAL, last_update REAL, last_publish REAL, status TEXT
);
CREATE TABLE posts (
    id TEXT PRIMARY KEY, story_id TEXT, reporter_id TEXT, category TEXT,
    text TEXT, created_at REAL, published_at REAL,
    driver TEXT, is_player_story INTEGER
);
```

`storage.py`'s public API (`save_post`, `upsert_story`, `get_story`,
`get_posts`) is backend-agnostic to callers — Editor/Scheduler never touch
SQL directly. Concurrency: short-lived connections per operation
(`sqlite3.connect(path, timeout=5)`), no shared long-lived connection, no
manual locking — sufficient at Phase 1's volume (a few writes/sec at most,
occasional reads from the Bottle request thread via `ui_bridge`).

## Reporters (Phase 1 roster)

- **Race Control** — factual, no humor. Covers incidents (RTMT/COLL/SPIN/
  OFFT), penalties (PENA/PENS), SC/VSC, flags, session start/end,
  retirements. Low publish threshold for these categories — they're
  inherently newsworthy on first mention.
- **Spotter Analytics** — stats-driven, fed by the periodic tick: gap
  trends, tyre-life/fuel/ERS reads, simple predictions. `story_key` by
  `(category, subject_driver)` so e.g. a player gap-trend story evolves
  across stages instead of re-publishing from scratch each tick.
- **Player's Garage** — dynamically bound to whichever team the player
  currently drives; covers events/stories tied to the player or their team
  (overtakes, pit stops, fastest laps, progression narrative like "only
  driver in Top 8 yet to pit"). Prompt explicitly instructs the LLM to
  write third-person journalist coverage, not to mimic or repeat engineer
  radio text.

Remaining reporters from the spec (other team garages, Paddock Insider,
Meme Department) are Phase 5.

## UI

New "RaceFeed" entry in `NewSpotterUI/components/spotter/sidebar.tsx`'s nav
array, new view component polling a new `GET /api/racefeed` endpoint
(`ui_bridge.get_posts()`). Cards: reporter name, timestamp, text — no
images/reactions/comments yet (later phases). Newest posts on top.

## Error handling

- LLM unavailable or fails at render time → candidate is dropped, no post
  published, logged at debug level. No template fallback: RaceFeed is not
  safety-critical (unlike voice, which needs the Piper fallback), so a
  dropped story is an acceptable degradation and avoids building
  `templates.py` before there's a real need for it.
- StoryBuilder/Editor scoring exception → caught, neutral defaults used,
  event still flows through (same pattern as `engine.py::_enqueue_event`'s
  existing try/except around the planner).
- Ingest queue is bounded; `put_nowait` + catch `queue.Full` → drop the new
  event with a debug log. Never blocks the caller (`_enqueue_event`,
  running on the telemetry/commentary hot path).
- Storage write failure → logged, post stays available in-memory for the
  current session/UI reads, retried on the next scheduler iteration.
  Corrupt/missing DB file on startup → recreated fresh (same
  fail-safe spirit as `core/settings.py`).

## Testing

- `editor.py`, `scheduler.py`, `storage.py`: pure unit tests, no LLM, no
  real I/O where avoidable (in-memory SQLite `:memory:` for storage tests).
- `reporters.py`: coverage-filter logic tested without a real LLM (mocked
  `AIProvider`, following this codebase's existing pattern for testing
  commentator/broadcast code).
- Integration test: feed ~80-100 synthetic `Event` fixtures representing a
  full race through the whole pipeline with a mocked `Generator.render()`;
  assert (a) published post count falls in a reasonable band, (b) no two
  posts share `story_id` + `stage` (the anti-repetition guarantee the spec
  cares about most, directly testable).
- Live verification (does it *feel* like journalism, are delays/thresholds
  well tuned) is out of scope for automated tests — same as every other
  voice/telemetry feature in this project, it's a pending manual check
  after code-complete.

## Out of scope for Phase 1 (explicitly deferred)

Media/screenshots, fake community (comments/reactions/views), World/season
cross-race persistence, remaining reporters (team garages ×4, Paddock
Insider, Meme Department), personalized deep player narratives beyond what
Player's Garage covers, UI filters/pins/search/breaking news, qualifying/
practice coverage.
