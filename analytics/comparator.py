from __future__ import annotations

from analytics.context import build_qwen_context
from core.f1_comparison_language import (
    COMPARISON_DISCLAIMER,
    describe_time_difference,
)

def compare(game: dict, f1: dict) -> dict:
    """Best-lap comparison. All output fields always present."""
    valid = [l for l in game.get("player_laps", []) if l.get("last_lap_ms", 0) > 0]
    best = min(valid, key=lambda l: l["last_lap_ms"]) if valid else None

    f1fl = f1.get("fastest_lap") or {}
    f1_time = f1fl.get("time_ms")
    f1_driver = f1fl.get("driver")

    if best is None:
        pcov = "none"
    elif all(best.get(k, 0) > 0 for k in ("s1_ms", "s2_ms", "s3_ms")):
        pcov = "full"
    else:
        pcov = "partial"

    if f1_time is None:
        fcov = "none"
    elif all(f1fl.get(k) and f1fl[k] > 0 for k in ("s1_ms", "s2_ms", "s3_ms")):
        fcov = "full"
    else:
        fcov = "partial"

    gap_ms = (best["last_lap_ms"] - f1_time) if (best and f1_time) else None

    sectors = None
    if pcov == "full" and fcov == "full":
        sectors = {s: {"player_ms": best[f"{s}_ms"], "f1_ms": f1fl[f"{s}_ms"],
                       "gap_ms": best[f"{s}_ms"] - f1fl[f"{s}_ms"]}
                   for s in ("s1", "s2", "s3")}

    partial = pcov != "full" or fcov != "full"

    proto = {"source_coverage": {"player": pcov, "f1": fcov},
             "player_best_lap_ms": best["last_lap_ms"] if best else None,
             "player_best_lap_lap_number": best["lap"] if best else None,
             "f1_fastest_ms": f1_time, "f1_best_lap_driver": f1_driver,
             "gap_ms": gap_ms, "sectors": sectors, "partial": partial}
    qwen = build_qwen_context(proto, f1)

    result = {"comparison_basis": "best_lap",
              "source_coverage": {"player": pcov, "f1": fcov},
              "player_best_lap_ms": proto["player_best_lap_ms"],
              "player_best_lap_lap_number": proto["player_best_lap_lap_number"],
              "f1_fastest_ms": f1_time, "f1_best_lap_driver": f1_driver,
              "gap_ms": gap_ms, "partial": partial, "qwen_context": qwen,
              "interpretation": describe_time_difference(gap_ms, decimals=3),
              "comparison_disclaimer": COMPARISON_DISCLAIMER}
    if sectors:
        result["sectors"] = sectors
    return result
