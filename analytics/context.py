from __future__ import annotations

from core.f1_comparison_language import (
    SHORT_COMPARISON_DISCLAIMER,
    describe_time_difference,
)

def _fmt(ms: int | None) -> str:
    if ms is None: return "?"
    if ms < 0: return f"-{_fmt(-ms)}"
    m = int(ms // 60000)
    s = (ms % 60000) / 1000
    return f"{m}:{s:06.3f}"

def build_qwen_context(compare: dict, f1_meta: dict) -> str:
    """≤ 250-char Russian string. Never raises."""
    try:
        return _build(compare, f1_meta)
    except Exception:
        return "Данные для сравнения недоступны."

def _build(compare: dict, f1_meta: dict) -> str:
    cov = compare.get("source_coverage", {})
    if cov.get("f1") == "none":
        return "Данные реального GP для этой трассы недоступны."

    event = f1_meta.get("event") or "GP"
    year = f1_meta.get("year") or ""
    top = f1_meta.get("results_top10") or []
    winner = top[0]["driver"] if top else "?"
    fl_driver = compare.get("f1_best_lap_driver") or "?"
    fl_time = _fmt(compare.get("f1_fastest_ms"))
    fl_lap = (f1_meta.get("fastest_lap") or {}).get("lap")

    header = f"{event} {year}: победил {winner}."
    fl = f" Быстрейший круг {fl_driver} {fl_time}"
    fl += f" (круг {fl_lap})." if fl_lap else "."

    if cov.get("player") == "none":
        return (header + fl + " Игровые данные не записаны.")[:250]

    pt = _fmt(compare.get("player_best_lap_ms"))
    pl = compare.get("player_best_lap_lap_number")
    player = f" Твой лучший — {pt}"
    player += f" (круг {pl})" if pl else ""
    player += f". {describe_time_difference(compare.get('gap_ms'))}"

    if compare.get("partial") or "sectors" not in compare:
        return (header + fl + player + " " + SHORT_COMPARISON_DISCLAIMER)[:250]

    secs = compare["sectors"]
    worst_k, worst_v = max(secs.items(), key=lambda kv: kv[1]["gap_ms"])
    sg = f"{worst_v['gap_ms']/1000:.1f}"
    sector = f" Теряешь в {worst_k.upper()} (+{sg}с)."
    result = header + fl + player + sector + " " + SHORT_COMPARISON_DISCLAIMER
    fallback = header + fl + player + " " + SHORT_COMPARISON_DISCLAIMER
    return result[:250] if len(result) <= 250 else fallback[:250]
