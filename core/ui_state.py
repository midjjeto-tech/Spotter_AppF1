"""Thread-safe public UI state projection."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import threading
import time

from core.overlay import build_overlay_state


def _strategy_default() -> dict:
    return {
        "action": "hold", "confidence": 0.0, "reason": "hold_pace",
        "advice": None, "mode": "HOLD", "tyre_status": "unknown",
        "current_event": None, "fuel_mode": "normal", "pace_trend": "stable",
    }


def initial_ui_state(
    *,
    llm_engine: str,
    tts_engine: str,
    voice_status: str,
    voice_available: bool,
    persona: str,
    yandex_ok: bool,
) -> dict:
    return {
        "connected": False,
        "speaking": False,
        "now_speaking": "",
        # Последняя реплика инженера ДЛЯ ЧТЕНИЯ — живёт и тогда, когда она не
        # прозвучала (авто-озвучка выключена, отвал TTS, порог важности).
        # `now_speaking` для этого не годится: он привязан к факту речи и
        # обнуляется, из-за чего игровой HUD молчал вместе с голосом.
        "radio_message": {"text": "", "voiced": False, "ts": 0.0},
        "feed": [],
        "llm_engine": llm_engine,
        "tts_engine": tts_engine,
        "voice_status": voice_status,
        "voice_available": voice_available,
        "metadata_loaded": False,
        "persona": persona,
        "telemetry": {
            "lap": "— / —", "position": "— / —", "speed": "—",
            "gear": "—", "fuel": "—",
        },
        "race": {
            "leader": "—", "leader_idx": None, "grid": [],
            "last_update": None, "safety_car_status": 0,
        },
        "race_ai": {
            "intensity": 0, "mode": "CALM", "current_event": None,
            "threat": None, "advice": None,
        },
        "track_ai": {
            "track_name": None, "corner": None, "corner_id": None,
            "corner_type": None, "phase": "straight", "sector": 1,
            "attack_zone": False, "defense_advice": "none", "advice_reason": "",
        },
        "strategy_ai": _strategy_default(),
        "coach_ai": {
            "weak_sector": None, "lost_time_ms": None,
            "consistency_score": 1.0, "pace_delta_ms": None,
            "tyre_advice": "ok", "lap_count": 0, "advice": None,
        },
        "rivals": {"rivals": [], "rival_count": 0, "nearby_count": 0},
        # Положение игрока в поле по секторам (core/sector_standing.py).
        # None до первого завершённого круга — экран прячет блок целиком.
        "field_pace": None,
        "broadcast_mode_enabled": False,
        "race_story": None,
        "voice_query": None,
        # Полное состояние радиообмена: что звучит, история, PTT-сеанс.
        # `speaking`/`now_speaking`/`radio_message`/`voice_query` СОХРАНЕНЫ
        # рядом — их читают «Обзор» и игровой оверлей, и ломать их контракт
        # ради новой секции нельзя (ТЗ §18: расширять проекцию, не заменять).
        "radio": {
            # Дефолт до первой реплики. Форма обязана совпадать с
            # `RadioSession.to_ui_dict()`: фронт типизирует одну секцию, и
            # расхождение всплыло бы только в рантайме на пустой сессии.
            "revision": 0,
            "speakers": {},
            "status": "idle", "active_message": None, "history": [],
            "ptt": {"state": "idle", "driver_text": None,
                    "engineer_text": None, "error": None, "updated_at": 0.0,
                    "answer_message_id": None},
            "repeatable": None,
        },
        "f1_benchmark": None,
        "career_memory": None,
        "damage": None,
        "final_classification": None,
        "session_type": "unknown",
        "yandex_ok": yandex_ok,
    }


@dataclass(frozen=True, slots=True)
class OverlayTelemetry:
    position: int | None
    lap_current: int | None
    lap_total: int | None
    speed_kmh: int | None
    drs_active: bool
    gap_leader_ms: int | None
    gap_front_ms: int | None
    gap_behind_ms: int | None
    tyre_compound: str | None
    tyre_age: int | None
    tyre_wear: float | None
    radar: list[dict] = field(default_factory=list)
    fuel_kg: float | None = None
    ers_percent: float | None = None
    ers_deploy_mode: int | None = None
    last_lap_ms: int | None = None
    # Driver inputs + power unit + conditions for the in-game HUD widgets.
    throttle_pct: float | None = None
    brake_pct: float | None = None
    steer: float | None = None
    rpm: int | None = None
    rev_lights_pct: int | None = None
    fuel_remaining_laps: float | None = None
    ers_harvested_pct: float | None = None
    ers_deployed_pct: float | None = None
    power_ice_kw: float | None = None
    power_mguk_kw: float | None = None
    air_temp_c: int | None = None
    track_temp_c: int | None = None
    corner_cutting_warnings: int | None = None
    drs_distance_m: int | None = None
    drs_allowed: bool = False


class UIStateProjection:
    """Own the public schema, lock, feed invariants and isolated snapshots."""

    def __init__(self, initial: dict, *, max_feed_items: int) -> None:
        self._state = deepcopy(initial)
        self._max_feed_items = max_feed_items
        self.lock = threading.RLock()

    def snapshot(self, dynamic: dict | None = None) -> dict:
        with self.lock:
            result = deepcopy(self._state)
        if dynamic:
            result.update(deepcopy(dynamic))
        return result

    def section(self, name: str) -> dict:
        with self.lock:
            return deepcopy(self._state.get(name, {}))

    def connected(self) -> bool:
        with self.lock:
            return bool(self._state["connected"])

    def broadcast_enabled(self) -> bool:
        with self.lock:
            return bool(self._state["broadcast_mode_enabled"])

    def set_connected(self, connected: bool) -> None:
        with self.lock:
            self._state["connected"] = bool(connected)

    def set_preferences(
        self,
        *,
        persona: str | None = None,
        broadcast_mode_enabled: bool | None = None,
        racefeed_enabled: bool | None = None,
    ) -> None:
        with self.lock:
            if persona is not None:
                self._state["persona"] = persona
            if broadcast_mode_enabled is not None:
                self._state["broadcast_mode_enabled"] = broadcast_mode_enabled
            if racefeed_enabled is not None:
                self._state["racefeed_enabled"] = racefeed_enabled

    def set_provider_health(self, *, healthy: bool, engine: str) -> None:
        with self.lock:
            self._state["yandex_ok"] = healthy
            self._state["llm_engine"] = engine

    def set_damage(self, damage: dict | None) -> None:
        with self.lock:
            self._state["damage"] = deepcopy(damage)

    def damage(self) -> dict | None:
        with self.lock:
            return deepcopy(self._state.get("damage"))

    def set_final_classification(self, classification: dict | None) -> None:
        with self.lock:
            self._state["final_classification"] = deepcopy(classification)

    def set_session_type(self, session_type: str) -> None:
        with self.lock:
            self._state["session_type"] = session_type

    def set_race(self, race: dict) -> None:
        with self.lock:
            projected = deepcopy(race)
            projected.setdefault(
                "safety_car_status",
                self._state.get("race", {}).get("safety_car_status", 0),
            )
            self._state["race"] = projected

    def race_grid(self) -> list[dict]:
        with self.lock:
            return deepcopy(self._state.get("race", {}).get("grid", []))

    def set_safety_car_status(self, status: int) -> None:
        with self.lock:
            self._state["race"]["safety_car_status"] = status

    def update_telemetry(
        self,
        *,
        current_lap: int | None = None,
        total_laps: int | None = None,
        position: int | None = None,
        speed: int | float | None = None,
        gear: int | str | None = None,
        fuel: int | float | None = None,
    ) -> None:
        with self.lock:
            telemetry = self._state["telemetry"]
            if current_lap is not None:
                telemetry["lap"] = f"{current_lap} / {total_laps or '—'}"
            if position is not None:
                telemetry["position"] = f"P{position} / 22"
            if speed is not None:
                telemetry["speed"] = f"{speed} км/ч"
            if gear is not None:
                telemetry["gear"] = gear
            if fuel is not None:
                telemetry["fuel"] = f"{fuel} кг"

    def set_analysis(
        self,
        *,
        race_ai: dict,
        strategy_ai: dict,
        coach_ai: dict,
        rivals: dict,
        track_ai: dict | None,
        track_name: str | None,
        field_pace: dict | None = None,
    ) -> None:
        with self.lock:
            self._state["race_ai"] = deepcopy(race_ai)
            self._state["strategy_ai"] = deepcopy(strategy_ai)
            self._state["coach_ai"] = deepcopy(coach_ai)
            self._state["rivals"] = deepcopy(rivals)
            # None означает «ещё не считали», и затирать им уже посчитанную
            # раскладку нельзя: секция обновляется раз в круг, а сама проекция
            # пересобирается на каждом снимке телеметрии.
            if field_pace is not None:
                self._state["field_pace"] = deepcopy(field_pace)
            if track_ai is not None:
                projected = deepcopy(track_ai)
                projected["track_name"] = track_name
                self._state["track_ai"] = projected
            elif track_name:
                self._state["track_ai"]["track_name"] = track_name

    def set_race_story(self, story: dict | None) -> None:
        with self.lock:
            self._state["race_story"] = deepcopy(story)

    def race_story(self) -> dict | None:
        with self.lock:
            return deepcopy(self._state.get("race_story"))

    def begin_voice_query(self) -> bool:
        with self.lock:
            current = self._state.get("voice_query")
            if current is not None and current.get("status") in {
                "listening", "recognizing", "thinking",
            }:
                return False
            self._state["voice_query"] = {
                "status": "listening", "question": None,
                "answer": None, "error": None,
            }
            return True

    def set_voice_query(self, query: dict | None) -> None:
        with self.lock:
            self._state["voice_query"] = deepcopy(query)

    def update_voice_query(self, **updates) -> None:
        with self.lock:
            query = dict(self._state.get("voice_query") or {})
            query.update(updates)
            self._state["voice_query"] = query

    def voice_query(self) -> dict | None:
        with self.lock:
            return deepcopy(self._state.get("voice_query"))

    def set_f1_benchmark(self, comparison: dict | None) -> None:
        with self.lock:
            self._state["f1_benchmark"] = deepcopy(comparison)

    def set_career_memory(self, comparison: dict | None) -> None:
        with self.lock:
            self._state["career_memory"] = deepcopy(comparison)

    def set_metadata_loaded(self, loaded: bool) -> None:
        with self.lock:
            self._state["metadata_loaded"] = bool(loaded)

    def append_feed(self, item: dict) -> None:
        with self.lock:
            self._state["feed"].insert(0, deepcopy(item))
            del self._state["feed"][self._max_feed_items:]

    def clear_feed(self) -> None:
        with self.lock:
            self._state["feed"] = []
            # «Очистить ленту» очищает и то, что висит на игровом HUD —
            # иначе стёртая реплика продолжала бы читаться поверх игры.
            self._state["radio_message"] = {"text": "", "voiced": False, "ts": 0.0}

    def set_speaking(self, phrase: str, speaking: bool) -> None:
        with self.lock:
            self._state["speaking"] = speaking
            self._state["now_speaking"] = phrase if speaking else ""

    def set_radio(self, projection: dict) -> None:
        """Обновить секцию `radio` целиком.

        Проекцию собирает `core/radio/session.py` под своим локом и отдаёт уже
        сериализуемый словарь — здесь только подстановка, чтобы два лока
        никогда не удерживались одновременно (ТЗ §18)."""
        with self.lock:
            self._state["radio"] = deepcopy(projection)

    def set_radio_message(self, text: str, *, voiced: bool,
                          now: float | None = None) -> None:
        """Показать реплику инженера в игровом HUD независимо от озвучки.

        Идея «System Message» из Grognaks Race Engineer App: если голос
        выключен или отвалился, инженер должен НАПИСАТЬ, а не исчезнуть.
        Пустой текст игнорируем — он бы стёр ещё читаемое сообщение."""
        if not text:
            return
        with self.lock:
            self._state["radio_message"] = {
                "text": text,
                "voiced": bool(voiced),
                "ts": time.time() if now is None else now,
            }

    def clear_radio_message(self) -> None:
        with self.lock:
            self._state["radio_message"] = {"text": "", "voiced": False, "ts": 0.0}

    def reset_session_view(self) -> None:
        with self.lock:
            self._state["race_story"] = None
            self._state["f1_benchmark"] = None
            self._state["career_memory"] = None
            self._state["final_classification"] = None
            self._state["strategy_ai"] = _strategy_default()
            # Раскладка по полю СЕССИОННАЯ, и обнулять её надо именно здесь.
            # `update_analysis` намеренно не затирает её значением None (секция
            # считается раз в круг, а проекция пересобирается на каждом снимке
            # телеметрии), поэтому движок, обнуливший свою `_field_pace` на
            # старте сессии, до экрана этим ничего не доносил: гонка показывала
            # квалификационные позиции по секторам как свои собственные, пока не
            # закроется первый круг.
            self._state["field_pace"] = None

    def set_strategy(self, state: dict) -> None:
        with self.lock:
            self._state["strategy_ai"] = deepcopy(state)

    def overlay(self, telemetry: OverlayTelemetry) -> dict:
        with self.lock:
            strategy = deepcopy(self._state.get("strategy_ai", {}))
            track = deepcopy(self._state.get("track_ai", {}))
            race_ai = deepcopy(self._state.get("race_ai", {}))
            race = deepcopy(self._state.get("race", {}))
        raw = {
            **asdict(telemetry),
            "tyre_status": strategy.get("tyre_status", "unknown"),
            **track,
            **{f"race_{key}": value for key, value in race_ai.items()},
            "strategy_action": strategy.get("action"),
            "strategy_confidence": strategy.get("confidence", 0.0),
            "strategy_advice": strategy.get("advice"),
            "leader": race.get("leader"),
            "grid": list(race.get("grid", [])),
        }
        return build_overlay_state(raw)
