"""
core/engine.py
================
Главный контроллер. Запускает два фоновых потока:

1. telemetry_thread — принимает UDP, обновляет RaceState, кладёт
   релевантные события в очередь
2. commentary_thread — берёт события из очереди, решает фразу (Commentator),
   озвучивает (Voice), обновляет shared-состояние для UI

Внешний код (UI) только читает self.state — потокобезопасно через lock.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from datetime import datetime

from core.telemetry import Telemetry
from core.race_state import RaceState
from core.packets import (
    parse_header, parse_participants, parse_event,
    parse_session, parse_lap_data, parse_player_lap,
    parse_player_telemetry, parse_player_status,
    PACKET_PARTICIPANTS, PACKET_EVENT, PACKET_SESSION,
    PACKET_LAP_DATA, PACKET_CAR_TELEMETRY, PACKET_CAR_STATUS,
    HEADER_SIZE,
)
from commentator.brain import Commentator
from commentator.ai_provider import AIProvider
from core.f1_metadata import F1Metadata
from voice.tts import Voice
from core.session_recorder import SessionRecorder
from analytics.loader import TRACK_ID_TO_GP

import config


class F1Engine:

    def __init__(self, settings: dict | None = None):
        self.settings = settings or {}
        self.race_state = RaceState()
        self.metadata = F1Metadata(config.F1_SEASON)
        self.voice = Voice()
        self.voice.set_persona(config.PERSONA)
        self.ai = AIProvider(config.ANTHROPIC_API_KEY, config.LLM_MODEL)
        self.commentator = Commentator(self.ai, config.PERSONA)

        self.event_queue: "queue.Queue[dict]" = queue.Queue()
        self.state_lock = threading.Lock()
        self._player_car_index = 255
        self._leader_idx: int | None = None
        self._positions: dict[int, int] = {}
        self.recorder = SessionRecorder()
        self._track_id: int = -1
        self._game_year: int = 0
        self._prev_lap: int = 0
        self._session_events: list[str] = []

        self.state = {
            "connected": False,
            "speaking": False,
            "now_speaking": "",
            "feed": [],
            "llm_engine": "Claude" if self.ai.available else "Шаблоны",
            "tts_engine": self.voice.engine_name,
            "voice_status": self.voice.status_message,
            "voice_available": self.voice.is_available,
            "metadata_loaded": False,
            "persona": config.PERSONA,
            "telemetry": {
                "lap": "— / —",
                "position": "— / —",
                "speed": "—",
                "gear": "—",
                "fuel": "—",
            },
            "race": {
                "leader": "—",
                "leader_idx": None,
                "grid": [],
                "last_update": None,
            },
        }

        self._race_cache_path = os.path.join(config.DATA_DIR, "race_cache.json")
        self._load_race_cache()

    # ------------------------------------------------------------
    # Race cache
    # ------------------------------------------------------------

    def _load_race_cache(self):
        try:
            if os.path.exists(self._race_cache_path):
                with open(self._race_cache_path, encoding="utf-8") as f:
                    cached = json.load(f)
                if cached.get("grid"):
                    self.state["race"] = cached
        except Exception:
            pass

    def _save_race_cache(self, data: dict):
        try:
            with open(self._race_cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass

    # ------------------------------------------------------------
    # Настройки
    # ------------------------------------------------------------

    def apply_settings(self, settings: dict):
        with self.state_lock:
            self.settings.update(settings)

        if "persona" in settings:
            self.commentator.persona = settings["persona"]
            self.voice.set_persona(settings["persona"])
            with self.state_lock:
                self.state["persona"] = settings["persona"]

        if "radio_fx" in settings:
            try:
                self.voice.set_radio_fx(bool(settings["radio_fx"]))
            except Exception:
                pass

    def _get_setting(self, key: str, default=None):
        return self.settings.get(key, default)

    def _is_paused(self) -> bool:
        return not self._get_setting("commentary_enabled", True)

    def _should_voice(self, event: dict) -> bool:
        if not self._get_setting("autovoice_enabled", True):
            return False
        if event.get("priority") == "critical":
            return self._get_setting("critical_events_enabled", True)
        return True

    def _event_involves(self, event: dict, vehicle_idx: int) -> bool:
        if vehicle_idx is None:
            return False
        involved = {
            event.get("vehicle_idx"),
            event.get("overtaking_idx"),
            event.get("being_overtaken_idx"),
        }
        return vehicle_idx in involved

    def _should_commentate(self, event: dict) -> bool:
        """Фильтр «Позиция комментатора»."""
        mode = self._get_setting("commentator_position", "auto")

        if mode == "all":
            return True

        if mode == "player":
            if self._player_car_index >= 22:
                return event.get("priority") == "critical"
            return self._event_involves(event, self._player_car_index)

        if mode == "leader":
            if self._leader_idx is None:
                return event.get("priority") == "critical"
            return self._event_involves(event, self._leader_idx)

        # auto — игрок + критические + борьба + быстрейший круг
        if event.get("priority") == "critical" or event.get("battle"):
            return True
        if event.get("event_code") == "FTLP":  # быстрейший круг всегда интересен
            return True
        if self._player_car_index < 22 and self._event_involves(event, self._player_car_index):
            return True
        player_pos = self._positions.get(self._player_car_index)
        if player_pos and event.get("event_code") == "OVTK":
            for idx in (event.get("overtaking_idx"), event.get("being_overtaken_idx")):
                other_pos = self._positions.get(idx)
                if other_pos and abs(other_pos - player_pos) <= 2:
                    return True
        return False

    # ------------------------------------------------------------
    # Запуск
    # ------------------------------------------------------------

    def start(self):
        threading.Thread(target=self._telemetry_loop, daemon=True).start()
        threading.Thread(target=self._commentary_loop, daemon=True).start()

    # ------------------------------------------------------------
    # Поток приёма телеметрии
    # ------------------------------------------------------------

    def _update_telemetry(self, header: dict, packet_id: int, data: bytes):
        player = header.get("player_car_index", 255)
        if player < 22:
            self._player_car_index = player
        gy = header.get("game_year", 0)
        if gy and gy > 0:
            self._game_year = (2000 + gy) if gy < 100 else int(gy)

        telem: dict = {}

        if packet_id == PACKET_SESSION:
            session = parse_session(data)
            if session.get("total_laps"):
                telem["total_laps"] = session["total_laps"]
            if session.get("track_id", -1) >= 0:
                self._track_id = session["track_id"]

        elif packet_id == PACKET_LAP_DATA:
            lap_info = parse_lap_data(data)
            self._positions = lap_info.get("positions", {})
            self._leader_idx = lap_info.get("leader_idx")
            positions = lap_info.get("positions", {})
            if any(v > 0 for v in positions.values()):
                grid = []
                for vehicle_idx, position in sorted(positions.items(), key=lambda item: item[1] or 999):
                    driver_info = self.race_state.driver(vehicle_idx)
                    grid.append({
                        "vehicle_idx": vehicle_idx,
                        "position": position,
                        "driver": driver_info["name"],
                        "team": driver_info["team"],
                        "color": driver_info["color"],
                        "lap": lap_info.get("laps", {}).get(vehicle_idx, 0),
                    })
                leader_name = self.race_state.driver(self._leader_idx)["name"] if self._leader_idx is not None else "—"
                race_data = {
                    "leader": leader_name,
                    "leader_idx": self._leader_idx,
                    "grid": grid,
                    "last_update": datetime.now().strftime("%H:%M:%S"),
                }
                with self.state_lock:
                    self.state["race"] = race_data
                self._save_race_cache(race_data)
            if self._player_car_index < 22:
                pl = parse_player_lap(data, self._player_car_index)
                if pl.get("current_lap"):
                    telem["current_lap"] = pl["current_lap"]
                if pl.get("position"):
                    telem["position"] = pl["position"]
                # Lap recording for analytics
                if pl:
                    cur = pl.get("current_lap", 0)
                    lms = pl.get("last_lap_ms", 0)
                    if cur > self._prev_lap and self._prev_lap > 0 and lms > 0:
                        self.recorder.on_lap_complete(
                            lap_num=self._prev_lap,
                            last_lap_ms=lms,
                            s1_ms=pl.get("s1_ms", 0),
                            s2_ms=pl.get("s2_ms", 0),
                            s3_ms=pl.get("s3_ms", 0),
                        )
                    if cur > 0:
                        self._prev_lap = cur

        elif packet_id == PACKET_CAR_TELEMETRY and self._player_car_index < 22:
            telem.update(parse_player_telemetry(data, self._player_car_index))

        elif packet_id == PACKET_CAR_STATUS and self._player_car_index < 22:
            telem.update(parse_player_status(data, self._player_car_index))

        if not telem:
            return

        with self.state_lock:
            t = self.state["telemetry"]
            total = telem.get("total_laps", getattr(self, "_total_laps", None))
            if telem.get("total_laps"):
                self._total_laps = telem["total_laps"]
                total = telem["total_laps"]
            if telem.get("current_lap") is not None:
                t["lap"] = f"{telem['current_lap']} / {total or '—'}"
            if telem.get("position") is not None:
                t["position"] = f"P{telem['position']} / 22"
            if telem.get("speed") is not None:
                t["speed"] = f"{telem['speed']} км/ч"
            if telem.get("gear") is not None:
                t["gear"] = telem["gear"]
            if telem.get("fuel") is not None:
                t["fuel"] = f"{telem['fuel']} кг"

    def _telemetry_loop(self):
        telemetry = Telemetry(config.UDP_IP, config.UDP_PORT)
        self._total_laps = None

        for data, connected in telemetry.listen():
            with self.state_lock:
                self.state["connected"] = connected

            if not connected or data is None or len(data) < HEADER_SIZE:
                continue

            header = parse_header(data)
            packet_id = header["packet_id"]

            if packet_id in (PACKET_SESSION, PACKET_LAP_DATA,
                             PACKET_CAR_TELEMETRY, PACKET_CAR_STATUS):
                self._update_telemetry(header, packet_id, data)

            if packet_id == PACKET_PARTICIPANTS:
                drivers = parse_participants(data)
                drivers = self.metadata.enrich_drivers(drivers)
                self.race_state.update_drivers(drivers)
                with self.state_lock:
                    self.state["metadata_loaded"] = self.metadata.loaded
                continue

            if packet_id != PACKET_EVENT:
                continue

            event = parse_event(data)
            if event is None:
                continue

            enriched = self.race_state.enrich(event)
            self.race_state.record_event(event)

            # Analytics: session lifecycle hooks
            code = event.get("event_code")
            if code == "SSTA":
                self.recorder.reset()
                self._session_events = []
                self._prev_lap = 0
            elif code in ("CHQF", "SEND"):
                self._session_events.append(code)
                track_name = TRACK_ID_TO_GP.get(self._track_id, ("Unknown", "Unknown"))[0]
                with self.state_lock:
                    grid = self.state.get("race", {}).get("grid", [])
                    pidx = self._player_car_index
                    pos = next((e.get("position") for e in grid
                                if e.get("vehicle_idx") == pidx), None)
                self.recorder.finalize(
                    track_id=self._track_id, track_name=track_name,
                    session_type="R", final_position=pos,
                    events=list(self._session_events),
                    game_year=self._game_year,
                )
            else:
                self._session_events.append(code)

            if self._is_paused() or not self._should_commentate(enriched):
                with self.state_lock:
                    self.state["feed"].insert(0, {
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "event_code": event["event_code"],
                        "phrase": enriched.get("description", event["event_code"]),
                        "color": enriched.get("color", "#9CA3AF"),
                        "driver": enriched.get("driver", ""),
                        "muted": True,
                    })
                    self.state["feed"] = self.state["feed"][:config.MAX_FEED_ITEMS]
                continue

            self.event_queue.put(enriched)

    # ------------------------------------------------------------
    # Поток генерации и озвучки комментариев
    # ------------------------------------------------------------

    def _commentary_loop(self):
        last_speak_time = 0.0

        while True:
            event = self.event_queue.get()

            if self._is_paused():
                continue

            min_gap = self._get_setting("min_comment_gap", config.MIN_COMMENT_GAP)

            now = time.time()
            wait = min_gap - (now - last_speak_time)
            if wait > 0 and event.get("priority") != "critical":
                time.sleep(wait)

            phrase = self.commentator.create(event)
            should_voice = self._should_voice(event)

            with self.state_lock:
                self.state["now_speaking"] = phrase if should_voice else ""
                self.state["speaking"] = should_voice
                self.state["feed"].insert(0, {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "event_code": event["event_code"],
                    "phrase": phrase,
                    "color": event.get("color", "#9CA3AF"),
                    "driver": event.get("driver", ""),
                    "muted": not should_voice,
                })
                self.state["feed"] = self.state["feed"][:config.MAX_FEED_ITEMS]

            if should_voice:
                self.voice.say(phrase)

            with self.state_lock:
                self.state["speaking"] = False
                self.state["now_speaking"] = ""

            last_speak_time = time.time()

    # ------------------------------------------------------------
    # Для UI
    # ------------------------------------------------------------

    def get_state(self) -> dict:
        with self.state_lock:
            snapshot = dict(self.state)
            snapshot["tts_engine"] = self.voice.engine_name
            snapshot["voice_status"] = self.voice.status_message
            snapshot["voice_available"] = self.voice.is_available
            snapshot["metadata_loaded"] = self.metadata.loaded
            return snapshot

    def clear_feed(self):
        with self.state_lock:
            self.state["feed"] = []

    def set_analytics_context(self, context: str | None) -> None:
        self.commentator.analytics_context = context
