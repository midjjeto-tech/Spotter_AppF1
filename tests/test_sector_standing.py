"""Положение в поле по секторам (core/sector_standing.py).

Главное здесь — что «слабейший сектор» выбирается по ОТРЫВУ, а не по месту:
восемнадцатое место с отрывом в сотую и третье с отрывом в полсекунды требуют
разного, и работать надо там, где лежит время.
"""
from core import sector_standing
from core.sector_standing import MIN_FIELD_CARS, build


def _car(s1: int | None = None, s2: int | None = None, s3: int | None = None,
         lap: int | None = None) -> dict:
    sectors = {i: ms for i, ms in ((1, s1), (2, s2), (3, s3)) if ms is not None}
    return {"best_sector_ms": sectors, "best_lap_ms": lap}


def _field(rows: dict[int, dict]) -> dict[int, dict]:
    return rows


_NAMES = {0: "Игрок", 1: "Норрис", 2: "Ферстаппен", 3: "Расселл", 4: "Пиастри"}


def _name_of(idx: int) -> str | None:
    return _NAMES.get(idx)


def test_rank_and_gap_are_measured_against_the_whole_field():
    field = _field({
        0: _car(30000, 31000, 29000),
        1: _car(29500, 30200, 29100),
        2: _car(29800, 30500, 28800),
        3: _car(30100, 31500, 29300),
    })

    pace = build(field, 0, _name_of)

    assert pace is not None
    by_sector = {s.sector: s for s in pace.sectors}
    # Быстрее игрока в первом секторе двое (29500 и 29800) — значит третий.
    assert by_sector[1].rank == 3
    assert by_sector[1].field_size == 4
    assert by_sector[1].gap_ms == 500
    assert by_sector[1].best_holder == "Норрис"
    assert by_sector[3].rank == 2
    assert by_sector[3].gap_ms == 200


def test_the_weakest_sector_is_the_one_holding_the_time_not_the_worst_place():
    """В первом секторе игрок последний, но отстаёт на сотую; во втором он
    третий, но там лежит почти секунда. Работать надо во втором."""
    field = _field({
        0: _car(30010, 32000, 29000),
        1: _car(30000, 31100, 29500),
        2: _car(30005, 31050, 29400),
        3: _car(30008, 32500, 29600),
    })

    pace = build(field, 0, _name_of)

    assert pace.weakest.sector == 2
    assert pace.weakest.gap_ms == 950


def test_the_strongest_sector_is_the_best_place():
    field = _field({
        0: _car(29000, 31000, 30000),
        1: _car(29500, 30200, 29100),
        2: _car(29800, 30500, 28800),
        3: _car(30100, 31500, 29300),
    })

    pace = build(field, 0, _name_of)

    assert pace.strongest.sector == 1
    assert pace.strongest.rank == 1
    assert pace.strongest.is_best is True


def test_leading_a_sector_gives_a_zero_gap_not_a_negative_one():
    field = _field({
        0: _car(28000, 31000, 30000),
        1: _car(29500, 30200, 29100),
        2: _car(29800, 30500, 28800),
        3: _car(30100, 31500, 29300),
    })

    pace = build(field, 0, _name_of)

    by_sector = {s.sector: s for s in pace.sectors}
    assert by_sector[1].gap_ms == 0
    assert by_sector[1].rank == 1
    assert by_sector[1].best_holder == "Игрок"


def test_a_tie_does_not_push_the_player_back():
    field = _field({
        0: _car(29000, 31000, 30000),
        1: _car(29000, 30200, 29100),
        2: _car(29800, 30500, 28800),
        3: _car(30100, 31500, 29300),
    })

    pace = build(field, 0, _name_of)

    assert {s.sector: s.rank for s in pace.sectors}[1] == 1


def test_a_negligible_gap_never_becomes_the_weakest_sector():
    """Отрыв ниже произносимого — не отрыв: экран не должен показывать то, о
    чём эфир сказать не может."""
    field = _field({
        0: _car(30020, 31030, 29010),
        1: _car(30000, 31000, 29000),
        2: _car(30005, 31010, 29005),
        3: _car(30008, 31020, 29008),
    })

    pace = build(field, 0, _name_of)

    assert pace.weakest is None
    assert pace.strongest is not None       # место при этом известно


def test_a_thin_field_is_not_a_standing():
    """Третий из трёх и третий из двадцати — разные новости."""
    field = _field({i: _car(30000 + i * 100) for i in range(MIN_FIELD_CARS - 1)})

    assert build(field, 0, _name_of) is None


def test_sector_missing_for_the_player_is_skipped_not_faked():
    field = _field({
        0: _car(30000, None, 29000),
        1: _car(29500, 30200, 29100),
        2: _car(29800, 30500, 28800),
        3: _car(30100, 31500, 29300),
    })

    pace = build(field, 0, _name_of)

    assert {s.sector for s in pace.sectors} == {1, 3}


def test_lap_rank_comes_from_the_same_field():
    field = _field({
        0: _car(30000, 31000, 29000, lap=90000),
        1: _car(29500, 30200, 29100, lap=88800),
        2: _car(29800, 30500, 28800, lap=89100),
        3: _car(30100, 31500, 29300, lap=90900),
    })

    pace = build(field, 0, _name_of)

    assert pace.lap_rank == 3
    assert pace.lap_field_size == 4
    assert pace.lap_gap_ms == 1200


def test_player_absent_from_the_history_is_no_standing():
    field = _field({i: _car(30000, 31000, 29000) for i in range(1, 5)})

    assert build(field, 0, _name_of) is None


def test_missing_name_does_not_cost_the_standing():
    """Имя приезжает из метаданных позже телеметрии."""
    field = _field({
        0: _car(30000, 31000, 29000),
        1: _car(29500, 30200, 29100),
        2: _car(29800, 30500, 28800),
        3: _car(30100, 31500, 29300),
    })

    pace = build(field, 0, name_of=None)

    assert pace is not None
    assert all(s.best_holder is None for s in pace.sectors)


def test_a_raising_name_lookup_does_not_cost_the_standing():
    def _boom(_idx):
        raise RuntimeError("metadata not ready")

    field = _field({
        0: _car(30000, 31000, 29000),
        1: _car(29500, 30200, 29100),
        2: _car(29800, 30500, 28800),
        3: _car(30100, 31500, 29300),
    })

    pace = build(field, 0, _boom)

    assert pace is not None
    assert pace.sectors


def test_garbage_entries_are_ignored_rather_than_crashing():
    field = {
        0: _car(30000, 31000, 29000),
        1: _car(29500, 30200, 29100),
        2: {"best_sector_ms": "нет"},
        3: {"best_sector_ms": {1: 0, 2: -5, 3: None}},
        4: "мусор",
        5: _car(29800, 30500, 28800),
        6: _car(30100, 31500, 29300),
    }

    pace = build(field, 0, _name_of)

    assert pace is not None
    assert {s.sector: s.field_size for s in pace.sectors}[1] == 4


def test_string_keys_from_a_saved_session_still_work():
    """Тот же словарь переживает круг через JSON в архиве, где ключи станут
    строками."""
    field = {
        0: {"best_sector_ms": {"1": 30000, "2": 31000}},
        1: {"best_sector_ms": {"1": 29500, "2": 30200}},
        2: {"best_sector_ms": {"1": 29800, "2": 30500}},
        3: {"best_sector_ms": {"1": 30100, "2": 31500}},
    }

    pace = build(field, 0, _name_of)

    assert pace is not None
    assert {s.sector for s in pace.sectors} == {1, 2}


def test_empty_history_is_silence():
    assert build({}, 0, _name_of) is None


def test_to_dict_is_json_ready():
    field = _field({
        0: _car(30000, 31000, 29000, lap=90000),
        1: _car(29500, 30200, 29100, lap=88800),
        2: _car(29800, 30500, 28800, lap=89100),
        3: _car(30100, 31500, 29300, lap=90900),
    })

    data = build(field, 0, _name_of).to_dict()

    assert data["weakest"]["sector"] in (1, 2, 3)
    assert isinstance(data["sectors"], list)
    assert data["lap_rank"] == 3
    assert sector_standing.MIN_GAP_MS >= 100
