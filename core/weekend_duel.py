"""Fact-only player-vs-teammate comparison for a finished race weekend."""
from __future__ import annotations


_PLACEHOLDER_TEAMS = {"", "unknown", "team", "команда"}


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _identity(driver_lookup, idx: int) -> dict:
    value = driver_lookup(idx) or {}
    return value if isinstance(value, dict) else {}


def _driver_name(identity: dict) -> str | None:
    value = identity.get("name")
    if not isinstance(value, str):
        return None
    name = value.strip()
    return name or None


def _team_name(identity: dict) -> str | None:
    value = identity.get("team")
    if not isinstance(value, str):
        return None
    team = value.strip()
    if team.casefold() in _PLACEHOLDER_TEAMS or team.startswith("Команда #"):
        return None
    return team


def _row(entry: dict, identity: dict) -> dict:
    return {
        "driver": _driver_name(identity),
        "start_position": _as_int(entry.get("grid_position")),
        "finish_position": _as_int(entry.get("position")),
        "best_lap_time_ms": _as_int(entry.get("best_lap_time_ms")),
        "points": max(0, _as_int(entry.get("points"))),
    }


def _score(player: dict, teammate: dict) -> tuple[int, int]:
    player_score = 0
    teammate_score = 0
    for key, lower_is_better in (
        ("start_position", True),
        ("finish_position", True),
        ("best_lap_time_ms", True),
        ("points", False),
    ):
        left = player[key]
        right = teammate[key]
        if key != "points" and (left <= 0 or right <= 0):
            continue
        if left == right:
            continue
        player_won = left < right if lower_is_better else left > right
        if player_won:
            player_score += 1
        else:
            teammate_score += 1
    return player_score, teammate_score


def build(grid: list[dict], driver_lookup, player_idx: int) -> dict | None:
    """Return a structured teammate duel from Final Classification facts."""
    player_entry = next(
        (entry for entry in grid
         if _as_int(entry.get("vehicle_idx"), -1) == player_idx),
        None,
    )
    if player_entry is None:
        return None
    player_identity = _identity(driver_lookup, player_idx)
    team = _team_name(player_identity)
    player_name = _driver_name(player_identity)
    if team is None or player_name is None:
        return None

    teammate_entry = None
    teammate_identity = None
    for entry in grid:
        idx = _as_int(entry.get("vehicle_idx"), -1)
        if idx < 0 or idx == player_idx:
            continue
        identity = _identity(driver_lookup, idx)
        if _team_name(identity) == team and _driver_name(identity):
            teammate_entry = entry
            teammate_identity = identity
            break
    if teammate_entry is None or teammate_identity is None:
        return None

    player = _row(player_entry, player_identity)
    teammate = _row(teammate_entry, teammate_identity)
    if player["finish_position"] <= 0 or teammate["finish_position"] <= 0:
        return None
    player_score, teammate_score = _score(player, teammate)
    return {
        "team": team,
        "player": player,
        "teammate": teammate,
        "player_score": player_score,
        "teammate_score": teammate_score,
        "winner": (
            "player" if player_score > teammate_score
            else "teammate" if teammate_score > player_score
            else "draw"
        ),
    }
