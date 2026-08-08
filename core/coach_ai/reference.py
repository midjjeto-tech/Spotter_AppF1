"""
core/coach_ai/reference.py
===========================
Захват метрик поворота на тике. Один автомат на круг: пока машина внутри зоны
поворота, ведёт четыре числа; на выходе из зоны закрывает запись.

Хранить сырую трассу телеметрии для этого не нужно — эталон это около
восьмидесяти чисел на круг, и они уезжают в файл сессии рядом с картой ошибок
(`core/session_recorder.py`).
"""
from __future__ import annotations

from core.coach_ai.models import CornerMetrics

BRAKE_ON_PCT = 15.0        # ниже — это подтормаживание, а не точка торможения
THROTTLE_ON_PCT = 40.0     # ниже — поддерживающий газ, а не разгон
#: Откат дистанции больше этого = флэшбек или пересечение финиша, а не движение.
DISTANCE_REWIND_M = 5.0


class _Corner:
    __slots__ = ("corner_id", "entry_ms", "exit_ms", "brake_m", "min_speed",
                 "min_speed_m", "throttle_m")

    def __init__(self, corner_id: int, lap_time_ms: int) -> None:
        self.corner_id = corner_id
        self.entry_ms = lap_time_ms
        self.exit_ms = lap_time_ms
        self.brake_m: float | None = None
        self.min_speed: float | None = None
        self.min_speed_m: float | None = None
        self.throttle_m: float | None = None


class LapTracer:
    """Один экземпляр на сессию. `tick()` зовётся на каждом тике телеметрии,
    `finish_lap()` — на пересечении финишной черты."""

    def __init__(self) -> None:
        self._done: dict[int, CornerMetrics] = {}
        self._cur: _Corner | None = None
        self._last_distance_m: float | None = None

    def reset(self) -> None:
        self._done.clear()
        self._cur = None
        self._last_distance_m = None

    def tick(self, corner_id: int | None, phase: str, lap_distance_m: float,
             lap_time_ms: int, brake_pct: float, throttle_pct: float,
             speed_kmh: float | None) -> None:
        if self._rewound(lap_distance_m):
            # Флэшбек: поворот в работе описывает уже несуществующий проезд.
            self._cur = None
            self._last_distance_m = lap_distance_m
            return
        self._last_distance_m = lap_distance_m

        if corner_id is None:
            self._close()
            return
        if self._cur is None or self._cur.corner_id != corner_id:
            self._close()
            self._cur = _Corner(corner_id, lap_time_ms)

        cur = self._cur
        cur.exit_ms = lap_time_ms

        if cur.brake_m is None and brake_pct >= BRAKE_ON_PCT:
            cur.brake_m = lap_distance_m

        # Минимум ищем ВНУТРИ поворота: на подходе скорость ещё падает, и её
        # минимум был бы концом прямой, а не апексом.
        if phase != "braking" and speed_kmh is not None:
            if cur.min_speed is None or speed_kmh < cur.min_speed:
                cur.min_speed = speed_kmh
                cur.min_speed_m = lap_distance_m
                # Газ, открытый ДО минимума, разгоном из поворота не является.
                cur.throttle_m = None

        if (cur.min_speed is not None and cur.throttle_m is None
                and throttle_pct >= THROTTLE_ON_PCT):
            cur.throttle_m = lap_distance_m

    def finish_lap(self) -> dict[int, CornerMetrics]:
        """Метрики круга. Поворот, не закрывшийся до финишной черты, всё равно
        засчитывается — на многих трассах она лежит внутри связки."""
        self._close()
        out = self._done
        self._done = {}
        self._cur = None
        self._last_distance_m = None
        return out

    def _rewound(self, lap_distance_m: float) -> bool:
        return (self._last_distance_m is not None
                and lap_distance_m < self._last_distance_m - DISTANCE_REWIND_M)

    def _close(self) -> None:
        cur = self._cur
        self._cur = None
        if cur is None:
            return
        metrics = CornerMetrics(
            corner_id=cur.corner_id, brake_point_m=cur.brake_m,
            min_speed_kmh=cur.min_speed, throttle_point_m=cur.throttle_m,
            duration_ms=cur.exit_ms - cur.entry_ms,
        )
        if metrics.usable():
            self._done[cur.corner_id] = metrics
