"""
core/strategy_ai/analysis.py
==============================
Pace and fuel analysis — push/save/hold recommendations.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from core.strategy_ai.tyres import tyre_saving_recommended, tyre_status

PACE_SLOW_DELTA_MS = 350
PACE_FAST_DELTA_MS = -200
PUSH_GAP_FRONT_MS = 1_500
SAVE_GAP_BEHIND_MS = 2_000
FUEL_LOW_KG = 2.0
ERS_LOW_PERCENT = 12.0
ERS_OVERTAKE_MIN_PERCENT = 50.0
ERS_OVERTAKE_GAP_MS = 1200


@dataclass
class LapRecord:
    lap_number: int
    lap_time_ms: int
    tyre_compound: str | None
    tyre_age: int | None


class PaceTracker:
    """Rolling window of last N laps — used to compute pace delta and trend."""
    _WINDOW = 5
    _TREND_THRESHOLD_MS = 200

    def __init__(self) -> None:
        self._laps: deque[LapRecord] = deque(maxlen=self._WINDOW)

    def push(self, record: LapRecord) -> None:
        self._laps.append(record)

    def prev_lap_ms(self) -> int | None:
        """Second-to-last recorded lap time (ms). Used by pace_mode() in strategy.py."""
        if len(self._laps) < 2:
            return None
        return self._laps[-2].lap_time_ms

    def trend(self) -> str:
        """'rising'|'falling'|'stable' based on last 3 laps."""
        if len(self._laps) < 3:
            return "stable"
        recent = list(self._laps)[-3:]
        d1 = recent[1].lap_time_ms - recent[0].lap_time_ms
        d2 = recent[2].lap_time_ms - recent[1].lap_time_ms
        thr = self._TREND_THRESHOLD_MS
        if d1 > thr and d2 > thr:
            return "rising"    # getting slower (tyre degradation)
        if d1 < -thr and d2 < -thr:
            return "falling"   # getting faster
        return "stable"

    def has_data(self) -> bool:
        return len(self._laps) >= 2


class FuelTracker:
    """Rolling window of fuel readings — computes actual per-lap consumption."""
    _WINDOW = 4

    def __init__(self) -> None:
        self._readings: deque[tuple[int, float]] = deque(maxlen=self._WINDOW)
        # entries: (lap_number, fuel_kg)

    def push(self, lap_number: int, fuel_kg: float) -> None:
        self._readings.append((lap_number, fuel_kg))

    def actual_per_lap(self) -> float | None:
        """Average fuel consumption rate (kg/lap). None if less than 2 readings."""
        if len(self._readings) < 2:
            return None
        oldest = self._readings[0]
        newest = self._readings[-1]
        laps = newest[0] - oldest[0]
        if laps <= 0:
            return None
        return (oldest[1] - newest[1]) / laps

    def fuel_mode(self, laps_remaining: int | None) -> str:
        """'attack'|'normal'|'save' based on projected finish fuel."""
        if laps_remaining is None or laps_remaining <= 0:
            return "normal"
        rate = self.actual_per_lap()
        if rate is None:
            return "normal"
        current = self._readings[-1][1]
        projected = current - rate * laps_remaining
        if projected > 2.0:
            return "attack"
        if projected < 0.0:
            return "save"
        return "normal"


def pace_mode(
    last_lap_ms: int | None,
    prev_lap_ms: int | None,
    gap_front_ms: int | None,
    gap_behind_ms: int | None,
    tyre_age: int | None,
    tyre_wear: float | None,
    compound: str | None = None,
) -> tuple[str, float]:
    """Return (mode, confidence): push | save | hold."""
    pace_delta = None
    if last_lap_ms is not None and prev_lap_ms is not None and prev_lap_ms > 0:
        pace_delta = last_lap_ms - prev_lap_ms

    status = tyre_status(tyre_age, tyre_wear, compound)

    if (
        gap_front_ms is not None
        and gap_front_ms < PUSH_GAP_FRONT_MS
        and status in ("fresh", "worn")
        and (tyre_wear is None or tyre_wear < 55)
    ):
        conf = 0.65 + max(0, (PUSH_GAP_FRONT_MS - gap_front_ms) / PUSH_GAP_FRONT_MS * 0.25)
        return "push", min(conf, 0.9)

    if tyre_saving_recommended(tyre_age, tyre_wear, compound):
        safe_behind = gap_behind_ms is None or gap_behind_ms > SAVE_GAP_BEHIND_MS
        slowing = pace_delta is not None and pace_delta > PACE_SLOW_DELTA_MS
        if safe_behind or slowing:
            conf = 0.6
            if slowing:
                conf += 0.1
            if status == "critical":
                conf += 0.1
            return "save", min(conf, 0.88)

    if pace_delta is not None and pace_delta < PACE_FAST_DELTA_MS:
        return "hold", 0.55

    return "hold", 0.4


def fuel_save_recommended(fuel_kg: float | None, laps_remaining: int | None) -> tuple[bool, float]:
    """Low fuel — lift and save."""
    if fuel_kg is None or laps_remaining is None or laps_remaining <= 0:
        return False, 0.0
    per_lap = fuel_kg / max(laps_remaining, 1)
    if fuel_kg < FUEL_LOW_KG or (fuel_kg < 5.0 and per_lap > 1.8):
        conf = 0.7 + max(0.0, (FUEL_LOW_KG - fuel_kg) / FUEL_LOW_KG * 0.2)
        return True, min(conf, 0.9)
    return False, 0.0


def ers_save_recommended(ers_percent: float | None) -> tuple[bool, float]:
    """Заряд ERS почти исчерпан — беречь деплой."""
    if ers_percent is None or ers_percent >= ERS_LOW_PERCENT:
        return False, 0.0
    conf = 0.6 + (ERS_LOW_PERCENT - ers_percent) / ERS_LOW_PERCENT * 0.25
    return True, min(conf, 0.85)


def ers_overtake_recommended(
    ers_percent: float | None,
    ers_deploy_mode: int | None,
    gap_front_ms: int | None,
) -> tuple[bool, float]:
    """Есть заряд + близкий соперник впереди + ещё не в overtake-режиме."""
    if ers_percent is None or gap_front_ms is None:
        return False, 0.0
    if ers_deploy_mode == 2:            # уже overtake — не советуем повторно
        return False, 0.0
    if ers_percent < ERS_OVERTAKE_MIN_PERCENT or gap_front_ms > ERS_OVERTAKE_GAP_MS:
        return False, 0.0
    conf = 0.6 + (ERS_OVERTAKE_GAP_MS - gap_front_ms) / ERS_OVERTAKE_GAP_MS * 0.25
    return True, min(conf, 0.85)
