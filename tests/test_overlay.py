"""
tests/test_overlay.py
======================
Unit tests for core/overlay.py — pure HUD state builder.
"""
import pytest
from core.overlay import _fmt_gap_ms, _compound_color, build_overlay_state


# ---------------------------------------------------------------------------
# _fmt_gap_ms
# ---------------------------------------------------------------------------

def test_fmt_gap_none():
    assert _fmt_gap_ms(None) == "—"


def test_fmt_gap_zero():
    assert _fmt_gap_ms(0) == "+0.000"


def test_fmt_gap_positive():
    assert _fmt_gap_ms(1234) == "+1.234"


def test_fmt_gap_large():
    assert _fmt_gap_ms(12345) == "+12.345"


# ---------------------------------------------------------------------------
# _compound_color
# ---------------------------------------------------------------------------

def test_compound_color_soft():
    assert _compound_color("S") == "#E8002D"


def test_compound_color_medium():
    assert _compound_color("M") == "#FFF200"


def test_compound_color_hard():
    assert _compound_color("H") == "#FFFFFF"


def test_compound_color_intermediate():
    assert _compound_color("I") == "#43B02A"


def test_compound_color_wet():
    assert _compound_color("W") == "#0078D7"


def test_compound_color_unknown():
    color = _compound_color("X")
    assert color == "#888888"


def test_compound_color_lowercase():
    # lowercase input should also work
    assert _compound_color("s") == "#E8002D"


# ---------------------------------------------------------------------------
# build_overlay_state — structure / defaults
# ---------------------------------------------------------------------------

def test_build_minimal_snapshot():
    result = build_overlay_state({})
    # All top-level keys must be present
    assert "position" in result
    assert "lap_current" in result
    assert "lap_total" in result
    assert "speed_kmh" in result
    assert "drs_active" in result
    assert "gaps" in result
    assert "tyre" in result
    assert "corner" in result
    assert "situation" in result
    assert "strategy" in result
    assert "grid_top5" in result
    assert "leader" in result
    assert "radar" in result
    assert "relative" in result
    assert "car" in result


def test_build_defaults_on_empty():
    result = build_overlay_state({})
    assert result["drs_active"] is False
    assert result["gaps"]["to_leader_str"] == "—"
    assert result["tyre"]["compound"] == "?"
    assert result["tyre"]["status"] == "unknown"
    assert result["corner"]["phase"] == "straight"
    assert result["corner"]["sector"] == 1
    assert result["corner"]["attack_zone"] is False
    assert result["situation"]["intensity"] == 0
    assert result["situation"]["mode"] == "CALM"
    assert result["strategy"]["action"] == "hold"
    assert result["grid_top5"] == []


def test_build_gaps_populated():
    snap = {
        "gap_leader_ms": 5000,
        "gap_front_ms": 1200,
        "gap_behind_ms": 800,
    }
    result = build_overlay_state(snap)
    gaps = result["gaps"]
    assert gaps["to_leader_ms"] == 5000
    assert gaps["to_front_ms"] == 1200
    assert gaps["to_behind_ms"] == 800
    assert gaps["to_leader_str"] == "+5.000"
    assert gaps["to_front_str"] == "+1.200"
    assert gaps["to_behind_str"] == "+0.800"


def test_build_tyre_fresh():
    snap = {
        "tyre_compound": "S",
        "tyre_age": 3,
        "tyre_wear": 12.5,
        "tyre_status": "fresh",
    }
    result = build_overlay_state(snap)
    tyre = result["tyre"]
    assert tyre["compound"] == "S"
    assert tyre["age_laps"] == 3
    assert tyre["wear_pct"] == 12.5
    assert tyre["status"] == "fresh"
    assert tyre["compound_color"] == "#E8002D"


def test_build_tyre_cliff():
    snap = {
        "tyre_compound": "M",
        "tyre_age": 35,
        "tyre_wear": 80.0,
        "tyre_status": "cliff",
    }
    result = build_overlay_state(snap)
    assert result["tyre"]["status"] == "cliff"
    assert result["tyre"]["compound_color"] == "#FFF200"


def test_build_drs_active():
    result = build_overlay_state({"drs_active": True})
    assert result["drs_active"] is True


def test_build_drs_inactive():
    result = build_overlay_state({"drs_active": False})
    assert result["drs_active"] is False


def test_build_car_status_for_compact_hud():
    result = build_overlay_state({
        "fuel_kg": 31.45,
        "ers_percent": 67.8,
        "ers_deploy_mode": 3,
        "last_lap_ms": 83_456,
    })

    assert result["car"] == {
        "fuel_kg": 31.45,
        "fuel_delta_laps": None,
        "ers_percent": 67.8,
        "ers_deploy_mode": 3,
        "ers_harvested_pct": None,
        "ers_deployed_pct": None,
        "power_ice_kw": None,
        "power_mguk_kw": None,
        "last_lap_ms": 83_456,
        "last_lap_str": "1:23.456",
    }


def test_build_corner_info():
    snap = {
        "corner": "La Source",
        "corner_type": "hairpin",
        "phase": "apex",
        "sector": 2,
        "attack_zone": True,
        "defense_advice": "cover_inside",
    }
    result = build_overlay_state(snap)
    corner = result["corner"]
    assert corner["name"] == "La Source"
    assert corner["type"] == "hairpin"
    assert corner["phase"] == "apex"
    assert corner["sector"] == 2
    assert corner["attack_zone"] is True
    assert corner["defense_advice"] == "cover_inside"


def test_build_situation_mode():
    snap = {
        "race_intensity": 85,
        "race_mode": "BATTLE",
        "race_threat": "Хэмилтон атакует (0.7с)",
        "race_advice": "cover_inside",
    }
    result = build_overlay_state(snap)
    sit = result["situation"]
    assert sit["intensity"] == 85
    assert sit["mode"] == "BATTLE"
    assert sit["mode_label"] == "Борьба"
    assert sit["threat"] == "Хэмилтон атакует (0.7с)"
    assert sit["advice"] == "cover_inside"


def test_build_grid_top5():
    grid = [
        {"position": 3, "driver": "Хэмилтон", "team": "Mercedes", "color": "#00D2BE"},
        {"position": 1, "driver": "Ферстаппен", "team": "Red Bull", "color": "#3671C6"},
        {"position": 2, "driver": "Леклер", "team": "Ferrari", "color": "#E8002D"},
        {"position": 5, "driver": "Норрис", "team": "McLaren", "color": "#FF8000"},
        {"position": 4, "driver": "Сайнс", "team": "Ferrari", "color": "#E8002D"},
        {"position": 6, "driver": "Пиастри", "team": "McLaren", "color": "#FF8000"},
    ]
    result = build_overlay_state({"grid": grid})
    top5 = result["grid_top5"]
    assert len(top5) == 5
    assert top5[0]["position"] == 1
    assert top5[4]["position"] == 5


def test_build_grid_top5_fewer_than_5():
    grid = [
        {"position": 1, "driver": "A", "team": "T1", "color": "#fff"},
        {"position": 2, "driver": "B", "team": "T2", "color": "#000"},
    ]
    result = build_overlay_state({"grid": grid})
    assert len(result["grid_top5"]) == 2


# ---------------------------------------------------------------------------
# radar / relative
# ---------------------------------------------------------------------------

def test_build_radar_passes_through_from_snapshot():
    radar = [{"vehicle_idx": 12, "side": "left", "lateral_m": 1.8, "longitudinal_m": -3.2}]
    result = build_overlay_state({"radar": radar})
    assert result["radar"] == radar


def test_build_radar_defaults_to_empty_list():
    result = build_overlay_state({})
    assert result["radar"] == []


def test_relative_rows_player_in_middle_of_pack():
    # 8 машин, игрок на P5 — ahead=3/behind=3 не упирается в край пелотона
    # (P1 намеренно НЕ входит в окно, чтобы отдельно проверить, что окно
    # действительно ограничено 3 позициями, а не "до лидера").
    grid = [
        {"position": 1, "driver": "A", "team": "T", "color": "#111", "gap_front_ms": 0},
        {"position": 2, "driver": "B", "team": "T", "color": "#222", "gap_front_ms": 500},
        {"position": 3, "driver": "C", "team": "T", "color": "#333", "gap_front_ms": 700},
        {"position": 4, "driver": "D", "team": "T", "color": "#444", "gap_front_ms": 900},
        {"position": 5, "driver": "E", "team": "T", "color": "#555", "gap_front_ms": 1100},
        {"position": 6, "driver": "F", "team": "T", "color": "#666", "gap_front_ms": 600},
        {"position": 7, "driver": "G", "team": "T", "color": "#777", "gap_front_ms": 800},
        {"position": 8, "driver": "H", "team": "T", "color": "#888", "gap_front_ms": 400},
    ]
    result = build_overlay_state({"grid": grid, "position": 5})
    rows = result["relative"]
    assert [r["position"] for r in rows] == [2, 3, 4, 5, 6, 7, 8]

    # gap_front_ms каждой строки — это её СОБСТВЕННЫЙ гэп до машины ВПЕРЕДИ
    # неё (F1 UDP m_deltaToCarInFront). Значит гэп "игрок -> P4" — это
    # СОБСТВЕННЫЙ gap_front_ms игрока (1100), а не P4 (900) — накопление
    # сдвинуто на одну строку относительно направления обхода.
    row4 = next(r for r in rows if r["position"] == 4)
    assert row4["ahead"] is True
    assert row4["gap_to_player_ms"] == 1100  # непосредственный сосед — собственный gap_front игрока

    row2 = next(r for r in rows if r["position"] == 2)
    assert row2["ahead"] is True
    assert row2["gap_to_player_ms"] == 1100 + 900 + 700  # накопленный: gap игрока + gap P4 + gap P3

    player_row = next(r for r in rows if r["position"] == 5)
    assert player_row["ahead"] is None
    assert player_row["gap_to_player_ms"] is None
    assert player_row["gap_to_player_str"] == "—"

    row6 = next(r for r in rows if r["position"] == 6)
    assert row6["ahead"] is False
    assert row6["gap_to_player_ms"] == 600
    assert row6["gap_to_player_str"] == "+0.600"

    row8 = next(r for r in rows if r["position"] == 8)
    assert row8["ahead"] is False
    assert row8["gap_to_player_ms"] == 600 + 800 + 400


def test_relative_rows_player_leading_has_no_ahead_rows():
    grid = [
        {"position": 1, "driver": "A", "team": "T", "color": "#111", "gap_front_ms": 0},
        {"position": 2, "driver": "B", "team": "T", "color": "#222", "gap_front_ms": 500},
    ]
    result = build_overlay_state({"grid": grid, "position": 1})
    rows = result["relative"]
    assert [r["position"] for r in rows] == [1, 2]
    assert rows[0]["ahead"] is None


def test_relative_rows_player_last_has_no_behind_rows():
    grid = [
        {"position": 1, "driver": "A", "team": "T", "color": "#111", "gap_front_ms": 0},
        {"position": 2, "driver": "B", "team": "T", "color": "#222", "gap_front_ms": 500},
    ]
    result = build_overlay_state({"grid": grid, "position": 2})
    rows = result["relative"]
    assert [r["position"] for r in rows] == [1, 2]
    assert rows[-1]["ahead"] is None
    # Гэп "игрок(P2) -> P1" — это СОБСТВЕННЫЙ gap_front игрока (500), не
    # gap_front_ms строки P1 (0, у лидера "гэп до впередиидущего" не задан).
    assert rows[0]["gap_to_player_ms"] == 500


def test_relative_rows_gap_in_grid_stops_accumulation():
    # Позиция 3 отсутствует (сошла машина/неполный тик). P2 физически
    # присутствует в grid, но "дыра" на P3 должна остановить накопление
    # ДО того, как накопитель дойдёт до P2 — иначе получим гэп, посчитанный
    # через неизвестный (сошедшая машина) промежуток.
    grid = [
        {"position": 1, "driver": "A", "team": "T", "color": "#111", "gap_front_ms": 0},
        {"position": 2, "driver": "B", "team": "T", "color": "#222", "gap_front_ms": 500},
        {"position": 4, "driver": "D", "team": "T", "color": "#444", "gap_front_ms": 900},
        {"position": 5, "driver": "E", "team": "T", "color": "#555", "gap_front_ms": 300},
        {"position": 6, "driver": "F", "team": "T", "color": "#666", "gap_front_ms": 200},
    ]
    result = build_overlay_state({"grid": grid, "position": 5})
    rows = result["relative"]
    # P2 существует в grid, но недостижим из-за дыры на P3 — не должен попасть
    # в результат, хотя формально "ahead" диапазон (3 позиции) его бы охватил.
    assert [r["position"] for r in rows] == [4, 5, 6]
    # Гэп "игрок(P5) -> P4" — собственный gap_front игрока (300), не P4 (900).
    row4 = next(r for r in rows if r["position"] == 4)
    assert row4["gap_to_player_ms"] == 300


def test_relative_rows_unknown_player_position_returns_empty():
    grid = [{"position": 1, "driver": "A", "team": "T", "color": "#111", "gap_front_ms": 0}]
    result = build_overlay_state({"grid": grid, "position": None})
    assert result["relative"] == []


def test_relative_rows_player_position_not_in_grid_returns_empty():
    grid = [{"position": 1, "driver": "A", "team": "T", "color": "#111", "gap_front_ms": 0}]
    result = build_overlay_state({"grid": grid, "position": 99})
    assert result["relative"] == []


def test_build_speed_and_position():
    snap = {"speed_kmh": 312.5, "position": 3, "lap_current": 18, "lap_total": 57}
    result = build_overlay_state(snap)
    assert result["speed_kmh"] == 312.5
    assert result["position"] == 3
    assert result["lap_current"] == 18
    assert result["lap_total"] == 57


# ---------------------------------------------------------------------------
# radio ATTACK_ZONE code
# ---------------------------------------------------------------------------

def test_attack_zone_has_no_radio_line_by_design():
    """ATTACK_ZONE НЕ маршрутизируется в CHANNEL_RADIO ни в одном типе сессии
    (`channel_router._RADIO_IN_RACE`), поэтому радио-реплики у него нет и быть
    не должно. Раньше пул для него существовал и был недостижим — вместе с
    семью другими; текст берётся из `templates.SIMPLE`, см. тест ниже."""
    from commentator.channel_router import route_event
    from commentator.radio import get_radio_line

    for session in ("race", "qualifying", "practice", "unknown"):
        assert route_event({"event_code": "ATTACK_ZONE"}, session) != "radio"
    assert get_radio_line("ATTACK_ZONE") is None


# ---------------------------------------------------------------------------
# templates ATTACK_ZONE code
# ---------------------------------------------------------------------------

def test_templates_attack_zone_in_simple():
    from commentator.templates import SIMPLE
    assert "ATTACK_ZONE" in SIMPLE
    assert len(SIMPLE["ATTACK_ZONE"]) >= 3


def test_templates_attack_zone_persona_hype():
    from commentator.templates import PERSONA
    assert "ATTACK_ZONE" in PERSONA.get("hype", {})
    assert len(PERSONA["hype"]["ATTACK_ZONE"]) >= 2


def test_templates_attack_zone_persona_calm():
    from commentator.templates import PERSONA
    assert "ATTACK_ZONE" in PERSONA.get("calm", {})


def test_templates_attack_zone_persona_toxic():
    from commentator.templates import PERSONA
    assert "ATTACK_ZONE" in PERSONA.get("toxic", {})


# ---------------------------------------------------------------------------
# inputs / session — in-game HUD blocks (pedals, rev lights, conditions)
# ---------------------------------------------------------------------------

def test_build_inputs_block_passes_driver_inputs_through():
    result = build_overlay_state({
        "throttle_pct": 100.0, "brake_pct": 12.5, "steer": -0.4,
        "rpm": 11800, "rev_lights_pct": 92,
    })
    assert result["inputs"] == {
        "throttle_pct": 100.0, "brake_pct": 12.5, "steer": -0.4,
        "rpm": 11800, "rev_lights_pct": 92,
    }


def test_build_inputs_block_is_all_none_before_any_telemetry():
    # Widgets must be able to render a placeholder rather than crash on boot.
    assert build_overlay_state({})["inputs"] == {
        "throttle_pct": None, "brake_pct": None, "steer": None,
        "rpm": None, "rev_lights_pct": None,
    }


def test_build_session_block_carries_conditions_and_track_limits():
    result = build_overlay_state({
        "air_temp_c": 27, "track_temp_c": 41,
        "corner_cutting_warnings": 2, "drs_distance_m": 180, "drs_allowed": True,
    })
    assert result["session"] == {
        "air_temp_c": 27, "track_temp_c": 41, "track_limit_warnings": 2,
        "drs_distance_m": 180, "drs_allowed": True,
    }


def test_build_car_block_exposes_ers_flow_and_power_split():
    result = build_overlay_state({
        "ers_harvested_pct": 42.0, "ers_deployed_pct": 65.0,
        "power_ice_kw": 560.0, "power_mguk_kw": 120.0,
        "fuel_remaining_laps": -0.8,
    })
    car = result["car"]
    assert car["ers_harvested_pct"] == 42.0
    assert car["ers_deployed_pct"] == 65.0
    assert car["power_ice_kw"] == 560.0
    assert car["power_mguk_kw"] == 120.0
    assert car["fuel_delta_laps"] == -0.8
