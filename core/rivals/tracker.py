"""
core/rivals/tracker.py
=======================
RivalTracker: per-tick rival position monitoring, pit detection,
style classification. Deterministic, no LLM, <0.5 ms per tick.
"""
from __future__ import annotations

from collections import deque
from statistics import mean, stdev

from core.rivals.models import RivalProfile

_NEARBY_WINDOW = 3          # positions ±N = nearby
_POSITION_LOSS_THRESHOLD = 8   # was _PIT_DROP_THRESHOLD — big position loss without
                                # a real pit_status is now a "mistake" signal, not a pit
_MIN_HISTORY_STYLE = 4      # need at least N ticks for style judgment
_STYLE_VARIANCE_HIGH = 4.0  # std dev threshold for "aggressive"
_STYLE_TREND_THRESHOLD = 2  # avg delta > this magnitude = charging/fading
_MISTAKE_RECENCY_WINDOW = 60.0   # seconds — how long a detected mistake stays "recent"


class RivalTracker:
    """Stateful per-session rival tracker. Call update() each telemetry tick."""

    def __init__(self) -> None:
        self._profiles: dict[int, RivalProfile] = {}
        self._player_position: int = 0

    def update(self, grid: list[dict], player_vehicle_idx: int, now: float = 0.0) -> None:
        player_pos = 0
        for entry in grid:
            if entry["vehicle_idx"] == player_vehicle_idx:
                player_pos = entry["position"]
                break
        self._player_position = player_pos

        for entry in grid:
            vi = entry["vehicle_idx"]
            if vi == player_vehicle_idx:
                continue
            pos = entry.get("position", 0)
            lap = entry.get("lap", 0)
            pit_status = entry.get("pit_status", 0)
            driver = entry.get("driver", f"Car #{vi}")
            team = entry.get("team", "—")

            if vi not in self._profiles:
                self._profiles[vi] = RivalProfile(
                    vehicle_idx=vi,
                    driver=driver,
                    team=team,
                    pit_count=0,
                    lap_count=lap,
                    current_position=pos,
                    style="consistent",
                    nearby=False,
                )

            profile = self._profiles[vi]
            if driver and driver != f"Car #{vi}":
                profile.driver = driver
                profile.team = team

            prev_pos = profile.current_position
            prev_pit_status = profile.pit_status
            profile.current_position = pos
            profile.pit_status = pit_status
            profile.lap_count = lap
            profile.nearby = player_pos > 0 and abs(pos - player_pos) <= _NEARBY_WINDOW

            if pos > 0:
                profile.position_history.append(pos)

            entered_pit = prev_pit_status == 0 and pit_status != 0
            if entered_pit:
                profile.pit_count += 1
            elif (prev_pos > 0 and pos > 0
                  and pos - prev_pos >= _POSITION_LOSS_THRESHOLD
                  and pit_status == 0):
                profile.mistake_at = now

            profile.style = _classify_style(profile.position_history)

    def get_style(self, vehicle_idx: int | None) -> str | None:
        """Стиль соперника по vehicle_idx, если он уже профилирован (см. update()).
        None — игрок (RivalTracker профилирует всех, КРОМЕ игрока, по конструкции
        update()) или машина ещё не встречалась в этой сессии."""
        if vehicle_idx is None:
            return None
        profile = self._profiles.get(vehicle_idx)
        return profile.style if profile else None

    def update_tyre(self, vehicle_idx: int, age: int) -> None:
        """Возраст резины соперника — приходит с CarStatus-тиков, независимо от
        update() (другой тип UDP-пакета). Молча игнорирует машину, ещё не
        встреченную через update() (LapData) — профиль появится на следующем
        тике, ничего страшного."""
        profile = self._profiles.get(vehicle_idx)
        if profile:
            profile.tyre_age = age

    def get_tyre_age(self, vehicle_idx: int | None) -> int | None:
        if vehicle_idx is None:
            return None
        profile = self._profiles.get(vehicle_idx)
        return profile.tyre_age if profile else None

    def update_damage(self, vehicle_idx: int, body_damage: float,
                       threshold: float, now: float) -> None:
        """body_damage — max(wing, floor, gearbox, engine) severity 0-100 для
        этой машины. threshold передаётся вызывающим кодом — переиспользует
        тот же порог заметности, что уже применяется к повреждениям игрока
        (core/engine.py::_DAMAGE_NOTICEABLE_THRESHOLD), не второй дубль
        магического числа в другом модуле."""
        profile = self._profiles.get(vehicle_idx)
        if profile is None:
            return
        if body_damage >= threshold and profile.body_damage < threshold:
            profile.mistake_at = now
        profile.body_damage = body_damage

    def get_recent_mistake(self, vehicle_idx: int | None, now: float,
                            window: float = _MISTAKE_RECENCY_WINDOW) -> bool:
        if vehicle_idx is None:
            return False
        profile = self._profiles.get(vehicle_idx)
        if profile is None or profile.mistake_at is None:
            return False
        return (now - profile.mistake_at) <= window

    def get_state(self, now: float = 0.0) -> dict:
        rivals = [
            {
                "driver": p.driver,
                "team": p.team,
                "position": p.current_position,
                "lap": p.lap_count,
                "pit_count": p.pit_count,
                "style": p.style,
                "nearby": p.nearby,
                "tyre_age": p.tyre_age,
                "recent_mistake": self.get_recent_mistake(p.vehicle_idx, now),
            }
            for p in sorted(self._profiles.values(), key=lambda x: x.current_position)
        ]
        nearby_count = sum(1 for r in rivals if r["nearby"])
        return {
            "rivals": rivals,
            "rival_count": len(rivals),
            "nearby_count": nearby_count,
        }


def _classify_style(history: deque) -> str:
    positions = [p for p in history if p > 0]
    if len(positions) < _MIN_HISTORY_STYLE:
        return "consistent"
    try:
        sd = stdev(positions)
    except Exception:
        sd = 0.0
    if sd >= _STYLE_VARIANCE_HIGH:
        return "aggressive"
    if len(positions) >= 2:
        deltas = [positions[i] - positions[i - 1] for i in range(1, len(positions))]
        avg_delta = mean(deltas)
        if avg_delta <= -_STYLE_TREND_THRESHOLD:
            return "charging"
        if avg_delta >= _STYLE_TREND_THRESHOLD:
            return "fading"
    return "consistent"
