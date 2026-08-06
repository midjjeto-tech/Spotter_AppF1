"""
core/race_ai/threat.py
=======================
Detect whether an opponent behind the player poses an attack threat.
"""

THREAT_GAP_MS = 1000   # gap below this (ms) → potential threat


def detect_threat(
    gap_behind_ms: int | None,
    drs_active: bool,
    gap_closing: bool,
    laps_remaining: int | None,
) -> tuple[bool, float]:
    """Return (is_threat, confidence).

    Confidence starts at 0.5 for any gap < 1s; increases with DRS, closing
    speed, final laps, and proximity.
    """
    if gap_behind_ms is None or gap_behind_ms <= 0 or gap_behind_ms >= THREAT_GAP_MS:
        return False, 0.0

    confidence = 0.5
    if drs_active:
        confidence += 0.15
    if gap_closing:
        confidence += 0.15
    if laps_remaining is not None and laps_remaining <= 5:
        confidence += 0.10
    if gap_behind_ms < 500:
        confidence += 0.10   # < 0.5s — very close

    return True, min(confidence, 1.0)
