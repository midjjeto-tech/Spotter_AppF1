"""Adaptive ambient, cooldown and throttle rules owned by CommentaryRuntime."""

import time

import pytest

import config
from core.commentary_runtime import CommentaryRuntime


@pytest.fixture
def runtime():
    return CommentaryRuntime()


def test_ambient_interval_quiet(runtime):
    runtime.recent_event_times.clear()
    runtime.last_significant_event_at = 0.0

    assert runtime.ambient_interval(time.time()) == config.AMBIENT_MAX_INTERVAL


def test_ambient_interval_normal(runtime):
    now = time.time()
    runtime.recent_event_times.append(now - 10)

    assert runtime.ambient_interval(now) == config.AMBIENT_BASE_INTERVAL


def test_ambient_interval_busy(runtime):
    now = time.time()
    for _ in range(config.AMBIENT_BUSY_EVENTS):
        runtime.recent_event_times.append(now - 5)

    assert runtime.ambient_interval(now) == config.AMBIENT_MIN_INTERVAL


def test_in_event_cooldown_blocks_recent(runtime):
    runtime.last_significant_event_at = time.time() - 5

    assert runtime.in_event_cooldown(time.time()) is True


def test_in_event_cooldown_expires(runtime):
    runtime.last_significant_event_at = (
        time.time() - config.COOLDOWN_AFTER_EVENT - 1
    )

    assert runtime.in_event_cooldown(time.time()) is False


def test_ambient_llm_throttled_blocks_too_soon(runtime):
    runtime.last_ambient_request_at = time.time() - 2

    assert runtime.ambient_throttled(time.time()) is True


def test_ambient_llm_not_throttled_after_floor(runtime):
    runtime.last_ambient_request_at = time.time() - config.LLM_MIN_INTERVAL - 1

    assert runtime.ambient_throttled(time.time()) is False


@pytest.mark.parametrize("event,expected", [
    ({"event_code": "OVTK", "priority": "normal"}, True),
    ({"event_code": "FTLP", "priority": "normal"}, True),
    ({"event_code": "RCWN", "priority": "critical"}, True),
    ({"event_code": "OVTK", "battle": True}, True),
    ({"event_code": "PENA", "priority": "normal"}, False),
    ({"event_code": "AMBIENT", "priority": "normal"}, False),
])
def test_is_significant_event(runtime, event, expected):
    assert runtime.is_significant_event(event) is expected


def test_activity_count_prunes_old_entries(runtime):
    now = time.time()
    for index in range(3):
        runtime.recent_event_times.append(
            now - config.ACTIVITY_WINDOW - 10 - index
        )
    runtime.recent_event_times.append(now - 5)
    runtime.recent_event_times.append(now - 2)

    assert runtime.activity_count(now) == 2
    assert len(runtime.recent_event_times) == 2
