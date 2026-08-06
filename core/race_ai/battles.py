"""
core/race_ai/battles.py
========================
Detect sustained battles — two cars within 1 second for multiple readings.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

BATTLE_GAP_MS = 1000
BATTLE_MIN_READINGS = 3   # readings within gap to count as active battle


@dataclass
class BattleState:
    active: bool
    cars: list[str]
    intensity: int   # 0–100, fraction of recent readings that were close


class BattleDetector:
    """Track proximity history to distinguish a momentary gap drop from a real battle."""

    def __init__(self, history_size: int = 10):
        self._history: deque[bool] = deque(maxlen=history_size)

    def update(
        self,
        gap_behind_ms: int | None,
        driver_behind: str,
        player_driver: str,
    ) -> BattleState:
        """Record one telemetry reading and return current battle state."""
        is_close = (gap_behind_ms is not None
                    and 0 < gap_behind_ms < BATTLE_GAP_MS)
        self._history.append(is_close)

        close_count = sum(self._history)
        active = close_count >= BATTLE_MIN_READINGS
        intensity = (int(close_count / len(self._history) * 100)
                     if self._history else 0)

        return BattleState(
            active=active,
            cars=[player_driver, driver_behind],
            intensity=intensity,
        )
