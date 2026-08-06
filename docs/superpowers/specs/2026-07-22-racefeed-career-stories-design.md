# RaceFeed — Career Stories (design)

## Context

Third of four RaceFeed follow-up pieces (comments-in-UI → post variety →
**career stories** → screenshots), each speced/planned/built independently.
Comments-in-UI and post variety turned out to already be substantially built
by a concurrent session (Codex) by the time they were investigated — this
feature is genuinely new, confirmed by research (no season/championship
tracking exists anywhere in this codebase; only per-track personal records
and all-time aggregate stats do).

**Scope, confirmed with the user:** surface data that already exists —
per-track personal-best/last-visit comparison (`core/career_memory.py`) and
all-time wins/podiums/races/avg-position (`core/career_stats.py`) — not a new
season/championship model. That would be its own, much larger effort
(effectively the "World/season persistence" phase from the original RaceFeed
spec, explicitly deferred).

## Two career moments

1. **Mid-race personal bests.** `core/engine.py::_update_career_memory()`
   already publishes `CAREER_PB`/`CAREER_SECTOR_PB` events, once per lap
   check, whenever the player beats their own lap/sector record at the
   current track. These already reach RaceFeed's ingest queue today (via
   `CommentaryEvents.publish()` → the `race_feed_provider` hook wired to
   `self._race_feed` in `core/engine.py`) — they're just silently dropped
   because `core/racefeed/engine.py::StoryBuilder`'s code-to-category maps
   don't recognize these event codes yet.

2. **Race-finish recap.** `core/engine.py` already computes `vs_last_visit`
   (lap-time/position delta vs. the player's last visit to this track) and
   `career_stats` (all-time wins/podiums/total races/avg finish) at race
   finish — but only feeds them to an unrelated existing feature (Post-Race
   Story). This needs one new `publish()` call at the same computation site.

## A real bug found and fixed along the way

Both `CAREER_PB`/`CAREER_SECTOR_PB`'s draft dicts (and any new event
following the same shape) have `"driver": ""` and no `vehicle_idx` key.
`core/engine.py::_event_involves()` — which determines whether an event
"involves" the player — only checks five `*_idx` keys (`vehicle_idx`,
`overtaking_idx`, `being_overtaken_idx`, `vehicle1_idx`, `vehicle2_idx`) and
never looks at `driver` at all. Traced and confirmed (not assumed): for a
dict with none of those keys, `player_involved` resolves to `False` today.
This means even after mapping `CAREER_PB` to a category in `StoryBuilder`,
`Event.is_player` would still be `False`, and `StoryBuilder.from_event()`'s
existing gate (`if category is None and (event.is_player or
event.is_player_team):`) would never resolve the category — the event would
still be silently dropped.

**Fix:** add `"vehicle_idx": self._player_car_index` to the `CAREER_PB`/
`CAREER_SECTOR_PB` draft dicts and to the new `CAREER_RECAP` draft dict. This
is the minimal, correct fix — it makes the existing, unmodified
`_event_involves()` correctly recognize these as player events, without
touching that shared function (which other unrelated event types also
depend on). `core/engine.py::F1_BENCH`/`F1_SECTOR_BENCH` events have the
identical bug but are explicitly out of scope here — not touched by RaceFeed,
not part of this feature; flagged as a separate, deferred observation.

## Components

- **`core/engine.py`**:
  - `_update_career_memory()`: add `"vehicle_idx": self._player_car_index`
    and the raw comparison fields (`gap_ms`, `player_best_ms`,
    `best_ever_ms`, `best_ever_date` from `cmp`) to the existing `CAREER_PB`/
    `CAREER_SECTOR_PB` draft dicts, alongside the `phrase` field already
    there — so RaceFeed can write its own independent sentence from real
    numbers instead of just forwarding the voice-engineer's phrase (matches
    the existing "don't repeat engineer radio verbatim" rule already
    documented for the Player's Garage reporter). Also set a new
    `self._career_pb_this_race: bool` flag to `True` whenever a lap or
    sector PB fires here (used by the importance scoring below); reset to
    `False` in the existing SSTA handling block.
  - New: right after the existing `vs_last_visit`/`career_stats`
    computation at race finish, publish a new `CAREER_RECAP` event carrying
    `vs_last_visit`, `career_stats`, `"vehicle_idx": self._player_car_index`,
    and a computed `"importance"`. **Corrected after reading
    `core/career_memory.py::story_facts()` directly** (two things the
    original design got wrong):
    - `vs_last_visit` can be `None` (e.g. first-ever visit to this track —
      `story_facts()` already handles this gracefully, returning
      `{"vs_last_visit": None}` rather than raising) — the scoring logic
      below MUST check `vs_last_visit is not None` before indexing into it,
      not just gate on `career_memory.ready` (a ready-but-first-visit track
      would still have `vs_last_visit is None`).
    - Sign convention is `position_delta > 0` (NOT `< 0`) means a *better*
      finish than last visit — per `career_memory.py`'s own docstring:
      "position_delta > 0 = финиш выше, чем в прошлый раз" (`last_visit
      ["final_position"] - final_position`, so improving from P10 to P5
      gives `10 - 5 = +5`). `laptime_delta_ms < 0` (faster) was correct as
      originally stated.

    Final scoring logic:
    - `90` if `final_pos <= 3` (win/podium)
    - else `70` if `self._career_pb_this_race` is `True`, or
      `vs_last_visit is not None and (vs_last_visit["position_delta"] > 0
      or vs_last_visit["laptime_delta_ms"] < 0)`
    - else `40` (below `PUBLISH_THRESHOLD`, naturally suppressed by the
      Editor — no special-casing needed, this is the existing generic
      threshold mechanism doing its job)
- **`core/racefeed/engine.py` (`StoryBuilder`)**: add `"CAREER_PB"`,
  `"CAREER_SECTOR_PB"`, `"CAREER_RECAP"` to `_PLAYER_ONLY_CODES`, all mapping
  to the existing, previously-unused `"player_progression"` category
  (already wired in `core/racefeed/reporters.py` to the Player's Garage
  reporter, `"analysis"` priority, `"ignore_if_pending"` — this category was
  reserved for exactly this kind of content since the original spec: "Career
  best qualifying" was a literal example). No changes needed to
  `reporters.py` or `prompts.py`.

## Error handling

Nothing new beyond what already exists — Editor suppresses low-importance
stories (the `40` "routine" score), LLM failure drops the candidate silently,
storage failure retries next tick. The one new failure mode ("career data
isn't ready yet") is handled by the explicit `career_memory.ready` guard
before the new publish call, matching the pattern already used for
`CAREER_PB`/`CAREER_SECTOR_PB`.

## Testing

- `tests/racefeed/test_story_builder.py`: new tests for the 3 new
  `_PLAYER_ONLY_CODES` mappings.
- `tests/test_engine_career_memory.py` (existing file, per research): new
  tests confirming the enriched draft dicts carry the raw comparison fields
  and `vehicle_idx`, that `player_involved`/`is_player` now resolves `True`
  for `CAREER_PB` (proving the bug fix), and that `career_memory.ready ==
  False` suppresses all three events (`CAREER_PB`, `CAREER_SECTOR_PB`, and
  the new `CAREER_RECAP`).
- Integration test: full `race → finish → CAREER_RECAP → StoryBuilder →
  Editor` flow across three scenarios — win/podium (importance 90, publishes),
  personal-best-but-no-win (importance 70, publishes), routine finish with no
  improvement (importance 40, suppressed).
- Live verification requires an actual race finish and/or beating a personal
  best in F1 25, same as the rest of RaceFeed.
