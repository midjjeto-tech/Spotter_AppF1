from analytics import archive
from core.career_memory import CareerMemory


def _write_session(tmp_path, name, *, track_id, session_type="race",
                   final_position=None, timestamp=None, player_laps=None):
    archive._atomic_write(tmp_path / name, {
        "track_id": track_id, "session_type": session_type,
        "final_position": final_position, "timestamp": timestamp,
        "player_laps": player_laps or [],
    })


def test_load_no_history_returns_false(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    cm = CareerMemory()
    assert cm.load(11) is False
    assert not cm.ready


def test_load_ignores_other_tracks(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    _write_session(tmp_path, "a.json", track_id=99, final_position=1,
                   timestamp="2026-01-01T10:00:00",
                   player_laps=[{"lap": 1, "last_lap_ms": 70000}])
    cm = CareerMemory()
    assert cm.load(11) is False


def test_load_ignores_non_race_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    _write_session(tmp_path, "a.json", track_id=11, session_type="practice",
                   final_position=1, timestamp="2026-01-01T10:00:00",
                   player_laps=[{"lap": 1, "last_lap_ms": 70000}])
    cm = CareerMemory()
    assert cm.load(11) is False


def test_load_best_ever_is_global_minimum_across_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    _write_session(tmp_path, "1_old.json", track_id=11, final_position=5,
                   timestamp="2026-01-01T10:00:00",
                   player_laps=[{"lap": 1, "last_lap_ms": 81000,
                                "s1_ms": 27000, "s2_ms": 28000, "s3_ms": 26000}])
    _write_session(tmp_path, "2_new.json", track_id=11, final_position=3,
                   timestamp="2026-02-01T10:00:00",
                   player_laps=[{"lap": 1, "last_lap_ms": 80000,
                                "s1_ms": 26500, "s2_ms": 27500, "s3_ms": 26000}])
    cm = CareerMemory()
    assert cm.load(11) is True
    assert cm.reference["best_ever"]["lap_ms"] == 80000
    assert cm.reference["best_ever"]["sector_ms"] == {1: 26500, 2: 27500, 3: 26000}


def test_load_last_visit_is_most_recent_not_fastest(tmp_path, monkeypatch):
    """last_visit — the MOST RECENT session, even if it was SLOWER than an older one."""
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    _write_session(tmp_path, "1_old_fast.json", track_id=11, final_position=2,
                   timestamp="2026-01-01T10:00:00",
                   player_laps=[{"lap": 1, "last_lap_ms": 79000}])
    _write_session(tmp_path, "2_new_slow.json", track_id=11, final_position=7,
                   timestamp="2026-02-01T10:00:00",
                   player_laps=[{"lap": 1, "last_lap_ms": 85000}])
    cm = CareerMemory()
    cm.load(11)
    assert cm.reference["last_visit"]["best_lap_ms"] == 85000
    assert cm.reference["last_visit"]["final_position"] == 7
    assert cm.reference["best_ever"]["lap_ms"] == 79000


def test_load_best_ever_sector_ms_none_when_fastest_lap_missing_sectors(tmp_path, monkeypatch):
    """The fastest HISTORICAL lap may lack valid s1/s2/s3 (old session format /
    telemetry cut out) — sector_ms degrades to None, not a partial dict."""
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    _write_session(tmp_path, "a.json", track_id=11, final_position=1,
                   timestamp="2026-01-01T10:00:00",
                   player_laps=[{"lap": 1, "last_lap_ms": 80000}])   # no s1/s2/s3
    cm = CareerMemory()
    assert cm.load(11) is True
    assert cm.reference["best_ever"]["lap_ms"] == 80000
    assert cm.reference["best_ever"]["sector_ms"] is None


def test_load_skips_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    (tmp_path / "corrupt.json").write_text("NOT JSON", encoding="utf-8")
    _write_session(tmp_path, "good.json", track_id=11, final_position=1,
                   timestamp="2026-01-01T10:00:00",
                   player_laps=[{"lap": 1, "last_lap_ms": 80000}])
    cm = CareerMemory()
    assert cm.load(11) is True
    assert cm.reference["best_ever"]["lap_ms"] == 80000


def test_compare_always_has_sectors_key():
    cm = CareerMemory()
    cm.reference = {"best_ever": {"lap_ms": 80000, "sector_ms": None, "date": "2026-01-01"},
                    "last_visit": {"best_lap_ms": 80000, "final_position": 1, "date": "2026-01-01"}}
    cmp = cm.compare([{"lap": 1, "last_lap_ms": 81000}])
    assert "sectors" in cmp and cmp["sectors"] is None


def test_compare_none_when_not_ready():
    cm = CareerMemory()
    assert cm.compare([{"last_lap_ms": 1000}]) is None


def test_compare_none_when_ready_but_no_valid_laps():
    cm = CareerMemory()
    cm.reference = {"best_ever": {"lap_ms": 80000, "sector_ms": None, "date": "2026-01-01"},
                    "last_visit": {"best_lap_ms": 80000, "final_position": 1, "date": "2026-01-01"}}
    assert cm.compare([]) is None
    assert cm.compare([{"last_lap_ms": 0}]) is None


def test_compare_computes_gap_and_sectors():
    cm = CareerMemory()
    cm.reference = {"best_ever": {"lap_ms": 80000, "sector_ms": {1: 26500, 2: 27500, 3: 26000},
                                  "date": "2026-01-01"},
                    "last_visit": {"best_lap_ms": 80000, "final_position": 1, "date": "2026-01-01"}}
    cmp = cm.compare([{"lap": 1, "last_lap_ms": 79500,
                       "s1_ms": 26400, "s2_ms": 27400, "s3_ms": 25700}])
    assert cmp["gap_ms"] == -500
    assert cmp["sectors"] == {
        1: {"player_ms": 26400, "gap_ms": -100},
        2: {"player_ms": 27400, "gap_ms": -100},
        3: {"player_ms": 25700, "gap_ms": -300},
    }


def test_compare_sectors_none_when_current_best_lap_missing_sectors():
    """Reference HAS sectors, but the current best lap doesn't (same all-or-nothing
    degradation as load()): "sectors" is still None, not a KeyError/partial dict."""
    cm = CareerMemory()
    cm.reference = {"best_ever": {"lap_ms": 80000, "sector_ms": {1: 26500, 2: 27500, 3: 26000},
                                  "date": "2026-01-01"},
                    "last_visit": {"best_lap_ms": 80000, "final_position": 1, "date": "2026-01-01"}}
    cmp = cm.compare([{"lap": 1, "last_lap_ms": 79500}])   # no s1/s2/s3
    assert cmp["gap_ms"] == -500
    assert cmp["sectors"] is None


def test_context_line_mentions_gap():
    cm = CareerMemory()
    line_ahead = cm.context_line({"gap_ms": -500, "player_best_ms": 79500,
                                  "best_ever_ms": 80000, "best_ever_date": "2026-01-01",
                                  "sectors": None})
    line_behind = cm.context_line({"gap_ms": 500, "player_best_ms": 80500,
                                   "best_ever_ms": 80000, "best_ever_date": "2026-01-01",
                                   "sectors": None})
    assert "0.5" in line_ahead and "быстрее" in line_ahead.lower()
    assert "0.5" in line_behind and "отставание" in line_behind.lower()


def test_story_facts_signs():
    """laptime_delta_ms<0 = faster than last visit; position_delta>0 = finished higher."""
    cm = CareerMemory()
    cm.reference = {"best_ever": {"lap_ms": 80000, "sector_ms": None, "date": "2026-01-01"},
                    "last_visit": {"best_lap_ms": 82000, "final_position": 8,
                                   "date": "2026-01-01T10:00:00"}}
    facts = cm.story_facts(final_position=5, player_laps=[{"last_lap_ms": 81000}])
    vlv = facts["vs_last_visit"]
    assert vlv["laptime_delta_ms"] == -1000
    assert vlv["position_delta"] == 3
    assert vlv["last_visit_date"] == "2026-01-01T10:00:00"


def test_story_facts_none_without_last_visit():
    cm = CareerMemory()
    assert cm.story_facts(final_position=5, player_laps=[])["vs_last_visit"] is None


def test_story_facts_none_when_reference_set_but_last_visit_incomplete():
    """Defensive path: best_ever present, last_visit incomplete (shouldn't happen in
    practice — both are computed from the same file set — but story_facts() must
    silently return None, not crash)."""
    cm = CareerMemory()
    cm.reference = {"best_ever": {"lap_ms": 80000, "sector_ms": None, "date": "2026-01-01"},
                    "last_visit": {"best_lap_ms": None, "final_position": None, "date": None}}
    facts = cm.story_facts(final_position=5, player_laps=[{"last_lap_ms": 81000}])
    assert facts["vs_last_visit"] is None


def test_pb_line_beat_history():
    cm = CareerMemory()
    line = cm.pb_line({"gap_ms": -500, "player_best_ms": 79500})
    assert "рекорд" in line.lower() and "быстрее" in line.lower()


def test_pb_line_session_best_still_behind_history():
    cm = CareerMemory()
    line = cm.pb_line({"gap_ms": 500, "player_best_ms": 80500})
    assert "лучший круг" in line.lower()


def test_sector_pb_line_beat_history():
    cm = CareerMemory()
    line = cm.sector_pb_line(2, {"gap_ms": -100, "player_ms": 27400})
    assert "Сектор 2" in line and "рекорд" in line.lower()


def test_sector_pb_line_session_best_still_behind():
    cm = CareerMemory()
    line = cm.sector_pb_line(1, {"gap_ms": 100, "player_ms": 26600})
    assert "Сектор 1" in line
