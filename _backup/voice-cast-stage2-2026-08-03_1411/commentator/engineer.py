"""
commentator/engineer.py
========================
Template-only engineer messages for race_ai events. No LLM. Max 20 words.

The wording is selected from context-specific shuffle bags.  A driver can hear
the same tactical fact several times without the engineer reciting the same
sentence or cadence on every visit to a corner.
"""
from __future__ import annotations

from commentator.phrase_pool import pick_phrase

_MESSAGES: dict[str, list[str]] = {
    "attack": [
        "{driver} атакует. DRS активен. Защищай позицию.",
        "{driver} рядом. Готовься к защите.",
        "Смотри в зеркала — {driver} давит.",
        "{driver} на хвосте. Держи линию.",
        "Соперник в пределах секунды. Прикрой внутреннюю.",
        "Давление сзади растёт. Выноси скорость из поворота.",
        "Разрыв тает. Без ошибок на выходе.",
        "Машина сзади близко — защита на следующем торможении.",
    ],
    "attack_high": [
        "{driver} на крыле! Немедленно защищай.",
        "Атака! Держи позицию, закрой внутреннюю.",
        "Срочно! {driver} атакует — не давай пространства.",
        "Соперник рядом на торможении! Закрывай дверь.",
        "Максимальная защита — обгон начинается сейчас.",
        "{driver} уже рядом. Одна машина ширины, не больше.",
    ],
    "battle": [
        "Борьба продолжается. Сохраняй темп.",
        "{driver} не уходит. Контролируй зеркала.",
        "Держи его за спиной.",
        "Плотная борьба. Не рискуй.",
        "Колесо в колесо — береги шины и нервы.",
        "{driver} терпелив. Не открывай внутреннюю на торможении.",
        "Размен ещё не закончен. Сохраняй чистую траекторию.",
    ],
    "tyre_warning": [
        "Пора заезжать в боксы. Шины на исходе.",
        "Износ критический. Думаем о пит-стопе.",
        "Резина сдаётся — темп уже не тот, готовь заезд.",
        "Шины за пределом окна. Дальше будет только хуже.",
        "Сцепление уходит. Не перегружай машину на входе.",
        "Температура и износ растут. Береги заднюю ось.",
    ],
    "final_lap": [
        "Финальные круги. Максимальный темп.",
        "Последние круги — выжми всё.",
        "Концовка. Всё, что осталось — отдай сейчас.",
        "Финал близко. Без ошибок, держи давление.",
        "Решающая часть заезда. Работай до самого флага.",
        "Осталось совсем немного. Чисто на торможениях.",
    ],
    "stable": [
        "Отрыв стабилен.",
        "Ситуация под контролем.",
        "Темп ровный. Держим как есть.",
        "Спокойно. Дистанция под контролем.",
        "Баланс хороший. Продолжай в этом ритме.",
        "План работает. Не меняй подход.",
    ],
}

_TRACK_MESSAGES: dict[str, list[str]] = {
    "attack_inside": [
        "{driver} атакует перед {corner}. Закрой внутреннюю.",
        "Перед {corner} будет атака. Защити внутреннюю линию.",
        "{corner}: {driver} ныряет внутрь. Закрывай дверь.",
        "Готовь защиту в {corner}. Внутреннюю не отдавай.",
    ],
    "attack_hold": [
        "{driver} атакует. {corner} — держи линию.",
        "В {corner} оставайся на своей траектории.",
        "{corner}: без резких движений, линия твоя.",
        "Атака перед {corner}. Спокойно держи выбранную линию.",
    ],
    "attack_drs": [
        "{driver} с DRS атакует перед {corner}. Защищайся.",
        "DRS у {driver}. В {corner} жди атаку.",
        "Перед {corner} соперник идёт с открытым крылом.",
        "{corner}: преимущество DRS у соперника, готовь защиту.",
    ],
    "attack_braking": [
        "{driver} атакует на торможении перед {corner}.",
        "Торможение в {corner}: соперник уже рядом.",
        "Перед {corner} поздняя атака. Оставь себе выход.",
        "{driver} ныряет в {corner}. Контролируй апекс.",
    ],
    "attack_approach": [
        "{driver} атакует перед {corner}. Защищайся.",
        "Давление перед {corner}. Подготовь хороший выход.",
        "{corner} впереди, соперник близко. Не открывай траекторию.",
        "К {corner} подъезжаем под атакой. Держи позицию.",
    ],
    "battle_braking": [
        "Борьба перед {corner}. Держи позицию.",
        "{corner}: тормозим бок о бок, оставь пространство.",
        "Перед {corner} плотная борьба. Не сорви передние шины.",
        "Соперник рядом в {corner}. Чисто пройди апекс.",
    ],
    "battle_line": [
        "Борьба. {corner} — держи линию.",
        "В {corner} вы рядом. Сохраняй траекторию.",
        "{corner}: позиционная борьба продолжается.",
        "До {corner} машина рядом. Выход важнее входа.",
    ],
}

_DATA_MESSAGES: dict[str, list[str]] = {
    "attack_gap": [
        "{driver} в {gap} секунды. Готовь защиту.",
        "Разрыв {gap}. {driver} сокращает дистанцию.",
        "Сзади {driver}, отрыв {gap}. Держи выходы чистыми.",
        "{gap} до машины сзади. Следующее торможение — защита.",
    ],
    "tyre_wear": [
        "Износ {wear} процентов. Сцепление будет падать.",
        "Шины: {wear} процентов износа. Избегай скольжения.",
        "Износ уже {wear}. Береги резину до боксов.",
        "{wear} процентов по шинам. Смягчи входы в поворот.",
    ],
    "laps_left": [
        "Осталось {laps} круга. Максимальный темп.",
        "{laps} круга до флага. Без ошибок.",
        "Финиш через {laps} круга. Используй всё, что осталось.",
        "Последние {laps} круга. Работай до клетчатого флага.",
    ],
}


def _pick(pool: list[str], key: str) -> str:
    """Draw every line once before any line in this context repeats."""
    return pick_phrase(pool, f"engineer:{key}")


def _render(pool: list[str], key: str, **values: object) -> str:
    return _pick(pool, key).format(**values)


def get_message(event_type: str, data: dict | None = None) -> str:
    """Return a random template message for the given race_ai event type.

    When track context is present (data["track"]), uses track-aware phrasing.
    High-confidence attacks get a more urgent variant.
    Falls back to 'stable' message for unknown types.
    """
    data = data or {}
    confidence = data.get("confidence", 0.5)
    track = data.get("track") or {}
    corner = track.get("corner")
    phase  = track.get("phase", "straight")
    advice = track.get("defense_advice", "none")
    driver = data.get("driver", "Соперник")
    drs    = data.get("drs", False)

    values = {"driver": driver, "corner": corner or "поворот"}

    if event_type == "attack" and corner:
        if phase in ("braking", "entry"):
            if advice in ("inside", "cover_inside"):
                key = "attack_inside"
            elif advice == "hold_line":
                key = "attack_hold"
            elif drs:
                key = "attack_drs"
            else:
                key = "attack_braking"
        else:
            key = "attack_drs" if drs else "attack_approach"
        return _render(_TRACK_MESSAGES[key], key, **values)

    if event_type == "battle" and corner:
        key = "battle_braking" if phase in ("braking", "entry") else "battle_line"
        return _render(_TRACK_MESSAGES[key], key, **values)

    gap = data.get("gap")
    if event_type == "attack" and gap is not None:
        return _render(
            _DATA_MESSAGES["attack_gap"], "attack_gap",
            driver=driver, gap=f"{float(gap):.1f}",
        )

    wear = data.get("wear")
    if event_type == "tyre_warning" and wear is not None:
        return _render(
            _DATA_MESSAGES["tyre_wear"], "tyre_wear",
            wear=int(round(float(wear))),
        )

    laps = data.get("laps_remaining")
    if event_type == "final_lap" and laps in (2, 3):
        return _render(_DATA_MESSAGES["laps_left"], "laps_left", laps=int(laps))

    if event_type == "attack" and confidence > 0.75:
        pool = _MESSAGES.get("attack_high", _MESSAGES["attack"])
        key = "attack_high"
    else:
        pool = _MESSAGES.get(event_type, _MESSAGES["stable"])
        key = event_type if event_type in _MESSAGES else "stable"

    return _render(pool, key, driver=driver)
