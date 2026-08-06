"""
core/strategy_ai/sector_comparison.py
========================================
Сравнение лучших секторов игрока и соперника за сессию (Session History,
packet 11) — "ты быстрее его во втором секторе" в гэп-дайджесте. Чистая
функция, без I/O — тот же паттерн, что gap_digest.py/drs_advisory.py.

См. docs/superpowers/plans/2026-07-20-session-history-sector-comparison.md.
"""
from __future__ import annotations

_SECTOR_ORDINAL = {1: "1-м", 2: "2-м", 3: "3-м"}


def compare_best_sectors(player_best_ms: dict[int, int], rival_best_ms: dict[int, int],
                          rival_name: str) -> str | None:
    """Возвращает готовую фразу по сектору с НАИБОЛЬШЕЙ разницей среди тех,
    что есть в обоих словарях (самое показательное сравнение для короткой
    рутинной сводки — не зачитывать все 3 сектора каждый раз). None, если
    общих секторов нет или лучший результат совпадает секунда в секунду."""
    common = set(player_best_ms) & set(rival_best_ms)
    if not common:
        return None
    sector = max(common, key=lambda s: abs(player_best_ms[s] - rival_best_ms[s]))
    delta_ms = player_best_ms[sector] - rival_best_ms[sector]
    if delta_ms == 0:
        return None
    ordinal = _SECTOR_ORDINAL[sector]
    delta_s = abs(delta_ms) / 1000.0
    if delta_ms < 0:
        return f"Ты быстрее {rival_name} в {ordinal} секторе на {delta_s:.1f}с."
    return f"{rival_name} быстрее тебя в {ordinal} секторе на {delta_s:.1f}с."
