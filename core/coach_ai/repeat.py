"""
core/coach_ai/repeat.py
========================
Правило «о чём стоит сказать вслух»: одна и та же тема на REPEAT_LAPS кругах из
последних WINDOW_LAPS, затем молчание COOLDOWN_LAPS кругов.

Живёт отдельным модулем, потому что нужно обеим фазам коуча — срывам сцепления
(фаза 1, `corner_log.py`) и отклонениям от эталона (фаза 2, вызывается из
движка). Две копии этого правила со временем разошлись бы и дали коучу два
разных характера внутри одной функции.
"""
from __future__ import annotations

WINDOW_LAPS = 5
REPEAT_LAPS = 3
#: Пилот не перестроит привычку за один круг, а повторённый совет раздражает
#: быстрее, чем помогает.
COOLDOWN_LAPS = 5


class RepeatGate:
    """Один экземпляр на источник тем. Ключ темы — любой хешируемый объект."""

    def __init__(self) -> None:
        self._laps: dict[object, list[int]] = {}
        self._fired_on_lap: dict[object, int] = {}

    def reset(self) -> None:
        self._laps.clear()
        self._fired_on_lap.clear()

    def observe(self, signature: object, lap: int) -> bool:
        """Записать наблюдение. True — пора сказать."""
        laps = self._laps.setdefault(signature, [])
        # Несколько наблюдений на одном круге — это один круг: иначе один
        # особенно неудачный круг выдавался бы за привычку.
        if lap not in laps:
            laps.append(lap)

        recent = [x for x in laps if lap - x < WINDOW_LAPS]
        if len(recent) < REPEAT_LAPS:
            return False

        fired = self._fired_on_lap.get(signature)
        if fired is not None and lap - fired < COOLDOWN_LAPS:
            return False

        self._fired_on_lap[signature] = lap
        return True
