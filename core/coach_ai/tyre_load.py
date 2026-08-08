"""
core/coach_ai/tyre_load.py
===========================
Перекос износа и температур резины за сессию — во что стиль пилота обходится
машине.

Это НЕ дубль `core/strategy_ai/tyres.py`: тот определяет стадию износа
(fresh/worn/critical/cliff) для решения о пит-стопе, то есть КОГДА менять
резину. Здесь — почему она умирает неравномерно.

Ключевое правило: перекос меряется ВНУТРИ оси. У передних и задних колёс
разная работа, поэтому «передняя левая против задней правой» не значит ничего,
а «передние в целом изношены сильнее задних» — это характер машины и трассы, а
не ошибка пилота.
"""
from __future__ import annotations

from core.coach_ai.models import TyreLoadReport

#: Ниже этого разброса внутри оси перекос не называем: колёса никогда не
#: изнашиваются идеально одинаково, и шум выдавать за находку нельзя.
MIN_WEAR_SPREAD_PCT = 8.0
#: То же для температуры: пара градусов между колёсами одной оси — норма.
MIN_TEMP_SPREAD_C = 12.0

_AXLES: dict[str, tuple[str, str]] = {
    "front": ("fl", "fr"),
    "rear": ("rl", "rr"),
}


class TyreLoadTracker:
    """Один экземпляр на сессию. Хранит ПОСЛЕДНИЙ снимок, а не историю:
    износ монотонно растёт, поэтому свежий снимок и есть итог сессии."""

    def __init__(self) -> None:
        self._wear: dict[str, float] = {}
        self._temp: dict[str, float] = {}

    def reset(self) -> None:
        self._wear = {}
        self._temp = {}

    def observe(self, wear: dict | None, surface_temp: dict | None) -> None:
        if wear:
            self._wear = dict(wear)
        if surface_temp:
            self._temp = dict(surface_temp)

    def report(self) -> TyreLoadReport | None:
        if not self._wear and not self._temp:
            return None
        wheel, axle, spread = _worst_axle_spread(self._wear, MIN_WEAR_SPREAD_PCT)
        hot, temp_spread = _hottest(self._temp)
        return TyreLoadReport(
            worst_wheel=wheel, worst_axle=axle, wear_spread_pct=spread,
            hottest_wheel=hot, temp_spread_c=temp_spread,
        )


def _worst_axle_spread(values: dict[str, float],
                       threshold: float) -> tuple[str | None, str | None, float]:
    """Ось с наибольшим разбросом внутри себя и её худшее колесо."""
    best_axle: str | None = None
    best_wheel: str | None = None
    best_spread = 0.0
    for axle, (left, right) in _AXLES.items():
        if left not in values or right not in values:
            continue
        spread = abs(values[left] - values[right])
        if spread > best_spread:
            best_spread = spread
            best_axle = axle
            best_wheel = left if values[left] > values[right] else right
    if best_spread < threshold:
        # Разброс есть всегда; ниже порога он не находка, поэтому колесо не
        # называем — но саму величину отдаём, её показывает дебриф.
        return None, None, best_spread
    return best_wheel, best_axle, best_spread


def _hottest(values: dict[str, float]) -> tuple[str | None, float]:
    """Самое горячее колесо относительно ХОЛОДНЕЙШЕГО на машине.

    В отличие от износа температуру сравниваем по всем четырём: перегрев одного
    колеса виден именно на фоне остальных, а не только напарника по оси."""
    if len(values) < 2:
        return None, 0.0
    hottest = max(values, key=lambda w: values[w])
    spread = values[hottest] - min(values.values())
    if spread < MIN_TEMP_SPREAD_C:
        return None, spread
    return hottest, spread
