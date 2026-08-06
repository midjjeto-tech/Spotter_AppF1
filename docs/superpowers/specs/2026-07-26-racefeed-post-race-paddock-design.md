# RaceFeed — post-race paddock and Driver of the Day

## Goal

After the authoritative Final Classification packet, RaceFeed publishes two
structured post-race stories:

1. a clearly labelled simulated paddock interview reconstructed from actual
   race facts;
2. a simulated audience vote for Driver of the Day.

Neither event is voiced. Both are RaceFeed-only editorial content.

## Driver of the Day

The existing `core/driver_of_the_day.py` pure function becomes the single
scoring module. It receives the official classification plus per-driver
overtake counts collected during the race.

Candidate score uses only observed facts:

- positions gained from grid to finish;
- overtakes completed;
- finishing-position bonus;
- fastest-lap bonus from the classification;
- penalty deduction.

The best three classified drivers form the poll. Vote percentages are derived
deterministically from their scores and always total 100. RaceFeed persists the
candidate list with the post so the UI can render stable result bars without
recomputing telemetry.

## Interview reconstruction

`core/post_race_interview.py` selects at most three unique drivers:

- race winner;
- Driver of the Day leader;
- the player's driver.

It creates short responses from each driver's actual finish, positions gained
and overtake count. The UI labels the block as a reconstruction so generated
text is never presented as a real quotation captured from team radio.

## Data flow

`F1Engine` counts `OVTK` events by overtaking vehicle for the current race and
resets the counts on `SSTA`.

After Final Classification:

```
grid + overtake counts
  -> driver_of_the_day.compute()
  -> post_race_interview.build()
  -> CommentaryEvents.publish(RACEFEED_DOTD / POST_RACE_INTERVIEW)
  -> EditorialDesk
  -> PaddockReporter
  -> RaceFeed Post.metadata
  -> poll bars / interview cards in RaceFeed UI
```

`Post.metadata` is a JSON object persisted in SQLite. It is an extension seam
for structured editorial cards; normal posts use an empty object.

## Failure handling

- Missing or placeholder driver identities are ignored.
- Missing grid positions count as zero positions gained rather than dropping an
  otherwise classified driver.
- If the LLM is unavailable, both post-race stories have deterministic text
  fallbacks; structured poll/interview data still renders.
- If no usable classification exists, neither story is published.

## Testing

- Pure score and percentage tests for Driver of the Day.
- Pure selection and fact-bound response tests for interview reconstruction.
- StoryBuilder and PaddockReporter coverage.
- SQLite metadata migration/round-trip.
- RaceFeed publication metadata integration.
- Existing RaceFeed, engine and channel-routing regression suites.
