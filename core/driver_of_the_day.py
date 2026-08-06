"""Deterministic simulated Driver-of-the-Day audience vote.

The score uses only authoritative Final Classification facts plus overtakes
observed by the engine during the race. The module is pure: it has no I/O,
randomness or dependency on RaceFeed.
"""
from __future__ import annotations

_FINISH_BONUS = {
    1: 15,
    2: 10,
    3: 7,
    4: 5,
    5: 4,
    6: 3,
    7: 2,
    8: 1,
}
_PLACEHOLDER_NAMES = {
    "",
    "driver",
    "unknown",
    "unknown driver",
    "гонщик",
    "пилот",
}


def _driver_name(driver_lookup, vehicle_idx: int) -> str | None:
    identity = driver_lookup(vehicle_idx) or {}
    raw = identity.get("name")
    if not isinstance(raw, str):
        return None
    name = raw.strip()
    if name.casefold() in _PLACEHOLDER_NAMES:
        return None
    return name


def _vote_percentages(scores: list[int]) -> list[int]:
    """Proportional percentages that deterministically add up to exactly 100."""
    weights = [max(1, score) for score in scores]
    total = sum(weights)
    percentages = [round(weight * 100 / total) for weight in weights]
    percentages[0] += 100 - sum(percentages)
    return percentages


def compute(
    grid: list[dict],
    driver_lookup,
    player_idx: int,
    *,
    overtakes_by_idx: dict[int, int] | None = None,
) -> dict | None:
    """Return structured Driver-of-the-Day facts for a finished race."""
    overtakes = overtakes_by_idx or {}
    lap_times = [
        int(entry.get("best_lap_time_ms") or 0)
        for entry in grid
        if int(entry.get("best_lap_time_ms") or 0) > 0
    ]
    fastest_lap_ms = min(lap_times) if lap_times else None

    scored: list[dict] = []
    for entry in grid:
        try:
            position = int(entry.get("position") or 0)
        except (TypeError, ValueError):
            position = 0
        if position <= 0:
            continue

        idx = entry.get("vehicle_idx")
        if not isinstance(idx, int):
            continue
        name = _driver_name(driver_lookup, idx)
        if name is None:
            continue

        try:
            grid_position = int(entry.get("grid_position") or 0)
        except (TypeError, ValueError):
            grid_position = 0
        gained = grid_position - position if grid_position > 0 else 0
        overtake_count = max(0, int(overtakes.get(idx, 0) or 0))
        penalties = max(0, int(entry.get("num_penalties") or 0))
        lap_ms = int(entry.get("best_lap_time_ms") or 0)
        fastest_lap = bool(fastest_lap_ms and lap_ms == fastest_lap_ms)

        score = (
            max(0, gained) * 4
            + overtake_count * 3
            + _FINISH_BONUS.get(position, 0)
            + (4 if fastest_lap else 0)
            - penalties * 2
            - max(0, -gained)
        )
        scored.append({
            "driver": name,
            "vehicle_idx": idx,
            "score": max(1, score),
            "positions_gained": gained,
            "overtakes": overtake_count,
            "position": position,
            "fastest_lap": fastest_lap,
            "penalties": penalties,
            "is_player": idx == player_idx,
        })

    if not scored:
        return None

    scored.sort(key=lambda candidate: (-candidate["score"], candidate["position"]))
    top = scored[:3]
    percentages = _vote_percentages([candidate["score"] for candidate in top])
    for candidate, percentage in zip(top, percentages):
        candidate["vote_pct"] = percentage

    winner = top[0]
    facts = {
        "dotd_driver": winner["driver"],
        "dotd_pct": winner["vote_pct"],
        "dotd_gained": winner["positions_gained"],
        "dotd_overtakes": winner["overtakes"],
        "player_is_dotd": winner["is_player"],
        "dotd_participants": [candidate["driver"] for candidate in top],
        "dotd_candidates": top,
    }
    if len(top) > 1:
        facts["dotd_second_driver"] = top[1]["driver"]
        facts["dotd_second_pct"] = top[1]["vote_pct"]
    return facts
