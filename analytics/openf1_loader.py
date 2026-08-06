"""Adapt OpenF1 historical data to the small Session surface used by analytics.

The archive normalizer intentionally consumes only pandas dataframes and a few
session metadata attributes.  This adapter keeps that contract intact, so the
web API, comparator and stored JSON format do not need source-specific branches.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from core.openf1_client import OpenF1Client


_SESSION_NAMES = {
    "R": "Race",
    "Q": "Qualifying",
    "S": "Sprint",
}


class _EventInfo(dict):
    def __init__(self, event_name: str, year: int):
        super().__init__(EventName=event_name)
        self.year = year


class OpenF1Laps(pd.DataFrame):
    """DataFrame with the one FastF1 ``Laps`` helper used by the normalizer."""

    @property
    def _constructor(self):
        return OpenF1Laps

    def pick_fastest(self):
        valid = self.dropna(subset=["LapTime"])
        if valid.empty:
            return None
        return valid.loc[valid["LapTime"].idxmin()]


@dataclass
class OpenF1Session:
    event: _EventInfo
    name: str
    results: pd.DataFrame
    laps: pd.DataFrame
    weather_data: pd.DataFrame
    race_control_messages: pd.DataFrame
    data_source: str = "openf1"


def _seconds(value: Any) -> float | None:
    """Return one scalar duration; qualifying results may contain Q1/Q2/Q3."""
    if isinstance(value, (list, tuple)):
        value = next((item for item in reversed(value) if item is not None), None)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _timedelta(value: Any):
    seconds = _seconds(value)
    return pd.to_timedelta(seconds, unit="s") if seconds is not None else pd.NaT


def _driver_map(records: list | None) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for row in records or []:
        if not isinstance(row, dict):
            continue
        try:
            out[int(row.get("driver_number"))] = row
        except (TypeError, ValueError):
            continue
    return out


def _results_frame(records: list | None, drivers: dict[int, dict]) -> pd.DataFrame:
    rows = []
    for row in records or []:
        if not isinstance(row, dict):
            continue
        try:
            number = int(row.get("driver_number"))
        except (TypeError, ValueError):
            continue
        driver = drivers.get(number, {})
        rows.append({
            "Position": row.get("position"),
            "Abbreviation": driver.get("name_acronym") or str(number),
            "TeamName": driver.get("team_name") or "?",
            # The existing normalizer interprets Time as gap for P2+.
            "Time": _timedelta(row.get("gap_to_leader")),
            "FastestLapTime": pd.NaT,
        })
    return pd.DataFrame(rows, columns=[
        "Position", "Abbreviation", "TeamName", "Time", "FastestLapTime",
    ])


def _laps_frame(records: list | None, drivers: dict[int, dict]) -> pd.DataFrame:
    rows = []
    for row in records or []:
        if not isinstance(row, dict):
            continue
        try:
            number = int(row.get("driver_number"))
        except (TypeError, ValueError):
            continue
        driver = drivers.get(number, {})
        rows.append({
            "Driver": driver.get("name_acronym") or str(number),
            "LapNumber": row.get("lap_number"),
            "LapTime": _timedelta(row.get("lap_duration")),
            "Sector1Time": _timedelta(row.get("duration_sector_1")),
            "Sector2Time": _timedelta(row.get("duration_sector_2")),
            "Sector3Time": _timedelta(row.get("duration_sector_3")),
        })
    return OpenF1Laps(rows, columns=[
        "Driver", "LapNumber", "LapTime", "Sector1Time", "Sector2Time", "Sector3Time",
    ])


def _weather_frame(records: list | None) -> pd.DataFrame:
    rows = []
    for row in records or []:
        if not isinstance(row, dict):
            continue
        rows.append({
            "AirTemp": row.get("air_temperature"),
            "TrackTemp": row.get("track_temperature"),
            "Rainfall": bool(row.get("rainfall", False)),
        })
    return pd.DataFrame(rows, columns=["AirTemp", "TrackTemp", "Rainfall"])


def _race_control_frame(records: list | None) -> pd.DataFrame:
    rows = [
        {"Message": row.get("message", "")}
        for row in (records or [])
        if isinstance(row, dict)
    ]
    return pd.DataFrame(rows, columns=["Message"])


def load_openf1_session(track_id: int, year: int, session_type: str,
                        client: OpenF1Client | None = None
                        ) -> tuple[OpenF1Session | None, str | None]:
    """Load an OpenF1 session and expose the subset expected by ``normalize``."""
    # Imported lazily to avoid a module cycle: f1_benchmark imports TRACK_ID_TO_GP
    # from analytics.loader, while both features share this verified circuit map.
    from analytics.loader import TRACK_ID_TO_GP
    from core.f1_benchmark import TRACK_ID_TO_CIRCUIT

    entry = TRACK_ID_TO_GP.get(track_id)
    circuit_id = TRACK_ID_TO_CIRCUIT.get(track_id)
    session_name = _SESSION_NAMES.get(session_type.upper())
    if entry is None or circuit_id is None:
        return None, "no_fastf1_data"
    if session_name is None:
        return None, f"session_not_found: unsupported session type {session_type}"

    source = client or OpenF1Client()
    session_key = source.get_session_key(year, circuit_id, session_name=session_name)
    if session_key is None:
        if source.blocked_by_live_session:
            return None, "openf1_live_session"
        return None, "no_data_for_session"

    metadata = source.get_session_record(session_key) or {}
    driver_records = source.get_drivers(session_key)
    result_records = source.get_session_results(session_key)
    lap_records = source.get_laps(session_key)
    if not result_records and not lap_records:
        return None, "no_data_for_session"

    drivers = _driver_map(driver_records)
    session = OpenF1Session(
        event=_EventInfo(entry[1], year),
        name=str(metadata.get("session_name") or session_name),
        results=_results_frame(result_records, drivers),
        laps=_laps_frame(lap_records, drivers),
        weather_data=_weather_frame(source.get_weather(session_key)),
        race_control_messages=_race_control_frame(source.get_race_control(session_key)),
    )
    return session, None
