"""
core/track_ai/survey.py
========================
Промер трассы ПО СВОЕЙ ТЕЛЕМЕТРИИ: где на круге на самом деле повороты.

Зачем модуль вообще существует. Карты в `tracks/*.json` неполные — на 24 трассах
к повороту привязывается в среднем 66% круга, а на Сузуке и Баку — 52%
(`python scripts/audit_tracks.py`). Ошибка, случившаяся вне размеченного участка,
получает `corner_id: null`, и коуч про неё сказать не может ничего: разбор живого
заезда в Майами дал шесть таких из семи.

Дописать недостающие повороты «на глаз» НЕЛЬЗЯ, и это не осторожность, а
единственное правило этой карты: по ней коуч выносит суждения о пилотаже, и
выдуманная доля означает уверенно неправильный совет — хуже молчания. Поэтому
доли берутся измерением, и вот оно.

**Что измеряется.** Кадр MotionEx (пакет 13) идёт 20-60 раз в секунду и несёт
`yaw_rate` — угловую скорость кузова. Вместе со скоростью она даёт боковое
ускорение (a = ω·v), то есть ФАКТ поворота, а не намерение пилота: руль можно
крутить и на прямой, кузов на прямой не доворачивает. Апекс — точка минимума
скорости внутри поворота, ровно так же, как его понимает `corner_log`.

**Чего этот модуль НЕ делает.** Он ничего не пишет в `tracks/` и не трогает
активную карту. Промер уезжает отдельным файлом, а решение, что из него взять,
принимает человек через `scripts/survey_track.py` — с диффом против текущей
карты. Автоматически подменять карту, по которой коуч судит о пилотаже, нельзя
по той же причине, по которой нельзя её выдумывать.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

#: Боковое ускорение, ниже которого это ещё прямая (м/с²). Машина F1 в повороте
#: держит 3-5 g; порог намеренно низкий — цель поймать ГРАНИЦУ поворота, а не его
#: предел. Ниже этого — снос по прямой, неровности и шум замера.
CORNER_MIN_LAT_ACCEL = 4.0

#: Ниже этой скорости кадр в промер не идёт: на пит-лейне и при развороте
#: `yaw_rate` большой, а поворотом трассы это не является.
MIN_SPEED_KMH = 60.0

#: Разрыв (в долях круга), который НЕ разрывает поворот. Кадры теряются, а
#: боковое ускорение на перекладке проходит через ноль — без склейки одна дуга
#: рассыпалась бы на несколько.
BRIDGE_GAP = 0.004

#: Короче этого участок — не поворот, а рябь. На круге в 5 км это 30 метров.
MIN_CORNER_LENGTH = 0.006

#: Ближе этого два поворота РАЗНОГО направления считаются шиканой: связка
#: проходится как одно целое, и коуч должен говорить о ней как об одном месте.
CHICANE_MAX_SEPARATION = 0.012

#: Апексная скорость (км/ч) -> тип поворота. Границы конвенциональные, но
#: значение измеренное: тип берётся из СВОЕЙ скорости в апексе, а не из
#: представлений о трассе.
_TYPE_BY_APEX_SPEED: tuple[tuple[float, str], ...] = (
    (100.0, "hairpin"),
    (140.0, "slow"),
    (200.0, "medium"),
)
_FASTEST_TYPE = "fast"

#: Меньше — круг негодный: телеметрия рвалась, или заезд начался с середины.
MIN_SAMPLES = 300

#: Какую долю круга обязаны покрыть замеры, чтобы круг считался полным.
MIN_COVERAGE = 0.9


@dataclass(frozen=True)
class SurveyedCorner:
    """Один измеренный поворот."""
    fraction: float      # апекс, доля круга
    type: str
    direction: str       # "left" | "right"
    apex_speed_kmh: float
    entry_fraction: float
    exit_fraction: float
    peak_lat_accel: float

    def to_dict(self) -> dict:
        return {
            "fraction": round(self.fraction, 4),
            "type": self.type,
            "direction": self.direction,
            "apex_speed_kmh": round(self.apex_speed_kmh, 1),
            "entry_fraction": round(self.entry_fraction, 4),
            "exit_fraction": round(self.exit_fraction, 4),
            "peak_lat_accel": round(self.peak_lat_accel, 2),
        }

    def to_map_entry(self, corner_id: int) -> dict:
        """Строка в формате `tracks/*.json` — ровно те поля, что читает загрузчик
        (`core/track_ai/loader.py`), без диагностических."""
        return {
            "id": corner_id,
            "name": f"Turn {corner_id}",
            "fraction": round(self.fraction, 3),
            "type": self.type,
            "direction": self.direction,
        }


@dataclass
class _Sample:
    fraction: float
    speed_kmh: float
    lat_accel: float     # со знаком: + вправо, - влево
    yaw_rate: float


class TrackSurvey:
    """Один экземпляр на сессию. `observe()` — на каждом кадре MotionEx.

    Круг копится в память и разбирается на `finish_lap()`. Памяти это стоит
    порядка пяти тысяч кадров по четыре числа — примерно как один эталонный круг
    коуча, ради которого хранилище уже заведено.
    """

    def __init__(self) -> None:
        self._samples: list[_Sample] = []

    def reset(self) -> None:
        self._samples.clear()

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def observe(self, *, lap_distance_m: float | None, length_m: float,
                speed_kmh: float | None, yaw_rate: float | None) -> None:
        """Кадр телеметрии. Молча игнорирует всё, из чего доли не получится:
        промер обязан быть дешевле и тише, чем то, что он измеряет."""
        if not length_m or length_m <= 0:
            return
        if lap_distance_m is None or speed_kmh is None or yaw_rate is None:
            return
        try:
            distance = float(lap_distance_m)
            speed = float(speed_kmh)
            yaw = float(yaw_rate)
        except (TypeError, ValueError):
            return
        if not all(map(math.isfinite, (distance, speed, yaw))):
            return
        if speed < MIN_SPEED_KMH or distance < 0.0:
            return
        fraction = (distance % length_m) / length_m
        # a = ω·v. Знак — направление поворота; яму на перекладке даёт сам знак,
        # поэтому склейка ниже работает по МОДУЛЮ, а направление берётся средним.
        lat_accel = yaw * (speed / 3.6)
        self._samples.append(_Sample(fraction, speed, lat_accel, yaw))

    # ── Разбор ───────────────────────────────────────────────────────────────

    def finish_lap(self) -> list[SurveyedCorner] | None:
        """Повороты круга, либо None — если круг для промера не годится.

        None, а не пустой список: «поворотов не нашлось» и «мерить было нечем» —
        разные ответы, и второй не должен выглядеть как трасса без поворотов."""
        samples = sorted(self._samples, key=lambda s: s.fraction)
        if len(samples) < MIN_SAMPLES:
            return None
        if samples[-1].fraction - samples[0].fraction < MIN_COVERAGE:
            return None

        groups = self._group(samples)
        corners = [c for c in (self._corner_from(g) for g in groups) if c is not None]
        corners.sort(key=lambda c: c.fraction)
        return self._merge_chicanes(corners)

    @staticmethod
    def _group(samples: list[_Sample]) -> list[list[_Sample]]:
        """Смежные участки, где машина реально поворачивает.

        Группа рвётся по ДВУМ причинам, и вторая не менее важна первой:

            разрыв по дистанции — кадры потерялись либо машина вышла на прямую;
            смена ЗНАКА бокового ускорения — перекладка, то есть новая дуга.

        Без второго условия шикана склеивалась в один поворот: обе её дуги идут
        вплотную и обе выше порога, так что по одному только разрыву они
        неразличимы. Знаковая сумма при этом взаимно гасилась, и связка получала
        направление того, кто оказался длиннее, и апекс между дугами — то есть
        коуч назвал бы место, которого нет. Поймано тестом на синтетическом
        круге, где правильный ответ известен заранее.
        """
        groups: list[list[_Sample]] = []
        current: list[_Sample] = []
        last_fraction: float | None = None
        current_sign = 0
        for sample in samples:
            if abs(sample.lat_accel) < CORNER_MIN_LAT_ACCEL:
                continue
            sign = 1 if sample.lat_accel >= 0 else -1
            broke_apart = (current and last_fraction is not None
                           and sample.fraction - last_fraction > BRIDGE_GAP)
            changed_hands = current and sign != current_sign
            if broke_apart or changed_hands:
                groups.append(current)
                current = []
            current.append(sample)
            current_sign = sign
            last_fraction = sample.fraction
        if current:
            groups.append(current)
        return groups

    @staticmethod
    def _corner_from(group: list[_Sample]) -> SurveyedCorner | None:
        entry = group[0].fraction
        exit_ = group[-1].fraction
        if exit_ - entry < MIN_CORNER_LENGTH:
            return None
        apex = min(group, key=lambda s: s.speed_kmh)
        signed = sum(s.lat_accel for s in group)
        peak = max(abs(s.lat_accel) for s in group)
        return SurveyedCorner(
            fraction=apex.fraction,
            type=_type_for(apex.speed_kmh),
            direction="right" if signed >= 0 else "left",
            apex_speed_kmh=apex.speed_kmh,
            entry_fraction=entry,
            exit_fraction=exit_,
            peak_lat_accel=peak,
        )

    @staticmethod
    def _merge_chicanes(corners: list[SurveyedCorner]) -> list[SurveyedCorner]:
        """Две дуги РАЗНОГО направления вплотную — это шикана.

        Тип переписывается обеим, но апексы остаются раздельными: связка
        проходится как одно целое, а ошибиться в ней можно на любой из двух дуг,
        и коуч должен уметь назвать которую. Ровно так шиканы и размечены в
        существующих картах (см. Casio Chicane в `tracks/suzuka.json`).
        """
        if len(corners) < 2:
            return corners
        out = list(corners)
        for i in range(len(out) - 1):
            first, second = out[i], out[i + 1]
            if first.direction == second.direction:
                continue
            if second.fraction - first.fraction > CHICANE_MAX_SEPARATION:
                continue
            if first.type != "chicane":
                out[i] = _retyped(first, "chicane")
            out[i + 1] = _retyped(second, "chicane")
        return out


def _retyped(corner: SurveyedCorner, corner_type: str) -> SurveyedCorner:
    return SurveyedCorner(
        fraction=corner.fraction, type=corner_type, direction=corner.direction,
        apex_speed_kmh=corner.apex_speed_kmh,
        entry_fraction=corner.entry_fraction, exit_fraction=corner.exit_fraction,
        peak_lat_accel=corner.peak_lat_accel,
    )


def _type_for(apex_speed_kmh: float) -> str:
    for ceiling, name in _TYPE_BY_APEX_SPEED:
        if apex_speed_kmh < ceiling:
            return name
    return _FASTEST_TYPE


def coverage(corners: list[SurveyedCorner]) -> float:
    """Какая доля круга попадает в измеренные повороты — то же число, что
    печатает `scripts/audit_tracks.py` для действующей карты, чтобы промер и
    аудит можно было сравнивать напрямую."""
    if not corners:
        return 0.0
    total = 0.0
    previous_end = -1.0
    for corner in sorted(corners, key=lambda c: c.entry_fraction):
        start = max(corner.entry_fraction, previous_end)
        if corner.exit_fraction > start:
            total += corner.exit_fraction - start
            previous_end = corner.exit_fraction
    return min(1.0, total)
