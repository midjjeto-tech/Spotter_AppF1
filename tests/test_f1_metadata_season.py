"""tests/test_f1_metadata_season.py — F1Metadata.game_year drives the Jolpica
season used for background enrichment (reserve/unlisted drivers), independent
of the season-agnostic static roster_by_number selection tested elsewhere.
"""
from unittest.mock import patch

from core.f1_metadata import F1Metadata


class _RecordingClient:
    """Stand-in JolpicaClient that records requested paths, never touches the network."""
    def __init__(self):
        self.paths: list[str] = []

    def get_json(self, path):
        self.paths.append(path)
        return None


def _meta(season: str = "2026") -> tuple[F1Metadata, _RecordingClient]:
    client = _RecordingClient()
    with patch("threading.Thread"):   # no real background thread during construction
        m = F1Metadata(season=season, client=client)
    return m, client


def test_default_season_is_2026():
    m, _ = _meta()
    assert m.season == "2026"


def test_game_year_matching_current_season_is_noop():
    m, _ = _meta(season="2026")
    with patch("threading.Thread") as thread:
        m.game_year = 2026
    assert m.season == "2026"
    assert not thread.called


def test_game_year_2026_switches_season_up_from_2025():
    # F1 25 сначала запущен без Season Pack (season=2025 передан явно), затем
    # тот же процесс получает 2026-сессию — сезон обогащения должен догнать её.
    m, _ = _meta(season="2025")
    with patch("threading.Thread") as thread:
        m.game_year = 2026
    assert m.season == "2026"
    assert thread.called


def test_game_year_2025_switches_season_away_from_default():
    # F1 25 без Season Pack — реальная сессия 2025 года, дефолт-сезон 2026 не подходит.
    m, _ = _meta(season="2026")
    with patch("threading.Thread") as thread:
        m.game_year = 2025
    assert m.season == "2025"
    assert thread.called


def test_season_switch_resets_loaded_and_stale_maps():
    m, client = _meta(season="2026")
    m._loaded = True
    m._by_number[999] = {"name": "Ghost", "team": "X", "number": 999}
    with patch("threading.Thread"):
        m.game_year = 2025
    assert m._loaded is False
    assert 999 not in m._by_number


def test_game_year_zero_is_noop():
    m, _ = _meta(season="2026")
    with patch("threading.Thread") as thread:
        m.game_year = 0
    assert m.season == "2026"
    assert not thread.called
    assert m.game_year == 0


def test_load_queries_switched_season(monkeypatch):
    """After a season switch, the (synchronously invoked) _load() call hits the NEW
    season's Jolpica path — not the constructor default."""
    m, client = _meta(season="2026")
    with patch("threading.Thread"):
        m.game_year = 2025
    m._load()   # invoke synchronously — avoids depending on real thread timing
    assert client.paths == ["2025/driverStandings.json"]
