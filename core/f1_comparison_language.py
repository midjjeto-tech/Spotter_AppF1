"""Truthful language for non-normalized F1 25 versus real-GP times."""

from __future__ import annotations


COMPARISON_DISCLAIMER = (
    "Условия F1 25 и реального Гран-при не сопоставимы напрямую: различаются "
    "физика, настройки, погода, топливо, шины и состояние трассы. Разница "
    "времён не показывает, кто быстрее как пилот."
)

SHORT_COMPARISON_DISCLAIMER = (
    "Условия игры и реального Гран-при не сопоставимы; это не сравнение "
    "мастерства пилотов."
)


def describe_time_difference(gap_ms: int | None, *, decimals: int = 1) -> str:
    """Describe recorded values without converting them into a skill claim."""
    if gap_ms is None:
        return "Разница времён недоступна."
    seconds = abs(gap_ms) / 1000.0
    value = f"{seconds:.{decimals}f} с"
    if gap_ms < 0:
        return f"Игровое время на {value} меньше реального ориентира."
    if gap_ms > 0:
        return f"Игровое время на {value} больше реального ориентира."
    return "Игровое время совпало с реальным ориентиром."
