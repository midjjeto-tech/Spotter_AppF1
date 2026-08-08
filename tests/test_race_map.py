"""Карта гонки (core/race_map.py) — позиции всех машин по кругам.

Строится из уже разобранных позиций, а не из отдельного пакета: снимок берётся
в момент, когда ЛИНИЮ ПЕРЕСЕКАЕТ ИГРОК. Соперники в этот момент могут быть на
другом круге — это честное «на момент твоего пересечения», и подписывать график
надо именно так.
"""
from core.race_map import RaceMap


def test_empty_map_has_no_laps():
    m = RaceMap()
    assert m.rows() == []
    assert m.summary() is None


def test_single_lap_recorded_for_every_car():
    m = RaceMap()
    m.observe_lap(1, {0: 3, 1: 1, 2: 2})
    rows = m.rows()
    assert {r["vehicle_idx"] for r in rows} == {0, 1, 2}
    assert next(r for r in rows if r["vehicle_idx"] == 0)["positions"] == [3]


def test_laps_accumulate_in_order():
    m = RaceMap()
    m.observe_lap(1, {0: 5})
    m.observe_lap(2, {0: 4})
    m.observe_lap(3, {0: 2})
    assert m.laps() == [1, 2, 3]
    assert m.rows()[0]["positions"] == [5, 4, 2]


def test_same_lap_observed_twice_does_not_duplicate():
    """LAP_DATA приходит десятки раз в секунду; защита от повторной записи
    того же круга должна быть в самой карте, а не у вызывающего."""
    m = RaceMap()
    m.observe_lap(1, {0: 5})
    m.observe_lap(1, {0: 4})
    assert m.laps() == [1]
    assert m.rows()[0]["positions"] == [5]


def test_car_appearing_late_is_padded_with_none():
    """Машина, которой не было в первых снимках (поздний коннект, зритель),
    не должна сдвигать чужие круги."""
    m = RaceMap()
    m.observe_lap(1, {0: 1})
    m.observe_lap(2, {0: 1, 5: 7})
    late = next(r for r in m.rows() if r["vehicle_idx"] == 5)
    assert late["positions"] == [None, 7]


def test_car_that_retires_keeps_none_tail():
    m = RaceMap()
    m.observe_lap(1, {0: 1, 5: 7})
    m.observe_lap(2, {0: 1})
    gone = next(r for r in m.rows() if r["vehicle_idx"] == 5)
    assert gone["positions"] == [7, None]


def test_names_are_attached_when_resolver_is_given():
    m = RaceMap()
    m.observe_lap(1, {0: 1, 1: 2})
    rows = m.rows(name_for=lambda idx: {0: "Верстаппен", 1: "Норрис"}.get(idx))
    assert next(r for r in rows if r["vehicle_idx"] == 0)["name"] == "Верстаппен"


def test_player_row_is_marked():
    m = RaceMap(player_idx=1)
    m.observe_lap(1, {0: 1, 1: 2})
    rows = m.rows()
    assert next(r for r in rows if r["vehicle_idx"] == 1)["is_player"] is True
    assert next(r for r in rows if r["vehicle_idx"] == 0)["is_player"] is False


def test_pit_laps_are_recorded_for_the_player():
    m = RaceMap(player_idx=0)
    m.observe_lap(1, {0: 4})
    m.observe_lap(2, {0: 9}, player_pit=True)
    assert m.pit_laps() == [2]


# ── Итог: где потеряна гонка ─────────────────────────────────────────────────

def test_summary_reports_the_worst_single_lap_for_the_player():
    m = RaceMap(player_idx=0)
    m.observe_lap(1, {0: 5})
    m.observe_lap(2, {0: 6})     # -1
    m.observe_lap(3, {0: 10})    # -4  <- худший круг
    m.observe_lap(4, {0: 9})     # +1
    s = m.summary()
    assert s["worst_lap"] == 3
    assert s["worst_delta"] == -4
    assert s["start_position"] == 5
    assert s["end_position"] == 9
    assert s["net"] == -4


def test_summary_ignores_pit_laps_as_the_worst_lap():
    """Потеря позиций на пит-круге — это пит-стоп, а не потерянная гонка.
    Назвать его «здесь ты проиграл» было бы враньём."""
    m = RaceMap(player_idx=0)
    m.observe_lap(1, {0: 3})
    m.observe_lap(2, {0: 12}, player_pit=True)   # -9, но это бокс
    m.observe_lap(3, {0: 10})                    # +2
    m.observe_lap(4, {0: 12})                    # -2 <- худший НЕпитовый
    s = m.summary()
    assert s["worst_lap"] == 4
    assert s["worst_delta"] == -2


def test_summary_without_losses_reports_no_worst_lap():
    m = RaceMap(player_idx=0)
    m.observe_lap(1, {0: 5})
    m.observe_lap(2, {0: 4})
    s = m.summary()
    assert s["worst_lap"] is None
    assert s["net"] == 1


def test_summary_is_none_without_a_player():
    m = RaceMap(player_idx=None)
    m.observe_lap(1, {0: 5})
    assert m.summary() is None


def test_reset_clears_everything():
    m = RaceMap(player_idx=0)
    m.observe_lap(1, {0: 5})
    m.reset()
    assert m.rows() == []
    assert m.pit_laps() == []
