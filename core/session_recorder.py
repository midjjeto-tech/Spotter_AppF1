from __future__ import annotations
from datetime import datetime
from pathlib import Path
from analytics import archive

class SessionRecorder:
    def __init__(self):
        self._laps: list[dict] = []
        self._coach_map: list[dict] = []
        self._coach_top: list[dict] = []
        self._reference_lap: dict | None = None
        self._garage: dict | None = None
        self._race_map: dict | None = None
        self._done = False

    def reset(self) -> None:
        self._laps = []
        self._coach_map = []
        self._coach_top = []
        self._reference_lap = None
        self._garage = None
        self._race_map = None
        self._done = False

    def set_race_map(self, race_map: dict | None) -> None:
        """Карта гонки: позиции всех машин по кругам. Архив должен показывать
        её и через месяц, когда живого состояния давно нет."""
        self._race_map = dict(race_map) if race_map else None

    def set_garage_report(self, report: dict | None) -> None:
        """Отчёт «Гараж»: перекос резины, сетап и советы по нему.

        Собирается движком из карты ошибок и пакета 5; рекордер только
        сохраняет — считать здесь нечего."""
        self._garage = dict(report) if report else None

    def set_reference_lap(self, lap_time_ms: int, corners: dict) -> None:
        """Метрики лучшего круга — эталон для следующих визитов на трассу.

        Ключи приводим к строкам явно: JSON всё равно это сделает, а читатель
        (`core/coach_ai/reference_store.py`) рассчитывает именно на строки и
        восстанавливает int из самой записи."""
        self._reference_lap = {
            "lap_time_ms": lap_time_ms,
            "corners": {str(cid): body for cid, body in corners.items()},
        }

    def set_coach_map(self, rows: list[dict], top_corners: list[dict]) -> None:
        """Карта ошибок пилотажа за сессию.

        Пишется целиком одним вызовом перед finalize: копилка живёт в
        core/coach_ai/corner_log.py, рекордер только сохраняет."""
        self._coach_map = list(rows)
        self._coach_top = list(top_corners)

    def on_lap_complete(self, lap_num: int, last_lap_ms: int,
                        s1_ms: int, s2_ms: int, s3_ms: int,
                        pit_lap: bool = False) -> None:
        self._laps.append({"lap": lap_num, "last_lap_ms": last_lap_ms,
                           "s1_ms": s1_ms, "s2_ms": s2_ms, "s3_ms": s3_ms,
                           "pit_lap": pit_lap})

    def laps(self) -> list[dict]:
        """Копия списка завершённых кругов (для генератора истории)."""
        return list(self._laps)

    def finalize(self, track_id: int, track_name: str, session_type: str,
                 final_position: int | None, events: list[str],
                 game_year: int = 0) -> Path | None:
        if self._done or not self._laps:
            return None
        self._done = True
        data = {"timestamp": datetime.now().isoformat(timespec="seconds"),
                "track_id": track_id, "track_name": track_name,
                "session_type": session_type,
                "game_year": game_year or None,
                "total_laps_completed": len(self._laps),
                "final_position": final_position,
                "player_laps": list(self._laps),
                "events": list(events),
                "coach_map": list(self._coach_map),
                "coach_top_corners": list(self._coach_top),
                "reference_lap": self._reference_lap,
                "garage": self._garage,
                "race_map": self._race_map}
        try:
            return archive.save_game_session(data)
        except Exception:
            return None
