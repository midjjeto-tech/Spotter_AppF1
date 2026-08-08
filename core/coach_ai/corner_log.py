"""
core/coach_ai/corner_log.py
============================
Копилка ошибок пилотажа за сессию. Два потребителя с намеренно РАЗНЫМИ
правилами:

    дебриф — ВСЁ, включая одиночные срывы: экран после сессии никого не
             перебивает;
    эфир   — только повтор (REPEAT_LAPS кругов из последних WINDOW_LAPS):
             разовый срыв пилот почувствовал сам, а комментировать каждый —
             это ровно та жалоба «говорит без остановки», которую в этом
             проекте чинили дважды с разных сторон.

Модуль решает, ЧТО повторяется. Каким словом это сказать — банк
`core/radio/phrases.py`; когда это можно озвучить — радио-конвейер.
"""
from __future__ import annotations

from core.coach_ai.models import CornerMistake
from core.coach_ai.repeat import RepeatGate


class CornerLog:
    """Один экземпляр на сессию."""

    def __init__(self) -> None:
        self._all: list[CornerMistake] = []
        # Правило повтора общее с фазой 2 (core/coach_ai/repeat.py): своей
        # копии здесь быть не должно, иначе характер коуча разойдётся по фазам.
        self._gate = RepeatGate()

    def reset(self) -> None:
        self._all.clear()
        self._gate.reset()

    def add(self, mistake: CornerMistake) -> CornerMistake | None:
        """Записать ошибку. Вернуть её же, если пора сказать вживую.

        Ошибка попадает в карту дебрифа ВСЕГДА, независимо от того, дошло ли
        дело до реплики."""
        self._all.append(mistake)
        if self._gate.observe(mistake.signature(), mistake.lap):
            return mistake
        return None

    def map_rows(self) -> list[dict]:
        """Плоская карта для дебрифа и архива — ВСЕ ошибки без фильтра."""
        return [
            {
                "lap": m.lap, "corner_id": m.corner_id,
                "corner_name": m.corner_name, "kind": m.kind, "wheel": m.wheel,
                "phase": m.phase, "peak": m.peak, "duration_s": m.duration_s,
                "speed_kmh": m.speed_kmh,
            }
            for m in self._all
        ]

    def top_corners(self, limit: int = 3) -> list[dict]:
        """Самые проблемные повороты по числу ошибок."""
        counts: dict[int | None, dict] = {}
        for m in self._all:
            row = counts.setdefault(m.corner_id, {
                "corner_id": m.corner_id, "corner_name": m.corner_name,
                "count": 0, "kinds": {},
            })
            row["count"] += 1
            row["kinds"][m.kind] = row["kinds"].get(m.kind, 0) + 1
        ranked = sorted(counts.values(), key=lambda r: -r["count"])
        return ranked[:limit]
