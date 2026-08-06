"""Тесты чистых функций-переводчиков core/iracing_packets.py (Phase 1).

В отличие от tests/test_packets_*.py здесь нет байтовых офсетов — вход это
уже словарь опрошенных переменных iRacing (см. core/iracing_telemetry.py),
поэтому тесты просто собирают такой словарь напрямую, без struct.pack_into.

Не требует установленного pyirsdk и живой сессии iRacing — модуль
iracing_packets.py не импортирует irsdk (это делает только
iracing_telemetry.py), чистые dict -> dict функции.
"""
from core import iracing_packets as ip


def _vars(**overrides) -> dict:
    base = {
        "CarIdxPosition": [1, 2, 0, 0],
        "CarIdxLap": [5, 5, 0, 0],
        "CarIdxOnPitRoad": [False, True, False, False],
        "CarIdxLapDistPct": [0.42, 0.10, 0.0, 0.0],
        "PlayerCarIdx": 0,
        "Speed": 50.0,   # м/с
        "Gear": 4,
        "_drivers": [],
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# parse_lap_data
# --------------------------------------------------------------------------- #

def test_parse_lap_data_positions_and_leader():
    out = ip.parse_lap_data(_vars())
    assert out["positions"] == {0: 1, 1: 2}
    assert out["laps"] == {0: 5, 1: 5}
    assert out["leader_idx"] == 0


def test_parse_lap_data_pit_status_from_on_pit_road():
    out = ip.parse_lap_data(_vars())
    assert out["pit_status"] == {0: 0, 1: 2}


def test_parse_lap_data_zero_position_cars_excluded():
    out = ip.parse_lap_data(_vars())
    assert 2 not in out["positions"]
    assert 3 not in out["positions"]


def test_parse_lap_data_empty_vars_returns_empty_dicts():
    out = ip.parse_lap_data({})
    assert out["positions"] == {}
    assert out["leader_idx"] is None


# --------------------------------------------------------------------------- #
# parse_player_lap
# --------------------------------------------------------------------------- #

def test_parse_player_lap_reads_player_index():
    out = ip.parse_player_lap(_vars(), player_idx=1)
    assert out["position"] == 2
    assert out["current_lap"] == 5
    assert out["pit_status"] == 2   # CarIdxOnPitRoad[1] == True


def test_parse_player_lap_unfinished_fields_are_safe_defaults():
    """last_lap_ms/s1-3/gaps не переведены в Phase 1 — должны быть
    0/None, а не отсутствовать (downstream делает .get с этими ключами)."""
    out = ip.parse_player_lap(_vars(), player_idx=0)
    assert out["last_lap_ms"] == 0
    assert out["gap_front_ms"] is None
    assert out["lap_distance_m"] is None
    assert out["corner_cutting_warnings"] is None


def test_parse_player_lap_out_of_range_index_returns_empty():
    assert ip.parse_player_lap(_vars(), player_idx=99) == {}


# --------------------------------------------------------------------------- #
# parse_player_telemetry
# --------------------------------------------------------------------------- #

def test_parse_player_telemetry_converts_speed_ms_to_kmh():
    out = ip.parse_player_telemetry(_vars(Speed=27.78), player_idx=0)
    assert out["speed"] == round(27.78 * 3.6)


def test_parse_player_telemetry_gear_labels_match_f1_convention():
    assert ip.parse_player_telemetry(_vars(Gear=0), 0)["gear"] == "N"
    assert ip.parse_player_telemetry(_vars(Gear=-1), 0)["gear"] == "R"
    assert ip.parse_player_telemetry(_vars(Gear=3), 0)["gear"] == "3"


def test_parse_player_telemetry_drops_implausible_speed():
    out = ip.parse_player_telemetry(_vars(Speed=200.0), player_idx=0)  # 720 км/ч
    assert "speed" not in out


# --------------------------------------------------------------------------- #
# parse_participants
# --------------------------------------------------------------------------- #

def test_parse_participants_reads_driver_info_list():
    drivers = [
        {"CarIdx": 0, "UserName": "Ivan Ivanov", "TeamName": "", "CarNumber": "7"},
        {"CarIdx": 1, "UserName": "", "TeamName": "GT Class", "CarNumber": "12"},
    ]
    out = ip.parse_participants(_vars(_drivers=drivers))
    assert out[0]["name"] == "Ivan Ivanov"
    assert out[0]["number"] == 7
    assert out[1]["name"] is None
    assert out[1]["team"] == "GT Class"


def test_parse_participants_skips_malformed_entries():
    out = ip.parse_participants(_vars(_drivers=[{"UserName": "no car idx"}]))
    assert out == {}


# --------------------------------------------------------------------------- #
# Phase 2/3 stubs — must not raise, must return the documented empty shape
# --------------------------------------------------------------------------- #

def test_phase2_phase3_stubs_return_empty_without_raising():
    assert ip.parse_session({}) == {}
    assert ip.parse_car_status_all({}) == {}
    assert ip.parse_car_damage_all({}) == {}
    assert ip.parse_player_status({}, 0) == {}
    assert ip.parse_player_damage({}, 0) == {}
    assert ip.parse_event({}) is None
    assert ip.synthesize_events(None, {}) == []
