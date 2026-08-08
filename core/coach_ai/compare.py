"""
core/coach_ai/compare.py
=========================
Сравнение круга с эталоном. Главное здесь — НОРМАЛИЗАЦИЯ.

Карьерный лучший круг почти всегда квалификационный: пустой бак, свежая резина,
в карьере иногда и другая машина. Сравнение в лоб даёт отчёт «ты медленнее
везде» — правду, из которой ничего не следует, и через две гонки тумблер
выключат. Поэтому смотрим не на отклонение, а на превышение СВЕРХ МЕДИАННОГО по
кругу: равномерное отставание съедается медианой и молчит, локальная потеря
остаётся видна.

То же касается всех метрик, а не только времени: тяжёлая машина тормозит раньше
в каждом повороте, и общий сдвиг точки торможения — тоже не ошибка пилота.

Медиана, а не среднее: один вылет не должен утаскивать базу.

Пороги значимости НЕ откалиброваны на живых данных — как и пороги фазы 1.
"""
from __future__ import annotations

from statistics import median

from core.coach_ai.models import CornerDelta, CornerMetrics

#: Меньше — медиана неустойчива, и сравнение не публикуется вовсе.
MIN_COMPARABLE_CORNERS = 5

#: метрика -> (поле CornerMetrics, знак «плохого», порог значимости).
#: Знак приводит превышение к правилу «положительное = хуже эталона»: тормозить
#: позже и проходить апекс быстрее — это прогресс, а не ошибка.
_METRICS: dict[str, tuple[str, float, float]] = {
    "duration":  ("duration_ms",       1.0, 150.0),   # мс
    "brake":     ("brake_point_m",    -1.0,  12.0),   # м
    "min_speed": ("min_speed_kmh",    -1.0,   6.0),   # км/ч
    "throttle":  ("throttle_point_m",  1.0,  15.0),   # м
}


def _raw_deltas(current: dict[int, CornerMetrics],
                reference: dict[int, CornerMetrics],
                field: str) -> dict[int, float]:
    """Сырые разницы по одной метрике для поворотов, где она есть с ОБЕИХ
    сторон."""
    out: dict[int, float] = {}
    for corner_id, cur in current.items():
        ref = reference.get(corner_id)
        if ref is None:
            continue
        a, b = getattr(cur, field), getattr(ref, field)
        if a is None or b is None:
            continue
        out[corner_id] = float(a) - float(b)
    return out


def compare_lap(current: dict[int, CornerMetrics],
                reference: dict[int, CornerMetrics],
                corner_names: dict[int, str]) -> CornerDelta | None:
    """Самое выраженное отклонение круга от эталона, либо None.

    Метрики в разных единицах, поэтому ранжируются не по величине превышения, а
    по его отношению к собственному порогу значимости — иначе метры всегда
    обыгрывали бы километры в час."""
    best: CornerDelta | None = None
    best_ratio = 1.0     # ниже порога значимости не публикуем вовсе

    for metric, (field, sign, threshold) in _METRICS.items():
        deltas = _raw_deltas(current, reference, field)
        if len(deltas) < MIN_COMPARABLE_CORNERS:
            continue
        base = median(deltas.values())
        for corner_id, raw in deltas.items():
            badness = (raw - base) * sign
            ratio = badness / threshold
            if ratio > best_ratio:
                best_ratio = ratio
                best = CornerDelta(
                    corner_id=corner_id,
                    corner_name=corner_names.get(corner_id),
                    metric=metric, raw=round(raw, 1),
                    badness=round(badness, 1),
                )
    return best


def corner_deltas(current: dict[int, CornerMetrics],
                  reference: dict[int, CornerMetrics],
                  corner_names: dict[int, str]) -> list[dict]:
    """Плоская таблица для дебрифа: сырые разницы по всем общим поворотам.

    Здесь именно СЫРЫЕ значения, без нормализации: на экране после сессии видны
    все столбцы сразу, и пилот сам видит, общий это сдвиг или локальный."""
    rows: list[dict] = []
    for corner_id in sorted(set(current) & set(reference)):
        cur, ref = current[corner_id], reference[corner_id]
        row: dict = {"corner_id": corner_id,
                     "corner_name": corner_names.get(corner_id)}
        for metric, (field, _sign, _threshold) in _METRICS.items():
            a, b = getattr(cur, field), getattr(ref, field)
            key = "duration_ms" if metric == "duration" else f"{metric}_delta"
            row[key] = (None if a is None or b is None
                        else round(float(a) - float(b), 1))
        rows.append(row)
    return rows
