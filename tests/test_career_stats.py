from analytics import archive
from core.career_stats import compute_career_stats, context_line


def _write_session(tmp_path, name, *, session_type="race", final_position=None):
    archive._atomic_write(tmp_path / name, {
        "track_id": 11, "session_type": session_type,
        "final_position": final_position, "timestamp": "2026-01-01T10:00:00",
    })


def test_no_sessions_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    assert compute_career_stats() is None


def test_ignores_non_race_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    _write_session(tmp_path, "a.json", session_type="practice", final_position=1)
    assert compute_career_stats() is None


def test_ignores_races_without_final_position(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    _write_session(tmp_path, "a.json", final_position=None)
    assert compute_career_stats() is None


def test_computes_wins_podiums_avg(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    _write_session(tmp_path, "1.json", final_position=1)
    _write_session(tmp_path, "2.json", final_position=3)
    _write_session(tmp_path, "3.json", final_position=8)
    stats = compute_career_stats()
    assert stats["total_races"] == 3
    assert stats["wins"] == 1
    assert stats["podiums"] == 2
    assert stats["avg_position"] == (1 + 3 + 8) / 3


def test_podiums_include_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    _write_session(tmp_path, "1.json", final_position=1)
    stats = compute_career_stats()
    assert stats["wins"] == 1
    assert stats["podiums"] == 1


def test_context_line_formats_all_fields():
    line = context_line({"total_races": 15, "wins": 2, "podiums": 5, "avg_position": 6.333})
    assert "15" in line
    assert "2" in line and "побед" in line
    assert "5" in line and "подиумов" in line
    assert "6.3" in line
