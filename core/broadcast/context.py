"""core/broadcast/context.py — sliding window of recent broadcast phrases."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class _Record:
    event_type: str
    phrase: str
    ts: float = field(default_factory=time.monotonic)


class BroadcastContext:
    """Keeps the last ``maxlen`` broadcast phrases for deduplication."""

    def __init__(self, maxlen: int = 10):
        self._q: deque[_Record] = deque(maxlen=maxlen)

    def add(self, event_type: str, phrase: str) -> None:
        self._q.append(_Record(event_type=event_type, phrase=phrase))

    def recent_phrases(self, n: int = 5) -> list[str]:
        """Return the last *n* phrases (oldest first)."""
        records = list(self._q)
        return [r.phrase for r in records[-n:]]

    def was_recent(self, event_type: str, seconds: float) -> bool:
        """True if an event of *event_type* was broadcast within *seconds* ago."""
        now = time.monotonic()
        return any(
            r.event_type == event_type and (now - r.ts) < seconds
            for r in self._q
        )

    def clear(self) -> None:
        """Drop phrases from the completed race before a new broadcast begins."""
        self._q.clear()
