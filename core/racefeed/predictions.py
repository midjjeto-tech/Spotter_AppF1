"""Deterministic pre-race forecast and post-race scoring for RaceFeed.

This module never calls an LLM.  A forecast is built once from telemetry and
the player's local career history, persisted, and later checked only against
Final Classification and observed race events.
"""
from __future__ import annotations

from statistics import mean

from analytics import archive
import core.weekend_duel as weekend_duel


FINISH_CHOICES = {"podium", "points", "outside_points"}
TEAMMATE_CHOICES = {"player", "teammate", "draw"}
RISK_CHOICES = {"safety_car", "rain", "penalty"}


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def finish_band(position: int | None) -> str | None:
    position = _as_int(position)
    if position <= 0:
        return None
    if position <= 3:
        return "podium"
    if position <= 10:
        return "points"
    return "outside_points"


def normalize_ticket(raw: dict | None) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    ticket = {
        "finish": str(raw.get("finish") or ""),
        "teammate": str(raw.get("teammate") or ""),
        "risk": str(raw.get("risk") or ""),
    }
    if ticket["finish"] not in FINISH_CHOICES:
        raise ValueError("bad finish choice")
    if ticket["teammate"] not in TEAMMATE_CHOICES:
        raise ValueError("bad teammate choice")
    if ticket["risk"] not in RISK_CHOICES:
        raise ValueError("bad risk choice")
    return ticket


def _recent_positions(driver: str, results: list[dict]) -> list[int]:
    positions: list[int] = []
    for result in results:
        for row in result.get("classification") or []:
            if str(row.get("driver") or "").casefold() != driver.casefold():
                continue
            position = _as_int(row.get("position"))
            if position > 0:
                positions.append(position)
            break
        if len(positions) >= 5:
            break
    return positions


def _expected_position(current: int, history: list[int]) -> float | None:
    if current > 0 and history:
        return current * 0.65 + mean(history) * 0.35
    if current > 0:
        return float(current)
    if history:
        return mean(history)
    return None


def _position_confidence(current: int, history: list[int]) -> int:
    confidence = 54 + min(20, len(history) * 4) + (6 if current > 0 else 0)
    if current > 0 and history and abs(current - mean(history)) <= 3:
        confidence += 5
    return _clamp(confidence, 52, 85)


def _risk_forecast(snapshot: dict, sessions: list[dict]) -> dict:
    rain = snapshot.get("rain_forecast") or {}
    rain_pct = _as_int(rain.get("rain_pct"))
    if rain_pct >= 35:
        minutes = _as_int(rain.get("minutes"))
        when = f" через {minutes} мин" if minutes > 0 else ""
        return {
            "choice": "rain",
            "confidence": _clamp(rain_pct, 40, 90),
            "basis": f"Прогноз игры: {rain_pct}% осадков{when}.",
        }

    track_id = snapshot.get("track_id")
    matching = [
        item for item in sessions
        if item.get("session_type") == "race"
        and (track_id is None or item.get("track_id") == track_id)
    ][:5]
    counts = {"safety_car": 0, "penalty": 0}
    loaded = 0
    for item in matching:
        data = archive.load_game_session(item.get("path", ""))
        if not data:
            continue
        loaded += 1
        codes = set(data.get("events") or [])
        if codes & {"SCAR", "SAFETY_CAR_DEPLOYED"}:
            counts["safety_car"] += 1
        if "PENA" in codes:
            counts["penalty"] += 1
    if loaded:
        choice = max(counts, key=lambda key: (counts[key], key == "safety_car"))
        rate = counts[choice] / loaded
        labels = {"safety_car": "Safety Car", "penalty": "штраф"}
        return {
            "choice": choice,
            "confidence": _clamp(round(42 + rate * 40), 42, 82),
            "basis": (
                f"На этой трассе: {labels[choice]} в {counts[choice]} "
                f"из {loaded} последних визитов."
            ),
        }
    return {
        "choice": "safety_car",
        "confidence": 38,
        "basis": "Истории трассы пока нет: базовый риск модели.",
    }


def build_model_forecast(
    snapshot: dict,
    *,
    season_results: list[dict] | None = None,
    game_sessions: list[dict] | None = None,
) -> dict | None:
    """Build one explainable forecast from known pre-race facts."""
    player = str(snapshot.get("player_driver") or "").strip()
    teammate = str(snapshot.get("teammate_driver") or "").strip()
    if not player or not teammate:
        return None

    results = season_results if season_results is not None else archive.list_season_results(5)
    sessions = game_sessions if game_sessions is not None else archive.list_game_sessions()
    player_current = _as_int(snapshot.get("player_position"))
    teammate_current = _as_int(snapshot.get("teammate_position"))
    player_history = _recent_positions(player, results)
    teammate_history = _recent_positions(teammate, results)
    player_expected = _expected_position(player_current, player_history)
    teammate_expected = _expected_position(teammate_current, teammate_history)
    if player_expected is None or teammate_expected is None:
        return None

    player_confidence = _position_confidence(player_current, player_history)
    gap = teammate_expected - player_expected
    teammate_choice = "draw" if abs(gap) < 0.75 else "player" if gap > 0 else "teammate"
    teammate_confidence = _clamp(
        51 + round(abs(gap) * 5) + min(12, (len(player_history) + len(teammate_history)) * 2),
        51,
        84,
    )
    history_note = (
        f"Старт P{player_current}; учтено гонок: {len(player_history)}."
        if player_current > 0
        else f"Учтено прошлых гонок: {len(player_history)}."
    )
    return {
        "participants": {"player": player, "teammate": teammate},
        "finish": {
            "choice": finish_band(round(player_expected)),
            "confidence": player_confidence,
            "basis": history_note,
        },
        "teammate": {
            "choice": teammate_choice,
            "confidence": teammate_confidence,
            "basis": (
                f"Ожидание модели: P{player_expected:.1f} против "
                f"P{teammate_expected:.1f}."
            ),
        },
        "risk": _risk_forecast(snapshot, sessions),
    }


def _hits(picks: dict, actual: dict) -> dict:
    risks = actual.get("risks") or {}
    return {
        "finish": picks.get("finish") == actual.get("finish"),
        "teammate": picks.get("teammate") == actual.get("teammate"),
        "risk": bool(risks.get(picks.get("risk"))),
    }


def resolve(
    model_forecast: dict,
    reader_ticket: dict,
    grid: list[dict],
    driver_lookup,
    player_idx: int,
    *,
    actual_risks: dict,
) -> dict | None:
    """Score fixed picks against authoritative post-race facts."""
    player_row = next(
        (row for row in grid if _as_int(row.get("vehicle_idx"), -1) == player_idx),
        None,
    )
    if player_row is None:
        return None
    actual_finish = finish_band(_as_int(player_row.get("position")))
    duel = weekend_duel.build(grid, driver_lookup, player_idx)
    if actual_finish is None or duel is None:
        return None
    risks = {
        "safety_car": bool(actual_risks.get("safety_car")),
        "rain": bool(actual_risks.get("rain")),
        "penalty": bool(actual_risks.get("penalty")),
    }
    actual = {"finish": actual_finish, "teammate": duel["winner"], "risks": risks}
    model_picks = {
        key: (model_forecast.get(key) or {}).get("choice")
        for key in ("finish", "teammate", "risk")
    }
    model_hits = _hits(model_picks, actual)
    result = {
        "actual": actual,
        "model_hits": model_hits,
        "model_score": sum(model_hits.values()),
    }
    if all(reader_ticket.get(key) for key in ("finish", "teammate", "risk")):
        reader_hits = _hits(reader_ticket, actual)
        result.update({
            "reader_hits": reader_hits,
            "reader_score": sum(reader_hits.values()),
        })
    else:
        result.update({"reader_hits": {}, "reader_score": None})
    return result


def scoreboard(rows: list[dict]) -> dict:
    resolved = [
        row for row in rows
        if row.get("status") == "resolved"
        and (row.get("result") or {}).get("reader_score") is not None
    ]
    reader = sum(
        _as_int((row.get("result") or {}).get("reader_score"))
        for row in resolved
    )
    model = sum(_as_int((row.get("result") or {}).get("model_score")) for row in resolved)
    return {"reader": reader, "model": model, "races": len(resolved)}
