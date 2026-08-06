"""Fact-only 'return to this circuit' card for RaceFeed."""
from __future__ import annotations

from analytics import archive


def _valid_laps(data: dict) -> list[dict]:
    return [
        lap for lap in data.get("player_laps") or []
        if int(lap.get("last_lap_ms") or 0) > 0
    ]


def _goal(position: int | None) -> dict:
    if position == 1:
        return {"kind": "win", "label": "Защитить победу"}
    if position is not None and position <= 3:
        return {"kind": "podium", "label": "Снова взять подиум"}
    if position is not None and position <= 10:
        target = max(1, position - 2)
        return {"kind": "position", "target_position": target,
                "label": f"Поднять планку до P{target}"}
    return {"kind": "points", "target_position": 10,
            "label": "Вернуться в очки"}


def build(track_id: int | None, track_name: str = "") -> dict | None:
    if track_id is None or int(track_id) < 0:
        return None
    visits = [
        item for item in archive.list_game_sessions()
        if item.get("session_type") == "race" and item.get("track_id") == track_id
    ]
    loaded: list[tuple[dict, dict, list[dict]]] = []
    for summary in visits:
        data = archive.load_game_session(summary.get("path", ""))
        if data:
            loaded.append((summary, data, _valid_laps(data)))
    if not loaded:
        return None

    _, latest, latest_laps = loaded[0]
    all_laps = [lap for _, _, laps in loaded for lap in laps]
    last_best = min((int(lap["last_lap_ms"]) for lap in latest_laps), default=None)
    personal_best = min((int(lap["last_lap_ms"]) for lap in all_laps), default=None)
    position = int(latest.get("final_position") or 0) or None
    if position is None:
        setback = None
    elif position > 10:
        setback = {"code": "outside_points", "label": f"Последний финиш — P{position}, вне очков"}
    else:
        # The archive has the player's final position, but its event list is
        # session-wide. Do not falsely attribute a collision or penalty to the
        # player when the result itself does not prove a setback.
        setback = None
    return {
        "track_name": track_name or str(latest.get("track_name") or ""),
        "last_visit_date": latest.get("timestamp"),
        "finish_position": position,
        "last_visit_best_lap_ms": last_best,
        "personal_best_lap_ms": personal_best,
        "main_setback": setback,
        "goal": _goal(position),
        "visits": len(loaded),
    }
