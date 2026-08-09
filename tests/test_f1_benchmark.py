"""core/f1_benchmark.py — эталон темпа из поля текущей сессии.

Источник переписан 2026-08-08: раньше эталоном был быстрейший круг реального
Гран-при (Jolpica + секторы OpenF1), теперь — быстрейшая машина поля из пакета
Session History. Тесты загрузки по сети удалены вместе с сетью; всё, что ниже,
проверяет отбор эталона из поля, форму контракта compare() и формулировки.
"""
from core.f1_benchmark import F1Benchmark


def _hist(**cars) -> dict[int, dict]:
    """car_idx → запись session history. Ключи — «c<idx>», значения —
    (best_lap_ms, сектора или None)."""
    out: dict[int, dict] = {}
    for key, (lap_ms, sectors) in cars.items():
        out[int(key[1:])] = {"car_idx": int(key[1:]), "best_lap_ms": lap_ms,
                             "best_sector_ms": sectors or {}}
    return out


def _names(mapping: dict[int, str]):
    return lambda idx: mapping.get(idx, "")


def _bench_with_field(**kwargs) -> F1Benchmark:
    b = F1Benchmark()
    b.update_from_field(_hist(c1=(90_000, {1: 30_000, 2: 30_000, 3: 30_000})),
                        player_idx=0, name_of=_names({1: "Норрис"}))
    return b


# --- отбор эталона из поля ---

def test_fastest_rival_becomes_the_reference():
    b = F1Benchmark()
    changed = b.update_from_field(
        _hist(c1=(91_000, None), c2=(89_500, None), c3=(93_000, None)),
        player_idx=0, name_of=_names({1: "Норрис", 2: "Пиастри", 3: "Расселл"}))

    assert changed is True
    assert b.ready is True
    assert b.reference["time_ms"] == 89_500
    assert b.reference["driver"] == "Пиастри"


def test_player_car_is_excluded_from_the_field():
    """Сравнивать игрока с самим собой бессмысленно — гэп всегда ноль. Личный
    рекорд трассы это задача career_memory, не этого модуля."""
    b = F1Benchmark()
    b.update_from_field(_hist(c0=(80_000, None), c1=(91_000, None)),
                        player_idx=0, name_of=_names({0: "Игрок", 1: "Норрис"}))

    assert b.reference["time_ms"] == 91_000
    assert b.reference["driver"] == "Норрис"


def test_zero_lap_times_are_not_a_reference():
    """Пустой слот в session history приходит нулём. Без фильтра ноль победил
    бы любой реальный круг и эталон стал бы недостижимым."""
    b = F1Benchmark()
    b.update_from_field(_hist(c1=(0, None), c2=(92_000, None)),
                        player_idx=0, name_of=_names({2: "Расселл"}))

    assert b.reference["time_ms"] == 92_000


def test_empty_field_leaves_benchmark_not_ready():
    b = F1Benchmark()
    assert b.update_from_field({}, player_idx=0, name_of=_names({})) is False
    assert b.ready is False


def test_unchanged_field_reports_no_change():
    """Пакет цикличен по всем машинам и приходит постоянно. Пересборка эталона
    из тех же данных не должна выглядеть как обновление."""
    b = F1Benchmark()
    hist = _hist(c1=(91_000, None))
    assert b.update_from_field(hist, 0, _names({1: "Норрис"})) is True
    assert b.update_from_field(hist, 0, _names({1: "Норрис"})) is False


def test_improving_rival_moves_the_reference():
    b = F1Benchmark()
    b.update_from_field(_hist(c1=(91_000, None)), 0, _names({1: "Норрис"}))
    changed = b.update_from_field(_hist(c1=(90_100, None)), 0, _names({1: "Норрис"}))

    assert changed is True
    assert b.reference["time_ms"] == 90_100


def test_partial_sectors_are_dropped_entirely():
    """Гэп по одному сектору и молчание по двум читается как «там ты в
    порядке», хотя данных просто нет."""
    b = F1Benchmark()
    b.update_from_field(_hist(c1=(91_000, {1: 30_000, 2: 31_000})),
                        0, _names({1: "Норрис"}))

    assert b.reference["sector_ms"] is None
    assert b.reference["sectors_source"] is None


def test_sectors_come_from_the_same_car_as_the_reference_lap():
    b = F1Benchmark()
    b.update_from_field(
        _hist(c1=(95_000, {1: 1, 2: 2, 3: 3}),
              c2=(90_000, {1: 30_000, 2: 30_000, 3: 30_000})),
        0, _names({1: "Норрис", 2: "Пиастри"}))

    assert b.reference["sector_ms"] == {1: 30_000, 2: 30_000, 3: 30_000}


# --- контракт compare() ---

def test_compare_computes_gap():
    b = _bench_with_field()
    cmp = b.compare([{"lap": 1, "last_lap_ms": 92_500}])

    assert cmp["gap_ms"] == 2_500
    assert cmp["player_best_ms"] == 92_500
    assert cmp["f1_time_ms"] == 90_000
    assert cmp["f1_driver"] == "Норрис"


def test_compare_none_when_not_ready_or_no_laps():
    assert F1Benchmark().compare([{"lap": 1, "last_lap_ms": 90_000}]) is None
    assert _bench_with_field().compare([]) is None
    assert _bench_with_field().compare([{"lap": 1, "last_lap_ms": 0}]) is None


def test_compare_always_has_sector_keys():
    """Контракт для HUD/Voice/Story: ключи есть всегда, чтобы потребители не
    делали hasattr-проверок."""
    cmp = _bench_with_field().compare([{"lap": 1, "last_lap_ms": 92_000}])

    assert "sectors" in cmp and "sectors_source" in cmp


def test_compare_sector_gaps_use_the_player_best_lap():
    b = _bench_with_field()
    cmp = b.compare([
        {"lap": 1, "last_lap_ms": 95_000, "s1_ms": 33_000, "s2_ms": 31_000, "s3_ms": 31_000},
        {"lap": 2, "last_lap_ms": 91_000, "s1_ms": 30_500, "s2_ms": 30_200, "s3_ms": 30_300},
    ])

    assert cmp["player_best_lap"] == 2
    assert cmp["sectors"][1]["gap_ms"] == 500
    assert cmp["sectors_source"] == "field"


def test_compare_sectors_none_when_best_lap_has_no_sector_data():
    cmp = _bench_with_field().compare([{"lap": 1, "last_lap_ms": 91_000}])
    assert cmp["sectors"] is None


def test_reset_clears():
    b = _bench_with_field()
    b.reset()
    assert b.ready is False and b.reference is None


# --- формулировки ---

def test_pb_line_names_the_rival_in_genitive():
    b = _bench_with_field()
    cmp = b.compare([{"lap": 1, "last_lap_ms": 92_500}])
    line = b.pb_line(cmp)

    assert "Личный рекорд круга!" in line
    assert "Норриса" in line


def test_pb_line_does_not_claim_the_player_is_a_better_driver():
    b = _bench_with_field()
    cmp = b.compare([{"lap": 1, "last_lap_ms": 88_000}])
    line = b.pb_line(cmp).lower()

    assert "опережение" not in line
    assert "быстрее" not in line
    assert "меньше ориентира" in line


def test_lines_survive_an_unnamed_rival():
    """Участник может ещё не приехать в race_state — имени нет, а эталон уже
    есть. Реплика обязана остаться произносимой."""
    b = F1Benchmark()
    b.update_from_field(_hist(c1=(90_000, None)), 0, _names({}))
    cmp = b.compare([{"lap": 1, "last_lap_ms": 92_000}])

    assert "Личный рекорд круга!" in b.pb_line(cmp)
    assert "лидера" in b.context_line(cmp)


def test_context_line_mentions_both_times():
    b = _bench_with_field()
    cmp = b.compare([{"lap": 1, "last_lap_ms": 92_500}])
    line = b.context_line(cmp)

    assert "1:30.000" in line and "1:32.500" in line


def test_sector_pb_line_reports_the_difference():
    b = _bench_with_field()
    faster = b.sector_pb_line(2, {"player_ms": 29_000, "gap_ms": -1_000})
    slower = b.sector_pb_line(3, {"player_ms": 31_000, "gap_ms": 1_000})

    assert "Сектор 2" in faster and "меньше ориентира" in faster.lower()
    assert "Сектор 3" in slower and "больше ориентира" in slower.lower()


# --- слабый сектор гонки ---

def _laps(*rows) -> list[dict]:
    return [{"lap": i + 1, "last_lap_ms": 91_000, "s1_ms": s1, "s2_ms": s2,
             "s3_ms": s3, "pit_lap": pit}
            for i, (s1, s2, s3, pit) in enumerate(rows)]


def test_race_weak_sector_picks_largest_average_gap():
    b = _bench_with_field()
    laps = _laps((30_100, 30_200, 31_500, False), (30_100, 30_200, 31_700, False))

    assert b.race_weak_sector(laps) == 3


def test_race_weak_sector_ignores_pit_laps():
    """Секторные времена пит-круга искажены пит-лейном, а не темпом.

    Числа подобраны так, чтобы ответ РАЗЛИЧАЛСЯ: по чистому кругу худший
    сектор — первый (+500), но пит-лейн в третьем секторе даёт +60 с, и стоит
    его посчитать — ответом станет третий."""
    b = _bench_with_field()
    laps = _laps((30_500, 30_200, 30_100, False),
                 (30_000, 30_000, 90_000, True))

    assert b.race_weak_sector(laps) == 1


def test_race_weak_sector_none_without_reference_sectors():
    b = F1Benchmark()
    b.update_from_field(_hist(c1=(90_000, None)), 0, _names({1: "Норрис"}))

    assert b.race_weak_sector(_laps((30_000, 30_000, 30_000, False))) is None


def test_race_weak_sector_none_without_valid_laps():
    assert _bench_with_field().race_weak_sector([]) is None


def test_race_weak_sector_ties_resolve_to_lowest_number():
    b = _bench_with_field()
    laps = _laps((30_500, 30_500, 30_500, False))

    assert b.race_weak_sector(laps) == 1
