"""
core/coach_ai/models.py
========================
Data types for the Driver Performance Coach.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LapData:
    lap_number: int
    lap_time_ms: int
    s1_ms: int
    s2_ms: int
    s3_ms: int
    tyre_compound: str | None
    tyre_age: int | None
    tyre_wear: float | None


@dataclass
class DriverReport:
    weak_sector: int | None       # 1, 2 or 3 — sector with most consistent time loss
    lost_time_ms: int | None      # ms lost in weak sector vs. session best
    consistency_score: float      # 0.0–1.0 (1.0 = perfectly consistent lap times)
    pace_delta_ms: int | None     # recent avg lap vs. session best (positive = slower)
    tyre_advice: str              # "push" | "save" | "cliff" | "ok"
    lap_count: int                # total laps fed to the coach
    advice: str | None            # Russian summary phrase
