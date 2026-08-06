"""
core/radio/plumbing.py
========================
Служебные поля радио-конвейера живут в ОДНОМ вложенном пространстве
`event["radio"]`, а не рассыпаны по корню события.

Зачем namespace, а не пять отдельных ключей. Эти значения (номер эпизода SC,
номер окна box-call, номер погодного фронта, индекс соседней машины) существуют
только для того, чтобы сообщение узнало свою ситуацию. За пределы конвейера им
нельзя: словарь события целиком попадает в `Event.extra` → `facts` → промпт LLM
и в `claim_fingerprint` RaceFeed. Пять ключей в корне — это пять шансов забыть
один из них в фильтре и пять будущих правок фильтра при добавлении шестого.
Одно namespaced-поле фильтруется один раз и навсегда.

`damage_severity` СОЗНАТЕЛЬНО живёт в корне, а не здесь: «крыло разбито на 45%»
— настоящий факт о гонке, ему место и в ленте, и в тексте репортёра. Здесь
только то, что пользователю показывать нечего.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Ключ вложенного пространства в словаре события.
PLUMBING_KEY = "radio"

_EMPTY: Mapping[str, Any] = {}


def plumbing(event: Mapping[str, Any]) -> Mapping[str, Any]:
    """Служебные поля события, либо пустой mapping.

    Никогда не бросает и никогда не возвращает None: у большинства событий этого
    пространства нет, и вызывающий код не должен обрастать проверками."""
    value = event.get(PLUMBING_KEY)
    return value if isinstance(value, Mapping) else _EMPTY


def field(event: Mapping[str, Any], name: str, default: Any = None) -> Any:
    """Одно служебное поле события."""
    return plumbing(event).get(name, default)


def attach(**fields: Any) -> dict[str, Any]:
    """Фрагмент драфта со служебными полями: `{**draft, **attach(sc_episode=1)}`.

    Значения `None` отбрасываются — «поля нет» и «поле равно None» для
    situation_id одно и то же, а пустой ключ в словаре только мешает читать лог.
    """
    payload = {name: value for name, value in fields.items() if value is not None}
    return {PLUMBING_KEY: payload} if payload else {}
