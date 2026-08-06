"""Runtime policy and timing state for live commentary."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
import threading

import config


class CommentaryRuntime:
    """Own commentary timing, threshold, backlog and ambient cadence rules."""

    def __init__(self) -> None:
        self.recent_event_times: deque[float] = deque()
        self.last_significant_event_at = 0.0
        self.last_ambient_request_at = 0.0
        self.last_voiced_at = 0.0
        self._lock = threading.Lock()

    def speak_threshold(self, now: float, *, mode: str = "live") -> float:
        offset = config.COMMENTARY_MODE_THRESHOLD_OFFSET.get(mode, 0)
        base = config.PLAN_BASE_THRESHOLD + offset
        spike = config.PLAN_SPIKE_THRESHOLD + offset
        elapsed = now - self.last_voiced_at
        if elapsed >= config.PLAN_THRESHOLD_DECAY_S:
            return base
        span = spike - base
        return spike - span * (elapsed / config.PLAN_THRESHOLD_DECAY_S)

    def muted_by_threshold(
        self,
        event: Mapping[str, object],
        now: float,
        *,
        mode: str = "live",
    ) -> bool:
        if event.get("ambient") or event.get("bypass_speak_threshold"):
            return False
        return int(event.get("importance", 50)) < self.speak_threshold(now, mode=mode)

    @staticmethod
    def is_stale_backlog_event(event: Mapping[str, object], now: float) -> bool:
        if event.get("bypass_speak_threshold"):
            return False
        importance = int(event.get("importance", 50))
        if importance >= config.PLAN_STALE_IMPORTANCE:
            return False
        age = now - float(event.get("enqueued_at", 0.0))
        return age > config.PLAN_STALE_S

    @staticmethod
    def is_significant_event(event: Mapping[str, object]) -> bool:
        if event.get("priority") == "critical" or event.get("battle"):
            return True
        return event.get("event_code") in ("OVTK", "FTLP")

    def _prune_activity(self, now: float) -> None:
        while (
            self.recent_event_times
            and now - self.recent_event_times[0] > config.ACTIVITY_WINDOW
        ):
            self.recent_event_times.popleft()

    def note_event_activity(self, now: float) -> None:
        with self._lock:
            self.recent_event_times.append(now)
            self.last_significant_event_at = now
            self._prune_activity(now)

    def activity_count(self, now: float) -> int:
        with self._lock:
            self._prune_activity(now)
            return len(self.recent_event_times)

    def ambient_interval(self, now: float) -> float:
        count = self.activity_count(now)
        if count == 0:
            return config.AMBIENT_MAX_INTERVAL
        if count >= config.AMBIENT_BUSY_EVENTS:
            return config.AMBIENT_MIN_INTERVAL
        return config.AMBIENT_BASE_INTERVAL

    def in_event_cooldown(self, now: float) -> bool:
        return (
            now - self.last_significant_event_at
        ) < config.COOLDOWN_AFTER_EVENT

    def ambient_throttled(self, now: float) -> bool:
        return (
            now - self.last_ambient_request_at
        ) < config.LLM_MIN_INTERVAL

    def note_ambient_request(self, now: float) -> None:
        with self._lock:
            self.last_ambient_request_at = now

    def note_spoken(self, now: float) -> None:
        with self._lock:
            self.last_voiced_at = now
