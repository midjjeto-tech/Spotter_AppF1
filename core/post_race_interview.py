"""Fact-bound reconstruction of a small post-race paddock interview."""
from __future__ import annotations

_PLACEHOLDER_NAMES = {"", "driver", "unknown", "гонщик", "пилот"}


def _name(driver_lookup, vehicle_idx: int) -> str | None:
    identity = driver_lookup(vehicle_idx) or {}
    raw = identity.get("name")
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    return value if value.casefold() not in _PLACEHOLDER_NAMES else None


def _response(*, position: int, gained: int, overtakes: int) -> str:
    if position == 1:
        return (
            "Гонка потребовала полной концентрации. После старта главным было "
            "держать темп и не отдавать контроль."
        )
    if gained >= 4 or overtakes >= 4:
        return (
            f"Пришлось постоянно атаковать: {overtakes} обгонов и "
            f"{gained:+d} позиций относительно старта. Машина позволяла бороться."
        )
    if position <= 3:
        return (
            "Подиум — хороший итог, хотя по ходу гонки были моменты, где можно "
            "было добиться большего."
        )
    if gained < 0:
        return (
            f"Результат ниже ожиданий: потеряно {abs(gained)} позиций. "
            "Нужно спокойно разобрать, где ушла гонка."
        )
    return (
        f"Финиш на P{position} отражает наш сегодняшний темп. "
        "Мы использовали возможности, которые появились по ходу гонки."
    )


def build(
    grid: list[dict],
    driver_lookup,
    player_idx: int,
    *,
    vote: dict | None,
    overtakes_by_idx: dict[int, int] | None = None,
) -> dict | None:
    """Select winner, vote leader and player, then reconstruct their answers."""
    overtakes = overtakes_by_idx or {}
    rows: list[dict] = []
    for entry in grid:
        idx = entry.get("vehicle_idx")
        if not isinstance(idx, int):
            continue
        name = _name(driver_lookup, idx)
        try:
            position = int(entry.get("position") or 0)
        except (TypeError, ValueError):
            position = 0
        if name is None or position <= 0:
            continue
        try:
            grid_position = int(entry.get("grid_position") or 0)
        except (TypeError, ValueError):
            grid_position = 0
        rows.append({
            "driver": name,
            "vehicle_idx": idx,
            "position": position,
            "positions_gained": (
                grid_position - position if grid_position > 0 else 0
            ),
            "overtakes": max(0, int(overtakes.get(idx, 0) or 0)),
            "is_player": idx == player_idx,
        })
    if not rows:
        return None

    by_name = {row["driver"]: row for row in rows}
    ordered: list[tuple[dict, str]] = []

    winner = min(rows, key=lambda row: row["position"])
    ordered.append((winner, "победитель"))

    dotd_driver = (vote or {}).get("dotd_driver")
    if dotd_driver in by_name and dotd_driver != winner["driver"]:
        ordered.append((by_name[dotd_driver], "лидер голосования"))

    player = next((row for row in rows if row["is_player"]), None)
    if player is not None and all(player["driver"] != row["driver"] for row, _ in ordered):
        ordered.append((player, "пилот игрока"))

    for row in sorted(rows, key=lambda item: item["position"]):
        if len(ordered) >= 3:
            break
        if all(row["driver"] != existing["driver"] for existing, _ in ordered):
            ordered.append((row, "после финиша"))

    quotes = []
    for row, role in ordered[:3]:
        quotes.append({
            **row,
            "role": role,
            "quote": _response(
                position=row["position"],
                gained=row["positions_gained"],
                overtakes=row["overtakes"],
            ),
        })
    return {
        "interview_quotes": quotes,
        "interview_drivers": [quote["driver"] for quote in quotes],
        "interview_transcript": "\n".join(
            f"{quote['driver']} ({quote['role']}): {quote['quote']}"
            for quote in quotes
        ),
    }
