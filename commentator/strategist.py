"""
commentator/strategist.py
==========================
Сообщения Strategy AI. Собственных пулов здесь больше НЕТ — формулировки живут
в едином банке `core/radio/phrases.py`, модуль остался картой
`strategy_ai_type -> semantic code` плюс единственное исключение, которому
нужен счёт кругов (`pit_window` с известным `laps_to_pit`).
"""
from __future__ import annotations

from core.num_to_words import ru_plural
from core.radio import phrases

#: strategy_ai_type -> semantic code банка. Ключи — типы из
#: `core/strategy_ai/module.py::_EVENT_CODES` плюс "stable" (дефолт).
_STRATEGY_CODE: dict[str, str] = {
    "undercut": "strategy.undercut",
    "overcut": "strategy.overcut",
    "cover_opponent": "strategy.pit_window",
    "pit_window": "strategy.pit_window",
    "tyre_save": "strategy.tyre_save",
    "push_pace": "strategy.push_pace",
    "fuel_save": "fuel.save",
    "ers_save": "strategy.ers_save",
    "ers_overtake": "strategy.ers_overtake",
    "stable": "strategy.stable",
    "box_call_1": "box.call_1",
    "box_call_2": "box.call_2",
    "box_call_3": "box.call_3",
}


def strategy_phrase_code(event_type: str) -> str:
    """Semantic code банка для типа стратегического события."""
    return _STRATEGY_CODE.get(event_type, _STRATEGY_CODE["stable"])


def _laps_phrase(n: int) -> str:
    """«Пит через N кругов» — единственная фраза со счётом кругов.

    Осталась здесь, а не в банке, потому что число известно ТОЛЬКО в этот
    момент и волатильным не является: `laps_to_pit` считается из текущего
    состояния стратегии и к моменту озвучки уже не пересчитывается."""
    return f"Пит через {n} " + ru_plural(n, "круг", "круга", "кругов")


def get_message(event_type: str, data: dict | None = None,
                selector_key: str | None = None) -> str:
    """Реплика Strategy AI для типа события.

    `selector_key` — стабильный ключ выбора варианта (обычно `dedupe_key`).
    Без него вариант закрепляется за ТИПОМ — прежнее поведение."""
    data = data or {}
    if event_type == "pit_window":
        laps = data.get("laps_to_pit")
        if laps is not None and laps >= 0:
            return _laps_phrase(int(laps))

    code = strategy_phrase_code(event_type)
    try:
        return phrases.render(
            code, selector_key=selector_key or f"strategist:{event_type}")
    except phrases.PhraseError:
        return phrases.render(
            _STRATEGY_CODE["stable"], selector_key=f"strategist:{event_type}")
