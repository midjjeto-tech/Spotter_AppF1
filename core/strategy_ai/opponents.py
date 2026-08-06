"""
core/strategy_ai/opponents.py
================================
Detect when the car ahead has pitted using gap_front_ms changes.
No UDP parser changes needed — a sudden gap increase > PIT_GAP_THRESHOLD_MS
is a reliable signal that the car ahead entered the pit lane.
"""
from __future__ import annotations

PIT_GAP_THRESHOLD_MS = 12_000
COVER_WINDOW = 10     # updates (~10 s at 1 update/s) the signal stays active


class OpponentPitDetector:
    """Detect opponent pit from gap_front_ms changes."""

    def __init__(self) -> None:
        self._prev_gap: int | None = None
        self._cover_counter: int = 0

    def update(self, gap_front_ms: int | None) -> None:
        if gap_front_ms is None:
            return
        if self._prev_gap is not None:
            delta = gap_front_ms - self._prev_gap
            if delta > PIT_GAP_THRESHOLD_MS:
                self._cover_counter = COVER_WINDOW
            elif self._cover_counter > 0:
                self._cover_counter -= 1
        self._prev_gap = gap_front_ms

    @property
    def opponent_pitted(self) -> bool:
        return self._cover_counter > 0

    def should_cover(self, our_tyre_status: str) -> tuple[bool, float]:
        """Return (cover_recommended, confidence).

        Only recommend covering if opponent pitted AND our tyres need changing.
        """
        if not self.opponent_pitted:
            return False, 0.0
        if our_tyre_status not in ("worn", "critical", "cliff"):
            return False, 0.0
        conf = 0.75 if our_tyre_status == "cliff" else 0.65
        return True, conf
