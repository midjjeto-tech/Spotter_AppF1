"""
core/radio/situations.py
==========================
Два ключа с РАЗНЫМ смыслом. Их постоянно путают, поэтому разница здесь, в шапке.

`situation_id` — личность продолжающейся ситуации. Одна фаза Safety Car, одно
окно box-call, одно повреждение, одна борьба с конкретным соперником. Нужен,
чтобы ситуацию можно было обновить, усилить и закрыть, и чтобы UI мог
сгруппировать связанные реплики.

`dedupe_key` — личность КОНКРЕТНОГО ВЫСКАЗЫВАНИЯ об этой ситуации. Совпал в
пределах cooldown → молчим. Не совпал при том же `situation_id` → произошло
смысловое изменение, говорим снова.

Почему нельзя обойтись одним ключом: `SAFETY_CAR_DEPLOYED` / `_ENDING` /
`_CLEAR` — это одна ситуация (ТЗ §9: «одна фаза Safety Car»), но три разных
факта. Дедуп по `situation_id` проглотил бы два из трёх, и пилот не узнал бы,
что трасса снова чистая. То же с эскалацией box-call: три tier'а — одно окно,
но три намеренно разных высказывания.

Этот модуль НЕ заменяет `core/situation_dedup.py`. Тот — рабочий дедуп
proximity-событий с собственным cooldown; здесь считаются ключи, которыми он
(и остальные категории, которых у него нет) сможет пользоваться. Логика band'а
гэпа сознательно переиспользует `situation_dedup.gap_band`, чтобы «смысловое
изменение дистанции» осталось одним понятием на весь проект.
"""
from __future__ import annotations

from collections.abc import Mapping

from core.radio.plumbing import field as _plumbing_field
from core.situation_dedup import gap_band

# Кириллица → ASCII для идентификаторов. Это НЕ фонетическая транслитерация:
# core/transliterate.py существует для произношения (латиница → кириллица на
# пути в TTS) и решает другую задачу. Здесь нужен стабильный, различающий,
# читаемый в логе слаг — «Ферстаппен» → «ferstappen» этого достаточно, обратный
# маппинг на типографски верное Verstappen не нужен и был бы вторым словарём
# имён, который пришлось бы поддерживать синхронно.
_CYR_TO_LAT: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

_DAMAGE_PART: dict[str, str] = {
    "DAMAGE_WING": "front_wing",
    "DAMAGE_FLOOR": "floor",
    "DAMAGE_GEARBOX": "gearbox",
    "DAMAGE_ENGINE": "engine",
}

_SPOTTER_SIDE: dict[str, str] = {
    "SPOTTER_CAR_LEFT": "left",
    "SPOTTER_CAR_RIGHT": "right",
    "SPOTTER_CAR_BOTH": "both",
    "SPOTTER_CLEAR": "clear",
}

_SAFETY_CAR_STAGE: dict[str, str] = {
    "SAFETY_CAR_DEPLOYED": "deployed",
    "SAFETY_CAR_ENDING": "ending",
    "SAFETY_CAR_CLEAR": "clear",
}

_BOX_CALL_CODES: frozenset[str] = frozenset({
    "STRAT_BOX_CALL_1", "STRAT_BOX_CALL_2", "STRAT_BOX_CALL_3", "PIT_CALL_NOTICE",
})

_BATTLE_CODES: frozenset[str] = frozenset({
    "BATTLE", "ATTACK", "ATTACK_ZONE", "OVTK", "DEFENSE",
})

_WEATHER_CODES: frozenset[str] = frozenset({"ENGINEER_RAIN_ADVISORY"})

_PENALTY_CODES: frozenset[str] = frozenset({"PENA", "ENGINEER_PENA_TRACK_LIMITS"})

_UNKNOWN = "unknown"


def slug(value: object) -> str:
    """Кириллица/латиница/пробелы → стабильный ASCII-слаг для идентификатора."""
    text = str(value or "").strip().lower()
    if not text:
        return _UNKNOWN
    out: list[str] = []
    for char in text:
        if char in _CYR_TO_LAT:
            out.append(_CYR_TO_LAT[char])
        elif char.isalnum() and char.isascii():
            out.append(char)
        elif char in " -_":
            out.append("_")
        # всё остальное (пунктуация, диакритика вне карты) отбрасываем
    result = "".join(out).strip("_")
    while "__" in result:
        result = result.replace("__", "_")
    return result or _UNKNOWN


def _lap_part(lap: int | None) -> str:
    return f"lap_{lap}" if lap is not None else "lap_unknown"


def _rival(event: Mapping[str, object]) -> str:
    """Имя соперника из события. `target` — сторона, против которой борьба;
    `driver` — резерв (у части кодов заполнено только оно)."""
    return slug(event.get("target") or event.get("driver"))


def situation_id(
    event: Mapping[str, object],
    *,
    lap: int | None = None,
    session_id: str | None = None,
) -> str | None:
    """Личность продолжающейся ситуации, либо None.

    None означает «это самостоятельная новость» (финиш, рекорд круга, старт) —
    её не нужно ни группировать, ни закрывать, ни дедупить по ситуации.

    `session_id` — стабильная идентичность заезда, добавляется префиксом. Без
    неё локальные счётчики трекеров (`front_id`, `window_id`) сталкивались бы
    между гонками: первый погодный фронт гонки B получил бы тот же
    `weather:rain_front_1`, что и первый фронт гонки A, и дедуп счёл бы его
    повтором уже закрытой ситуации. Полагаться на то, что процессный счётчик
    только растёт, нельзя — он сбрасывается вместе с процессом, а история и
    архив живут дольше.
    """
    base = _situation_body(event, lap=lap)
    if base is None:
        return None
    return f"{session_id}:{base}" if session_id else base


def _situation_body(
    event: Mapping[str, object],
    *,
    lap: int | None = None,
) -> str | None:
    code = str(event.get("event_code") or "")

    if code in _SPOTTER_SIDE:
        side = _SPOTTER_SIDE[code]
        neighbour = _plumbing_field(event, "neighbour_idx")
        target = f"vehicle_{neighbour}" if neighbour is not None else _UNKNOWN
        return f"spotter:{side}:{target}"

    if code in _DAMAGE_PART:
        return f"damage:{_DAMAGE_PART[code]}:{_lap_part(lap)}"

    if code in _BOX_CALL_CODES:
        window = _plumbing_field(event, "box_call_window")
        suffix = window if window is not None else _lap_part(lap)
        return f"box_call:window_{suffix}"

    if code in _WEATHER_CODES:
        front = _plumbing_field(event, "rain_front_id")
        return f"weather:rain_front_{front if front is not None else _UNKNOWN}"

    if code in _BATTLE_CODES:
        return f"battle:{_rival(event)}:{_lap_part(lap)}"

    if code in _SAFETY_CAR_STAGE:
        episode = _plumbing_field(event, "sc_episode")
        return f"safety_car:episode_{episode if episode is not None else _UNKNOWN}"

    if code in _PENALTY_CODES:
        # Один штрафной эпизод. `penalty_id` от игры нет, поэтому эпизод — это
        # круг: два разных штрафа на одном круге сольются в один эпизод, и это
        # правильнее обратной ошибки (повторное объявление того же штрафа при
        # повторной телеметрии).
        return f"penalty:{_lap_part(lap)}"

    if code == "USER_Q":
        # Один запрос пилота. Уникален по времени: два одинаковых вопроса —
        # это два законных запроса, а не повтор одной ситуации.
        asked_at = _plumbing_field(event, "asked_at")
        return f"driver_request:{asked_at if asked_at is not None else _UNKNOWN}"

    return None


def dedupe_key(
    event: Mapping[str, object],
    *,
    lap: int | None = None,
    session_id: str | None = None,
    timeline_revision: int = 0,
) -> str | None:
    """Личность конкретного ВЫСКАЗЫВАНИЯ о ситуации, либо None.

    None (нет ситуации) означает «дедуп по ситуации не применим» — вызывающий
    обязан трактовать это как «говорить», а не как «молчать».

    `timeline_revision` растёт на каждом флэшбеке и входит ТОЛЬКО в этот ключ, не
    в `situation_id`. Разница принципиальная: физический погодный фронт после
    перемотки остался тем же самым, и дробить его историю нельзя — а вот
    предупреждение о нём пилот не слышал и должен услышать снова. Один ключ на
    оба смысла не работает: общий заблокировал бы повтор, а общий без ревизии
    раздробил бы физическую ситуацию.
    """
    base = situation_id(event, lap=lap, session_id=session_id)
    if base is None:
        return None
    if timeline_revision:
        base = f"{base}:r{timeline_revision}"

    code = str(event.get("event_code") or "")

    if code in _SAFETY_CAR_STAGE:
        return f"{base}:{_SAFETY_CAR_STAGE[code]}"

    if code in _BOX_CALL_CODES:
        # Эскалация 1→2→3 — намеренно разные высказывания об одном окне.
        return f"{base}:{code.lower()}"

    if code in _BATTLE_CODES:
        # Смена band'а дистанции = материальное изменение, колебания внутри
        # band'а — нет. Та же семантика, что в core/situation_dedup.py.
        band = gap_band(_gap_ms(event))
        return f"{base}:{band or 'noband'}"

    if code in _SPOTTER_SIDE:
        # Состояние «машина рядом» либо есть, либо снято — сам код это и несёт,
        # он уже в base. Повторная телеметрия обязана дать тот же ключ.
        return base

    return base


def _gap_ms(event: Mapping[str, object]) -> int | None:
    raw = event.get("gap_ms")
    if raw is None:
        return None
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
