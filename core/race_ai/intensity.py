"""
core/race_ai/intensity.py
==========================
Race intensity score (0–100) and named mode.
"""


def calculate_intensity(
    gap_behind_ms: int | None,
    drs_active: bool,
    position_battle: bool,
    laps_remaining: int | None,
    total_laps: int | None,
    fastest_lap_set: bool = False,
) -> int:
    """Score race intensity 0–100.

    +20 close gap (< 1s)
    +20 DRS active
    +20 active position battle (sustained proximity)
    +20 final laps (≤ 10% of race remaining, minimum 3 laps)
    +10 fastest lap just set
    Clamped to [0, 100].
    """
    score = 0
    if gap_behind_ms is not None and 0 < gap_behind_ms < 1000:
        score += 20
    if drs_active:
        score += 20
    if position_battle:
        score += 20
    if (laps_remaining is not None and total_laps is not None and total_laps > 0
            and laps_remaining <= max(3, total_laps // 10)):
        score += 20
    if fastest_lap_set:
        score += 10
    return min(score, 100)


def get_mode(intensity: int) -> str:
    """Map 0–100 intensity to named mode."""
    if intensity < 25:
        return "CALM"
    if intensity < 60:
        return "RACE"
    if intensity < 85:
        return "BATTLE"
    return "CLIMAX"
