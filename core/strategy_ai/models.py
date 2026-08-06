"""
core/strategy_ai/models.py
============================
Data types for deterministic race strategy intelligence.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StrategyDecision:
    """One deterministic strategy recommendation."""
    action: str         # "pit" | "push" | "save" | "hold"
    confidence: float   # 0.0–1.0
    reason: str         # machine key, e.g. "undercut_available"
    data: dict = field(default_factory=dict)


@dataclass
class StrategyEvent:
    """Strategy signal suitable for commentary queue."""
    type: str           # undercut | overcut | pit_window | tyre_save | push_pace | fuel_save
    priority: str       # high | medium | low
    confidence: float
    decision: StrategyDecision
    data: dict = field(default_factory=dict)


@dataclass
class StrategyAIState:
    """Current strategy snapshot — returned by /api/strategy-ai."""
    action: str
    confidence: float
    reason: str
    advice: str | None
    mode: str                   # PIT | PUSH | SAVE | HOLD
    tyre_status: str            # fresh | worn | critical | cliff
    current_event: StrategyEvent | None = None
