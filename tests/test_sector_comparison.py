"""compare_best_sectors — чистая функция (без I/O), сравнивает лучшие секторы
игрока и соперника за сессию (Session History, packet 11), возвращает готовую
фразу для гэп-дайджеста, выбирая сектор с наибольшей разницей. См.
docs/superpowers/plans/2026-07-20-session-history-sector-comparison.md.
"""
from core.strategy_ai.sector_comparison import compare_best_sectors


def test_player_faster_picks_largest_delta_sector():
    player = {1: 28000, 2: 29500, 3: 31000}
    rival = {1: 28100, 2: 30200, 3: 31050}
    # deltas: s1=100, s2=700, s3=50 -> s2 largest, player faster (29500 < 30200)
    result = compare_best_sectors(player, rival, "Норрис")
    assert result == "Ты быстрее Норрис в 2-м секторе на 0.7с."


def test_rival_faster_in_largest_delta_sector():
    player = {1: 28000, 2: 30200, 3: 31000}
    rival = {1: 28100, 2: 29500, 3: 31050}
    result = compare_best_sectors(player, rival, "Ферстаппен")
    assert result == "Ферстаппен быстрее тебя в 2-м секторе на 0.7с."


def test_partial_overlap_compares_only_shared_sector():
    player = {2: 29500}
    rival = {1: 28000, 2: 30200, 3: 31000}
    result = compare_best_sectors(player, rival, "Расселл")
    assert result == "Ты быстрее Расселл в 2-м секторе на 0.7с."


def test_no_overlap_returns_none():
    player = {1: 28000}
    rival = {2: 30200}
    assert compare_best_sectors(player, rival, "Пиастри") is None


def test_empty_dicts_return_none():
    assert compare_best_sectors({}, {1: 28000}, "X") is None
    assert compare_best_sectors({1: 28000}, {}, "X") is None
    assert compare_best_sectors({}, {}, "X") is None


def test_exact_tie_returns_none():
    assert compare_best_sectors({1: 28000}, {1: 28000}, "X") is None
