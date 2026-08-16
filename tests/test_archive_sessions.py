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


# ── Чистка архива ────────────────────────────────────────────────────────────
#
# Архив — не лента, а КАРЬЕРНАЯ ПАМЯТЬ: по нему коуч ищет эталон трассы (самый
# быстрый круг среди всех заездов) и прошлый разбор для сравнения прогресса.
# Поэтому главное здесь — не «удаляет старое», а «не удаляет то, что держит
# коуч». Наивное «оставить N свежих» молча откатило бы цель к более медленному
# кругу.

def _write(directory, name: str, *, track_id=None, ref_ms=None, lesson=None):
    doc: dict = {"track_name": f"T{track_id}", "session_type": "race"}
    if track_id is not None:
        doc["track_id"] = track_id
    if ref_ms is not None:
        doc["reference_lap"] = {"lap_time_ms": ref_ms, "corners": {}}
    if lesson is not None:
        doc["coach_lesson"] = lesson
    archive._atomic_write(directory / f"{name}.json", doc)
    return directory / f"{name}.json"


def test_nothing_is_removed_while_the_archive_is_small(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    for i in range(5):
        _write(tmp_path, f"2026-01-0{i}")

    assert archive.prune_game_sessions(keep_recent=10) == 0
    assert len(list(tmp_path.glob("*.json"))) == 5


def test_the_recent_window_is_always_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    for i in range(10):
        _write(tmp_path, f"2026-01-{i:02d}")

    removed = archive.prune_game_sessions(keep_recent=3)

    assert removed == 7
    kept = sorted(p.stem for p in tmp_path.glob("*.json"))
    assert kept == ["2026-01-07", "2026-01-08", "2026-01-09"]


def test_a_track_record_survives_however_old_it_is(tmp_path, monkeypatch):
    """Рекорд Монцы может лежать в заезде полугодовой давности. Удалить его —
    значит молча откатить цель коуча к более медленному кругу."""
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    record = _write(tmp_path, "2026-01-01", track_id=11, ref_ms=80_000)
    for i in range(2, 12):                     # десять свежих и МЕДЛЕННЕЕ
        _write(tmp_path, f"2026-01-{i:02d}", track_id=11, ref_ms=90_000)

    archive.prune_game_sessions(keep_recent=3)

    assert record.exists(), "удалён карьерный рекорд трассы"


def test_the_progress_baseline_survives(tmp_path, monkeypatch):
    """Свежайший разбор по трассе — точка отсчёта прогресса на следующем
    визите (`lesson.progress`). Без него сравнивать будет не с чем."""
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    baseline = _write(tmp_path, "2026-01-02", track_id=7,
                      lesson={"best_lap_ms": 92_000})
    _write(tmp_path, "2026-01-01", track_id=7, lesson={"best_lap_ms": 93_000})
    for i in range(3, 13):
        _write(tmp_path, f"2026-01-{i:02d}", track_id=99)

    archive.prune_game_sessions(keep_recent=3)

    assert baseline.exists(), "удалена точка отсчёта прогресса"
    assert not (tmp_path / "2026-01-01.json").exists(), "прошлый разбор не нужен"


def test_records_of_different_tracks_are_kept_independently(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    monza = _write(tmp_path, "2026-01-01", track_id=11, ref_ms=80_000)
    spa = _write(tmp_path, "2026-01-02", track_id=13, ref_ms=105_000)
    for i in range(3, 13):
        _write(tmp_path, f"2026-01-{i:02d}", track_id=99)

    archive.prune_game_sessions(keep_recent=2)

    assert monza.exists() and spa.exists()


def test_a_session_without_a_track_id_is_ordinary(tmp_path, monkeypatch):
    """Легаси-запись без track_id ничего не держит и чистится как обычная."""
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path)
    old = _write(tmp_path, "2026-01-01", ref_ms=80_000)   # track_id отсутствует
    for i in range(2, 12):
        _write(tmp_path, f"2026-01-{i:02d}", track_id=99)

    archive.prune_game_sessions(keep_recent=2)

    assert not old.exists()


def test_pruning_an_absent_directory_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_GAME_SESSIONS", tmp_path / "нет")

    assert archive.prune_game_sessions() == 0
