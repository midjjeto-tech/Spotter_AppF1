from core.session_recorder import SessionRecorder


def test_laps_accessor_returns_copy():
    r = SessionRecorder()
    r.on_lap_complete(1, 95000, 30000, 33000, 32000)
    laps = r.laps()
    assert laps == [{"lap": 1, "last_lap_ms": 95000,
                     "s1_ms": 30000, "s2_ms": 33000, "s3_ms": 32000,
                     "pit_lap": False}]
    laps.append({"x": 1})            # мутация копии не трогает внутренний список
    assert len(r.laps()) == 1


def test_on_lap_complete_records_pit_lap_flag():
    r = SessionRecorder()
    r.on_lap_complete(1, 95000, 30000, 33000, 32000, pit_lap=True)
    assert r.laps()[0]["pit_lap"] is True


from core import session_recorder as rec_mod
from core.session_recorder import SessionRecorder


def _finalize_captured(rec, monkeypatch) -> dict:
    """Вызвать finalize, перехватив то, что ушло бы в архив.

    Живой каталог game_sessions/ тесты трогать не должны: один раз тест уже
    писал в боевые данные пользователя."""
    captured = {}

    def _fake_save(data: dict):
        captured.update(data)
        return None

    monkeypatch.setattr(rec_mod.archive, "save_game_session", _fake_save)
    rec.finalize(track_id=1, track_name="Bahrain", session_type="practice",
                 final_position=5, events=[])
    return captured


def test_finalize_stores_coach_map_and_top_corners(monkeypatch):
    rec = SessionRecorder()
    rec.on_lap_complete(lap_num=1, last_lap_ms=91000,
                        s1_ms=30000, s2_ms=31000, s3_ms=30000)
    rec.set_coach_map(
        rows=[{"lap": 1, "corner_id": 3, "corner_name": "Turn 3",
               "kind": "lockup", "wheel": "fl", "phase": "braking",
               "peak": 0.5, "duration_s": 0.3, "speed_kmh": 180}],
        top_corners=[{"corner_id": 3, "corner_name": "Turn 3",
                      "count": 1, "kinds": {"lockup": 1}}],
    )

    saved = _finalize_captured(rec, monkeypatch)

    assert saved["coach_map"][0]["corner_id"] == 3
    assert saved["coach_top_corners"][0]["count"] == 1


def test_finalize_without_coach_data_keeps_empty_lists(monkeypatch):
    """Сессия без коуча обязана сохраняться и читаться как раньше."""
    rec = SessionRecorder()
    rec.on_lap_complete(lap_num=1, last_lap_ms=91000,
                        s1_ms=30000, s2_ms=31000, s3_ms=30000)

    saved = _finalize_captured(rec, monkeypatch)

    assert saved["coach_map"] == []
    assert saved["coach_top_corners"] == []


def test_reset_clears_coach_map(monkeypatch):
    rec = SessionRecorder()
    rec.set_coach_map(rows=[{"lap": 1}], top_corners=[{"corner_id": 3}])
    rec.reset()
    rec.on_lap_complete(lap_num=1, last_lap_ms=91000,
                        s1_ms=30000, s2_ms=31000, s3_ms=30000)

    saved = _finalize_captured(rec, monkeypatch)

    assert saved["coach_map"] == []


def test_finalize_stores_reference_lap(monkeypatch):
    rec = SessionRecorder()
    rec.on_lap_complete(lap_num=1, last_lap_ms=91000,
                        s1_ms=30000, s2_ms=31000, s3_ms=30000)
    rec.set_reference_lap(lap_time_ms=91000, corners={
        3: {"corner_id": 3, "brake_point_m": 100.0, "min_speed_kmh": 120.0,
            "throttle_point_m": 140.0, "duration_ms": 4000}})

    saved = _finalize_captured(rec, monkeypatch)

    assert saved["reference_lap"]["lap_time_ms"] == 91000
    assert saved["reference_lap"]["corners"]["3"]["min_speed_kmh"] == 120.0


def test_finalize_without_reference_lap_writes_nothing_misleading(monkeypatch):
    rec = SessionRecorder()
    rec.on_lap_complete(lap_num=1, last_lap_ms=91000,
                        s1_ms=30000, s2_ms=31000, s3_ms=30000)

    saved = _finalize_captured(rec, monkeypatch)

    assert saved["reference_lap"] is None


def test_reset_clears_reference_lap(monkeypatch):
    rec = SessionRecorder()
    rec.set_reference_lap(lap_time_ms=91000, corners={3: {"corner_id": 3}})
    rec.reset()
    rec.on_lap_complete(lap_num=1, last_lap_ms=91000,
                        s1_ms=30000, s2_ms=31000, s3_ms=30000)

    assert _finalize_captured(rec, monkeypatch)["reference_lap"] is None


def test_finalize_stores_the_garage_report(monkeypatch):
    rec = SessionRecorder()
    rec.on_lap_complete(lap_num=1, last_lap_ms=91000,
                        s1_ms=30000, s2_ms=31000, s3_ms=30000)
    rec.set_garage_report({"tyre_load": {"worst_wheel": "fl"},
                           "setup": {"brake_bias": 54}, "hints": []})

    saved = _finalize_captured(rec, monkeypatch)

    assert saved["garage"]["tyre_load"]["worst_wheel"] == "fl"


def test_finalize_without_garage_report_keeps_none(monkeypatch):
    """Сессия без пакета 5 (или до его прихода) обязана сохраняться как раньше."""
    rec = SessionRecorder()
    rec.on_lap_complete(lap_num=1, last_lap_ms=91000,
                        s1_ms=30000, s2_ms=31000, s3_ms=30000)

    saved = _finalize_captured(rec, monkeypatch)

    assert saved["garage"] is None
