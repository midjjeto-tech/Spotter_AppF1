import time

from core.racefeed.editor import Editor, StoryMemory
from core.racefeed.engine import StoryBuilder
from core.racefeed.models import Event
from core.racefeed.reporters import REPORTERS


def _career_recap_event(importance: int) -> Event:
    return Event(
        event_code="CAREER_RECAP", session_type="race", driver=None, team=None,
        vehicle_idx=4, is_player=True, importance=importance, laps_remaining=0,
        description="career recap", extra={
            "vs_last_visit": {"laptime_delta_ms": -200, "position_delta": 2,
                              "last_visit_date": "2026-01-01"},
            "career_stats": {"total_races": 10, "wins": 1, "podiums": 3, "avg_position": 5.0},
        },
        enqueued_at=time.time(),
    )


def _propose_and_evaluate(story):
    """Mirrors RaceFeedEngine._propose_and_schedule for a single story, without
    needing a running worker thread — returns the Editor's decision, or None if
    no reporter covers the story at all."""
    editor = Editor()
    for reporter in REPORTERS:
        candidate = reporter.propose(story)
        if candidate is None:
            continue
        return editor.evaluate(candidate, story)
    return None


def test_podium_recap_publishes():
    builder = StoryBuilder(StoryMemory())
    story = builder.from_event(_career_recap_event(importance=90))
    assert _propose_and_evaluate(story) == "new"


def test_improved_recap_publishes():
    builder = StoryBuilder(StoryMemory())
    story = builder.from_event(_career_recap_event(importance=70))
    assert _propose_and_evaluate(story) == "new"


def test_routine_recap_is_suppressed():
    builder = StoryBuilder(StoryMemory())
    story = builder.from_event(_career_recap_event(importance=40))
    assert _propose_and_evaluate(story) == "suppress"
