"""
core/coach_ai/analyzer.py
==========================
DriverCoach: per-lap sector analysis, consistency scoring, pace delta,
tyre advice. Deterministic, no LLM, <1 ms per lap.
"""
from __future__ import annotations

from core.coach_ai.models import DriverReport, LapData

_TYRE_ADVICE_THRESHOLD_MS = 300   # ms pace rise per lap = degrading
_PUSH_THRESHOLD_MS = 200          # ms pace drop per lap = improving
_CLIFF_MIN_TYRE_AGE = 25          # laps — beyond this, rapid rise = cliff
_WEAK_SECTOR_MIN_LOSS_MS = 100    # ignore sector differences below this
_ADVICE_MIN_LOSS_MS = 200         # show weak-sector advice only if loss exceeds this
_MIN_LAPS_SECTOR = 3              # need at least 3 laps to judge sectors
_CONSISTENCY_MAX_CV = 0.02        # 2% coefficient of variation → score 0.0

_ADVICE: dict[str, str] = {
    "cliff": "Шины на пределе — готовься к пит-стопу.",
    "save":  "Темп падает — береги шины.",
    "push":  "Темп растёт — можно давить.",
}

_SECTOR_RU = {1: "первом", 2: "втором", 3: "третьем"}


class DriverCoach:
    """Stateful per-session coach. Feed laps as they complete; read report any time."""

    def __init__(self) -> None:
        self._laps: list[LapData] = []

    def add_lap(
        self,
        lap_number: int,
        lap_time_ms: int,
        s1_ms: int,
        s2_ms: int,
        s3_ms: int,
        tyre_compound: str | None = None,
        tyre_age: int | None = None,
        tyre_wear: float | None = None,
    ) -> None:
        self._laps.append(LapData(
            lap_number=lap_number,
            lap_time_ms=lap_time_ms,
            s1_ms=s1_ms,
            s2_ms=s2_ms,
            s3_ms=s3_ms,
            tyre_compound=tyre_compound,
            tyre_age=tyre_age,
            tyre_wear=tyre_wear,
        ))

    def get_report(self) -> DriverReport:
        laps = self._laps
        weak_s, lost = _weak_sector(laps)
        cons = _consistency(laps)
        delta = _pace_delta(laps)
        tyre = _tyre_advice(laps)
        adv = _build_advice(tyre, weak_s, lost, cons)
        return DriverReport(
            weak_sector=weak_s,
            lost_time_ms=lost,
            consistency_score=cons,
            pace_delta_ms=delta,
            tyre_advice=tyre,
            lap_count=len(laps),
            advice=adv,
        )

    def get_state(self) -> dict:
        r = self.get_report()
        return {
            "weak_sector": r.weak_sector,
            "lost_time_ms": r.lost_time_ms,
            "consistency_score": round(r.consistency_score, 3),
            "pace_delta_ms": r.pace_delta_ms,
            "tyre_advice": r.tyre_advice,
            "lap_count": r.lap_count,
            "advice": r.advice,
        }


def _weak_sector(laps: list[LapData]) -> tuple[int | None, int | None]:
    valid = [l for l in laps if l.s1_ms > 0 and l.s2_ms > 0 and l.s3_ms > 0]
    if len(valid) < _MIN_LAPS_SECTOR:
        return None, None
    best_s = [
        min(l.s1_ms for l in valid),
        min(l.s2_ms for l in valid),
        min(l.s3_ms for l in valid),
    ]
    recent = valid[-5:]
    avg_s = [
        round(sum(l.s1_ms for l in recent) / len(recent)),
        round(sum(l.s2_ms for l in recent) / len(recent)),
        round(sum(l.s3_ms for l in recent) / len(recent)),
    ]
    losses = [avg_s[i] - best_s[i] for i in range(3)]
    max_loss = max(losses)
    if max_loss < _WEAK_SECTOR_MIN_LOSS_MS:
        return None, None
    sector_num = losses.index(max_loss) + 1
    return sector_num, max_loss


def _consistency(laps: list[LapData]) -> float:
    valid = [l.lap_time_ms for l in laps if l.lap_time_ms > 0]
    if len(valid) < 3:
        return 1.0
    mean = sum(valid) / len(valid)
    if mean == 0:
        return 1.0
    variance = sum((t - mean) ** 2 for t in valid) / len(valid)
    stddev = variance ** 0.5
    cv = stddev / mean
    return max(0.0, min(1.0, 1.0 - cv / _CONSISTENCY_MAX_CV))


def _pace_delta(laps: list[LapData]) -> int | None:
    valid = [l.lap_time_ms for l in laps if l.lap_time_ms > 0]
    if len(valid) < 2:
        return None
    # Compare recent 3 laps vs. early laps average — negative = improving, positive = slowing
    recent = valid[-3:]
    early = valid[: max(1, len(valid) - len(recent))]
    recent_avg = round(sum(recent) / len(recent))
    early_avg = round(sum(early) / len(early))
    return recent_avg - early_avg


def _tyre_advice(laps: list[LapData]) -> str:
    if len(laps) < 3:
        return "ok"
    recent = [l for l in laps[-3:] if l.lap_time_ms > 0]
    if len(recent) < 3:
        return "ok"
    d1 = recent[1].lap_time_ms - recent[0].lap_time_ms
    d2 = recent[2].lap_time_ms - recent[1].lap_time_ms
    thr = _TYRE_ADVICE_THRESHOLD_MS
    if d1 > thr and d2 > thr:
        age = recent[-1].tyre_age
        if age is not None and age >= _CLIFF_MIN_TYRE_AGE:
            return "cliff"
        return "save"
    if d1 < -_PUSH_THRESHOLD_MS and d2 < -_PUSH_THRESHOLD_MS:
        return "push"
    return "ok"


def _build_advice(
    tyre: str,
    weak_sector: int | None,
    lost_ms: int | None,
    consistency: float,
) -> str | None:
    if tyre in _ADVICE:
        return _ADVICE[tyre]
    if weak_sector and lost_ms and lost_ms >= _ADVICE_MIN_LOSS_MS:
        name = _SECTOR_RU.get(weak_sector, str(weak_sector))
        return f"Теряешь больше всего в {name} секторе."
    if consistency < 0.5:
        return "Темп нестабильный — работай над консистентностью."
    return None
