"""
core/rivals/models.py
======================
Data types for the Rival Intelligence layer.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class RivalSnapshot:
    vehicle_idx: int
    driver: str
    team: str
    position: int
    lap: int


@dataclass
class RivalProfile:
    vehicle_idx: int
    driver: str
    team: str
    pit_count: int
    lap_count: int
    current_position: int
    style: str                          # "consistent"|"aggressive"|"charging"|"fading"
    nearby: bool                        # within ±3 positions of player
    position_history: deque = field(default_factory=lambda: deque(maxlen=10))
    tyre_age: int | None = None
    body_damage: float = 0.0
    pit_status: int = 0                 # последний известный m_pitStatus (0/1/2)
    mistake_at: float | None = None     # timestamp последней детектированной ошибки
