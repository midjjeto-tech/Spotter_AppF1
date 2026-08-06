# ADR 0001: Deep Telemetry and Strategy modules

- Status: Accepted
- Date: 2026-07-21

## Context

`F1Engine` selected ten parser implementations, dispatched raw F1 packet ids,
maintained a second iRacing loop with synthetic F1 headers, and orchestrated
strategy trackers, their ordering, cooldown and reset lists.  The existing
interfaces were shallow: source and strategy implementation details leaked
into the engine and made changes non-local.

## Decision

Telemetry uses two adapters behind one message stream:

- `F1TelemetryAdapter` owns UDP transport, binary decoding and packet dispatch.
- `IRacingTelemetryAdapter` owns SDK polling, translation and source dispatch.
- Both expose `ConnectionChanged`, sparse `TelemetryDelta` and decoded
  `TelemetryRaceEvent` messages.
- `F1Engine` owns `RaceState` and consumes the normalized stream.  Adapters do
  not own race state, strategy or commentary.

Strategy uses a deep `StrategyModule`:

- It owns `StrategyAnalyzer`, pit-window approach, box-call escalation,
  advisory cooldown, decision ordering and construction of strategy events.
- Its main interface is `tick(StrategySnapshot, now) -> StrategyResult`, plus
  lifecycle reset operations.
- Race Engineer, Spotter and Race Situation behavior remain separate modules;
  they must not be folded into Strategy AI.

## Consequences

- Adding a telemetry source requires a new adapter rather than branches in the
  engine.
- F1 and iRacing retain sparse/unknown values; adapters do not invent zeros.
- iRacing Phase 2/3 mapping and synthetic events remain explicitly deferred.
- `StrategyModule.reset(reason)` clears analyzer observations on session
  start/end; flashback preserves lap-level strategy by design.  Both paths
  clear box-call, pit-window, advisory cooldown and diagnostics.
- Engine scenarios now consume the same normalized messages as production.
  Raw `_update_telemetry`, `_handle_event_packet` and the second iRacing loop
  were removed together with packet-parser imports from `core.engine`.
- Strategy tracker and cooldown aliases were removed from `F1Engine`; tests
  use `StrategyModule` and its `tick/reset/note_pit_exit` interface.
