"""Fact-only post-race recap for RaceFeed.

The compact card is intentionally deterministic: every number comes from the
authoritative Final Classification or from overtakes observed during the race.
"""
from __future__ import annotations


_PLACEHOLDER_NAMES = {"", "driver", "unknown", "unknown driver", "гонщик", "пилот"}


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _driver_name(driver_lookup, vehicle_idx: int) -> str | None:
    identity = driver_lookup(vehicle_idx) or {}
    raw = identity.get("name")
    if not isinstance(raw, str):
        return None
    name = raw.strip()
    return None if name.casefold() in _PLACEHOLDER_NAMES else name


def build(
    grid: list[dict],
    driver_lookup,
    player_idx: int,
    *,
    overtakes_by_idx: dict[int, int] | None = None,
) -> dict | None:
    """Return flat narrative facts plus the structured UI recap payload."""
    entry = next(
        (row for row in grid if _as_int(row.get("vehicle_idx"), -1) == player_idx),
        None,
    )
    if entry is None:
        return None
    driver = _driver_name(driver_lookup, player_idx)
    finish_position = _as_int(entry.get("position"))
    if driver is None or finish_position <= 0:
        return None

    grid_position = _as_int(entry.get("grid_position"))
    positions_gained = grid_position - finish_position if grid_position > 0 else 0
    overtakes = max(0, _as_int((overtakes_by_idx or {}).get(player_idx)))
    best_lap_ms = _as_int(entry.get("best_lap_time_ms"))
    valid_laps = [
        _as_int(row.get("best_lap_time_ms"))
        for row in grid
        if _as_int(row.get("best_lap_time_ms")) > 0
    ]
    recap = {
        "driver": driver,
        "finish_position": finish_position,
        "grid_position": grid_position,
        "positions_gained": positions_gained,
        "overtakes": overtakes,
        "points": max(0, _as_int(entry.get("points"))),
        "pit_stops": max(0, _as_int(entry.get("num_pit_stops"))),
        "fastest_lap": bool(valid_laps and best_lap_ms == min(valid_laps)),
        "penalties": max(0, _as_int(entry.get("num_penalties"))),
    }
    return {
        "race_recap": recap,
        **recap,
    }
