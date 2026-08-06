"""
core/career_memory.py
======================
Личная память игрока по трассе — сравнение с СОБСТВЕННОЙ историей (не с реальным
F1 — это core/f1_benchmark.py, независимая фича). Источник — уже сохранённый архив
игровых сессий (analytics/archive.py, DATA_DIR/game_sessions/*.json), без сети.

Две независимые метрики (см. design spec, §2):
- best_ever — лучший круг+секторы за ВСЮ историю трассы (фиксированная цель, как
  у F1Benchmark). Питает HUD и голосовые PB-реплики.
- last_visit — данные САМОЙ ПОСЛЕДНЕЙ прошлой сессии на трассе (лучший круг +
  финишная позиция). Питает ТОЛЬКО факт Post-Race Story (прогресс с прошлого раза,
  НЕ рекорд).

Скоуп — только session_type == "race" (практика/квалификация не сравнимы по темпу).
Фильтр по track_id (надёжный числовой enum), не track_name (см. CONTEXT.md — баг
"Unknown" был из-за строкового маппинга трасс).
"""
from __future__ import annotations

import logging

from analytics import archive

_log = logging.getLogger(__name__)


def _valid_laps(laps: list[dict]) -> list[dict]:
    """Круги, которые реально были проехены (last_lap_ms > 0) — общее правило
    валидности для load()/compare()/story_facts(), единая точка изменения."""
    return [lap for lap in laps if (lap.get("last_lap_ms") or 0) > 0]


class CareerMemory:
    def __init__(self):
        self.reference: dict | None = None

    @property
    def ready(self) -> bool:
        return self.reference is not None

    def reset(self) -> None:
        self.reference = None

    def load(self, track_id: int) -> bool:
        """Просканировать архив на предмет прошлых RACE-сессий на этой трассе.
        True, если найдена хотя бы одна. best_ever — глобальный минимум круга
        среди ВСЕХ совпадающих сессий; last_visit — САМАЯ НОВАЯ (список от
        list_game_sessions() уже отсортирован новыми-сначала — первое совпадение
        и есть last_visit, без доп. сортировки)."""
        matches = [s for s in archive.list_game_sessions()
                  if s.get("track_id") == track_id and s.get("session_type") == "race"]
        if not matches:
            return False

        best_ms: int | None = None
        best_sectors: dict[int, int] | None = None
        last_visit: dict | None = None

        for summary in matches:
            data = archive.load_game_session(summary["path"])
            if data is None:
                continue
            laps = data.get("player_laps") or []
            valid = _valid_laps(laps)
            session_best = min(valid, key=lambda lap: lap["last_lap_ms"]) if valid else None
            if session_best is not None:
                if best_ms is None or session_best["last_lap_ms"] < best_ms:
                    best_ms = session_best["last_lap_ms"]
                    s1 = session_best.get("s1_ms")
                    s2 = session_best.get("s2_ms")
                    s3 = session_best.get("s3_ms")
                    best_sectors = {1: s1, 2: s2, 3: s3} if s1 and s2 and s3 else None
            if last_visit is None:   # первое совпадение в списке = самое новое
                last_visit = {
                    "best_lap_ms": session_best["last_lap_ms"] if session_best else None,
                    "final_position": data.get("final_position"),
                    "date": data.get("timestamp"),
                }

        if best_ms is None:
            return False

        self.reference = {
            "best_ever": {"lap_ms": best_ms, "sector_ms": best_sectors,
                         "date": last_visit["date"] if last_visit else None},
            "last_visit": last_visit,
        }
        return True

    def compare(self, player_laps: list[dict]) -> dict | None:
        """Гэп ЛУЧШЕГО круга текущей гонки к best_ever. Ключ "sectors" присутствует
        ВСЕГДА (словарь либо None) — тот же контракт, что у F1Benchmark.compare()."""
        if not self.ready:
            return None
        valid = _valid_laps(player_laps)
        if not valid:
            return None
        best = min(valid, key=lambda lap: lap["last_lap_ms"])
        best_ever = self.reference["best_ever"]
        return {
            "gap_ms": best["last_lap_ms"] - best_ever["lap_ms"],
            "player_best_ms": best["last_lap_ms"],
            "best_ever_ms": best_ever["lap_ms"],
            "best_ever_date": best_ever["date"],
            "sectors": self._sector_gaps(best, best_ever.get("sector_ms")),
        }

    def _sector_gaps(self, best_lap: dict, ref_sectors: dict[int, int] | None) -> dict | None:
        """Посекторный гэп ЛУЧШЕГО круга к best_ever-секторам. None — эталонных
        секторов нет ИЛИ у лучшего круга нет валидных s1/s2/s3."""
        if not ref_sectors:
            return None
        player = {1: best_lap.get("s1_ms"), 2: best_lap.get("s2_ms"), 3: best_lap.get("s3_ms")}
        if any(not player[n] for n in (1, 2, 3)):
            return None
        return {n: {"player_ms": player[n], "gap_ms": player[n] - ref_sectors[n]}
                for n in (1, 2, 3)}

    def story_facts(self, final_position: int | None, player_laps: list[dict]) -> dict:
        """Сравнение ТЕКУЩЕГО финиша с last_visit (НЕ с best_ever!) для Post-Race
        Story. Знаки: laptime_delta_ms < 0 = быстрее прошлого визита; position_delta
        > 0 = финиш выше, чем в прошлый раз."""
        last_visit = (self.reference or {}).get("last_visit")
        if (not last_visit or last_visit.get("best_lap_ms") is None
                or last_visit.get("final_position") is None):
            return {"vs_last_visit": None}
        valid = _valid_laps(player_laps)
        if not valid or final_position is None:
            return {"vs_last_visit": None}
        current_best_ms = min(lap["last_lap_ms"] for lap in valid)
        return {"vs_last_visit": {
            "laptime_delta_ms": current_best_ms - last_visit["best_lap_ms"],
            "position_delta": last_visit["final_position"] - final_position,
            "last_visit_date": last_visit["date"],
        }}

    def context_line(self, cmp: dict) -> str:
        """Строка-сверка для контекста LLM (Voice Q&A через analytics_context)."""
        gap = cmp["gap_ms"] / 1000.0
        word = "отставание" if gap >= 0 else "быстрее рекорда на"
        return (f"Твой личный рекорд трассы. Сейчас лучший круг отличается: "
                f"{word} {abs(gap):.1f}с.")

    def pb_line(self, cmp: dict) -> str:
        """Реплика на новом ЛИЧНОМ РЕКОРДЕ КРУГА ЭТОЙ СЕССИИ (зеркалит
        F1Benchmark.pb_line — фиксирует сам факт улучшения в рамках текущей гонки;
        gap_ms<=0 значит этот круг ЕЩЁ И побил исторический best_ever)."""
        gap = cmp["gap_ms"] / 1000.0
        if gap <= 0:
            return f"Новый личный рекорд трассы! Быстрее прежнего рекорда на {abs(gap):.1f} секунды!"
        return f"Лучший круг в этой гонке! Отставание {gap:.1f} секунды от личного рекорда трассы."

    def sector_pb_line(self, sector_n: int, sector_cmp: dict) -> str:
        """Реплика на новом личном рекорде СЕКТОРА этой сессии (не путать с
        F1Benchmark.sector_pb_line — эталон СВОЙ, не реальный F1)."""
        gap = sector_cmp["gap_ms"] / 1000.0
        if gap <= 0:
            return (f"Сектор {sector_n} — новый личный рекорд трассы, "
                    f"быстрее прежнего на {abs(gap):.1f} секунды!")
        return f"Сектор {sector_n} — твой лучший в этой гонке."
