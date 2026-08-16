"""core/racefeed/scheduler.py — publish-time delay heap + update_policy
enforcement. Runs entirely inside RaceFeedEngine's single worker thread loop
(see engine.py) — not designed to be called from multiple threads concurrently."""
from __future__ import annotations

import heapq
import itertools
import random

from core.racefeed.models import Candidate

PUBLISH_DELAY_S: dict[str, tuple[float, float]] = {
    "incident":   (2.0, 5.0),
    "pit_stop":   (5.0, 10.0),
    "statistics": (15.0, 25.0),
    "analysis":   (25.0, 35.0),
    "default":    (5.0, 10.0),
}


class Scheduler:
    def __init__(self):
        self._heap: list[tuple[float, int, Candidate]] = []
        self._counter = itertools.count()
        self._pending: dict[str, tuple[float, int, Candidate]] = {}

    # Assumes all candidates for a given story_id share one update_policy
    # (guaranteed by reporters.py's static category->policy map, since category
    # is embedded in story_id). If that ever stops holding, append's
    # unconditional _pending.pop() could let a later ignore_if_pending candidate
    # schedule alongside a still-pending, un-tracked earlier supersede candidate.
    def has_pending(self, story_id: str) -> bool:
        return story_id in self._pending

    def schedule(self, candidate: Candidate, now: float) -> str:
        """Schedule Candidate and report whether it used a new editorial slot.

        ``scheduled`` adds a new slot, ``replaced`` reuses a superseded slot,
        and ``ignored`` leaves the heap unchanged. EditorialDesk owns the
        session budget and uses this result to keep its counters truthful.
        """
        delay_min, delay_max = candidate.publish_after
        publish_at = now + random.uniform(delay_min, delay_max)
        pending = self._pending.get(candidate.story_id)
        replaced = False

        if pending is not None:
            if candidate.update_policy == "ignore_if_pending":
                return "ignored"
            if candidate.update_policy == "supersede":
                self._remove(pending)
                replaced = True

        entry = (publish_at, next(self._counter), candidate)
        heapq.heappush(self._heap, entry)
        if candidate.update_policy == "append":
            self._pending.pop(candidate.story_id, None)
        else:
            self._pending[candidate.story_id] = entry
        return "replaced" if replaced else "scheduled"

    def _remove(self, entry: tuple[float, int, Candidate]) -> None:
        try:
            self._heap.remove(entry)
            heapq.heapify(self._heap)
        except ValueError:
            pass

    def clear(self) -> None:
        """Discard every candidate still waiting for publication."""
        self._heap.clear()
        self._pending.clear()

    def due(self, now: float) -> list[Candidate]:
        """Pop and return every candidate whose publish_at <= now, dropping any
        that expired while waiting."""
        result: list[Candidate] = []
        while self._heap and self._heap[0][0] <= now:
            _, _, candidate = heapq.heappop(self._heap)
            existing = self._pending.get(candidate.story_id)
            if existing is not None and existing[2] is candidate:
                del self._pending[candidate.story_id]
            if candidate.expires_at >= now:
                result.append(candidate)
        return result
