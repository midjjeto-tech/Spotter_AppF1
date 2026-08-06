"""
core/race_ai/decisions.py
==========================
Convert a RaceEvent into a concrete action and advice string.
"""
from __future__ import annotations

from core.race_ai.models import RaceEvent

# Maps drs flag -> (action, advice) for attack events
_ATTACK_RULES: dict[bool, tuple[str, str]] = {
    True:  ("defend", "cover_inside"),
    False: ("defend", "hold_line"),
}


def make_decision(
    event: RaceEvent,
    gap_front_ms: int | None,
    gap_closing: bool,
) -> dict[str, str]:
    """Return {"action": ..., "advice": ...} for a given race event."""
    t = event.type

    if t == "attack":
        drs = bool(event.data.get("drs"))
        action, advice = _ATTACK_RULES[drs]
        return {"action": action, "advice": advice}

    if t == "battle":
        return {"action": "defend",
                "advice": "maintain_pace" if gap_closing else "monitor"}

    if t == "tyre_warning":
        return {"action": "pit", "advice": "consider_pit"}

    if t == "final_lap":
        return {"action": "push", "advice": "maximum_attack"}

    # Generic: decide by gap to car ahead
    if gap_front_ms is not None and gap_front_ms < 500:
        return {"action": "push", "advice": "attack_ahead"}
    return {"action": "hold_line", "advice": "focus"}
