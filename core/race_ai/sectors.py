"""
core/race_ai/sectors.py
========================
Determine race sector (1, 2, 3) from lap distance percentage.
"""


def get_sector(lap_distance_pct: float) -> int:
    """Return sector number (1, 2, or 3) for a given lap completion fraction.

    Boundaries: 0–33% → S1, 33–67% → S2, 67–100% → S3.
    Values outside [0, 1] clamp gracefully.
    """
    if lap_distance_pct < 0.33:
        return 1
    if lap_distance_pct < 0.67:
        return 2
    return 3
