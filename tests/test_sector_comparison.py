"""compare_best_sectors — чистая функция (без I/O), сравнивает лучшие секторы
игрока и соперника за сессию (Session History, packet 11), возвращает готовую
фразу для гэп-дайджеста, выбирая сектор с наибольшей разницей.

**Строка идёт в эфир мимо банка фраз**, поэтому защиты банка (падежи имён,
запрет цифровых порядковых, согласование числительных) на неё не действуют — и
проверяются здесь поимённо. Три из них были нарушены в первой редакции и
зафиксированы прежними тестами как «правильный» результат:
«Ты быстрее Ландо Норрис в 1-м секторе на 0.7с».

См. docs/superpowers/plans/2026-07-20-session-history-sector-comparison.md.
"""
from core.strategy_ai.sector_comparison import compare_best_sectors


def test_player_faster_picks_largest_delta_sector():
    player = {1: 28000, 2: 29500, 3: 31000}
    rival = {1: 28100, 2: 30200, 3: 31050}
    # deltas: s1=100, s2=700, s3=50 -> s2 largest, player faster (29500 < 30200)
    result = compare_best_sectors(player, rival, "Норрис")
    assert result == "Ты быстрее Норриса во втором секторе на семь десятых."


def test_rival_faster_in_largest_delta_sector():
    player = {1: 28000, 2: 30200, 3: 31000}
    rival = {1: 28100, 2: 29500, 3: 31050}
    result = compare_best_sectors(player, rival, "Ферстаппен")
    assert result == "Ферстаппен быстрее тебя во втором секторе на семь десятых."


def test_partial_overlap_compares_only_shared_sector():
    player = {2: 29500}
    rival = {1: 28000, 2: 30200, 3: 31000}
    result = compare_best_sectors(player, rival, "Расселл")
    assert result == "Ты быстрее Расселла во втором секторе на семь десятых."


# ── Правила, за которые здесь никто больше не отвечает ───────────────────────

def test_full_name_is_cut_down_to_the_surname():
    """Радио говорит «Норрис», а не «Ландо Норрис» — как и весь остальной эфир."""
    result = compare_best_sectors({1: 29000}, {1: 28000}, "Ландо Норрис")

    assert result is not None
    assert "Ландо" not in result
    assert result.startswith("Норрис ")


def test_name_after_a_comparative_is_declined():
    """«быстрее Норрис» — имя не склонилось. Нужен родительный."""
    result = compare_best_sectors({1: 28000}, {1: 29000}, "Ландо Норрис")

    assert "быстрее Норриса" in result
    assert "быстрее Норрис " not in result


def test_sector_number_is_a_word_not_a_digit():
    """«в 1-м секторе» офлайновый Piper читает посимвольно — тот же класс
    брака, что чинили для номеров поворотов у коуча."""
    result = compare_best_sectors({3: 29000}, {3: 28000}, "Норрис")

    assert "в третьем секторе" in result
    assert "3-м" not in result


def test_magnitude_is_a_spoken_fragment():
    """«0.7с» num_to_words превращал в «ноль целых семь десятых с»."""
    result = compare_best_sectors({1: 28000}, {1: 28700}, "Норрис")

    assert "на семь десятых" in result
    assert "с." not in result.replace("секторе", "").replace("Норрис", "")


# ── Молчание ─────────────────────────────────────────────────────────────────

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


def test_difference_below_the_spoken_floor_is_silence():
    """На четырёх сотых секунды сравнение секторов не значит ничего, а прежняя
    версия зачитывала его как «ноль целых ноль десятых»."""
    assert compare_best_sectors({1: 28000}, {1: 28040}, "Норрис") is None


def test_unknown_name_is_still_usable():
    """Кастомное имя не склоняется — но реплика обязана состояться."""
    result = compare_best_sectors({1: 28000}, {1: 29000}, "Кузнецов")

    assert result is not None
    assert "Кузнецов" in result
