# tests/test_analytics_loader.py
"""analytics/loader.py::load_f1_session — обёртка над fastf1.

Баг: fastf1 сам ловит SessionNotAvailableError на каждом под-запросе внутри
session.load() (session_info/driver_info/laps/weather/race_control...) и не
пробрасывает исключение наружу — load() "успешно" завершается, даже когда
реально не получено ни результатов, ни кругов. Раньше это считалось успехом
и api_load_f1 (web_server.py) отдавал фронтенду пустой f1_data вместо явной
ошибки — см. dist/spotter.log реальной сессии: "Finished loading data for 20
drivers" в конце, хотя все под-запросы выше провалились.
"""
import pandas as pd
import pytest

from analytics import loader


class _FakeSession:
    def __init__(self, results=None, laps=None):
        self.results = results
        self.laps = laps

    def load(self, **kwargs):
        pass  # fastf1 проглатывает SessionNotAvailableError сам — не бросает


class _FakeFF1:
    def __init__(self, session):
        self._session = session

    def get_session(self, year, gp_name, session_type):
        return self._session


def _patch_legacy_fastf1(monkeypatch, session):
    """FastF1 is intentionally only used for seasons before OpenF1 coverage."""
    monkeypatch.setattr(loader, "_ensure_fastf1", lambda: _FakeFF1(session))


def test_empty_results_and_laps_returns_no_data_error(monkeypatch):
    session = _FakeSession(results=pd.DataFrame(), laps=pd.DataFrame())
    _patch_legacy_fastf1(monkeypatch, session)

    result, err = loader.load_f1_session(track_id=2, year=2022, session_type="R")

    assert result is None
    assert err == "no_data_for_session"


def test_none_results_and_laps_returns_no_data_error(monkeypatch):
    session = _FakeSession(results=None, laps=None)
    _patch_legacy_fastf1(monkeypatch, session)

    result, err = loader.load_f1_session(track_id=2, year=2022, session_type="R")

    assert result is None
    assert err == "no_data_for_session"


def test_results_present_returns_session_without_error(monkeypatch):
    session = _FakeSession(results=pd.DataFrame({"Position": [1]}), laps=pd.DataFrame())
    _patch_legacy_fastf1(monkeypatch, session)

    result, err = loader.load_f1_session(track_id=2, year=2022, session_type="R")

    assert result is session
    assert err is None


def test_laps_present_returns_session_without_error(monkeypatch):
    session = _FakeSession(results=pd.DataFrame(), laps=pd.DataFrame({"LapTime": [1]}))
    _patch_legacy_fastf1(monkeypatch, session)

    result, err = loader.load_f1_session(track_id=2, year=2022, session_type="R")

    assert result is session
    assert err is None


def test_unknown_track_id_still_returns_no_fastf1_data():
    result, err = loader.load_f1_session(track_id=-1, year=2025, session_type="R")
    assert result is None
    assert err == "no_fastf1_data"


def test_modern_season_uses_openf1_without_touching_fastf1(monkeypatch):
    session = _FakeSession(results=pd.DataFrame({"Position": [1]}), laps=pd.DataFrame())
    calls = []
    monkeypatch.setattr(
        loader,
        "load_openf1_session",
        lambda track_id, year, session_type: calls.append((track_id, year, session_type))
        or (session, None),
    )
    monkeypatch.setattr(
        loader,
        "_ensure_fastf1",
        lambda: pytest.fail("FastF1 must not be called for OpenF1-covered seasons"),
    )

    result, err = loader.load_f1_session(track_id=30, year=2025, session_type="R")

    assert result is session
    assert err is None
    assert calls == [(30, 2025, "R")]


def test_modern_no_data_does_not_fall_through_to_fastf1_warning_storm(monkeypatch):
    monkeypatch.setattr(
        loader,
        "load_openf1_session",
        lambda track_id, year, session_type: (None, "no_data_for_session"),
    )
    monkeypatch.setattr(
        loader,
        "_ensure_fastf1",
        lambda: pytest.fail("A known OpenF1 miss must not trigger noisy FastF1 requests"),
    )

    result, err = loader.load_f1_session(track_id=30, year=2025, session_type="R")

    assert result is None
    assert err == "no_data_for_session"
