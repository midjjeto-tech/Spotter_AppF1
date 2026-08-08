"""
core/coach_ai/models.py
========================
Data types for the Driver Performance Coach.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LapData:
    lap_number: int
    lap_time_ms: int
    s1_ms: int
    s2_ms: int
    s3_ms: int
    tyre_compound: str | None
    tyre_age: int | None
    tyre_wear: float | None


@dataclass
class CornerMistake:
    """Одна завершённая ошибка пилотажа, привязанная к месту на трассе.

    Создаётся детектором только ПОСЛЕ окончания срыва: нужен пик, а не факт.
    `peak` — модуль максимального проскальзывания за событие, он же степень
    ошибки; `duration_s` отсекает шум подвески от настоящей потери сцепления.
    """
    kind: str            # "lockup" | "wheelspin" | "understeer" | "oversteer" | "offtrack"
    wheel: str | None    # "rl" | "rr" | "fl" | "fr"; None для ошибок всей машины
    corner_id: int | None
    corner_name: str | None
    phase: str           # "braking" | "entry" | "apex" | "exit" | "straight"
    lap: int
    peak: float
    duration_s: float
    speed_kmh: int | None

    def signature(self) -> tuple[str, int | None, str]:
        """Ключ повторяемости: та же ошибка, тот же поворот, та же фаза.

        Колесо в ключ НЕ входит: «блокирую передние в третьем» остаётся одной и
        той же проблемой, каким бы колесом ни поймалось в этот раз."""
        return (self.kind, self.corner_id, self.phase)


@dataclass
class CornerMetrics:
    """Как пилот проехал ОДИН поворот.

    Четыре числа, из которых собирается эталонный круг: хранить сырую трассу
    телеметрии для этого не нужно — на круг выходит около восьмидесяти чисел,
    и они помещаются в файл сессии рядом с картой ошибок."""
    corner_id: int
    brake_point_m: float | None      # где нажал тормоз
    min_speed_kmh: float | None      # скорость в самой медленной точке
    throttle_point_m: float | None   # где открыл газ после минимума
    duration_ms: int | None          # время прохождения зоны поворота

    def usable(self) -> bool:
        """Годится ли запись в эталон.

        Минимум скорости и время есть у ЛЮБОГО проеханного поворота; торможение
        и газ бывают не во всех (пологие связки проходятся без тормоза) — их
        отсутствие не повод выбрасывать поворот целиком, такая метрика просто
        не сравнивается."""
        return self.min_speed_kmh is not None and (self.duration_ms or 0) > 0

    def to_dict(self) -> dict:
        return {
            "corner_id": self.corner_id, "brake_point_m": self.brake_point_m,
            "min_speed_kmh": self.min_speed_kmh,
            "throttle_point_m": self.throttle_point_m,
            "duration_ms": self.duration_ms,
        }

    @staticmethod
    def from_dict(raw: dict) -> "CornerMetrics":
        return CornerMetrics(
            corner_id=raw["corner_id"], brake_point_m=raw.get("brake_point_m"),
            min_speed_kmh=raw.get("min_speed_kmh"),
            throttle_point_m=raw.get("throttle_point_m"),
            duration_ms=raw.get("duration_ms"),
        )


@dataclass
class TyreLoadReport:
    """Перекос износа и температур резины за сессию.

    Всё меряется ВНУТРИ оси: у передних и задних колёс разная работа, и
    «передняя левая против задней правой» не значит ничего. Перекос между
    осями — это характер машины и трассы, а не ошибка пилота."""
    worst_wheel: str | None      # колесо с наибольшим износом относительно пары
    worst_axle: str | None       # "front" | "rear"
    wear_spread_pct: float       # разница износа внутри худшей оси
    hottest_wheel: str | None
    temp_spread_c: float

    def to_dict(self) -> dict:
        return {
            "worst_wheel": self.worst_wheel, "worst_axle": self.worst_axle,
            "wear_spread_pct": round(self.wear_spread_pct, 1),
            "hottest_wheel": self.hottest_wheel,
            "temp_spread_c": round(self.temp_spread_c, 1),
        }


@dataclass
class SetupHint:
    """Один совет по гаражу — всегда вместе с наблюдением, на котором он стоит.

    Совет без основания это приказ, а не совет: пилот должен иметь возможность
    не согласиться, посмотрев на те же цифры."""
    parameter: str      # "brake_bias" | "diff_on_throttle"
    direction: str      # "up" | "down"
    advice: str         # что сделать, по-русски
    evidence: str       # почему так считаем

    def to_dict(self) -> dict:
        return {
            "parameter": self.parameter, "direction": self.direction,
            "advice": self.advice, "evidence": self.evidence,
        }


@dataclass
class CornerDelta:
    """Отклонение одной метрики в одном повороте от эталона — уже
    нормализованное.

    `raw` — сырая разница с эталоном, её показывает дебриф.
    `badness` — превышение сверх медианы по кругу, приведённое к «плохому»
    знаку: положительное всегда означает «здесь хуже эталона». Именно по нему
    решается, о чём говорить."""
    corner_id: int
    corner_name: str | None
    metric: str          # "duration" | "brake" | "min_speed" | "throttle"
    raw: float
    badness: float


@dataclass
class DriverReport:
    weak_sector: int | None       # 1, 2 or 3 — sector with most consistent time loss
    lost_time_ms: int | None      # ms lost in weak sector vs. session best
    consistency_score: float      # 0.0–1.0 (1.0 = perfectly consistent lap times)
    pace_delta_ms: int | None     # recent avg lap vs. session best (positive = slower)
    tyre_advice: str              # "push" | "save" | "cliff" | "ok"
    lap_count: int                # total laps fed to the coach
    advice: str | None            # Russian summary phrase
