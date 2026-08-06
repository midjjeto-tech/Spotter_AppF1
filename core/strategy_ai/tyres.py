"""
core/strategy_ai/tyres.py
==========================
Tyre degradation analysis — compound-aware, no LLM.
"""
from __future__ import annotations

TYRE_AGE_WORN = 20
TYRE_WEAR_WORN = 45.0
TYRE_AGE_CRITICAL = 30
TYRE_WEAR_CRITICAL = 60.0
TYRE_WEAR_CLIFF = 75.0

# Soft tyres degrade faster — lower worn thresholds.
_COMPOUND_FACTOR: dict[str, float] = {
    "S": 0.85,
    "M": 1.0,
    "H": 1.15,
    "I": 0.9,
    "W": 1.1,
}


def _compound_factor(compound: str | None) -> float:
    if not compound:
        return 1.0
    return _COMPOUND_FACTOR.get(compound.upper().strip()[:1], 1.0)


def tyre_status(
    age: int | None,
    wear: float | None,
    compound: str | None = None,
) -> str:
    """Return degradation band: fresh | worn | critical | cliff | unknown."""
    if age is None and wear is None:
        return "unknown"

    factor = _compound_factor(compound)
    eff_age = (age or 0) / factor
    eff_wear = (wear or 0.0) * factor

    if eff_wear >= TYRE_WEAR_CLIFF or eff_age >= TYRE_AGE_CRITICAL + 8:
        return "cliff"
    if eff_wear >= TYRE_WEAR_CRITICAL or eff_age >= TYRE_AGE_CRITICAL:
        return "critical"
    if eff_wear >= TYRE_WEAR_WORN or eff_age >= TYRE_AGE_WORN:
        return "worn"
    return "fresh"


def needs_pit_soon(
    age: int | None,
    wear: float | None,
    compound: str | None = None,
) -> bool:
    """True when stint is clearly past optimal window."""
    status = tyre_status(age, wear, compound)
    return status in ("critical", "cliff")


def tyre_saving_recommended(
    age: int | None,
    wear: float | None,
    compound: str | None = None,
) -> bool:
    """Tyres degrading but not yet cliff — conserve pace."""
    status = tyre_status(age, wear, compound)
    return status in ("worn", "critical")
