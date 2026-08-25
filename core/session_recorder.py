from __future__ import annotations
from datetime import datetime
import math
from pathlib import Path
import time
from analytics import archive


_EVENT_TRACE_LIMIT = 4096
_EVENT_PRESENTATION_FIELDS = {
    "event_code", "phrase", "priority", "color", "speaker", "channel",
    "description", "driver", "muted", "bypass_speak_threshold", "radio",
}


def _json_safe(value):
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)

class SessionRecorder:
    def __init__(self):
        self._laps: list[dict] = []
        self._coach_map: list[dict] = []
        self._coach_top: list[dict] = []
        self._reference_lap: dict | None = None
        self._garage: dict | None = None
        self._lesson: dict | None = None
        self._lap_metrics: list[dict] = []
        self._race_map: dict | None = None
        self._event_trace: list[dict] = []
        self._event_trace_dropped = 0
        self._trace_started_at = time.monotonic()
        self._done = False

    def reset(self, *, trace_started_at: float | None = None) -> None:
        self._laps = []
        self._coach_map = []
        self._coach_top = []
        self._reference_lap = None
        self._garage = None
        self._lesson = None
        self._lap_metrics = []
        self._race_map = None
        self._event_trace = []
        self._event_trace_dropped = 0
        self._trace_started_at = (
            time.monotonic() if trace_started_at is None else trace_started_at)
        self._done = False

    def record_event(
        self,
        event: dict,
        *,
        observed_at_s: float | None = None,
        source_session_id: int | str | None = None,
        source_event_id: int | str | None = None,
        source_frame_id: int | None = None,
        source_time_s: float | None = None,
    ) -> None:
        """Keep a compact, source-aware event timeline for post-race diagnosis."""
        if len(self._event_trace) >= _EVENT_TRACE_LIMIT:
            self._event_trace_dropped += 1
            return
        observed_at = time.monotonic() if observed_at_s is None else observed_at_s
        details = {
            str(key): _json_safe(value)
            for key, value in event.items()
            if key not in _EVENT_PRESENTATION_FIELDS
        }
        self._event_trace.append({
            "event_code": str(event.get("event_code") or ""),
            "offset_s": round(max(0.0, observed_at - self._trace_started_at), 3),
            "source_time_s": source_time_s,
            "source_session_id": source_session_id,
            "source_event_id": source_event_id,
            "source_frame_id": source_frame_id,
            "details": details,
        })

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

    def set_coach_lap_metrics(self, rows: list[dict] | None) -> None:
        """Замеры поворотов ПО КРУГАМ — вход, из которого посчитан урок.

        Урок и карта ошибок рядом — это выводы; здесь лежат числа, на которых
        они стоят. Без них «битый замер» после заезда не диагностируется: разбор
        08-11 упёрся ровно в это — потенциал круга обещал 11,4 с при 0,93 с
        найденных потерь, а проверить, какой поворот и на каком круге дал
        выброс, было нечем."""
        self._lap_metrics = list(rows or [])

    def set_coach_lesson(self, lesson: dict | None) -> None:
        """Разбор сессии: потенциал круга, куда ушло время, что дальше.

        Уезжает в файл заезда не только ради экрана «Итоги»: следующий визит на
        эту трассу читает его отсюда (`core/coach_ai/reference_store.py`) и
        показывает пилоту, сдвинулось ли то, над чем работали в прошлый раз.
        Без этого каждая сессия начинается с чистого листа."""
        self._lesson = dict(lesson) if lesson else None

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
        data = {"schema_version": 2,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "track_id": track_id, "track_name": track_name,
                "session_type": session_type,
                "game_year": game_year or None,
                "total_laps_completed": len(self._laps),
                "final_position": final_position,
                "player_laps": list(self._laps),
                "events": list(events),
                "event_trace": list(self._event_trace),
                "event_trace_dropped": self._event_trace_dropped,
                "coach_map": list(self._coach_map),
                "coach_top_corners": list(self._coach_top),
                "reference_lap": self._reference_lap,
                "garage": self._garage,
                "coach_lesson": self._lesson,
                "coach_lap_metrics": list(self._lap_metrics),
                "race_map": self._race_map}
        try:
            return archive.save_game_session(data)
        except Exception:
            return None
