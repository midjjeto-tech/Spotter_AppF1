# ADR 0002: Deep Commentary runtime, Race Engineer and UI projection

- Status: Accepted
- Date: 2026-07-21

## Context

`F1Engine` owned commentary queue normalization, scoring, RaceFeed fanout,
anti-spam timing, engineer tracker lifecycle, UI feed invariants and public
snapshot construction. These responsibilities shared mutable dictionaries
and independent reset lists. That made session transitions non-local and
allowed lap observations to leak into a later session.

F1 and Career lap comparison also duplicated best-lap and best-sector
milestones in four engine fields.

## Decision

Commentary is split across two deep modules with narrow interfaces:

- `CommentaryEvents.publish(draft)` creates one immutable canonical event,
  applies defaults and importance scoring, timestamps it, fans it out to
  RaceFeed once and enqueues it by importance.
- `CommentaryRuntime` owns the speaking threshold, stale-backlog rule,
  activity window, cooldown and ambient request throttle.

Race Engineer is a separate deep module:

- `RaceEngineer` owns gap, rain, track-limits, DRS, position, leader, spotter
  and defense implementations.
- One `reset(reason)` replaces repeated tracker reset lists. Session end now
  clears gap trends and armed rain observations as well as the other trackers.
- Strategy, Race Situation and Driver Coach remain separate modules.

UI state is a projection rather than an engine-owned shared dictionary:

- `UIStateProjection` owns the public schema, re-entrant lock, bounded feed,
  speaking state, session-view reset and overlay construction.
- Public reads return deep snapshots, so callers cannot mutate live nested
  state through a returned value.
- All public-state writers use semantic projection methods. Domain decisions
  read engine-owned values rather than reading the UI projection back.

Lap milestone state is owned by `LapComparisonProgress`. F1 Benchmark and
Career Memory keep their source-specific comparison semantics but share the
same best-lap/best-sector progress implementation.

## Consequences

- Event defaults, scoring, queue order and RaceFeed fanout have one locality.
- Commentary timing can be tested without constructing the engine.
- Adding an engineer observation no longer adds another engine lifecycle list.
- Session reset cannot retain gap/rain or Strategy Analyzer observations.
- UI consumers receive isolated nested values and the feed cap has one owner.
- Queue, timing, tracker and mutable-state compatibility seams are removed.
  Engine tests cross the same module interfaces as production.

## Completed migration

`F1EngineCompatibility`, `UIStateProjection.compatibility_state` and
`CommentaryEvents.compatibility_queue` were deleted after all callers moved to
the owning modules. `F1Engine` now keeps a separate domain lock, while the UI
projection owns its lock and never exposes its live nested dictionary.
