"""core/track_ai/track_manager.py — TrackManager orchestrator."""
from __future__ import annotations

from core.race_ai.sectors import get_sector
from core.track_ai.corners import get_corner, get_phase
from core.track_ai.models import Corner, TrackContext, TrackInfo
from core.track_ai.racing_line import get_advice
from core.track_ai.zones import is_attack_zone


class TrackManager:
    """Resolves lap distance → TrackContext for the currently active track."""

    def __init__(self, track: TrackInfo):
        self._track = track

    @property
    def track_name(self) -> str:
        return self._track.name

    def corners(self) -> list[Corner]:
        """Разметка активной трассы. Нужна коучу, чтобы называть повороты по
        имени, не таща к себе загрузчик треков."""
        return list(self._track.corners)

    def resolve(
        self,
        lap_dist_m: float,
        drs_active: bool = False,
        threat_active: bool = False,
    ) -> TrackContext | None:
        """Compute TrackContext from raw lap distance (metres).

        Returns None if lap_dist_m is invalid or track has no length.
        """
        if lap_dist_m < 0 or self._track.length_m <= 0:
            return None

        lap_pct = (lap_dist_m % self._track.length_m) / self._track.length_m
        corner = get_corner(lap_pct, self._track.corners)
        phase  = get_phase(lap_pct, corner) if corner else "straight"
        sector = get_sector(lap_pct)
        attack = is_attack_zone(corner, phase, drs_active)
        advice = get_advice(corner, threat_active)

        return TrackContext(
            corner=corner,
            phase=phase,
            sector=sector,
            attack_zone=attack,
            advice=advice["advice"],
            advice_reason=advice["advice_reason"],
        )
