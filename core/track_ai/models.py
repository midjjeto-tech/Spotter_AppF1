"""core/track_ai/models.py — dataclasses for Track Intelligence Layer."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Corner:
    id: int
    name: str           # "Turn 1", "La Source", …
    start: float        # lap fraction 0.0-1.0 where corner begins
    end: float          # lap fraction where corner ends
    type: str           # "hairpin" | "slow" | "medium" | "fast" | "chicane"
    direction: str      # "left" | "right"
    attack_side: str    # "inside" | "outside" | "none"
    defense_side: str   # "inside" | "outside" | "none"


@dataclass
class TrackInfo:
    name: str
    length_m: float
    corners: list[Corner] = field(default_factory=list)


@dataclass
class TrackContext:
    corner: Corner | None   # None when on a straight
    phase: str              # "straight"|"braking"|"entry"|"apex"|"exit"
    sector: int             # 1 / 2 / 3
    attack_zone: bool
    advice: str             # "cover_inside"|"hold_line"|"late_brake"|"none"
    advice_reason: str      # human-readable reason

    def to_dict(self) -> dict:
        return {
            "corner":          self.corner.name if self.corner else None,
            "corner_id":       self.corner.id   if self.corner else None,
            "corner_type":     self.corner.type if self.corner else None,
            "phase":           self.phase,
            "sector":          self.sector,
            "attack_zone":     self.attack_zone,
            "defense_advice":  self.advice,
            "advice_reason":   self.advice_reason,
        }
