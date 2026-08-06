"""
core/milestones.py
==================
Career/season achievement detection for RaceFeed, at race finish. Pure function
over the all-time player race history (analytics/archive.py::list_game_sessions,
newest-first, index 0 = the just-finished race) — no I/O of its own, the engine
reads the archive and passes the list in, same testable pattern as
core/career_stats.py and core/season.py.

At most ONE milestone per race (the highest-priority match) so a milestone post
stays special, never spammy.
"""
from __future__ import annotations

_RACE_MILESTONES = frozenset({10, 25, 50, 100, 150, 200})
_PODIUM_STREAK_MIN = 3
_POINTS_STREAK_MIN = 5


def _leading_streak(positions: list[int], cutoff: int) -> int:
    """How many races from newest (index 0) stayed within `cutoff` positions."""
    streak = 0
    for position in positions:
        if position <= cutoff:
            streak += 1
        else:
            break
    return streak


def detect(race_sessions: list[dict]) -> dict | None:
    """Highest-priority milestone for the just-finished race, or None.

    race_sessions: race sessions newest-first, each with a "final_position";
    index 0 is the race that just finished.
    """
    positions = [s["final_position"] for s in race_sessions
                 if s.get("final_position") is not None]
    if not positions:
        return None

    this = positions[0]
    previous = positions[1:]
    total = len(positions)
    wins = sum(1 for p in positions if p == 1)
    podiums = sum(1 for p in positions if p <= 3)
    podium_streak = _leading_streak(positions, 3)
    points_streak = _leading_streak(positions, 10)

    # "importance" is consumed by RaceFeed's Editor and filtered out of what the
    # LLM sees (prompts._INTERNAL_ONLY_KEYS) — so it can ride in the fact dict.
    if this == 1 and wins == 1:
        return {"milestone": "first_win", "importance": 92,
                "label": "Первая победа в карьере!", "position": this}
    if this <= 3 and podiums == 1:
        return {"milestone": "first_podium", "importance": 85,
                "label": "Первый подиум в карьере!", "position": this}
    if previous and this < min(previous):
        return {"milestone": "career_best", "importance": 82,
                "label": f"Лучший результат в карьере — P{this}", "position": this}
    if this <= 3 and podium_streak >= _PODIUM_STREAK_MIN:
        return {"milestone": "podium_streak", "importance": 80,
                "label": f"Серия подиумов: {podium_streak} подряд",
                "position": this, "streak": podium_streak}
    if this <= 10 and points_streak >= _POINTS_STREAK_MIN:
        return {"milestone": "points_streak", "importance": 72,
                "label": f"Серия очковых финишей: {points_streak} подряд",
                "position": this, "streak": points_streak}
    if total in _RACE_MILESTONES:
        return {"milestone": "race_milestone", "importance": 70,
                "label": f"{total}-я гонка в карьере",
                "position": this, "race_count": total}
    return None
