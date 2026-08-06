"""
core/strategy_ai/pit_window.py
================================
Pit window, undercut and overcut detection — deterministic, no LLM.
Also hosts PitWindowApproachTracker (edge-triggered heads-up, tightly
coupled to detect_pit_window()'s output) — см.
docs/superpowers/specs/2026-07-13-engineer-phase-a-cheap-calls-design.md.
"""
from __future__ import annotations

from core.strategy_ai.tyres import needs_pit_soon, tyre_status

# Typical pit-loss delta on track (ms) used for undercut/overcut geometry.
PIT_LOSS_MS = 23_000
UNDERCUT_GAP_MAX_MS = 3_000
OVERCUT_GAP_MIN_MS = 3_500
OVERCUT_GAP_MAX_MS = 6_500

PIT_WINDOW_MIN_LAPS_LEFT = 4
UNDERCUT_MIN_LAPS_LEFT = 5
OVERCUT_MIN_LAPS_LEFT = 8


def _laps_to_pit(age: int | None, wear: float | None) -> int | None:
    """Rough estimate: laps until tyres force a stop."""
    if age is None and wear is None:
        return None
    by_age = max(0, 32 - (age or 0))
    by_wear = max(0, int((78 - (wear or 0.0)) / 2.5))
    return min(by_age, by_wear)


def detect_undercut(
    gap_front_ms: int | None,
    tyre_age: int | None,
    tyre_wear: float | None,
    laps_remaining: int | None,
    compound: str | None = None,
) -> tuple[bool, float]:
    """Car ahead close enough that pitting now may undercut them."""
    if gap_front_ms is None or laps_remaining is None:
        return False, 0.0
    if laps_remaining < UNDERCUT_MIN_LAPS_LEFT:
        return False, 0.0
    if gap_front_ms > UNDERCUT_GAP_MAX_MS:
        return False, 0.0
    if not needs_pit_soon(tyre_age, tyre_wear, compound):
        status = tyre_status(tyre_age, tyre_wear, compound)
        if status not in ("worn", "critical"):
            return False, 0.0

    gap_s = gap_front_ms / 1000.0
    conf = 0.55 + (UNDERCUT_GAP_MAX_MS - gap_front_ms) / UNDERCUT_GAP_MAX_MS * 0.35
    if tyre_wear is not None and tyre_wear > 55:
        conf += 0.08
    if gap_s * 1000 < PIT_LOSS_MS * 0.6:
        conf += 0.05
    return True, min(conf, 0.95)


def detect_overcut(
    gap_front_ms: int | None,
    tyre_age: int | None,
    tyre_wear: float | None,
    laps_remaining: int | None,
    compound: str | None = None,
) -> tuple[bool, float]:
    """Stay out while rival pits — tyres still have life."""
    if gap_front_ms is None or laps_remaining is None:
        return False, 0.0
    if laps_remaining < OVERCUT_MIN_LAPS_LEFT:
        return False, 0.0
    if not (OVERCUT_GAP_MIN_MS <= gap_front_ms <= OVERCUT_GAP_MAX_MS):
        return False, 0.0

    status = tyre_status(tyre_age, tyre_wear, compound)
    if status not in ("fresh", "worn"):
        return False, 0.0
    if tyre_age is not None and tyre_age > 18:
        return False, 0.0
    if tyre_wear is not None and tyre_wear > 42:
        return False, 0.0

    conf = 0.5 + (gap_front_ms - OVERCUT_GAP_MIN_MS) / (
        OVERCUT_GAP_MAX_MS - OVERCUT_GAP_MIN_MS) * 0.25
    return True, min(conf, 0.85)


def detect_pit_window(
    tyre_age: int | None,
    tyre_wear: float | None,
    laps_remaining: int | None,
    compound: str | None = None,
) -> tuple[bool, float, int | None]:
    """Optimal pit window open — returns (open, confidence, laps_to_pit)."""
    if laps_remaining is None or laps_remaining < PIT_WINDOW_MIN_LAPS_LEFT:
        return False, 0.0, None

    laps_left = _laps_to_pit(tyre_age, tyre_wear)
    status = tyre_status(tyre_age, tyre_wear, compound)

    if status == "cliff":
        return True, 0.92, laps_left or 0
    if status == "critical":
        return True, 0.85, laps_left or 1
    if status == "worn" and laps_left is not None and laps_left <= 4:
        return True, 0.72, laps_left

    return False, 0.0, laps_left


APPROACH_LAPS_THRESHOLD = 8


# Семантический код банка (core/radio/phrases.py::box.window_approach).
CODE_WINDOW_APPROACH = "box.window_approach"


class PitWindowApproachTracker:
    """Разовый heads-up "приближаемся к окну пит-стопа" — армируется ОДИН
    раз за стинт (не за тик), не повторяется при колебаниях laps_left из-за
    смены темпа/стратегии внутри одного стинта. Сброс — только на реальном
    начале нового стинта (собственный пит-стоп) или сессионных границах.

    TODO (не в объёме Фазы A): полный пересчёт стратегии посреди стинта
    (например, дождь -> смена на интермедиэйты) сейчас НЕ сбрасывает
    _announced_this_stint — редкий кейс, осознанно отложено."""

    def __init__(self) -> None:
        self._announced_this_stint = False

    def check(self, open_: bool, laps_left: int | None) -> str | None:
        """Один тик LapData. Возвращает готовую фразу при приближении к окну
        (window не открыто, laps_left <= APPROACH_LAPS_THRESHOLD), но только
        один раз за стинт. Возвращает None при повторных вызовах с близкими
        значениями, если уже объявлялось, при открытом окне или если
        laps_left None или слишком высокий."""
        if self._announced_this_stint:
            return None
        if not open_ and laps_left is not None and laps_left <= APPROACH_LAPS_THRESHOLD:
            self._announced_this_stint = True
            return CODE_WINDOW_APPROACH
        return None

    def reset(self) -> None:
        """Сброс состояния (SSTA/CHQF/flashback или начало нового стинта)."""
        self._announced_this_stint = False
