"""
core/pre_race_pep_talk.py
==========================
Классификация финишной позиции ПОСЛЕДНЕЙ гонки карьеры (независимо от трассы)
в тир для пред-гоночной реплики инженера. Чистый модуль: без I/O и LLM —
данные приходят уже готовыми из analytics/archive.py::get_last_race().

Не путать с core/career_memory.py (трек-специфичная память) и
core/career_stats.py (агрегат за всю карьеру) — здесь нужна ИМЕННО последняя
гонка, любая трасса, только финишная позиция.
"""
from __future__ import annotations

PODIUM, POINTS, STRUGGLED = "podium", "points", "struggled"


def facts(last_race: dict | None) -> dict | None:
    """None, если гонок в карьере ещё не было (первая гонка) — реплика не
    звучит вообще. Иначе {"tier", "position", "track"}."""
    if last_race is None:
        return None
    pos = last_race.get("final_position")
    if pos is None or pos > 10:
        tier = STRUGGLED
    elif pos <= 3:
        tier = PODIUM
    else:
        tier = POINTS
    return {"tier": tier, "position": pos, "track": last_race.get("track_name")}
