import time

from core.racefeed.models import Candidate
from core.racefeed.scheduler import PUBLISH_DELAY_S, Scheduler


def _candidate(story_id, update_policy, base_importance=1, priority="default",
                delay=(0.0, 0.0), expires_in=60.0):
    now = time.time()
    return Candidate(
        story_id=story_id, story_key=(story_id,), category="x",
        reporter_id="r", base_importance=base_importance, priority=priority,
        publish_after=delay, expires_at=now + expires_in,
        update_policy=update_policy,
    )


def test_not_due_before_publish_at():
    sched = Scheduler()
    now = time.time()
    sched.schedule(_candidate("s1", "supersede", delay=(1000.0, 1000.0)), now)
    assert sched.due(now) == []


def test_due_after_publish_at():
    sched = Scheduler()
    now = time.time()
    sched.schedule(_candidate("s1", "supersede", delay=(0.0, 0.0)), now)
    due = sched.due(now + 0.01)
    assert len(due) == 1
    assert due[0].story_id == "s1"


def test_supersede_cancels_pending_and_replaces():
    sched = Scheduler()
    now = time.time()
    sched.schedule(_candidate("s1", "supersede", base_importance=1, delay=(0.0, 0.0)), now)
    sched.schedule(_candidate("s1", "supersede", base_importance=2, delay=(0.0, 0.0)), now)

    due = sched.due(now + 0.01)
    assert len(due) == 1
    assert due[0].base_importance == 2


def test_ignore_if_pending_drops_the_new_one():
    sched = Scheduler()
    now = time.time()
    sched.schedule(_candidate("s1", "ignore_if_pending", base_importance=1, delay=(0.0, 0.0)), now)
    sched.schedule(_candidate("s1", "ignore_if_pending", base_importance=2, delay=(0.0, 0.0)), now)

    due = sched.due(now + 0.01)
    assert len(due) == 1
    assert due[0].base_importance == 1


def test_append_publishes_both():
    sched = Scheduler()
    now = time.time()
    sched.schedule(_candidate("s1", "append", base_importance=1, delay=(0.0, 0.0)), now)
    sched.schedule(_candidate("s1", "append", base_importance=2, delay=(0.0, 0.0)), now)

    due = sched.due(now + 0.01)
    assert sorted(c.base_importance for c in due) == [1, 2]


def test_expired_candidate_is_dropped():
    sched = Scheduler()
    now = time.time()
    sched.schedule(_candidate("s1", "supersede", delay=(0.0, 0.0), expires_in=-1.0), now)
    assert sched.due(now + 0.01) == []


def test_schedule_due_then_schedule_again_for_same_story_id():
    sched = Scheduler()
    now = time.time()
    sched.schedule(_candidate("s1", "supersede", base_importance=1, delay=(0.0, 0.0)), now)
    first_due = sched.due(now + 0.01)
    assert len(first_due) == 1

    # After the first candidate fired and was popped, a second candidate for the
    # SAME story_id must not be blocked/dropped by stale _pending tracking from
    # the first one.
    sched.schedule(_candidate("s1", "supersede", base_importance=2, delay=(0.0, 0.0)), now + 0.02)
    second_due = sched.due(now + 0.03)
    assert len(second_due) == 1
    assert second_due[0].base_importance == 2


def test_publish_delay_s_has_all_priority_buckets():
    for key in ("incident", "pit_stop", "statistics", "analysis", "default"):
        assert key in PUBLISH_DELAY_S
        lo, hi = PUBLISH_DELAY_S[key]
        assert 0 <= lo <= hi
