from core import track_return


def test_track_return_uses_latest_visit_and_all_time_pb(monkeypatch):
    sessions = [
        {"path": "new", "track_id": 13, "track_name": "Спа", "session_type": "race"},
        {"path": "old", "track_id": 13, "track_name": "Спа", "session_type": "race"},
        {"path": "q", "track_id": 13, "track_name": "Спа", "session_type": "qualifying"},
    ]
    data = {
        "new": {"timestamp": "2026-07-01T12:00:00", "final_position": 12,
                "player_laps": [{"last_lap_ms": 91_000}]},
        "old": {"timestamp": "2025-07-01T12:00:00", "final_position": 5,
                "player_laps": [{"last_lap_ms": 89_500}]},
    }
    monkeypatch.setattr(track_return.archive, "list_game_sessions", lambda: sessions)
    monkeypatch.setattr(track_return.archive, "load_game_session", data.get)

    result = track_return.build(13, "Спа")

    assert result["finish_position"] == 12
    assert result["last_visit_best_lap_ms"] == 91_000
    assert result["personal_best_lap_ms"] == 89_500
    assert result["goal"]["kind"] == "points"
    assert result["main_setback"]["code"] == "outside_points"


def test_track_return_is_absent_before_first_visit(monkeypatch):
    monkeypatch.setattr(track_return.archive, "list_game_sessions", lambda: [])
    assert track_return.build(13, "Спа") is None
