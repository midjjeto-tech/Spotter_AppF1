# RaceFeed — Milestones / Achievements (design)

## Context

Retention amplifier on top of the season/championship layer: celebrate the
player's career/season achievements as RaceFeed posts. Ego/identity hooks —
"Первая победа в карьере!", "Лучший результат карьеры — P2", "Третий подиум
подряд" — are exactly what pull a player back to a channel about *them*.

Reuses the existing event→category→reporter pipeline one-for-one (same shape as
`CHAMPIONSHIP` and `QualifyingReporter`), so the surface area is a new pure
module + a new reporter, with a single localized `core/engine.py` publish added
at the race-finish site. **Isolation matters here** — a parallel session is
concurrently editing `ui_bridge.py`/`race-feed-channel.tsx`/`api.ts` for other
RaceFeed work; this feature deliberately avoids those files.

## Milestone set

Detected at race finish from the all-time player race history
(`analytics/archive.py::list_game_sessions()`, newest-first, the just-finished
race at index 0). **At most one post per race** — the single highest-priority
milestone — so it stays special, never spammy.

Priority order (first match wins):

1. `first_win` — this race is P1 **and** career wins == 1. importance 92.
2. `first_podium` — this race ≤ P3 **and** career podiums == 1 (and not also a
   first win). importance 85.
3. `career_best` — a previous race exists **and** this position is strictly
   better (lower) than every previous finish. importance 82.
4. `podium_streak` — this race ≤ P3 **and** ≥ 3 consecutive podiums ending now.
   importance 80. Carries `streak`.
5. `points_streak` — this race ≤ P10 **and** ≥ 5 consecutive points finishes
   ending now. importance 72. Carries `streak`.
6. `race_milestone` — total career races in {10, 25, 50, 100, 150, 200}.
   importance 70. Carries `race_count`.

All importances are above `editor.PUBLISH_THRESHOLD` (60) — a milestone always
earns its post. Source is the CHQF-time `final_position` stored in
`game_sessions` (a rare post-race penalty could shift a real position; accepted
— milestones are flavor, not safety-critical, matching the rest of RaceFeed).

## Components

- **`core/milestones.py`** (new, pure — mirrors `core/career_stats.py`/
  `core/season.py`): `detect(race_sessions: list[dict]) -> dict | None`.
  `race_sessions` = `list_game_sessions()` filtered to `session_type == "race"`
  with a non-null `final_position`, newest-first (index 0 = just-finished).
  Returns the single highest-priority milestone as
  `{"milestone": <code>, "label": <ru text>, "position": <int>, ...}` (streak
  / race_count where relevant), or `None`. No I/O beyond the passed list — the
  engine reads the archive and passes it in, so the function is trivially
  testable.

- **`core/engine.py`** — one localized addition at the race-finish site
  (`_maybe_record_championship`, packet-8, where the season result is already
  recorded so `game_sessions` includes this race): read
  `archive.list_game_sessions()`, filter to races, call
  `milestones.detect(...)`; if non-None, `self._commentary_events.publish(
  {"event_code": "MILESTONE", "priority": "normal", "driver": "",
   "color": "#F5C518", "vehicle_idx": self._player_car_index,
   "importance": <from milestone>, **milestone})`. Guarded once-per-race by the
  existing `self._championship_recorded` flag (same finish, same guard).

- **`core/racefeed/engine.py` (`StoryBuilder`)**: add `"MILESTONE"` →
  `"milestone"` to `_PLAYER_ONLY_CODES` (player-only: it's the player's
  achievement).

- **`core/racefeed/reporters.py`**: new `AchievementsReporter`
  (`id = "achievements"`) covering `category == "milestone"` in
  `session_type == "race"`, priority `"analysis"`, update_policy `"supersede"`.
  Added to `REPORTERS`.

- **`core/racefeed/prompts.py`**: `SYSTEM_PROMPTS["achievements"]` — a
  celebratory-but-factual desk: one short line naming the achievement, warm,
  no invented numbers. Facts already filtered by `_format_facts`.

- **Comments**: `milestone` is not in `comments.py::_NO_COMMENT_CATEGORIES`, so
  the post gets a congratulations thread — desired.

- **Frontend**: none. Milestone posts render through the existing
  `TelegramPost`; a new reporter label/avatar is a nice-to-have but not
  required (falls back to the id/grandstand avatar). Deliberately no frontend
  change to avoid colliding with the parallel session's `race-feed-channel.tsx`
  edits.

## Data flow

```
race finish (engine._maybe_record_championship, packet-8, once per race)
  → archive.list_game_sessions() filtered to races (this race already saved at CHQF)
  → milestones.detect(races) → highest-priority milestone | None
  → if not None: self._commentary_events.publish({event_code:"MILESTONE", ...facts})
        → RaceFeed StoryBuilder → AchievementsReporter → Editor → post + comments
```

## Error handling

Fail-safe, nothing new: no race history / first-ever race with no qualifying
milestone → `detect` returns `None` → no post. LLM/storage failures degrade as
everywhere else in RaceFeed (candidate dropped / retried). The once-per-race
guard prevents duplicate milestone posts if the Final Classification packet
arrives more than once.

## Testing

- **`core/milestones.py`** (pure, synthetic session lists): each milestone code
  fires on its trigger and not otherwise; priority resolution (first win beats
  everything; career_best only when strictly better and a previous race
  exists; streak counting; round-race counts); `None` when nothing qualifies;
  first-ever race edge cases.
- **RaceFeed**: `StoryBuilder` maps `MILESTONE`→`milestone`;
  `AchievementsReporter` covers it only in race; a `MILESTONE` event flows to a
  published post from `achievements`; `REPORTERS` has the new id and a matching
  system prompt (auto-checked by `test_every_reporter_has_a_system_prompt`).
- Live verification needs a real race that actually hits a milestone — manual,
  same as the rest of RaceFeed.

## Out of scope

Frontend badge/label for the achievements reporter, milestone history/gallery,
constructors or teammate milestones, configurable thresholds, non-race
(qualifying/practice) achievements.
