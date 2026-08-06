"""
core/race_ai/models.py
=======================
Data types shared by all race_ai modules.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class RaceEvent:
    """One deterministic race situation detected from telemetry."""
    type: str           # "attack" | "battle" | "tyre_warning" | "final_lap"
    priority: str       # "high" | "medium" | "low"
    confidence: float   # 0.0–1.0
    driver: str         # name of attacking / relevant driver
    target: str         # "player" or driver name
    data: dict = field(default_factory=dict)


@dataclass
class RaceAIState:
    """Current snapshot of race intelligence — returned by /api/race-ai."""
    intensity: int              # 0–100
    mode: str                   # "CALM" | "RACE" | "BATTLE" | "CLIMAX"
    current_event: RaceEvent | None
    threat: str | None          # human-readable, e.g. "Sainz атакует (0.8с)"
    advice: str | None          # human-readable, e.g. "cover_inside"
