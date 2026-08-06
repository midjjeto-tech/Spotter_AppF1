"""
core/career_stats.py
=====================
Карьерная статистика игрока — агрегат по ВСЕМ гоночным сессиям в архиве,
независимо от трассы (в отличие от core/career_memory.py, который сравнивает
только визиты на ОДНУ И ТУ ЖЕ трассу). Источник — analytics/archive.py
(DATA_DIR/game_sessions/*.json), без сети.

Чистая функция, не класс: в отличие от CareerMemory (live-обновление каждый
круг во время гонки), карьерная статистика считается ОДИН РАЗ, в момент
финиша — состояние между вызовами не нужно.
"""
from __future__ import annotations

from analytics import archive


def compute_career_stats() -> dict | None:
    """Агрегат по всем гонкам с известным final_position. None, если таких
    гонок нет (архив пуст / ни одна гонка не имеет зафиксированного
    результата) — тот же паттерн, что CareerMemory.load() -> False."""
    races = [s for s in archive.list_game_sessions()
             if s.get("session_type") == "race" and s.get("final_position") is not None]
    if not races:
        return None
    positions = [s["final_position"] for s in races]
    total = len(positions)
    return {
        "total_races": total,
        "wins": sum(1 for p in positions if p == 1),
        "podiums": sum(1 for p in positions if p <= 3),
        "avg_position": sum(positions) / total,
    }


def context_line(stats: dict) -> str:
    """Строка-сверка для контекста LLM (Voice Q&A через analytics_context,
    по аналогии с core/career_memory.py::context_line)."""
    return (f"Карьерная статистика игрока: {stats['total_races']} гонок, "
            f"{stats['wins']} побед, {stats['podiums']} подиумов, "
            f"средняя финишная позиция {stats['avg_position']:.1f}.")
