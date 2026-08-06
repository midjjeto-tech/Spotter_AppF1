"""
core/race_story.py
==================
Накопитель фактов гонки для пост-гоночной истории (Post-Race Story Mode).

RaceTimeline — скользящее окно (windowed), для полного рассказа не годится.
Здесь копим за ВСЮ гонку только то, из чего строится нарратив: старт-позиция,
ключевые события игрока (обгоны/штрафы/сходы/быстрейший круг). На финише facts()
сводит всё в плоский факт-блок для commentator/story.py.

Чистый модуль: без I/O, сети и LLM. Вовлечённость игрока определяет вызывающий
(engine): сюда передаются уже отфильтрованные, разрешённые имена.
"""
from __future__ import annotations

# События, попадающие в историю (передаются engine'ом уже как игрок-релевантные).
_NOTABLE = {"OVTK", "PENA", "RTMT", "FTLP"}
_MAX_EVENTS = 12


class RaceStoryCollector:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Очистить (вызывать на SSTA)."""
        self._start_position: int | None = None
        self._events: list[dict] = []

    def note_start_position(self, position: int | None) -> None:
        """Зафиксировать стартовую позицию (только первая известная)."""
        if self._start_position is None and position:
            self._start_position = position

    def note_event(self, code: str, lap: int | None,
                   driver: str | None = None, target: str | None = None) -> None:
        """Запомнить значимое игрок-событие. Незначимые коды игнорируются."""
        if code not in _NOTABLE:
            return
        if len(self._events) >= _MAX_EVENTS:
            self._events.pop(len(self._events) // 2)   # выкидываем из середины
        self._events.append({"code": code, "lap": lap,
                             "driver": driver, "target": target})

    def facts(self, *, final_position: int | None, laps: list[dict],
              coach_state: dict | None = None, leader_name: str | None = None,
              total_laps: int | None = None, track: str | None = None,
              weak_sector_vs_f1: int | None = None,
              vs_last_visit: dict | None = None,
              career_stats: dict | None = None,
              teammate_result: str | None = None,
              session_type: str = "race") -> dict:
        """Свести накопленное + финальные данные в плоский факт-блок для LLM.

        session_type гейтит гоночно-специфичные факты: "positions_gained"
        (старт vs финиш) и "career_stats"/"vs_last_visit" (кросс-гоночные
        агрегаты, race-only уже на уровне career_memory.py/career_stats.py) не
        имеют смысла для квалификации/практики — читались бы как отсебятина.
        """
        best_ms: int | None = None
        best_lap: int | None = None
        for lp in laps:
            ms = lp.get("last_lap_ms") or 0
            if ms > 0 and (best_ms is None or ms < best_ms):
                best_ms, best_lap = ms, lp.get("lap")

        overtakes = [{"lap": e["lap"], "target": e["target"]}
                     for e in self._events if e["code"] == "OVTK" and e.get("target")]
        incidents = [{"lap": e["lap"], "code": e["code"], "driver": e.get("driver")}
                     for e in self._events if e["code"] in ("PENA", "RTMT")]
        coach = coach_state or {}

        is_race = session_type == "race"
        is_practice = session_type == "practice"
        start_position = self._start_position if is_race else None
        gained = (self._start_position - final_position
                  if is_race and self._start_position and final_position else None)
        reported_final_position = None if is_practice else final_position

        return {
            "track": track,
            "start_position": start_position,
            "final_position": reported_final_position,
            "positions_gained": gained,
            "total_laps": total_laps,
            "best_lap_ms": best_ms,
            "best_lap_number": best_lap,
            "overtakes": overtakes,
            "incidents": incidents,
            "fastest_lap_flag": any(e["code"] == "FTLP" for e in self._events),
            "weak_sector": coach.get("weak_sector"),
            "weak_sector_vs_f1": weak_sector_vs_f1,
            "vs_last_visit": vs_last_visit if is_race else None,
            "career_stats": career_stats if is_race else None,
            # Дуэль с напарником — гоночный факт: в практике позиции ничего не
            # значат, в квалификации сравнение уже даёт стартовая решётка.
            "teammate_result": teammate_result if is_race else None,
            "consistency": coach.get("consistency_score"),
            "leader": leader_name,
            "session_type": session_type,
        }
