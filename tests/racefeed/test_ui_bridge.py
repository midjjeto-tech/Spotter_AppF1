from core.racefeed import ui_bridge
from core.racefeed.engine import RaceFeedEngine


class _FakeAI:
    available = False

    def generate_with_system(self, system, user):
        return None


def test_get_posts_returns_disabled_when_engine_is_none():
    result = ui_bridge.get_posts(None)
    assert result == {"enabled": False, "posts": []}


def test_get_posts_returns_empty_posts_before_reset(tmp_path):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=lambda: {},
                         data_dir=str(tmp_path))
    result = ui_bridge.get_posts(rf)
    assert result == {"enabled": True, "posts": []}


def test_get_posts_returns_posts_after_publish(tmp_path):
    from core.racefeed.models import Post

    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=lambda: {},
                         data_dir=str(tmp_path))
    rf.reset()

    from core.racefeed import storage
    post = Post(
        id="p1", session_id="s", story_id="st1", reporter_id="race_control",
        category="incident", text="Norris receives a penalty.",
        created_at=1.0, published_at=2.0, driver="Norris", is_player_story=False,
    )
    storage.save_post(rf.current_db_path(), post)

    result = ui_bridge.get_posts(rf)
    assert result["enabled"] is True
    assert len(result["posts"]) == 1
    assert result["posts"][0]["text"] == "Norris receives a penalty."


def test_get_posts_includes_the_current_prediction(tmp_path, monkeypatch):
    from core.racefeed import predictions, storage
    import core.track_return as track_return

    monkeypatch.setattr(predictions.archive, "list_season_results", lambda limit=5: [])
    monkeypatch.setattr(predictions.archive, "list_game_sessions", lambda: [])
    monkeypatch.setattr(track_return, "build", lambda *args: None)
    rf = RaceFeedEngine(
        ai_provider=_FakeAI(),
        state_provider=lambda: {
            "session_type": "race", "track_id": 13, "track_name": "Спа",
            "player_driver": "Артём", "teammate_driver": "Леклер",
            "player_position": 4, "teammate_position": 7,
        },
        data_dir=str(tmp_path),
    )
    rf.reset(session_type="race")

    result = ui_bridge.get_posts(rf)

    assert result["prediction"]["status"] == "open"
    assert result["prediction"]["model_forecast"]["participants"]["player"] == "Артём"
    assert storage.get_prediction(rf.current_db_path()) is not None


def test_get_posts_returns_empty_on_storage_error(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=lambda: {},
                         data_dir=str(tmp_path))
    rf.reset()
    # Point at a path with no schema, forcing storage.get_posts to raise.
    bad_path = str(tmp_path / "no_such_table.sqlite3")
    import sqlite3
    sqlite3.connect(bad_path).close()  # creates an empty file, no tables
    monkeypatch.setattr(rf, "current_db_path", lambda: bad_path)

    result = ui_bridge.get_posts(rf)
    assert result == {"enabled": True, "posts": []}


def test_get_stats_returns_disabled_when_engine_is_none():
    assert ui_bridge.get_stats(None) == {"enabled": False, "stats": {}}


def test_get_stats_reports_session_and_counters(tmp_path):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=lambda: {},
                         data_dir=str(tmp_path))

    before = ui_bridge.get_stats(rf)
    assert before["enabled"] is True
    assert before["session_active"] is False  # no reset() yet → no db file
    assert before["stats"]["events_ingested"] == 0

    rf.reset()
    after = ui_bridge.get_stats(rf)
    assert after["session_active"] is True
    assert set(after["stats"]) >= {"posts_published", "comments_skipped"}


def test_get_standings_disabled_when_engine_is_none():
    assert ui_bridge.get_standings(None) == {
        "enabled": False, "standings": [], "races_counted": 0, "profile": None}


def test_get_standings_returns_table(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=lambda: {},
                         data_dir=str(tmp_path))
    import core.season as season
    monkeypatch.setattr(season, "compute_standings", lambda window=22: {
        "standings": [{"driver": "You", "points": 40, "team": "Ferrari",
                       "color": "#E8002D", "position": 1, "is_player": True}],
        "races_counted": 3,
    })
    out = ui_bridge.get_standings(rf)
    assert out["enabled"] is True
    assert out["races_counted"] == 3
    assert out["standings"][0]["driver"] == "You"


def test_get_standings_empty_before_any_race(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=lambda: {},
                         data_dir=str(tmp_path))
    import core.season as season
    monkeypatch.setattr(season, "compute_standings", lambda window=22: None)
    assert ui_bridge.get_standings(rf) == {
        "enabled": True, "standings": [], "races_counted": 0, "profile": None}


def test_get_standings_includes_profile(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=lambda: {},
                         data_dir=str(tmp_path))
    import core.season as season
    import core.career_stats as career_stats
    monkeypatch.setattr(season, "compute_standings", lambda window=22: {
        "standings": [{"driver": "You", "points": 40, "team": "Ferrari",
                       "color": "#E8002D", "position": 2, "is_player": True}],
        "races_counted": 3})
    monkeypatch.setattr(season, "season_summary", lambda **k: {
        "player_position": 2, "player_points": 40})
    monkeypatch.setattr(season, "best_result", lambda window=22: 1)
    monkeypatch.setattr(career_stats, "compute_career_stats", lambda: {
        "total_races": 12, "wins": 3, "podiums": 7, "avg_position": 4.2})
    out = ui_bridge.get_standings(rf)
    assert out["profile"]["championship_position"] == 2
    assert out["profile"]["championship_points"] == 40
    assert out["profile"]["best_result"] == 1
    assert out["profile"]["career"]["wins"] == 3


def test_get_standings_profile_null_when_no_season(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=lambda: {},
                         data_dir=str(tmp_path))
    import core.season as season
    monkeypatch.setattr(season, "compute_standings", lambda window=22: None)
    assert ui_bridge.get_standings(rf)["profile"] is None


def test_get_standings_marks_the_rival_row(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=lambda: {},
                         data_dir=str(tmp_path))
    import core.season as season
    monkeypatch.setattr(season, "compute_standings", lambda window=22: {
        "standings": [
            {"driver": "Max", "points": 50, "position": 1, "is_player": False},
            {"driver": "You", "points": 40, "position": 2, "is_player": True},
        ],
        "races_counted": 2,
    })
    rows = {r["driver"]: r for r in ui_bridge.get_standings(rf)["standings"]}
    assert rows["Max"].get("is_rival") is True
    assert rows["You"].get("is_rival") is not True


def test_get_posts_forwards_limit(tmp_path):
    from core.racefeed.models import Post

    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=lambda: {},
                         data_dir=str(tmp_path))
    rf.reset()

    from core.racefeed import storage
    for i in range(3):
        storage.save_post(rf.current_db_path(), Post(
            id=f"p{i}", session_id="s", story_id="st", reporter_id="race_control",
            category="incident", text=str(i), created_at=float(i),
            published_at=float(i), driver=None, is_player_story=False,
        ))

    result = ui_bridge.get_posts(rf, limit=1)
    assert len(result["posts"]) == 1


# --- архив прошлых гонок ----------------------------------------------------

def _archived_session(directory, name, *, posts=1, track_name="", session_type="race",
                      started_at=0.0):
    from core.racefeed import storage
    from core.racefeed.models import Post
    path = str(directory / name)
    storage.init_db(path)
    if track_name or session_type or started_at:
        storage.save_session_meta(path, name.replace(".sqlite3", ""),
                                  track_name=track_name, session_type=session_type,
                                  started_at=started_at)
    for index in range(posts):
        storage.save_post(path, Post(
            id=f"{name}-{index}", session_id=name, story_id="s",
            reporter_id="race_control", category="penalty", text=f"пост {index}",
            created_at=1.0, published_at=float(index), driver="Норрис",
            is_player_story=False,
        ))
    return path


def _engine(tmp_path):
    return RaceFeedEngine(ai_provider=_FakeAI(),
                          state_provider=lambda: {"session_type": "race"},
                          data_dir=str(tmp_path))


def test_archive_is_disabled_when_the_feed_is_off():
    assert ui_bridge.get_archive(None) == {"enabled": False, "sessions": []}


def test_archive_returns_previous_sessions_newest_first(tmp_path):
    ui_bridge._ARCHIVE_CACHE.clear()
    _archived_session(tmp_path, "20260701_120000.sqlite3", track_name="Монца")
    _archived_session(tmp_path, "20260705_120000.sqlite3", track_name="Спа")

    result = ui_bridge.get_archive(_engine(tmp_path))

    assert result["enabled"] is True
    assert [s["track_name"] for s in result["sessions"]] == ["Спа", "Монца"]
    assert result["sessions"][0]["post_count"] == 1
    assert result["sessions"][0]["posts"][0]["text"] == "пост 0"


def test_archive_excludes_the_live_session(tmp_path):
    """Живую гонку показывает get_posts — в архиве она была бы вторым экземпляром."""
    ui_bridge._ARCHIVE_CACHE.clear()
    _archived_session(tmp_path, "20260701_120000.sqlite3", track_name="Монца")
    rf = _engine(tmp_path)
    rf.reset()

    sessions = ui_bridge.get_archive(rf)["sessions"]

    assert [s["session_id"] for s in sessions] == ["20260701_120000"]


def test_archive_skips_sessions_without_posts(tmp_path):
    ui_bridge._ARCHIVE_CACHE.clear()
    _archived_session(tmp_path, "20260701_120000.sqlite3", posts=0)
    _archived_session(tmp_path, "20260702_120000.sqlite3", posts=2)

    sessions = ui_bridge.get_archive(_engine(tmp_path))["sessions"]

    assert [s["session_id"] for s in sessions] == ["20260702_120000"]


def test_archive_labels_old_files_by_their_timestamp_name(tmp_path):
    """Файлы, записанные до появления session_meta, всё равно подписываются."""
    ui_bridge._ARCHIVE_CACHE.clear()
    _archived_session(tmp_path, "20260701_143000.sqlite3", session_type="")

    session = ui_bridge.get_archive(_engine(tmp_path))["sessions"][0]

    assert session["track_name"] == ""
    from datetime import datetime
    assert (datetime.fromtimestamp(session["started_at"]).strftime("%Y%m%d_%H%M%S")
            == "20260701_143000")


def test_archive_reads_each_file_once_until_it_changes(tmp_path, monkeypatch):
    """Лента показывает все гонки сразу, поэтому без кэша каждый опрос читал бы
    до 20 SQLite-файлов."""
    from core.racefeed import storage
    ui_bridge._ARCHIVE_CACHE.clear()
    path = _archived_session(tmp_path, "20260701_120000.sqlite3", track_name="Монца")
    rf = _engine(tmp_path)

    reads = {"count": 0}
    real_get_posts = storage.get_posts

    def counting_get_posts(*args, **kwargs):
        reads["count"] += 1
        return real_get_posts(*args, **kwargs)

    monkeypatch.setattr(ui_bridge.storage, "get_posts", counting_get_posts)

    ui_bridge.get_archive(rf)
    ui_bridge.get_archive(rf)
    ui_bridge.get_archive(rf)
    assert reads["count"] == 1

    # a changed file invalidates its entry
    import os
    stat = os.stat(path)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    ui_bridge.get_archive(rf)
    assert reads["count"] == 2


def test_archive_cache_forgets_files_the_gc_removed(tmp_path):
    ui_bridge._ARCHIVE_CACHE.clear()
    path = _archived_session(tmp_path, "20260701_120000.sqlite3")
    rf = _engine(tmp_path)
    ui_bridge.get_archive(rf)
    assert len(ui_bridge._ARCHIVE_CACHE) == 1

    from pathlib import Path
    Path(path).unlink()
    ui_bridge.get_archive(rf)

    assert ui_bridge._ARCHIVE_CACHE == {}


def test_archive_caps_the_number_of_sessions(tmp_path):
    ui_bridge._ARCHIVE_CACHE.clear()
    for day in range(1, 8):
        _archived_session(tmp_path, f"202607{day:02d}_120000.sqlite3")

    sessions = ui_bridge.get_archive(_engine(tmp_path), max_sessions=3)["sessions"]

    assert len(sessions) == 3
    assert sessions[0]["session_id"] == "20260707_120000"


def test_archive_survives_an_unreadable_file(tmp_path):
    ui_bridge._ARCHIVE_CACHE.clear()
    (tmp_path / "20260709_120000.sqlite3").write_text("не база данных")
    _archived_session(tmp_path, "20260701_120000.sqlite3", track_name="Монца")

    sessions = ui_bridge.get_archive(_engine(tmp_path))["sessions"]

    assert [s["track_name"] for s in sessions] == ["Монца"]
