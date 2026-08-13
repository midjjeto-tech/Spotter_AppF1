"""core/track_ai/corners.py — corner/phase detection from lap distance fraction."""
from __future__ import annotations

from core.track_ai.models import Corner

# How far before the corner start we treat as "braking zone" (fraction of lap).
# Fallback only — prefer braking_offset_for(length_m): braking is a DISTANCE,
# not a share of the lap. See the note there.
BRAKING_OFFSET: float = 0.018

#: Зона торможения в метрах. Разбор живого заезда 2026-08-11: доля 0.018 даёт на
#: Майами 97 м, а торможение с 320 км/ч начинается заметно раньше — поэтому
#: блокировка колеса на 224 км/ч попадала в «straight» и теряла поворот, к
#: которому относилась. В метрах порог физичен и не зависит от длины круга: на
#: Монако 0.018 это 60 м, на Спа — 126 м, хотя тормозят там одинаково.
BRAKING_ZONE_M: float = 150.0


def braking_offset_for(length_m: float) -> float:
    """Зона торможения как доля круга для трассы этой длины."""
    if length_m <= 0:
        return BRAKING_OFFSET
    return BRAKING_ZONE_M / length_m


def get_corner(lap_pct: float, corners: list[Corner],
               braking_offset: float = BRAKING_OFFSET) -> Corner | None:
    """Return the corner the car is approaching or inside; None if on a straight.

    Зона торможения НЕ заезжает за конец предыдущего поворота: на тесных
    уличных трассах повороты стоят вплотную, а функция возвращает первый
    совпавший по порядку списка — без ограничителя торможение в связке
    приписывалось бы уже следующему повороту.

    Зона первого поворота может заходить за линию старта — тогда она
    проверяется и с той стороны круга.
    """
    if not corners:
        return None
    for i, c in enumerate(corners):
        # Для первого поворота «предыдущий» — последний поворот круга,
        # сдвинутый на круг назад.
        prev_end = corners[i - 1].end if i > 0 else corners[-1].end - 1.0
        start = max(c.start - braking_offset, prev_end)
        if start <= lap_pct <= c.end:
            return c
        if start < 0.0 and lap_pct >= start + 1.0:
            return c
    return None


def get_phase(lap_pct: float, corner: Corner) -> str:
    """Return driving phase within a corner (call only when corner is not None)."""
    if lap_pct < corner.start:
        return "braking"
    mid = (corner.start + corner.end) / 2.0
    if lap_pct < mid:
        return "entry"
    if lap_pct < corner.end - 0.005:
        return "apex"
    return "exit"
