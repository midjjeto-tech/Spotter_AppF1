import queue

from commentator.planner import PlanContext
from core.commentary_events import CommentaryEvent, CommentaryEvents


def _context(event):
    return PlanContext(
        player_involved=bool(event.get("player")),
        battle=bool(event.get("battle")),
        laps_remaining=7,
        session_type="race",
    )


def test_publish_copies_draft_and_delivers_immutable_canonical_event():
    clock = lambda: 123.0
    events = CommentaryEvents(_context, scorer=lambda _e, _c: 71, clock=clock)
    draft = {"event_code": "OVTK", "facts": {"target": "Norris"}}

    published = events.publish(draft)
    draft["event_code"] = "PENA"
    draft["facts"]["target"] = "Changed"

    queued = events.next()
    assert isinstance(queued, CommentaryEvent)
    assert queued["event_code"] == "OVTK"
    assert queued["facts"] == {"target": "Norris"}
    assert queued["importance"] == 71
    assert queued["laps_remaining"] == 7
    assert queued["enqueued_at"] == 123.0
    assert published.to_dict() == queued.to_dict()


def test_priority_order_and_fifo_ties_are_hidden_behind_next():
    events = CommentaryEvents(_context)
    events.publish({"event_code": "LOW", "importance": 10})
    events.publish({"event_code": "HIGH_A", "importance": 90})
    events.publish({"event_code": "HIGH_B", "importance": 90})

    assert [events.next()["event_code"] for _ in range(3)] == [
        "HIGH_A", "HIGH_B", "LOW"]


def test_planning_failure_uses_neutral_defaults():
    def broken(_event):
        raise RuntimeError("boom")

    events = CommentaryEvents(broken, clock=lambda: 10.0)
    event = events.publish({"event_code": "SAFE"})

    assert event["importance"] == 50
    assert event["laps_remaining"] is None


def test_race_feed_receives_exactly_one_projection():
    class Feed:
        def __init__(self):
            self.received = []

        def ingest(self, event):
            self.received.append(event)

    feed = Feed()
    events = CommentaryEvents(
        _context,
        race_feed_provider=lambda: feed,
        player_team_provider=lambda: "McLaren",
    )

    events.publish({
        "event_code": "PENA", "driver": "Norris", "team": "McLaren",
        "importance": 90,
    })

    assert len(feed.received) == 1
    assert feed.received[0].event_code == "PENA"
    assert feed.received[0].is_player_team is True


def test_clear_returns_number_of_discarded_events():
    events = CommentaryEvents(_context)
    events.publish({"event_code": "A"})
    events.publish({"event_code": "B"})

    assert events.clear() == 2
    try:
        events.get_nowait()
    except queue.Empty:
        pass
    else:
        raise AssertionError("queue must be empty")


def test_media_hook_runs_before_fanout_and_can_mutate_values():
    seen = {}

    def media_hook(values, context):
        seen["code"] = values.get("event_code")
        seen["player"] = context.player_involved
        values["image"] = "shot.png"

    class _RF:
        def __init__(self):
            self.got = None

        def ingest(self, event):
            self.got = event

    rf = _RF()
    events = CommentaryEvents(_context, race_feed_provider=lambda: rf, media_hook=media_hook)
    events.publish({"event_code": "OVTK", "player": True, "importance": 90})

    assert seen == {"code": "OVTK", "player": True}
    assert rf.got.extra.get("image") == "shot.png"
