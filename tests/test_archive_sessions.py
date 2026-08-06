from analytics import archive


def test_normalize_session_type_values():
    assert archive._normalize_session_type("R") == "race"          # legacy-код
    assert archive._normalize_session_type("Q") == "qualifying"
    assert archive._normalize_session_type("race") == "race"
    assert archive._normalize_session_type(None) == "unknown"
    assert archive._normalize_session_type("garbage") == "unknown"


def test_list_includes_normalized_session_type(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    archive._atomic_write(tmp_path / "a.json",
                          {"track_name": "Monza", "session_type": "R"})        # legacy
    archive._atomic_write(tmp_path / "b.json",
                          {"track_name": "Spa", "session_type": "practice"})   # readable
    archive._atomic_write(tmp_path / "c.json", {"track_name": "Baku"})         # missing
    out = {s["track_name"]: s["session_type"] for s in archive.list_game_sessions()}
    assert out["Monza"] == "race"          # legacy "R" нормализован
    assert out["Spa"] == "practice"
    assert out["Baku"] == "unknown"


def test_list_includes_track_id(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    archive._atomic_write(tmp_path / "a.json",
                          {"track_name": "Monza", "track_id": 11, "session_type": "race"})
    archive._atomic_write(tmp_path / "b.json",
                          {"track_name": "NoId", "session_type": "race"})   # legacy record without track_id
    out = {s["track_name"]: s["track_id"] for s in archive.list_game_sessions()}
    assert out["Monza"] == 11
    assert out["NoId"] is None


def test_get_last_race_returns_none_when_archive_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    assert archive.get_last_race() is None


def test_get_last_race_ignores_non_race_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    archive._atomic_write(tmp_path / "2026-01-01_10-00-00_000001.json",
                          {"track_name": "Monza", "session_type": "practice", "final_position": 1})
    assert archive.get_last_race() is None


def test_get_last_race_returns_most_recent_by_time_not_track(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    archive._atomic_write(tmp_path / "2026-01-01_10-00-00_000001.json",
                          {"track_name": "Monza", "session_type": "race", "final_position": 2})
    archive._atomic_write(tmp_path / "2026-01-03_10-00-00_000001.json",
                          {"track_name": "Baku", "session_type": "race", "final_position": 9})
    archive._atomic_write(tmp_path / "2026-01-02_10-00-00_000001.json",
                          {"track_name": "Spa", "session_type": "race", "final_position": 1})
    last = archive.get_last_race()
    assert last["track_name"] == "Baku"      # most recent by timestamp in filename
    assert last["final_position"] == 9


def test_get_last_race_skips_newer_non_race_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    archive._atomic_write(tmp_path / "2026-01-01_10-00-00_000001.json",
                          {"track_name": "Monza", "session_type": "race", "final_position": 3})
    archive._atomic_write(tmp_path / "2026-01-02_10-00-00_000001.json",
                          {"track_name": "Baku", "session_type": "qualifying", "final_position": 1})
    last = archive.get_last_race()
    assert last["track_name"] == "Monza"     # qualifying is newer, but not a race — skipped


def test_get_last_race_allows_missing_final_position(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    archive._atomic_write(tmp_path / "2026-01-01_10-00-00_000001.json",
                          {"track_name": "Monza", "session_type": "race", "final_position": None})
    last = archive.get_last_race()
    assert last is not None and last["final_position"] is None
