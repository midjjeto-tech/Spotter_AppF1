"""
core/strategy_ai/driver_query.py
=================================
Инженер сам начинает разговор: «Как шины держат?»

Зачем. Рация в проекте односторонняя по инициативе: PTT работает на втягивание —
пилот спрашивает, инженер отвечает. Сам инженер не заговаривает ни разу, кроме
проверки связи на старте (`session.radio_check`). В реальной рации и в F1
Manager вопрос инженера — половина её жизни: он не только сообщает, но и
спрашивает, и по ответу строит план.

Три ограничения, и каждое существует по своей причине:

  * ТОЛЬКО когда пилот не занят. Вопрос в разгар борьбы — это помеха, а не
    участие: пилоту нечем на него отвечать, руки заняты. Занятость определяется
    близостью соседа, а не догадкой о настроении.
  * РЕДКО. Кулдаун втрое больше, чем у советов: вопрос, заданный часто,
    перестаёт быть вопросом и становится тиком.
  * ОДИН И ТОТ ЖЕ вопрос не повторяется. Спросив про шины, инженер не
    спрашивает про них снова — он уже слышал ответ (или не услышал, что тоже
    ответ).

Про шины спрашиваем не раньше, чем на резине накатано: «Как шины?» на первом
круге стинта — вопрос ни о чём, ответа на него ещё не существует.
"""
from __future__ import annotations

#: Кулдаун между вопросами, секунды. Втрое больше обычного совета: вопрос —
#: событие, а не фон.
COOLDOWN_S = 180.0

#: Сосед ближе этого (мс) — пилот занят борьбой, вопрос неуместен. Порог
#: намеренно шире зоны DRS: в секунде позади соперника пилот уже атакует.
BUSY_GAP_MS = 1500

#: Кругов на комплекте, раньше которых спрашивать про шины бессмысленно.
MIN_STINT_LAPS_FOR_TYRES = 8

CODE_TYRES = "ask.tyres"
CODE_BALANCE = "ask.balance"
CODE_BRAKES = "ask.brakes"
CODE_FEEL = "ask.feel"


class DriverQueryTracker:
    """Решает, задать ли пилоту вопрос — и какой."""

    def __init__(self, cooldown: float = COOLDOWN_S):
        self._cooldown = cooldown
        self._last_t = 0.0
        self._asked: set[str] = set()

    def check(self, *, gap_front_ms: int | None, gap_behind_ms: int | None,
              tyre_age: int | None, safety_car: bool, now: float) -> str | None:
        """Semantic code вопроса, либо None если спрашивать не время.

        `safety_car` — под машиной безопасности пилот как раз свободен, но
        эфир занят организационными вводными, и лезть в него с разговором
        нельзя.
        """
        if safety_car or self._busy(gap_front_ms, gap_behind_ms):
            return None
        if now - self._last_t < self._cooldown:
            return None
        for code in self._candidates(tyre_age):
            if code in self._asked:
                continue
            self._asked.add(code)
            self._last_t = now
            return code
        return None

    @staticmethod
    def _busy(gap_front_ms: int | None, gap_behind_ms: int | None) -> bool:
        """Пилот в борьбе, если сосед с любой стороны ближе порога.

        Отсутствие гэпа (None) занятостью НЕ считается: рядом попросту никого
        нет, это самый спокойный момент из возможных."""
        return any(gap is not None and 0 < gap <= BUSY_GAP_MS
                   for gap in (gap_front_ms, gap_behind_ms))

    @staticmethod
    def _candidates(tyre_age: int | None) -> list[str]:
        """Вопросы в порядке полезности ответа для дальнейших решений."""
        out: list[str] = []
        if tyre_age is not None and tyre_age >= MIN_STINT_LAPS_FOR_TYRES:
            out.append(CODE_TYRES)
        out.append(CODE_BALANCE)
        out.append(CODE_BRAKES)
        out.append(CODE_FEEL)
        return out

    def reset(self) -> None:
        self._last_t = 0.0
        self._asked.clear()
