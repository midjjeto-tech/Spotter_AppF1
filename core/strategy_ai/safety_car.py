"""
core/strategy_ai/safety_car.py
================================
Phase B (Safety Car/VSC/красный флаг) — чистая проекция сырого SCAR-события
(m_safetyCarType, m_eventType из SafetyCarEventData) на синтетический
event_code, который дальше идёт через ОБЫЧНЫЙ пайплайн major-событий
(как RTMT/PENA/RCWN) — без отдельной проводки в engine.py, кроме подмены
event_code до enrich()/record_event(). См. docs/superpowers/plans/
2026-07-19-safety-car-vsc-red-flag.md.

Formation Lap Safety Car (type 3) и промежуточное состояние "Returned"
(reason 2, между "едет в питы" и зелёным флагом) намеренно не объявляются —
не несут отдельной драмы, см. docstring derive_safety_car_event().
"""
from __future__ import annotations

_SC_TYPE_LABEL = {1: "Safety car", 2: "Virtual Safety Car"}

_DEPLOYED_COLOR = "#FBBF24"
_ENDING_COLOR = "#FBBF24"
_CLEAR_COLOR = "#22C55E"


def derive_safety_car_event(safety_car_type: int, event_reason: int) -> dict | None:
    """Raw SCAR (safety_car_type, event_reason) -> {"event_code", "sc_type",
    "description", "color"}, либо None если это состояние не стоит отдельной
    реплики:
    - safety_car_type not in (1=Full SC, 2=VSC) — 0=none (не должно долетать
      как SCAR, защитно), 3=Formation Lap (не гоночная драма).
    - event_reason == 2 (Returned) — переходное состояние между "уходит в
      питы" (reason=1, уже объявлено как ENDING) и зелёным флагом
      (reason=3, CLEAR) — третья реплика об одном и том же моменте не нужна.
    """
    sc_type = _SC_TYPE_LABEL.get(safety_car_type)
    if sc_type is None:
        return None

    if event_reason == 0:
        return {
            "event_code": "SAFETY_CAR_DEPLOYED", "sc_type": sc_type,
            "description": f"{sc_type} на трассе", "color": _DEPLOYED_COLOR,
        }
    if event_reason == 1:
        return {
            "event_code": "SAFETY_CAR_ENDING", "sc_type": sc_type,
            "description": f"{sc_type} уходит в конце круга", "color": _ENDING_COLOR,
        }
    if event_reason == 3:
        return {
            "event_code": "SAFETY_CAR_CLEAR", "sc_type": sc_type,
            "description": "Гонка возобновляется, трасса чистая", "color": _CLEAR_COLOR,
        }
    return None
