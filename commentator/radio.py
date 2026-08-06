"""
commentator/radio.py
=====================
Короткие реплики кабинного радио.

Собственных пулов здесь больше НЕТ: формулировки живут в едином банке
`core/radio/phrases.py`, этот модуль остался тонкой картой
`event_code -> semantic code` для канала CHANNEL_RADIO.

Почему пулы убраны. Их было два на одни и те же коды: `get_radio_line`
вызывается в `_commentary_loop` РАНЬШЕ `strategist.get_message`, поэтому для
STRAT_*, которые маршрутизируются в radio, второй пул был недостижим. Плюс
восемь пулов (ATTACK, ATTACK_ZONE, PIT_IN, PIT_OUT, PUSH_LAP, QUALI_LAP, SSTA,
TYRE_CLIFF) не маршрутизировались в radio НИ В ОДНОМ типе сессии — то есть
пятьдесят фраз не могли прозвучать никогда. Единый банк делает такие дыры
видимыми: спека без кода-источника всплывает на тесте связности.
"""
from __future__ import annotations

from core.radio import phrases

#: event_code -> semantic code банка. Только коды, которые `channel_router`
#: реально отправляет в CHANNEL_RADIO (`_RADIO_IN_RACE`). Расхождение с этим
#: набором ловится тестом.
_RADIO_CODE: dict[str, str] = {
    "DRSE": "drs.enabled",
    "DRSD": "drs.disabled",
    "TYRE_WARN": "tyres.wear",
    "STRAT_PIT": "strategy.pit_window",
    "STRAT_UNDERCUT": "strategy.undercut",
    "STRAT_OVERCUT": "strategy.overcut",
    "STRAT_SAVE": "strategy.tyre_save",
    "STRAT_PUSH": "strategy.push_pace",
    "STRAT_FUEL": "fuel.save",
}


#: race_ai event_type -> semantic code банка для случая БЕЗ привязки к трассе.
#: Раньше эти ситуации обслуживал второй банк `commentator/engineer.py` — со
#: своими пулами, своим лимитом длины (20 слов против 9–18) и без единого
#: инварианта общего банка. Он был достижим только при отказе LLM, поэтому
#: манера речи менялась ровно тогда, когда что-то ломалось, и заметить это по
#: логам было нельзя.
_RACE_AI_CODE: dict[str, str] = {
    "attack": "battle.defend",
    "battle": "battle.defend",
    "tyre_warning": "tyres.cliff",
    "final_lap": "session.final_laps",
    "stable": "strategy.stable",
}

#: Фазы поворота, в которых атака уже происходит, а не только назревает.
_ACTIVE_PHASES: frozenset[str] = frozenset({"braking", "entry"})


def _corner_code(event_type: str, phase: str, advice: str, drs: bool) -> str:
    """Какой СОВЕТ уместен в этом повороте.

    Решение принимается здесь, а не в банке, и не одним общим пулом. Закрыть
    внутреннюю, держать линию и сохранить выход — это разные УКАЗАНИЯ, и если
    сложить их в один пул, выбор совета начнёт делать колода: пилот получит
    «сохрани выход» там, где нужно было «закрой дверь».

    Правила перенесены из `commentator/engineer.py::get_message` (модуль удалён)
    без изменений: приоритет у явного `defense_advice`, затем DRS, затем фаза.
    """
    if event_type == "battle":
        return ("battle.corner_braking" if phase in _ACTIVE_PHASES
                else "battle.corner_line")
    if phase in _ACTIVE_PHASES:
        if advice in ("inside", "cover_inside"):
            return "battle.defend_corner_inside"
        if advice == "hold_line":
            return "battle.defend_corner_hold"
        if drs:
            return "battle.defend_corner_drs"
        return "battle.defend_corner_braking"
    return "battle.defend_corner_approach"


def race_ai_phrase(event_type: str, data: dict | None = None,
                   selector_key: str | None = None) -> str:
    """Реплика банка для события race_ai. Пустая строка, если собрать нечего.

    Заменяет `commentator/engineer.py::get_message`. Решение «какая сейчас
    ситуация» принимается ЗДЕСЬ, у вызывающего, а не в банке: банк отвечает на
    вопрос «как коротко сказать», а не «есть ли впереди поворот и в какой он
    фазе» (то же разделение, что во всём `core/radio/`).

    Отсутствие названия поворота не роняет реплику — берётся вариант без
    привязки к трассе. Промолчать здесь хуже, чем сказать общее: это фолбэк, он
    срабатывает в момент, когда что-то уже пошло не так.

    Износ шин сознательно уходит в `tyres.cliff` БЕЗ числа: точное значение —
    волатильное поле, оно связывается поздно, у порога озвучки
    (`core/radio/resolver.py`). Подставить его здесь значило бы назвать пилоту
    цифру, снятую за десятки секунд до звука. Число по шинам доезжает своим
    путём — через радио-канал (`_RADIO_CODE`), где резолвер обновляет его перед
    самой озвучкой.
    """
    data = data or {}
    rival = str(data.get("driver") or "").strip() or "Соперник"
    track = data.get("track") or {}
    corner = track.get("corner")

    if event_type in ("attack", "battle") and corner:
        code = _corner_code(event_type, track.get("phase", "straight"),
                            track.get("defense_advice", "none"),
                            bool(data.get("drs")))
        fields = {"rival": rival, "corner": str(corner)}
    else:
        code = _RACE_AI_CODE.get(event_type, _RACE_AI_CODE["stable"])
        fields = {"rival": rival} if code == "battle.defend" else {}

    try:
        return phrases.render(code, fields,
                              selector_key=selector_key or f"race_ai:{event_type}")
    except phrases.PhraseError:
        return ""


def radio_phrase_code(event_code: str) -> str | None:
    """Semantic code банка для события радио-канала, либо None."""
    return _RADIO_CODE.get(event_code)


def get_radio_line(event_code: str, selector_key: str | None = None) -> str | None:
    """Короткая радио-реплика для события, либо None.

    `selector_key` — стабильный ключ выбора варианта (обычно `dedupe_key`
    сообщения). Без него вариант закрепляется за КОДОМ, то есть одна и та же
    формулировка на всю сессию — прежнее поведение, сохранено для вызывающих,
    которым нечего передать."""
    code = _RADIO_CODE.get(event_code)
    if code is None:
        return None
    try:
        return phrases.render(code, selector_key=selector_key or f"radio:{event_code}")
    except phrases.PhraseError:
        return None
