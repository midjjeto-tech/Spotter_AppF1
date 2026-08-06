from __future__ import annotations
from datetime import datetime
from pathlib import Path
from analytics import archive

class SessionRecorder:
    def __init__(self):
        self._laps: list[dict] = []
        self._done = False

    def reset(self) -> None:
        self._laps = []
        self._done = False

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
                "events": list(events)}
        try:
            return archive.save_game_session(data)
        except Exception:
            return None
