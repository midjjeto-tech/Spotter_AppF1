"""core/track_ai/zones.py — attack/defense zone detection."""
from __future__ import annotations

from core.track_ai.models import Corner

# Corner types that offer genuine overtaking opportunities under braking
_OVERTAKE_TYPES = {"hairpin", "slow", "chicane", "medium"}


def is_attack_zone(corner: Corner | None, phase: str, drs_active: bool) -> bool:
    """Return True if the current position is a typical attack opportunity.

    Attack zone = DRS straight (no corner) OR braking zone before a slow corner.
    """
    if drs_active and corner is None:
        return True  # DRS zone on open straight
    if corner is not None and phase == "braking" and corner.type in _OVERTAKE_TYPES:
        return True
    return False
