# RaceFeed — Season / Championship layer (design)

## Context

RaceFeed today is technically solid but has no *return* pull: each race is a
throwaway SQLite (`core/racefeed/engine.py::RaceFeedEngine.reset()`), nothing
accumulates across sessions, nothing is at stake. The liveliness work (growing
likes/views/reactions, progressive comment reveal) is polish on a fundamentally
passive artifact. Retention needs continuity + stakes: a season that persists,
a championship position that moves, a recurring rival, and a post-race
cliffhanger.

This is the "#1" lever from the retention discussion, scoped down from the full
deferred "World/season persistence" phase to a **sliding-window championship**
computed from data the game already provides — no calendar/round model, no
constructors' cup, no multi-career separation.

**Confirmed with the user:**
- Depth: **real championship table + recurring rival** (not player-only).
- Season boundary: **sliding window** (last ~22 races) — robust to career
  restarts; a "form championship," not a strict calendar season.
- Surface: **post-race narrative post + pinned standings table** at the top of
  the channel.
- Rival: the driver **adjacent to the player by points** (ahead; behind if the
  player leads).
- Points: taken **from the game** (`points` in final classification), **race
  sessions only** (no sprint), accumulated **by driver name**.

## Prior art reused (not reinvented)

- **Archive already persists across app runs.** `analytics/archive.py`'s
  `save_game_session()` / `list_game_sessions()` / `load_game_session()` write
  one JSON per session to `DATA_DIR/game_sessions/`. `core/career_stats.py` is
  the precedent: a pure function aggregating `final_position` across all
  archived races. This design follows that model exactly.
- **The game gives per-race points and the full grid.** `core/packets.py::
  parse_final_classification_grid()` returns every car with `position`,
  `points`, `grid_position`, `result_status`. The engine already holds it as
  `self._final_classification_grid` and already joins vehicle_idx → driver
  name/team via `race_state.driver()` (see `engine.py`'s reality-result
  enrichment at ~line 754). Championship = sum of the game's own `points` per
  driver — no F1 points table needed.
- **RaceFeed pipeline is category-driven.** A new event code → category →
  reporter drops in the same way `QualifyingReporter` and the career-stories
  `CAREER_RECAP` did, reusing comments/stats/scheduling untouched.
- **`vehicle_idx` bug pattern.** `core/engine.py::_event_involves()` only
  recognizes an event as player-owned via `*_idx` keys. The career-stories work
  established the fix: put `"vehicle_idx": self._player_car_index` on the draft
  dict. The new `CHAMPIONSHIP` event follows the same rule.

## Components

### 1. Data capture — a dedicated season-results store

**Ordering correction (found while planning):** `recorder.finalize()` runs at
`CHQF` (session end), but the authoritative full grid *with the game's points*
arrives one packet later — the Final Classification packet, handled by
`core/engine.py::_update_final_classification_grid()` (~line 808). The live grid
available at `CHQF` has positions but **no points**. So capture must hang off the
packet-8 site, not `finalize()`.

- **`analytics/archive.py`**: add `save_season_result(data: dict) -> Path` and
  `list_season_results(limit: int | None = None) -> list[dict]`, mirroring the
  existing `save_game_session`/`list_game_sessions` pair but writing full dicts
  to a new `DATA_DIR/season/` folder, newest-first by filename.
- **`core/engine.py::_update_final_classification_grid()`**: right after the
  grid is stored (`self._final_classification_grid = list(parsed)`), for
  `session_type == "race"` and once per session (a `self._championship_recorded`
  flag reset at `SSTA`): enrich each entry via `self.race_state.driver(idx)`
  into `{position, points, driver, team, is_player}` (flagging
  `vehicle_idx == self._player_car_index`) and `archive.save_season_result(
  {"timestamp", "track_id", "game_year", "classification": [...]})`. Runs
  before the existing reality-mode gates, so it fires for every race regardless
  of reality mode.

This decouples championship capture from the `finalize()`/story timing race and
matches how the existing reality "season auto mode" already hooks packet 8.

### 2. Standings computation — `core/season.py` (new, pure)

Mirrors `career_stats.py`: pure functions over the archive, no state, no
network, computed on demand.

- `compute_standings(window: int = 22) -> dict | None`
  - Read `archive.list_season_results(limit=window)` (newest-first race records
    written by the capture step).
  - Sum `points` per `driver` across those records; carry each driver's latest
    `team`; mark the player via any `is_player` entry.
  - Return `{"standings": [{driver, team, points, position, is_player}],
    "races_counted": N}` sorted by points desc (ties broken by more wins, then
    name for stability). `None` if no race has a `classification` yet.
- `pick_rival(standings: list[dict]) -> dict | None`
  - Find the player row; return the driver directly **ahead** by points, or the
    one directly **behind** if the player is P1. `None` if the player isn't in
    the table or is the only entry.
- `season_summary(window: int = 22, race_points: int | None = None) -> dict | None`
  - Compose player points, championship position, `races_counted`, the rival's
    name + points gap, and `race_points` (points the player scored in the race
    that just finished, passed in by the caller). `None` when standings are
    `None` or the player isn't classified. This dict is exactly the fact set the
    `CHAMPIONSHIP` event carries.

### 3. Post-race championship post — RaceFeed pipeline

- **`core/engine.py`**: in the same `_update_final_classification_grid()` block,
  immediately after `save_season_result(...)` (so `compute_standings` includes
  the just-finished race), publish a new `CHAMPIONSHIP` event via
  `self._commentary_events.publish({...})` (the same fan-out that reaches
  RaceFeed, exactly like `_publish_career_recap`), carrying
  `season.season_summary(race_points=<player's points this race>)`'s fields plus
  `"event_code": "CHAMPIONSHIP"`, `"priority": "normal"`, `"driver": ""`,
  `"vehicle_idx": self._player_car_index`, and a computed `"importance"`.
  Importance: `85` if the player is championship leader, else `70` if they
  scored points this race, else `55` (still above the Editor's threshold — a
  championship update is always worth one post). Guarded by
  `season_summary(...) is not None` (no season store yet → no event). Publishing
  after `CHQF` still reaches a live RaceFeed post: the session db stays open
  (only ticks stop on `CHQF`), so the event drains → story → post normally.
- **`core/racefeed/engine.py` (`StoryBuilder`)**: add `"CHAMPIONSHIP"` to
  `_PLAYER_ONLY_CODES` → category `"championship"`. (Player-only: the whole post
  is about the player's title fight.)
- **`core/racefeed/reporters.py`**: new `ChampionshipReporter`
  (`id = "championship_desk"`) covering `category == "championship"` in
  `session_type == "race"`, priority `"analysis"`, update_policy `"supersede"`
  (at most one per race). Added to `REPORTERS` (now 5).
- **`core/racefeed/prompts.py`**: `SYSTEM_PROMPTS["championship_desk"]` — season
  narrative desk: reports the standings shift, names the rival and the gap, ends
  on the title-fight stakes ("до соперника N очков"). Facts already filtered by
  `_format_facts` (technical keys dropped); no team-placeholder risk since the
  rival name comes from the standings, not a raw team_id.
- **Comments**: `championship` is not in `comments.py::_NO_COMMENT_CATEGORIES`,
  so the post gets a discussion thread (people argue standings) — desired.
- **Stats**: the pipeline counters (`posts_published`, etc.) apply automatically.

### 4. Pinned standings table — UI

- **Backend read API**: `core/racefeed/ui_bridge.py::get_standings()` →
  `season.compute_standings()`; `core/engine.py::get_season_standings()` wraps
  it; `web_server.py` route `GET /api/racefeed/standings` returns
  `{enabled, standings, races_counted}` (or `{enabled: True, standings: []}`
  before any classified race). Independent of the posts feed so the table shows
  even with an empty channel.
- **Frontend**:
  - `lib/api.ts`: `StandingsRow` type + `getSeasonStandings()` fetch;
    `lib/use-racefeed.ts` (or a sibling hook) polls `/api/racefeed/standings`
    on the same ~3s cadence.
  - `components/spotter/views/race-feed-channel.tsx`: a pinned
    `ChampionshipStandings` card above the post stream — compact table
    (position, driver, team-color dot, points), the player's row highlighted,
    the rival's row marked. Collapsible; hidden entirely when `standings` is
    empty. Reuses the existing card styling.

## Data flow

```
Final Classification packet (engine._update_final_classification_grid)
  → enrich grid (position, points, driver, team, is_player) from race_state
  → archive.save_season_result({track, game_year, classification})  → DATA_DIR/season/
  → season.season_summary(race_points=<player points>)  (reads store incl. this race)
  → self._commentary_events.publish({event_code:"CHAMPIONSHIP", vehicle_idx:player, ...facts})
        → RaceFeed StoryBuilder → ChampionshipReporter → Editor → post + comments
GET /api/racefeed          → posts feed (unchanged)
GET /api/racefeed/standings → season.compute_standings() → pinned table
```

## Error handling

Nothing new in spirit. No `classification` in any archived race (fresh install,
old archives) → `compute_standings()` returns `None`/empty → no `CHAMPIONSHIP`
event, no pinned card (fail-open, matches `career_stats`). A grid entry with a
missing driver name is skipped from the sum rather than mislabeled. Standings
with fewer than `window` races use what exists. LLM/storage failures degrade
exactly as the rest of RaceFeed already does (candidate dropped / retried).

## Testing

- **`core/season.py`** (pure, no I/O beyond a monkeypatched archive): standings
  sum by driver, sliding-window truncation, ties, player-row detection,
  `pick_rival` ahead/behind/leader/edge cases, `season_summary` shape and
  `None` guards.
- **`analytics/archive.py`**: `save_season_result` round-trips via
  `list_season_results`; `limit` truncates newest-first; empty folder → `[]`.
- **RaceFeed**: `StoryBuilder` maps `CHAMPIONSHIP`→`championship`;
  `ChampionshipReporter` covers it only in race; a `CHAMPIONSHIP` event flows to
  a published post from `championship_desk`; `REPORTERS` has the new id and a
  matching system prompt.
- **`ui_bridge.get_standings`** / route: disabled/empty/populated shapes.
- **Frontend**: `tsc --noEmit` (no test infra), manual visual check needs a real
  race — same level as the rest of RaceFeed's frontend.

## Out of scope (explicitly deferred)

Real calendar / round numbers / "races remaining in the season", sprint points,
constructors' championship, multi-career separation (the sliding window sidesteps
it), notifications/unread badge (a separate cheap follow-up on the existing
counters), season reset UI.
