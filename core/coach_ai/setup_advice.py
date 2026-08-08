"""
core/coach_ai/setup_advice.py
==============================
Советы по гаражу из карты ошибок фазы 1 и настроек машины (пакет 5).

**Три связки, и ни одной больше.** Крылья, подвеска, стабилизаторы, развал и
давления сознательно вне советов: их эффект в F1 25 нелинеен и зависит от
трассы, причинной модели у нас нет, а догадку пилот не отличит от обоснованного
вывода. Текущий сетап показывается в дебрифе целиком как факт — выводы по
остальным параметрам пилот делает сам.

Каждый совет несёт наблюдение, на котором стоит: совет без основания это
приказ, а не совет.

См. docs/superpowers/specs/2026-08-07-driving-coach-phase3-garage.md.
"""
from __future__ import annotations

from core.coach_ai.models import SetupHint

#: Сколько раз ошибка должна повториться за сессию, чтобы трогать машину.
#: Единичная блокировка — это круг, а не сетап.
MIN_OCCURRENCES = 6

#: Границы, за которыми совет двигать параметр становится мусором.
BRAKE_BIAS_MIN = 50
BRAKE_BIAS_MAX = 70
DIFF_MIN = 50

_FRONT = ("fl", "fr")
_REAR = ("rl", "rr")


def build_hints(mistakes: list[dict], setup: dict | None) -> list[SetupHint]:
    """Советы по итогам сессии. Пустой список — нормальный результат."""
    if not setup or not mistakes:
        return []
    hints: list[SetupHint] = []
    hint = _brake_bias_hint(mistakes, setup)
    if hint is not None:
        hints.append(hint)
    hint = _differential_hint(mistakes, setup)
    if hint is not None:
        hints.append(hint)
    return hints


def _count(mistakes: list[dict], kind: str, wheels: tuple[str, ...] | None = None,
           phase: str | None = None) -> int:
    total = 0
    for m in mistakes:
        if m.get("kind") != kind:
            continue
        if wheels is not None and m.get("wheel") not in wheels:
            continue
        if phase is not None and m.get("phase") != phase:
            continue
        total += 1
    return total


def _brake_bias_hint(mistakes: list[dict], setup: dict) -> SetupHint | None:
    """Блокировка передних → баланс назад, задних → вперёд.

    Если блокирует ОБЕ оси — это не баланс, а перетормаживание, и сдвиг в любую
    сторону сделает хуже одной из осей. Молчим."""
    bias = setup.get("brake_bias")
    if bias is None:
        return None
    front = _count(mistakes, "lockup", _FRONT)
    rear = _count(mistakes, "lockup", _REAR)
    front_hit = front >= MIN_OCCURRENCES
    rear_hit = rear >= MIN_OCCURRENCES
    if front_hit == rear_hit:
        return None

    if front_hit:
        if bias <= BRAKE_BIAS_MIN:
            return None
        return SetupHint(
            parameter="brake_bias", direction="down",
            advice="Сдвинь баланс тормозов назад на один-два процента.",
            evidence=(f"{front} блокировок передних за сессию, "
                      f"баланс {bias}% вперёд."),
        )

    if bias >= BRAKE_BIAS_MAX:
        return None
    return SetupHint(
        parameter="brake_bias", direction="up",
        advice="Сдвинь баланс тормозов вперёд на один-два процента.",
        evidence=f"{rear} блокировок задних за сессию, баланс {bias}% вперёд.",
    )


def _differential_hint(mistakes: list[dict], setup: dict) -> SetupHint | None:
    """Пробуксовка на выходе → мягче дифференциал на разгоне."""
    diff = setup.get("diff_on_throttle")
    if diff is None or diff <= DIFF_MIN:
        return None
    spin = _count(mistakes, "wheelspin", phase="exit")
    if spin < MIN_OCCURRENCES:
        return None
    return SetupHint(
        parameter="diff_on_throttle", direction="down",
        advice="Смягчи дифференциал на разгоне на пару процентов.",
        evidence=f"{spin} пробуксовок на выходе, дифференциал {diff}%.",
    )
