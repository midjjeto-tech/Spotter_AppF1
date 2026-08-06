"""core/track_ai/corners.py — corner/phase detection from lap distance fraction."""
from __future__ import annotations

from core.track_ai.models import Corner

# How far before the corner start we treat as "braking zone" (fraction of lap)
BRAKING_OFFSET: float = 0.018


def get_corner(lap_pct: float, corners: list[Corner]) -> Corner | None:
    """Return the corner the car is approaching or inside; None if on a straight."""
    for c in corners:
        if c.start - BRAKING_OFFSET <= lap_pct <= c.end:
            return c
    return None


def get_phase(lap_pct: float, corner: Corner) -> str:
    """Return driving phase within a corner (call only when corner is not None)."""
    if lap_pct < corner.start:
        return "braking"
    mid = (corner.start + corner.end) / 2.0
    if lap_pct < mid:
        return "entry"
    if lap_pct < corner.end - 0.005:
        return "apex"
    return "exit"
