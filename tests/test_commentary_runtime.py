from __future__ import annotations

import config
from core.commentary_runtime import CommentaryRuntime


def test_threshold_decays_from_spike_to_base():
    runtime = CommentaryRuntime()
    runtime.note_spoken(100.0)

    assert runtime.speak_threshold(100.0) == config.PLAN_SPIKE_THRESHOLD
    assert runtime.speak_threshold(
        100.0 + config.PLAN_THRESHOLD_DECAY_S
    ) == config.PLAN_BASE_THRESHOLD


def test_threshold_bypass_and_stale_backlog_share_event_contract():
    runtime = CommentaryRuntime()
    runtime.note_spoken(100.0)
    event = {
        "event_code": "ENGINEER_GAP_DIGEST",
        "importance": 50,
        "enqueued_at": 0.0,
        "bypass_speak_threshold": True,
    }

    assert runtime.muted_by_threshold(event, 100.0) is False
    assert runtime.is_stale_backlog_event(event, 1000.0) is False


def test_activity_window_drives_ambient_cadence_and_cooldown():
    runtime = CommentaryRuntime()
    now = 1000.0
    runtime.note_event_activity(now)

    assert runtime.activity_count(now) == 1
    assert runtime.ambient_interval(now) == config.AMBIENT_BASE_INTERVAL
    assert runtime.in_event_cooldown(now) is True

    later = now + config.ACTIVITY_WINDOW + 1
    assert runtime.activity_count(later) == 0
    assert runtime.ambient_interval(later) == config.AMBIENT_MAX_INTERVAL


def test_ambient_request_throttle_is_owned_by_runtime():
    runtime = CommentaryRuntime()
    runtime.note_ambient_request(100.0)

    assert runtime.ambient_throttled(100.0) is True
    assert runtime.ambient_throttled(100.0 + config.LLM_MIN_INTERVAL + 1) is False
