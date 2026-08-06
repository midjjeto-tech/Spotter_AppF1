"""core/track_ai/racing_line.py — racing line / defense advice by corner type."""
from __future__ import annotations

from core.track_ai.models import Corner


def get_advice(corner: Corner | None, threat_active: bool) -> dict:
    """Return {advice, advice_reason}.

    advice values: "cover_inside" | "hold_line" | "late_brake" | "none"
    """
    if not threat_active or corner is None:
        return {"advice": "none", "advice_reason": ""}

    if corner.type == "hairpin":
        return {
            "advice":        corner.defense_side if corner.defense_side != "none" else "cover_inside",
            "advice_reason": "hairpin defense",
        }
    if corner.type == "fast":
        return {
            "advice":        "hold_line",
            "advice_reason": "fast corner — hold racing line",
        }
    if corner.type == "slow":
        return {
            "advice":        corner.defense_side if corner.defense_side != "none" else "cover_inside",
            "advice_reason": "slow corner defense",
        }
    if corner.type == "chicane":
        return {
            "advice":        corner.defense_side if corner.defense_side != "none" else "cover_inside",
            "advice_reason": "chicane defense",
        }
    # medium
    return {
        "advice":        corner.defense_side if corner.defense_side != "none" else "cover_inside",
        "advice_reason": f"{corner.type} corner defense",
    }
