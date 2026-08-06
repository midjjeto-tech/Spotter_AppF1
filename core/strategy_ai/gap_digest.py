"""
core/strategy_ai/gap_digest.py
================================
Периодическая радио-сводка инженера по гэпам впереди/сзади — детерминированная,
без LLM. См. docs/superpowers/specs/2026-07-10-engineer-gap-digest-design.md.
"""
from __future__ import annotations

import re

TREND_THRESHOLD_MS = 300

# Заряд ERS — самое быстроменяющееся число во всём приложении: полный цикл
# разряд-заряд укладывается в один круг. Поэтому он НЕ вписывается сюда, а
# приходит фрагментом `ers.level` с волатильным токеном, который резолвер
# раскрывает на пороге озвучки (core/radio/resolver.py).
# Фрагменты банка (core/radio/phrases.py). Сводка не выбирается целиком, а
# СКЛЕИВАЕТСЯ: сторона × тренд плюс заряд плюс сравнение секторов. Собирает
# `phrases.compose()`, вызывает движок.
CODE_ERS = "ers.level"
_FRONT_CODE = {
    "first":   "gap.front_first",
    "closing": "gap.front_closing",
    "growing": "gap.front_growing",
    "stable":  "gap.front_stable",
}
_BEHIND_CODE = {
    "first":   "gap.behind_first",
    "closing": "gap.behind_closing",
    "growing": "gap.behind_growing",
    "stable":  "gap.behind_stable",
}

_TOKEN_RE = re.compile(r"\{(\w+)\}")


class GapDigestTracker:
    """Строит готовую фразу-сводку и хранит предыдущие гэпы для тренда."""

    def __init__(self) -> None:
        self._prev_front_ms: int | None = None
        self._prev_behind_ms: int | None = None

    def build(self, gap_front_ms: int | None, gap_behind_ms: int | None,
              ers_percent: float | None = None,
              sector_comparison: str | None = None) -> tuple[str, ...] | None:
        """Возвращает готовую фразу, либо None (нечего сказать). Батарея и
        сравнение секторов (docs/superpowers/plans/2026-07-20-session-history-
        sector-comparison.md) — только ДОПОЛНЕНИЯ к гэп-части, одни не
        запускают дайджест (spec п.3)."""
        codes: list[str] = []
        if gap_front_ms is not None and gap_front_ms > 0:
            codes.append(_FRONT_CODE[_trend(gap_front_ms, self._prev_front_ms)])
        if gap_behind_ms is not None and gap_behind_ms > 0:
            codes.append(_BEHIND_CODE[_trend(gap_behind_ms, self._prev_behind_ms)])
        # На хранение — та же нормализация (0/None -> None), что и на текущий тик:
        # иначе переход "был лидером (0, отфильтровано)" -> "снова есть машина
        # впереди" считал бы delta от 0 и почти всегда ложно объявлял бы "растёт"
        # для совершенно нового замера без реального тренда.
        self._prev_front_ms = gap_front_ms if gap_front_ms else None
        self._prev_behind_ms = gap_behind_ms if gap_behind_ms else None
        if not codes:
            return None
        if ers_percent is not None:
            # Значение здесь решает ТОЛЬКО, упоминать ли батарею вообще; само
            # число подставит резолвер на пороге озвучки.
            codes.append(CODE_ERS)
        return tuple(codes)

    def reset(self) -> None:
        self._prev_front_ms = None
        self._prev_behind_ms = None


def has_volatile_tokens(phrase: str) -> bool:
    return bool(phrase) and "{" in phrase and bool(_TOKEN_RE.search(phrase))


def volatile_tokens(phrase: str) -> tuple[str, ...]:
    """Имена токенов позднего связывания в порядке появления, без дублей.

    Живёт здесь, а не в core/radio: словарь токенов принадлежит этому модулю
    и второе место, знающее их синтаксис, пришлось бы держать синхронно.
    Само разрешение живёт в `core/radio/resolver.py` — единственной точке
    позднего связывания."""
    if not has_volatile_tokens(phrase):
        return ()
    seen: dict[str, None] = {}
    for match in _TOKEN_RE.finditer(phrase):
        seen.setdefault(match.group(1), None)
    return tuple(seen)


def _trend(gap_ms: int, prev_ms: int | None) -> str:
    """Куда идёт разрыв: first / closing / growing / stable.

    Возвращает КЛЮЧ фрагмента, а не текст: формулировка живёт в банке."""
    if prev_ms is None:
        return "first"
    delta = gap_ms - prev_ms
    if delta <= -TREND_THRESHOLD_MS:
        return "closing"
    if delta >= TREND_THRESHOLD_MS:
        return "growing"
    return "stable"
