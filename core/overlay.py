"""
core/overlay.py
================
Pure functions for building the Broadcast Overlay HUD state dict.

Called from engine.get_overlay_state() — no I/O, no side effects.
"""
from __future__ import annotations

# CSS hex colors per tyre compound letter
_COMPOUND_COLORS: dict[str, str] = {
    "S": "#E8002D",
    "M": "#FFF200",
    "H": "#FFFFFF",
    "I": "#43B02A",
    "W": "#0078D7",
}

# Human-readable race mode labels (RU)
_MODE_LABELS: dict[str, str] = {
    "CALM":   "Спокойно",
    "RACE":   "Гонка",
    "BATTLE": "Борьба",
    "CLIMAX": "Кульминация",
}

_ADVICE_LABELS: dict[str, str | None] = {
    "cover_inside": "Закрой внутреннюю траекторию",
    "hold_line": "Держи выбранную траекторию",
    "late_brake": "Тормози позже",
    "focus": "Сохраняй концентрацию",
    "none": None,
}


#: Насколько круг должен быть хуже личного лучшего, чтобы стать «красным».
#:
#: Ступени с этим цветом в телевизионном хронометраже нет — её попросил пилот
#: (разбор заезда 2026-08-27): фиолетовый/зелёный/жёлтый описывают, насколько
#: круг хорош, но не отделяют «чуть хуже» от «загубленного».
#:
#: Порог ОТНОСИТЕЛЬНЫЙ, а не в секундах: полторы секунды на круге Монако
#: (1:11) и на круге Спа (1:44) — разные величины ошибки, и фиксированное
#: число красило бы длинные трассы строже коротких.
RED_LAP_MARGIN = 0.02


def lap_tone(last_lap_ms: int | None, *, personal_best_ms: int | None,
             session_best_ms: int | None) -> str | None:
    """Цвет времени круга по конвенции хронометража F1.

        purple — быстрейший круг сессии (всего поля)
        green  — личный лучший в этой сессии
        yellow — медленнее личного лучшего
        red    — хуже личного лучшего больше чем на `RED_LAP_MARGIN`

    None означает «красить нечем»: круга нет или сравнивать не с чем. Серое
    время честнее выдуманного цвета — на первом круге личного лучшего ещё не
    существует.

    Эталон поля (`session_best_ms`) приходит позже личного: `f1_benchmark`
    ждёт данных о поле. Пока его нет, шкала работает без фиолетового — это
    лучше, чем держать время серым весь первый стинт.
    """
    if last_lap_ms is None or last_lap_ms <= 0:
        return None
    if personal_best_ms is None or personal_best_ms <= 0:
        return None
    if session_best_ms is not None and 0 < session_best_ms and \
            last_lap_ms <= session_best_ms:
        return "purple"
    if last_lap_ms <= personal_best_ms:
        return "green"
    if last_lap_ms > personal_best_ms * (1.0 + RED_LAP_MARGIN):
        return "red"
    return "yellow"


def _fmt_advice(value: str | None) -> str | None:
    """Keep internal snake_case decision codes out of the driver-facing HUD."""
    if value is None:
        return None
    return _ADVICE_LABELS.get(value, value.replace("_", " "))


def _fmt_gap_ms(ms: int | None) -> str:
    """Format gap in milliseconds to '+1.234' string or '—' if unknown."""
    if ms is None:
        return "—"
    return f"+{ms / 1000:.3f}"


def _fmt_lap_ms(ms: int | None) -> str:
    """Format milliseconds as M:SS.mmm for a compact lap-time panel."""
    if ms is None or ms <= 0:
        return "—"
    minutes, remainder = divmod(int(ms), 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{minutes}:{seconds:02d}.{millis:03d}"


def _compound_color(compound: str) -> str:
    """Return CSS hex color for tyre compound letter, grey if unknown."""
    return _COMPOUND_COLORS.get(compound.upper(), "#888888")


def _relative_rows(grid: list[dict], player_position: int | None,
                    *, ahead: int = 3, behind: int = 3) -> list[dict]:
    """Строки вокруг игрока с накопленным гэпом (сумма gap_front_ms между
    позициями от игрока до целевой строки) — не сырым gap_front_ms целевой
    строки (тот — гэп только к её непосредственному соседу впереди)."""
    if player_position is None:
        return []
    by_pos = {row["position"]: row for row in grid if row.get("position")}
    player_row = by_pos.get(player_position)
    if player_row is None:
        return []

    rows: list[dict] = []
    cumulative = 0
    # gap_front_ms of a row is its OWN gap to the car ahead of it (F1 UDP
    # m_deltaToCarInFront semantics) — walking towards better positions, the
    # gap to the NEXT row is the gap owned by the row we are LEAVING, not the
    # one we are arriving at. Start from the player's own gap, then shift.
    prev_gap = player_row.get("gap_front_ms") or 0
    for pos in range(player_position - 1, player_position - ahead - 1, -1):
        row = by_pos.get(pos)
        if row is None:
            break
        cumulative += prev_gap
        rows.append({**row, "gap_to_player_ms": cumulative,
                     "gap_to_player_str": _fmt_gap_ms(cumulative), "ahead": True})
        prev_gap = row.get("gap_front_ms") or 0
    rows.reverse()
    rows.append({**player_row, "gap_to_player_ms": None,
                 "gap_to_player_str": _fmt_gap_ms(None), "ahead": None})

    # Walking towards worse positions, each row's OWN gap_front_ms already
    # measures its gap to the row directly ahead of it — no shift needed
    # here (unlike the ahead-loop above).
    cumulative = 0
    for pos in range(player_position + 1, player_position + behind + 1):
        row = by_pos.get(pos)
        if row is None:
            break
        cumulative += row.get("gap_front_ms") or 0
        rows.append({**row, "gap_to_player_ms": cumulative,
                     "gap_to_player_str": _fmt_gap_ms(cumulative), "ahead": False})
    return rows


def build_overlay_state(snapshot: dict) -> dict:
    """Build consolidated HUD overlay dict from an engine snapshot.

    Parameters
    ----------
    snapshot : dict
        Flat dict assembled by engine.get_overlay_state() with all raw fields.

    Returns
    -------
    dict
        Structured overlay dict consumed by /api/overlay and the frontend.
    """
    compound: str = (snapshot.get("tyre_compound") or "").upper()

    gaps: dict = {
        "to_leader_ms": snapshot.get("gap_leader_ms"),
        "to_front_ms":  snapshot.get("gap_front_ms"),
        "to_behind_ms": snapshot.get("gap_behind_ms"),
        "to_leader_str": _fmt_gap_ms(snapshot.get("gap_leader_ms")),
        "to_front_str":  _fmt_gap_ms(snapshot.get("gap_front_ms")),
        "to_behind_str": _fmt_gap_ms(snapshot.get("gap_behind_ms")),
    }

    tyre: dict = {
        "compound":       compound or "?",
        "age_laps":       snapshot.get("tyre_age"),
        "wear_pct":       snapshot.get("tyre_wear"),
        "status":         snapshot.get("tyre_status", "unknown"),
        "compound_color": _compound_color(compound),
    }

    corner: dict = {
        "name":           snapshot.get("corner"),
        "type":           snapshot.get("corner_type"),
        "phase":          snapshot.get("phase", "straight"),
        "sector":         snapshot.get("sector", 1),
        "attack_zone":    bool(snapshot.get("attack_zone", False)),
        "defense_advice": snapshot.get("defense_advice", "none"),
    }

    situation: dict = {
        "intensity": snapshot.get("race_intensity", 0),
        "mode":      snapshot.get("race_mode", "CALM"),
        "mode_label": _MODE_LABELS.get(snapshot.get("race_mode", "CALM"), ""),
        "threat":    snapshot.get("race_threat"),
        "advice":    _fmt_advice(snapshot.get("race_advice")),
    }

    strategy: dict = {
        "action":      snapshot.get("strategy_action", "hold"),
        "confidence":  float(snapshot.get("strategy_confidence") or 0.0),
        "advice":      _fmt_advice(snapshot.get("strategy_advice")),
        "tyre_status": snapshot.get("tyre_status", "unknown"),
    }

    car: dict = {
        "fuel_kg": snapshot.get("fuel_kg"),
        # Laps of fuel left relative to the race distance: negative = short.
        "fuel_delta_laps": snapshot.get("fuel_remaining_laps"),
        "ers_percent": snapshot.get("ers_percent"),
        "ers_deploy_mode": snapshot.get("ers_deploy_mode"),
        # Harvest/deploy so far THIS lap, as % of the 4 MJ store — the two arcs
        # around the HUD's battery ring.
        "ers_harvested_pct": snapshot.get("ers_harvested_pct"),
        "ers_deployed_pct": snapshot.get("ers_deployed_pct"),
        "power_ice_kw": snapshot.get("power_ice_kw"),
        "power_mguk_kw": snapshot.get("power_mguk_kw"),
        "last_lap_ms": snapshot.get("last_lap_ms"),
        "last_lap_str": _fmt_lap_ms(snapshot.get("last_lap_ms")),
        # Цвет решается ЗДЕСЬ, а не в вёрстке: правило хронометража — это
        # логика с порогом и тремя эталонами, и её место там, где её можно
        # покрыть тестами. Виджет получает готовое слово и красит.
        "last_lap_tone": lap_tone(
            snapshot.get("last_lap_ms"),
            personal_best_ms=snapshot.get("personal_best_lap_ms"),
            session_best_ms=snapshot.get("session_best_lap_ms"),
        ),
        "personal_best_lap_ms": snapshot.get("personal_best_lap_ms"),
        "session_best_lap_ms": snapshot.get("session_best_lap_ms"),
    }

    # Live driver inputs — pedal/steering traces and the rev-light strip.
    inputs: dict = {
        "throttle_pct": snapshot.get("throttle_pct"),
        "brake_pct": snapshot.get("brake_pct"),
        "steer": snapshot.get("steer"),
        "rpm": snapshot.get("rpm"),
        "rev_lights_pct": snapshot.get("rev_lights_pct"),
    }

    # Conditions + the running track-limits count, shown on the HUD info row.
    session: dict = {
        "air_temp_c": snapshot.get("air_temp_c"),
        "track_temp_c": snapshot.get("track_temp_c"),
        "track_limit_warnings": snapshot.get("corner_cutting_warnings"),
        # Metres to the next DRS zone; 0/None = not approaching one.
        "drs_distance_m": snapshot.get("drs_distance_m"),
        "drs_allowed": bool(snapshot.get("drs_allowed", False)),
    }

    # Top-5 grid sorted by position ascending
    grid_raw: list = snapshot.get("grid", [])
    grid_top5 = sorted(grid_raw, key=lambda x: x.get("position", 99))[:5]

    return {
        "position":    snapshot.get("position"),
        "lap_current": snapshot.get("lap_current"),
        "lap_total":   snapshot.get("lap_total"),
        "speed_kmh":   snapshot.get("speed_kmh"),
        "drs_active":  bool(snapshot.get("drs_active", False)),
        "gaps":        gaps,
        "tyre":        tyre,
        "corner":      corner,
        "situation":   situation,
        "strategy":    strategy,
        "car":         car,
        "inputs":      inputs,
        "session":     session,
        "grid_top5":   grid_top5,
        "leader":      snapshot.get("leader"),
        "radar":       snapshot.get("radar", []),
        "relative":    _relative_rows(grid_raw, snapshot.get("position")),
    }
