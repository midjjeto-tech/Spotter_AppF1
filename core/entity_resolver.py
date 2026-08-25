"""
core/entity_resolver.py
========================
Human-readable name resolution for events.

These functions are the commentary layer's public API over race_state.driver().
They never return bare car numbers — fall back to Russian generic labels instead.
"""
from __future__ import annotations

from core.f1_metadata import roster_by_number

_GENERIC_DRIVER = "гонщик"
_GENERIC_TEAM = "команда"
_GENERIC_OPPONENT = "соперник"

# Placeholders that indicate the name wasn't resolved yet — bypass and try number lookup
_UNRESOLVED_DRIVER = {"гонщик", "пилот", ""}


#: Обобщённые метки соперника: для банка фраз «соперник» — такой же
#: неразрешённый плейсхолдер, как «гонщик».
_UNRESOLVED_ANY = _UNRESOLVED_DRIVER | {_GENERIC_OPPONENT}


def is_unresolved_name(name: object) -> bool:
    """Является ли имя служебной заглушкой, а не именем пилота.

    Один источник правды на два слоя: резолвер этими словами СООБЩАЕТ о
    неудаче, а банк фраз по ним решает, что имя произносить нельзя. Держать
    список в двух местах значит однажды разойтись и снова выпустить «гонщик»
    в эфир."""
    if not isinstance(name, str):
        return True
    stripped = name.strip()
    return not stripped or stripped.startswith("#") or stripped in _UNRESOLVED_ANY


def resolve_driver_name(event: dict, game_year: int = 0) -> str:
    """Return human-readable driver name from event dict.

    Resolution order:
    1. event["driver"] if it's a real name (not empty, not "#N", not generic label)
    2. roster_by_number(game_year) lookup by event["number"] or event["driver_number"]
    3. Extract number from "#N" placeholder and lookup
    4. Generic fallback "гонщик"

    game_year (Engine._game_year, 0 = неизвестно) выбирает сезонный ростер —
    номера машин переиспользуются между сезонами (Ферстаппен 1->3 в 2026),
    поэтому без сезона нельзя резолвить по номеру однозначно.
    """
    name: str = event.get("driver") or ""
    if name and not name.startswith("#") and name not in _UNRESOLVED_DRIVER:
        return name

    roster = roster_by_number(game_year)
    for key in ("number", "driver_number"):
        raw = event.get(key)
        if raw is not None:
            try:
                static = roster.get(int(raw))
                if static:
                    return static[0]
            except (TypeError, ValueError):
                pass

    # Try to extract number from "#N" placeholder
    if name.startswith("#"):
        try:
            num = int(name[1:])
            static = roster.get(num)
            if static:
                return static[0]
        except (ValueError, IndexError):
            pass

    return _GENERIC_DRIVER


def resolve_team_name(event: dict) -> str:
    """Return human-readable team name from event dict.

    Falls back to "команда" if unavailable or placeholder.
    """
    team: str = event.get("team") or ""
    if team and not team.startswith("#"):
        return team
    return _GENERIC_TEAM


_UNRESOLVED_OPPONENT = {"соперник", "пилот", ""}


def resolve_opponent_name(event: dict) -> str:
    """Return human-readable opponent/target name from event dict.

    Uses event["target"]; falls back to "соперник".
    """
    target: str = event.get("target") or ""
    if target and not target.startswith("#") and target not in _UNRESOLVED_OPPONENT:
        return target
    return _GENERIC_OPPONENT
