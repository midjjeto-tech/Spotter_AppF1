"""
core/coach_ai/diagnosis.py
===========================
Связка «сколько стоит» с «почему». Цена без причины — это приговор без разбора:
«в седьмом ты теряешь три десятых» пилот и сам чувствует, а сделать с этим
по-прежнему нечего.

Два источника причины, и порядок между ними не косметический:

    СРЫВ (фаза 1)      — блокировка, пробуксовка, снос, занос, выезд. Это
                         НАБЛЮДЕНИЕ: колесо действительно сорвалось, деталь
                         зафиксирована детектором.
    ТЕХНИКА (фаза 2)   — раннее торможение, низкая скорость в апексе, поздний
                         газ. Это ВЫВОД из сравнения с собственным эталоном.

Срыв бьёт технику, когда он повторяется. Причина: сорванное колесо пилот может
проверить сам на повторе, а «тормозишь на пятнадцать метров раньше» ему
приходится принимать на веру. При равной убедительности тренер называет то, что
можно перепроверить.

**Поворот без причины фокусом не становится.** Ровно из-за таких «здесь ты
теряешь время» коуч и выглядел бесполезным: указание без применимого действия
не отличается от молчания, а раздражает сильнее.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.coach_ai.cost import CornerCost
from core.num_to_words import ru_plural

#: Сколько раз срыв должен повториться, чтобы стать ПРИЧИНОЙ потери. Три — то же
#: число, которым `core/coach_ai/repeat.py` отличает привычку от случая; здесь
#: оно считается за сессию, а не в окне кругов, потому что диагноз подводит итог,
#: а не решает, когда открыть рот.
#:
#: Заметно ниже, чем `setup_advice.MIN_OCCURRENCES = 6`, и это осознанно: назвать
#: причину дешевле, чем полезть в настройки машины, — ошибка диагноза стоит
#: одной неверной фразы, ошибка сетапа портит весь следующий заезд.
MIN_MISTAKE_OCCURRENCES = 3

#: Отклонение техники считается причиной, только если оно перешагнуло порог
#: значимости своей метрики (`compare.METRICS`). Единица — это и есть порог.
MIN_TECHNIQUE_RATIO = 1.0

#: Виды срывов словами — для экрана, не для эфира. В эфире те же ситуации
#: озвучивает банк фраз (`core/radio/phrases.py`, спеки `coach.*`), и второй
#: копии формулировок здесь нет намеренно.
MISTAKE_RU: dict[str, str] = {
    "lockup": "блокировка колёс на торможении",
    "wheelspin": "пробуксовка на выходе",
    "understeer": "снос передней оси",
    "oversteer": "занос задней оси",
    "offtrack": "выезд за пределы трассы",
}

TECHNIQUE_RU: dict[str, str] = {
    "brake": "тормозишь раньше, чем в своём лучшем круге",
    "min_speed": "проходишь апекс медленнее, чем умеешь",
    "throttle": "открываешь газ позже, чем в своём лучшем круге",
}


@dataclass
class CornerDiagnosis:
    """Поворот, его цена и — если она известна — причина."""
    corner_id: int
    corner_name: str | None
    cost_ms: float
    share: float
    laps: int
    cause: str | None          # вид срыва либо метрика техники
    cause_kind: str | None     # "mistake" | "technique"
    occurrences: int           # для срыва — сколько раз за сессию
    evidence: str              # основание, на котором стоит вывод

    @property
    def actionable(self) -> bool:
        """Есть ли что делать. Только такой поворот может стать работой сессии."""
        return self.cause is not None

    def to_dict(self) -> dict:
        return {
            "corner_id": self.corner_id, "corner_name": self.corner_name,
            "cost_ms": round(self.cost_ms), "share": round(self.share, 3),
            "laps": self.laps, "cause": self.cause, "cause_kind": self.cause_kind,
            "occurrences": self.occurrences, "evidence": self.evidence,
        }


def diagnose(costs: list[CornerCost], mistakes: list[dict],
             badness: dict[int, dict[str, float]] | None = None,
             ) -> list[CornerDiagnosis]:
    """Диагноз по каждому оценённому повороту, в том же порядке — от дорогого.

    `mistakes` — плоская карта сессии (`CornerLog.map_rows()`).
    `badness` — рутинные отклонения техники (`CornerHistory.metric_badness()`).
    """
    per_corner = _mistakes_by_corner(mistakes)
    badness = badness or {}
    out: list[CornerDiagnosis] = []
    for row in costs:
        cause, kind, occurrences, evidence = _cause_for(
            row.corner_id, per_corner, badness.get(row.corner_id, {}))
        out.append(CornerDiagnosis(
            corner_id=row.corner_id, corner_name=row.corner_name,
            cost_ms=row.cost_ms, share=row.share, laps=row.laps,
            cause=cause, cause_kind=kind, occurrences=occurrences,
            evidence=evidence))
    return out


def _cause_for(corner_id: int, per_corner: dict[int, dict[str, int]],
               badness: dict[str, float],
               ) -> tuple[str | None, str | None, int, str]:
    kinds = per_corner.get(corner_id) or {}
    if kinds:
        kind, count = max(kinds.items(), key=lambda pair: (pair[1], pair[0]))
        if count >= MIN_MISTAKE_OCCURRENCES:
            return (kind, "mistake", count,
                    f"{MISTAKE_RU.get(kind, kind)} — {count} "
                    f"{ru_plural(count, 'раз', 'раза', 'раз')} за сессию")

    if badness:
        metric, ratio = max(badness.items(), key=lambda pair: (pair[1], pair[0]))
        if ratio >= MIN_TECHNIQUE_RATIO:
            return (metric, "technique", 0,
                    TECHNIQUE_RU.get(metric, metric))

    # Причины нет — и это честный результат, а не пробел. Такой поворот попадёт в
    # разбор как факт («здесь уходит время»), но работой сессии не станет.
    return None, None, 0, ""


def _mistakes_by_corner(mistakes: list[dict]) -> dict[int, dict[str, int]]:
    out: dict[int, dict[str, int]] = {}
    for row in mistakes or ():
        corner_id = row.get("corner_id")
        kind = row.get("kind")
        if corner_id is None or not kind:
            continue
        per_kind = out.setdefault(int(corner_id), {})
        per_kind[str(kind)] = per_kind.get(str(kind), 0) + 1
    return out
