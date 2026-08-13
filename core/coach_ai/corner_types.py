"""
core/coach_ai/corner_types.py
==============================
Потеря по ТИПАМ поворотов — и что из этого следует про машину.

Разметка типов лежит в `tracks/*.json` с самого начала (325 поворотов на 24
трассах: 154 medium, 57 slow, 56 fast, 33 chicane, 25 hairpin) и до сих пор
работала только на споттера — сторону атаки и зону обгона. Коуч её не видел.

Разница принципиальная. «Теряешь в седьмом» — это про поворот, и лечится он
техникой. «Теряешь во ВСЕХ медленных» — это уже подпись машины: одинаковая
проблема в непохожих местах трассы техникой не объясняется.

**Отсюда же берётся то, чего фазе 3 не хватило для советов по гаражу.** Там
советы сознательно ограничили тремя связками: «эффект крыльев и подвески в F1 25
нелинеен и зависит от трассы, причинной модели у нас нет, а догадку пилот не
отличит от обоснованного вывода». Тип поворота даёт ровно ту причинную модель,
которой не было, — но только для ОДНОГО вывода, зато учебникового:

    снос/занос держится на МЕДЛЕННЫХ поворотах  → механический баланс
    снос/занос держится на БЫСТРЫХ поворотах    → аэродинамический баланс

Прижимная сила растёт с квадратом скорости: на медленных её почти нет, и там
машину держит механика — дифференциал, стабилизаторы, жёсткость. На быстрых
наоборот. Поэтому одно и то же поведение в разных скоростных диапазонах имеет
РАЗНЫЕ причины, и это не догадка, а физика.

**Числа мы по-прежнему не называем.** Модуль говорит, КУДА смотреть, и не
говорит, на сколько щёлкать: величина зависит от трассы и от того, что уже стоит
в сетапе, и здесь ограничение фазы 3 остаётся в силе.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.coach_ai.diagnosis import CornerDiagnosis

#: Меньше поворотов этого типа на трассе — говорить о «всех медленных» нельзя:
#: два поворота это не закономерность, а два поворота.
MIN_CORNERS_FOR_PATTERN = 3

#: Какая доля поворотов типа должна нести проблему, чтобы это была подпись
#: машины, а не одно плохое место. Больше половины — и с запасом.
PATTERN_SHARE = 0.6

#: Виды срывов, у которых скоростной диапазон вообще что-то означает.
#: Блокировка и пробуксовка сюда не входят: они про педали, а не про баланс.
BALANCE_KINDS = ("understeer", "oversteer")

#: Тип поворота -> скоростной диапазон. Шикана идёт к медленным (её проходят на
#: скорости медленного поворота), «medium» не относится ни к одному: там работают
#: оба механизма сразу, и разделить их нельзя.
_DOMAIN_BY_TYPE: dict[str, str] = {
    "hairpin": "mechanical",
    "slow": "mechanical",
    "chicane": "mechanical",
    "fast": "aero",
}

_DOMAIN_RU = {
    "mechanical": "механический баланс",
    "aero": "аэродинамический баланс",
}

_KIND_RU = {
    "understeer": "снос передней оси",
    "oversteer": "занос задней оси",
}

#: Два разных падежа для двух разных конструкций, и одним словарём тут не
#: обойтись. Первая версия обслуживала обе именительной формой и давала
#: «в 3 из 4 медленных ПОВОРОТАХ» — тесты на подстроку «3 из 4» это пропустили,
#: нашлось чтением вывода.
#:
#: `_TYPE_NAME` — заголовок строки на экране («медленные повороты»);
#: `_TYPE_GEN`  — родительный после счётного оборота («3 из 4 медленных
#: поворотов»).
_TYPE_NAME = {
    "hairpin": "шпильки", "slow": "медленные повороты",
    "chicane": "шиканы", "fast": "быстрые повороты",
    "medium": "повороты средней скорости",
}

_TYPE_GEN = {
    "hairpin": "шпилек", "slow": "медленных поворотов",
    "chicane": "шикан", "fast": "быстрых поворотов",
    "medium": "поворотов средней скорости",
}

_DOMAIN_ADVICE = {
    "mechanical": ("Смотри механический баланс — дифференциал, стабилизаторы, "
                   "жёсткость подвески."),
    "aero": "Смотри аэродинамический баланс — крылья и клиренс.",
}


@dataclass
class TypeLoss:
    """Сколько уходит по всем поворотам одного типа."""
    corner_type: str
    cost_ms: float
    corners: int
    share: float

    def to_dict(self) -> dict:
        return {
            "corner_type": self.corner_type, "cost_ms": round(self.cost_ms),
            "corners": self.corners, "share": round(self.share, 3),
            "label": _TYPE_NAME.get(self.corner_type, self.corner_type),
        }


@dataclass
class BalanceSignature:
    """Подпись машины: одинаковое поведение в непохожих местах трассы."""
    kind: str            # "understeer" | "oversteer"
    domain: str          # "mechanical" | "aero"
    corners_affected: int
    corners_total: int
    evidence: str
    advice: str

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "domain": self.domain,
            "corners_affected": self.corners_affected,
            "corners_total": self.corners_total,
            "evidence": self.evidence, "advice": self.advice,
        }


def by_corner_type(diagnoses: list[CornerDiagnosis],
                   types: dict[int, str]) -> list[TypeLoss]:
    """Потери, сгруппированные по типу поворота, от дорогого к дешёвому."""
    grouped: dict[str, list[CornerDiagnosis]] = {}
    for row in diagnoses:
        corner_type = types.get(row.corner_id)
        if not corner_type or row.cost_ms <= 0:
            continue
        grouped.setdefault(corner_type, []).append(row)

    total = sum(row.cost_ms for rows in grouped.values() for row in rows)
    if total <= 0:
        return []
    out = [
        TypeLoss(corner_type=corner_type,
                 cost_ms=sum(r.cost_ms for r in rows),
                 corners=len(rows),
                 share=sum(r.cost_ms for r in rows) / total)
        for corner_type, rows in grouped.items()
    ]
    out.sort(key=lambda t: (-t.cost_ms, t.corner_type))
    return out


def balance_signature(mistakes: list[dict],
                      types: dict[int, str]) -> BalanceSignature | None:
    """Держится ли снос (занос) на целом скоростном диапазоне, а не в одном
    месте. None — если закономерности нет, и это нормальный ответ.

    Считаются ПОВОРОТЫ, а не срывы: пять сносов в одной шпильке — это одна
    шпилька, а не механический баланс. Ровно на этой подмене строится
    большинство ложных советов по сетапу."""
    if not types:
        return None

    # Сколько поворотов КАЖДОГО типа вообще есть на трассе — знаменатель.
    total_by_type: dict[str, int] = {}
    for corner_type in types.values():
        total_by_type[corner_type] = total_by_type.get(corner_type, 0) + 1

    # Какие повороты какого типа несут проблему — числитель, по уникальным
    # поворотам.
    affected: dict[tuple[str, str], set[int]] = {}
    for row in mistakes or ():
        kind = row.get("kind")
        corner_id = row.get("corner_id")
        if kind not in BALANCE_KINDS or corner_id is None:
            continue
        corner_type = types.get(int(corner_id))
        if corner_type is None:
            continue
        affected.setdefault((str(kind), corner_type), set()).add(int(corner_id))

    best: BalanceSignature | None = None
    best_share = PATTERN_SHARE
    for (kind, corner_type), corners in affected.items():
        domain = _DOMAIN_BY_TYPE.get(corner_type)
        # «medium» намеренно вне разбора: там работают оба механизма сразу, и
        # разделить их нельзя. Молчание здесь честнее любого из двух ответов.
        if domain is None:
            continue
        total = total_by_type.get(corner_type, 0)
        if total < MIN_CORNERS_FOR_PATTERN:
            continue
        share = len(corners) / total
        if share < best_share:
            continue
        best_share = share
        best = BalanceSignature(
            kind=kind, domain=domain,
            corners_affected=len(corners), corners_total=total,
            evidence=(f"{_KIND_RU.get(kind, kind)} в {len(corners)} из {total} "
                      f"{_TYPE_GEN.get(corner_type, corner_type)}"),
            advice=_DOMAIN_ADVICE[domain])
    return best
