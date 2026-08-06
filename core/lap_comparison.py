"""Shared session-progress module for lap-reference comparisons."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ComparisonMilestones:
    lap_improved: bool
    sector_improved: int | None


class LapComparisonProgress:
    """Own PB state shared by real-F1 and personal-history comparisons.

    One observation updates the best lap and every improved sector.  When
    several sectors improve together, the returned sector is the one with the
    smallest reference gap, so callers publish at most one announcement.
    """

    def __init__(self) -> None:
        self.best_lap_ms: int | None = None
        self.best_sector_ms: dict[int, int] = {}

    def reset(self) -> None:
        self.best_lap_ms = None
        self.best_sector_ms = {}

    def observe(self, comparison: dict) -> ComparisonMilestones:
        player_best = comparison["player_best_ms"]
        lap_improved = self.best_lap_ms is None or player_best < self.best_lap_ms
        if lap_improved:
            self.best_lap_ms = player_best

        improved: list[int] = []
        sectors = comparison.get("sectors")
        if sectors is not None:
            for number, sector in sectors.items():
                player_ms = sector["player_ms"]
                best = self.best_sector_ms.get(number)
                if best is None or player_ms < best:
                    self.best_sector_ms[number] = player_ms
                    improved.append(number)

        sector_improved = None
        if improved:
            sector_improved = min(improved, key=lambda n: sectors[n]["gap_ms"])
        return ComparisonMilestones(lap_improved, sector_improved)
