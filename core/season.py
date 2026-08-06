"""
core/season.py
==============
Sliding-window championship over the season store (analytics/archive.py::
list_season_results). Pure functions, no state, no network — computed on demand,
same pattern as core/career_stats.py. "Season" = the last SEASON_WINDOW races
(a form championship; the telemetry has no round/season id — see design doc).
"""
from __future__ import annotations

from analytics import archive

SEASON_WINDOW = 22

_PLACEHOLDER_DRIVER_NAMES = frozenset({
    "driver",
    "unknown",
    "unknown driver",
    "гонщик",
    "пилот",
    "неизвестный гонщик",
})
_PLACEHOLDER_DRIVER_PREFIXES = ("driver #", "гонщик #", "пилот #")


def _resolved_driver_name(value) -> str | None:
    """Return a real driver name, rejecting identity-resolution fallbacks."""
    if not isinstance(value, str):
        return None
    name = value.strip()
    folded = name.casefold()
    if (
        not name
        or folded in _PLACEHOLDER_DRIVER_NAMES
        or folded.startswith(_PLACEHOLDER_DRIVER_PREFIXES)
    ):
        return None
    return name


def _valid_race_classifications(window: int) -> list[list[dict]]:
    """Newest valid race classifications; corrupt placeholders use no slot."""
    if window <= 0:
        return []
    classifications: list[list[dict]] = []
    for race in archive.list_season_results(limit=None):
        valid = [
            entry
            for entry in race.get("classification", [])
            if _resolved_driver_name(entry.get("driver")) is not None
        ]
        if not valid:
            continue
        classifications.append(valid)
        if len(classifications) >= window:
            break
    return classifications


def build_classification(grid: list[dict], driver_lookup, player_idx: int) -> list[dict]:
    """Turn raw final-classification entries into season-store rows.

    grid: entries with position/points/vehicle_idx (parse_final_classification_grid).
    driver_lookup: callable vehicle_idx -> {"name","team","color"} (race_state.driver).
    """
    rows: list[dict] = []
    for entry in grid:
        idx = entry.get("vehicle_idx")
        ident = driver_lookup(idx)
        driver = _resolved_driver_name(ident.get("name"))
        if driver is None:
            continue
        rows.append({
            "position": entry.get("position"),
            "points": int(entry.get("points") or 0),
            "driver": driver,
            "team": ident.get("team"),
            "color": ident.get("color"),
            "is_player": idx == player_idx,
        })
    return rows


def compute_standings(window: int = SEASON_WINDOW) -> dict | None:
    """Championship table over the last `window` recorded races, newest-first.
    None if the season store is empty (no classified race yet)."""
    classifications = _valid_race_classifications(window)
    if not classifications:
        return None
    totals: dict[str, dict] = {}
    for classification in classifications:
        # newest-first: first sighting of a driver = latest team
        for entry in classification:
            driver = _resolved_driver_name(entry.get("driver"))
            if driver is None:
                continue
            row = totals.setdefault(driver, {
                "driver": driver, "points": 0, "wins": 0,
                "team": entry.get("team"), "color": entry.get("color"),
                "is_player": False,
            })
            row["points"] += int(entry.get("points") or 0)
            if entry.get("position") == 1:
                row["wins"] += 1
            if entry.get("is_player"):
                row["is_player"] = True
    standings = sorted(
        totals.values(), key=lambda r: (-r["points"], -r["wins"], r["driver"])
    )
    for position, row in enumerate(standings, start=1):
        row["position"] = position
    return {"standings": standings, "races_counted": len(classifications)}


def best_result(window: int = SEASON_WINDOW) -> int | None:
    """The player's best (lowest) finishing position across the window, or None
    if the player isn't classified in any recorded race."""
    positions = [
        entry["position"]
        for classification in _valid_race_classifications(window)
        for entry in classification
        if entry.get("is_player") and entry.get("position") is not None
    ]
    return min(positions) if positions else None


def pick_rival(standings: list[dict]) -> dict | None:
    """Driver adjacent to the player: the one directly ahead by points, or
    directly behind if the player leads. None if the player isn't in the table
    or is the only entry."""
    idx = next((i for i, r in enumerate(standings) if r.get("is_player")), None)
    if idx is None or len(standings) < 2:
        return None
    return standings[1] if idx == 0 else standings[idx - 1]


def race_head_to_head(classification: list[dict], rival_driver: str) -> dict | None:
    """Player-vs-rival result in a single race's classification, for the
    championship post's callout ("снова впереди тебя" / "ты ответил сопернику").
    None if either driver isn't classified in this race."""
    player = next((e for e in classification if e.get("is_player")), None)
    rival = next((e for e in classification if e.get("driver") == rival_driver), None)
    if player is None or rival is None:
        return None
    if player.get("position") is None or rival.get("position") is None:
        return None
    return {
        "rival_race_position": rival["position"],
        "player_race_position": player["position"],
        "rival_ahead": rival["position"] < player["position"],
    }


def _position(entry: dict | None) -> int | None:
    if entry is None:
        return None
    try:
        value = int(entry.get("position"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _player_entry(classification: list[dict]) -> dict | None:
    return next((entry for entry in classification if entry.get("is_player")), None)


def _race_count(value: int) -> str:
    tail = abs(value) % 100
    last = tail % 10
    if tail > 10 and tail < 20:
        word = "гонок"
    elif last == 1:
        word = "гонка"
    elif 2 <= last <= 4:
        word = "гонки"
    else:
        word = "гонок"
    return f"{value} {word}"


def season_storylines(rival_driver: str | None, window: int = SEASON_WINDOW) -> list[dict]:
    """Up to three continuing, fact-bound arcs from recent race results."""
    classifications = _valid_race_classifications(window)
    if not classifications:
        return []
    storylines: list[dict] = []

    if rival_driver:
        meetings: list[tuple[int, int]] = []
        for classification in classifications[:5]:
            player_pos = _position(_player_entry(classification))
            rival_pos = _position(next(
                (entry for entry in classification
                 if entry.get("driver") == rival_driver),
                None,
            ))
            if player_pos is not None and rival_pos is not None:
                meetings.append((player_pos, rival_pos))
        if meetings:
            player_wins = sum(player < rival for player, rival in meetings)
            rival_wins = sum(rival < player for player, rival in meetings)
            count = len(meetings)
            storylines.append({
                "id": "rivalry",
                "title": f"Дуэль с {rival_driver}",
                "value": f"{player_wins}:{rival_wins}",
                "detail": f"Очная серия: {_race_count(count)}",
                "tone": "amber" if player_wins >= rival_wins else "red",
            })

    podium_streak = 0
    for classification in classifications:
        position = _position(_player_entry(classification))
        if position is not None and position <= 3:
            podium_streak += 1
        else:
            break
    points_streak = 0
    for classification in classifications:
        player = _player_entry(classification)
        if player is not None and int(player.get("points") or 0) > 0:
            points_streak += 1
        else:
            break
    if podium_streak >= 2:
        storylines.append({
            "id": "podium_streak",
            "title": "Серия подиумов",
            "value": f"{podium_streak} подряд",
            "detail": "Продолжается после этого этапа",
            "tone": "violet",
        })

    if len(classifications) >= 2:
        current = _position(_player_entry(classifications[0]))
        previous = _position(_player_entry(classifications[1]))
        if current is not None and previous is not None and previous - current >= 5:
            storylines.append({
                "id": "comeback",
                "title": "Ответ после прошлого этапа",
                "value": f"P{previous} → P{current}",
                "detail": f"Прогресс на {previous - current} позиций",
                "tone": "green",
            })
    if len(storylines) < 3 and points_streak >= 3:
        storylines.append({
            "id": "points_streak",
            "title": "В очках без перерыва",
            "value": _race_count(points_streak),
            "detail": "Серия продолжается",
            "tone": "sky",
        })
    return storylines[:3]


def return_hook(summary: dict, storylines: list[dict]) -> dict | None:
    """One unresolved season stake shown between race weekends."""
    rival = str(summary.get("rival") or "").strip()
    gap = summary.get("gap_to_rival")
    if not rival or not isinstance(gap, (int, float)):
        return None
    player_position = int(summary.get("player_position") or 0)
    rival_position = int(summary.get("rival_position") or 0)
    if int(gap) == 0:
        title = f"С {rival} — поровну"
        detail = "Следующая гонка решит, кто перехватит инициативу."
    elif player_position and rival_position and player_position < rival_position:
        title = f"Удержать преимущество над {rival}"
        detail = f"Запас в чемпионате — {int(gap)} очков."
    else:
        title = f"До {rival} — {int(gap)} очков"
        detail = "Следующая гонка продолжит эту дуэль."
    podium = next(
        (row for row in storylines if row.get("id") == "podium_streak"), None
    )
    if podium:
        detail += f" На кону серия: {podium['value']}."
    return {"title": title, "detail": detail}


def season_summary(window: int = SEASON_WINDOW,
                   race_points: int | None = None) -> dict | None:
    """Fact set for the CHAMPIONSHIP RaceFeed event. None when there's no
    season store yet or the player isn't classified in the window."""
    result = compute_standings(window)
    if result is None:
        return None
    standings = result["standings"]
    player = next((r for r in standings if r.get("is_player")), None)
    if player is None:
        return None
    summary = {
        "player_points": player["points"],
        "player_position": player["position"],
        "races_counted": result["races_counted"],
    }
    if race_points is not None:
        summary["race_points"] = race_points
    rival = pick_rival(standings)
    if rival is not None:
        summary["rival"] = rival["driver"]
        summary["rival_position"] = rival["position"]
        summary["rival_points"] = rival["points"]
        summary["gap_to_rival"] = abs(player["points"] - rival["points"])
    storylines = season_storylines(summary.get("rival"), window)
    if storylines:
        summary["storylines"] = storylines
    hook = return_hook(summary, storylines)
    if hook:
        summary["return_hook"] = hook
    return summary
