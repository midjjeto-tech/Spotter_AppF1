"""Deep race-engineer module for deterministic radio observations."""

from __future__ import annotations

from core.strategy_ai.defense import DefenseTracker
from core.strategy_ai.driver_query import DriverQueryTracker
from core.strategy_ai.drs_advisory import DRSAdvisoryTracker
from core.strategy_ai.gap_digest import GapDigestTracker
from core.strategy_ai.leader_change import LeaderChangeTracker
from core.strategy_ai.position_calls import PositionCallTracker
from core.strategy_ai.spotter import SpotterTracker
from core.strategy_ai.track_limits import TrackLimitsTracker
from core.strategy_ai.weather_advisory import RainAdvisoryTracker


class RaceEngineer:
    """Own deterministic engineer trackers and their lifecycle as one unit."""

    def __init__(self) -> None:
        self.gap_digest_tracker = GapDigestTracker()
        self.rain_advisory_tracker = RainAdvisoryTracker()
        self.track_limits_tracker = TrackLimitsTracker()
        self.drs_advisory_tracker = DRSAdvisoryTracker()
        self.position_call_tracker = PositionCallTracker()
        self.leader_change_tracker = LeaderChangeTracker()
        self.spotter_tracker = SpotterTracker()
        self.defense_tracker = DefenseTracker()
        self.driver_query_tracker = DriverQueryTracker()

    def reset(self, reason: str) -> None:
        """Clear all observations that cannot cross a race-time discontinuity."""
        del reason  # reserved for future reason-specific policy
        self.gap_digest_tracker.reset()
        self.rain_advisory_tracker.reset()
        self.track_limits_tracker.reset()
        self.drs_advisory_tracker.reset()
        self.position_call_tracker.reset()
        self.leader_change_tracker.reset()
        self.spotter_tracker.reset()
        self.defense_tracker.reset()
        self.driver_query_tracker.reset()

    def driver_query(self, **kwargs) -> str | None:
        return self.driver_query_tracker.check(**kwargs)

    def gap_digest(self, *args, **kwargs) -> str | None:
        return self.gap_digest_tracker.build(*args, **kwargs)

    def rain_advisory(self, forecast: dict | None) -> str | None:
        return self.rain_advisory_tracker.check(forecast)

    def track_limits_warning(self, warnings: int, now: float) -> str | None:
        return self.track_limits_tracker.check_warning(warnings, now)

    def note_track_limits_penalty(self, now: float) -> bool:
        return self.track_limits_tracker.note_penalty(now)

    def track_limits_penalty_tier(self) -> int:
        """Ступень компаньон-реплики к трек-лимитному штрафу (1..3)."""
        return self.track_limits_tracker.penalty_tier()

    def drs_advisory(
        self,
        gap_front_ms: int | None,
        drs_allowed: bool | None,
        now: float,
    ) -> str | None:
        return self.drs_advisory_tracker.update(gap_front_ms, drs_allowed, now)

    def position_advisory(self, position: int | None, now: float) -> str | None:
        return self.position_call_tracker.check(position, now)

    def note_own_pit_exit(self, position: int | None, now: float) -> None:
        self.position_call_tracker.note_own_pit_exit(position, now)

    def note_overtake(self, now: float) -> None:
        self.position_call_tracker.note_ovtk_involving_player(now)

    def leader_change(self, leader_idx: int | None, now: float) -> int | None:
        return self.leader_change_tracker.check(leader_idx, now)

    def spotter_advisory(
        self,
        candidates: list[tuple[float, str]],
        now: float,
    ) -> str | None:
        return self.spotter_tracker.update(candidates, now)

    def defense_advisory(
        self,
        battle_active: bool,
        now: float,
        last_overtaken_at: float,
    ) -> str | None:
        return self.defense_tracker.update(battle_active, now, last_overtaken_at)
