# RaceFeed — deep Editorial Pacing module

## Context

RaceFeed's Phase 1 contract targets 15–25 posts per race, but two current
session databases contain 78 and 81 posts. The existing pipeline makes only
per-Story decisions: `Editor` knows materiality, `Scheduler` knows pending
Candidates, and Reporter modules know coverage. No module owns session-wide
editorial volume.

ADR-0002 remains unchanged: `CommentaryEvents.publish()` owns canonical event
publication and fans out to RaceFeed exactly once. RaceFeed still consumes
canonical events and snapshots, not raw telemetry or `RaceState`.

## Accepted language and rules

- **Editorial Pacing**: target 15–25 posts, working budget 20, non-critical
  ceiling 30. After 20, only high-importance non-critical publications pass.
  Critical publications bypass both limits.
- **Critical RaceFeed Publication**: finish, Safety Car/red flag, retirement,
  key player event, championship or milestone.
- **Battle Story**: one evolving Story per unordered driver pair. The first
  overtake opens it; repeated exchanges may produce at most one meaningful
  update. Overtakes against different opponents remain separate.
- **Analytics Budget**: at most six publications — two `gap_trend`, two
  `tyre_status`, one `fuel_status`, one `ers_status`. It is a ceiling, not a
  quota; quiet races may remain below 15 posts.
- **Incident Story**: repeated contacts for one unordered pair within 30
  seconds or one lap are one Story. Player incidents publish immediately.
  Non-player contacts are deferred and publish only if followed by a penalty,
  retirement or Safety Car consequence. The consequence may still receive its
  own official publication.

## Module shape

`EditorialDesk` is the external editorial seam used by `RaceFeedEngine`. It
owns:

- Story construction and Story Memory;
- Reporter selection;
- deterministic materiality;
- session budgets and per-Story limits;
- deferred Incident Stories;
- Candidate timing and update policy;
- Story advancement after publication.

`RaceFeedEngine` continues to own worker lifecycle, LLM calls, comments and
publication persistence. It no longer orchestrates Reporter → Editor →
Scheduler itself.

## Pacing policy

Order of checks:

1. Reporter coverage and deterministic materiality.
2. Pending update policy (`supersede`, `append`, `ignore_if_pending`).
3. Battle/Incident/Analytics limits.
4. Working budget: once 20 slots are accepted, non-critical importance below
   80 is suppressed.
5. Non-critical ceiling: once 30 slots are accepted, all further non-critical
   Candidates are suppressed.
6. Critical publications always pass the session budget, but still obey
   Battle/Incident duplicate limits.

Accepted slots are counted when scheduled. A superseding Candidate reuses the
existing slot. Failed rendering does not reopen the slot: conservative
under-publication is preferable to a retry-driven burst.

## Testing

- Tests cross `EditorialDesk` through the same methods used by production.
- A time-distributed replay covers a whole synthetic race rather than stopping
  as soon as 20 posts appear.
- Contract assertions cover representative 15–25 volume, the non-critical
  ceiling, critical bypass, Analytics Budget, Battle Story pair identity and
  deferred Incident Story consequences.
- Existing RaceFeed persistence, comments and lifecycle tests remain green.

