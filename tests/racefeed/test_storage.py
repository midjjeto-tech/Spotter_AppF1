import sqlite3
from pathlib import Path

from core.racefeed import storage
from core.racefeed.models import Comment, Post, Story


def _db(tmp_path):
    path = str(tmp_path / "racefeed_test.sqlite3")
    storage.init_db(path)
    return path


def test_init_db_creates_tables(tmp_path):
    path = _db(tmp_path)
    assert storage.get_posts(path) == []
    assert storage.get_story(path, "nope") is None


def test_upsert_story_then_get(tmp_path):
    path = _db(tmp_path)
    story = Story(id="pit|Norris", story_key=("pit", "Norris"), category="pit",
                   session_type="race", stage=1, facts={"lap": 12},
                   history=[{"lap": 5}], created_at=1.0, last_update=2.0,
                   last_publish=2.5, status="published", post_ids=["p1"])
    storage.upsert_story(path, story)

    loaded = storage.get_story(path, "pit|Norris")
    assert loaded.id == "pit|Norris"
    assert loaded.story_key == ("pit", "Norris")
    assert loaded.stage == 1
    assert loaded.facts == {"lap": 12}
    assert loaded.history == [{"lap": 5}]
    assert loaded.status == "published"


def test_upsert_story_overwrites_on_same_id(tmp_path):
    path = _db(tmp_path)
    story = Story(id="s1", story_key=("x",), category="x", session_type="race")
    storage.upsert_story(path, story)
    story.stage = 5
    story.facts = {"a": 1}
    storage.upsert_story(path, story)

    loaded = storage.get_story(path, "s1")
    assert loaded.stage == 5
    assert loaded.facts == {"a": 1}


def test_save_post_and_get_posts_ordered_newest_first(tmp_path):
    path = _db(tmp_path)
    p1 = Post(id="p1", session_id="s", story_id="st1", reporter_id="race_control",
               category="incident", text="first", created_at=1.0, published_at=10.0,
               driver="Norris", is_player_story=False)
    p2 = Post(id="p2", session_id="s", story_id="st1", reporter_id="race_control",
               category="incident", text="second", created_at=2.0, published_at=20.0,
               driver="Norris", is_player_story=False)
    storage.save_post(path, p1)
    storage.save_post(path, p2)

    rows = storage.get_posts(path)
    assert [r["id"] for r in rows] == ["p2", "p1"]
    assert rows[0]["text"] == "second"


def test_get_posts_respects_limit(tmp_path):
    path = _db(tmp_path)
    for i in range(5):
        storage.save_post(path, Post(
            id=f"p{i}", session_id="s", story_id="st", reporter_id="race_control",
            category="incident", text=str(i), created_at=float(i),
            published_at=float(i), driver=None, is_player_story=False,
        ))
    assert len(storage.get_posts(path, limit=2)) == 2


def test_post_comments_are_persisted_and_hydrated(tmp_path):
    path = _db(tmp_path)
    post = Post(
        id="p1", session_id="s", story_id="st", reporter_id="race_control",
        category="incident", text="news", created_at=1.0, published_at=2.0,
        driver="Norris", is_player_story=True,
        comments=[Comment(
            id="c1", post_id="p1", parent_id=None, author_id="apex_nerd",
            author_name="ApexData", author_badge="аналитик", avatar="AD",
            text="Темп подтверждается.", created_at=3.0, likes=12,
        )],
    )
    storage.save_post(path, post)

    loaded = storage.get_posts(path)
    assert loaded[0]["comments"] == [{
        "id": "c1", "post_id": "p1", "parent_id": None,
        "author_id": "apex_nerd", "author_name": "ApexData",
        "author_badge": "аналитик", "avatar": "AD",
        "text": "Темп подтверждается.", "created_at": 3.0, "likes": 12,
    }]


def test_post_image_round_trips(tmp_path):
    from core.racefeed import storage
    from core.racefeed.models import Post
    db = str(tmp_path / "s.sqlite3")
    storage.init_db(db)
    storage.save_post(db, Post(
        id="p1", session_id="s", story_id="st", reporter_id="race_control",
        category="incident", text="x", created_at=1.0, published_at=2.0,
        driver="Norris", is_player_story=True, image="shot.png"))
    rows = storage.get_posts(db)
    assert rows[0]["image"] == "shot.png"


def test_post_metadata_round_trips_as_json_object(tmp_path):
    db = _db(tmp_path)
    metadata = {
        "poll": [{"driver": "Alonso", "vote_pct": 47, "overtakes": 6}],
    }
    storage.save_post(db, Post(
        id="p1", session_id="s", story_id="dotd", reporter_id="paddock",
        category="driver_of_the_day", text="Итоги голосования",
        created_at=1.0, published_at=2.0, driver="Alonso",
        is_player_story=False, metadata=metadata,
    ))

    assert storage.get_posts(db)[0]["metadata"] == metadata


# --- чистка старых сессионных файлов ----------------------------------------

def _session_with_posts(directory, name, count=1):
    path = str(directory / name)
    storage.init_db(path)
    for index in range(count):
        storage.save_post(path, Post(
            id=f"{name}-{index}", session_id=name, story_id="s",
            reporter_id="race_control", category="penalty", text="text",
            created_at=1.0, published_at=2.0, driver="Норрис",
            is_player_story=False,
        ))
    return path


def _empty_session(directory, name):
    path = str(directory / name)
    storage.init_db(path)
    return path


def test_prune_removes_empty_sessions_and_keeps_the_ones_with_posts(tmp_path):
    empty = [_empty_session(tmp_path, f"2026010{i}_000000.sqlite3") for i in range(1, 4)]
    kept = _session_with_posts(tmp_path, "20260105_000000.sqlite3")

    removed_empty, removed_old = storage.prune_sessions(str(tmp_path))

    assert (removed_empty, removed_old) == (3, 0)
    assert not any(Path(path).exists() for path in empty)
    assert Path(kept).exists()


def test_prune_keeps_only_the_newest_non_empty_sessions(tmp_path):
    paths = [_session_with_posts(tmp_path, f"202601{day:02d}_000000.sqlite3")
             for day in range(1, 11)]

    removed_empty, removed_old = storage.prune_sessions(str(tmp_path),
                                                        keep_with_posts=4)

    assert (removed_empty, removed_old) == (0, 6)
    # file names are timestamps → the four newest survive
    assert [Path(p).exists() for p in paths] == [False] * 6 + [True] * 4


def test_prune_never_touches_the_open_session(tmp_path):
    current = _empty_session(tmp_path, "20260110_000000.sqlite3")

    removed_empty, _ = storage.prune_sessions(str(tmp_path), protect=current)

    assert removed_empty == 0
    assert Path(current).exists()


def test_prune_removes_wal_sidecars(tmp_path):
    path = _empty_session(tmp_path, "20260101_000000.sqlite3")
    Path(f"{path}-wal").write_bytes(b"")
    Path(f"{path}-shm").write_bytes(b"")

    storage.prune_sessions(str(tmp_path))

    assert not Path(f"{path}-wal").exists()
    assert not Path(f"{path}-shm").exists()


def test_prune_skips_files_that_are_not_racefeed_databases(tmp_path):
    junk = tmp_path / "not-a-db.sqlite3"
    junk.write_text("definitely not sqlite")

    removed_empty, removed_old = storage.prune_sessions(str(tmp_path))

    assert (removed_empty, removed_old) == (0, 0)
    assert junk.exists()


def test_prune_on_a_missing_directory_is_a_no_op(tmp_path):
    assert storage.prune_sessions(str(tmp_path / "nope")) == (0, 0)


# --- метаданные сессии ------------------------------------------------------

def test_session_meta_round_trip(tmp_path):
    path = _db(tmp_path)
    storage.save_session_meta(path, "20260726_202326", track_name="Монца",
                              session_type="race", started_at=1234.0)

    meta = storage.get_session_meta(path)

    assert meta["session_id"] == "20260726_202326"
    assert meta["track_name"] == "Монца"
    assert meta["session_type"] == "race"
    assert meta["started_at"] == 1234.0


def test_session_meta_is_none_for_files_written_before_the_table_existed(tmp_path):
    assert storage.get_session_meta(_db(tmp_path)) is None


def test_later_write_fills_the_track_without_losing_the_start_time(tmp_path):
    """SSTA часто приходит раньше, чем резолвится трасса — тик дописывает её."""
    path = _db(tmp_path)
    storage.save_session_meta(path, "s1", session_type="race", started_at=99.0)
    storage.save_session_meta(path, "s1", track_name="Спа", session_type="race")

    meta = storage.get_session_meta(path)

    assert meta["track_name"] == "Спа"
    assert meta["started_at"] == 99.0


def test_empty_value_never_overwrites_a_known_one(tmp_path):
    path = _db(tmp_path)
    storage.save_session_meta(path, "s1", track_name="Монца", session_type="race")
    storage.save_session_meta(path, "s1")

    meta = storage.get_session_meta(path)

    assert (meta["track_name"], meta["session_type"]) == ("Монца", "race")


def test_prediction_ticket_locks_and_resolves_in_the_session_db(tmp_path):
    path = _db(tmp_path)
    model = {"finish": {"choice": "points"}}
    storage.create_prediction(
        path, "s1", track_name="Спа", model_forecast=model,
        track_return={"finish_position": 8}, created_at=10.0,
    )
    assert storage.save_prediction_ticket(path, "s1", {
        "finish": "points", "teammate": "player", "risk": "rain",
    }) is True
    assert storage.lock_prediction(path, "s1", locked_at=20.0) is True
    assert storage.save_prediction_ticket(path, "s1", {
        "finish": "podium", "teammate": "player", "risk": "rain",
    }) is False
    assert storage.resolve_prediction(
        path, "s1", {"reader_score": 2, "model_score": 1}, resolved_at=30.0
    ) is True

    row = storage.get_prediction(path)
    assert row["status"] == "resolved"
    assert row["model_forecast"] == model
    assert row["reader_ticket"]["finish"] == "points"
    assert row["result"]["reader_score"] == 2


def test_prune_keeps_a_session_with_a_prediction_but_no_posts(tmp_path):
    path = _empty_session(tmp_path, "20260101_000000.sqlite3")
    storage.create_prediction(
        path, "s1", track_name="Спа", model_forecast={}, track_return=None,
    )

    assert storage.prune_sessions(str(tmp_path)) == (0, 0)
    assert Path(path).exists()


def test_meta_table_is_created_in_databases_that_predate_it(tmp_path):
    """init_db переоткрывает старый файл — CREATE TABLE IF NOT EXISTS в _SCHEMA
    и есть миграция, отдельный ALTER не нужен."""
    path = str(tmp_path / "old.sqlite3")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE posts (id TEXT PRIMARY KEY)")
    con.commit()
    con.close()

    storage.init_db(path)
    storage.save_session_meta(path, "s1", track_name="Сузука")

    assert storage.get_session_meta(path)["track_name"] == "Сузука"


# --- действия читателя ------------------------------------------------------

def _post_row(path, post_id="p1"):
    storage.save_post(path, Post(
        id=post_id, session_id="s", story_id="st", reporter_id="race_control",
        category="incident", text="текст", created_at=1.0, published_at=2.0,
        driver="Норрис", is_player_story=False,
    ))


def test_reaction_and_vote_travel_with_the_post(tmp_path):
    path = _db(tmp_path)
    _post_row(path)
    storage.save_reader_action(path, "p1", "reaction", "🔥")
    storage.save_reader_action(path, "p1", "vote", "Алонсо")

    assert storage.get_posts(path)[0]["reader"] == {"reaction": "🔥", "vote": "Алонсо"}


def test_post_without_reader_actions_has_an_empty_reader_dict(tmp_path):
    path = _db(tmp_path)
    _post_row(path)

    assert storage.get_posts(path)[0]["reader"] == {}


def test_archived_post_from_before_reader_actions_is_still_readable(tmp_path):
    """Old race databases are immutable and must not require a write migration."""
    path = _db(tmp_path)
    _post_row(path)
    con = sqlite3.connect(path)
    try:
        con.execute("DROP TABLE reader_actions")
        con.commit()
    finally:
        con.close()

    assert storage.get_posts(path)[0]["reader"] == {}


def test_second_reaction_replaces_the_first(tmp_path):
    path = _db(tmp_path)
    _post_row(path)
    storage.save_reader_action(path, "p1", "reaction", "🔥")
    storage.save_reader_action(path, "p1", "reaction", "👏")

    assert storage.get_posts(path)[0]["reader"]["reaction"] == "👏"


def test_empty_value_clears_the_action(tmp_path):
    """Повторный клик по той же реакции должен её снимать."""
    path = _db(tmp_path)
    _post_row(path)
    storage.save_reader_action(path, "p1", "reaction", "🔥")
    storage.save_reader_action(path, "p1", "reaction", "")

    assert storage.get_posts(path)[0]["reader"] == {}


def test_reader_actions_are_per_post(tmp_path):
    path = _db(tmp_path)
    _post_row(path, "p1")
    _post_row(path, "p2")
    storage.save_reader_action(path, "p1", "reaction", "🔥")

    rows = {row["id"]: row["reader"] for row in storage.get_posts(path)}
    assert rows["p1"] == {"reaction": "🔥"}
    assert rows["p2"] == {}


def test_reader_table_appears_in_databases_that_predate_it(tmp_path):
    """8 уже сохранённых гонок писались до появления таблицы — init_db создаёт
    её при следующем открытии, отдельная миграция не нужна."""
    path = str(tmp_path / "old.sqlite3")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE stories (id TEXT PRIMARY KEY)")
    con.commit()
    con.close()

    storage.init_db(path)
    storage.save_reader_action(path, "p1", "reaction", "🔥")

    con = sqlite3.connect(path)
    try:
        assert con.execute(
            "SELECT value FROM reader_actions WHERE post_id = 'p1'"
        ).fetchone()[0] == "🔥"
    finally:
        con.close()


# ── Сироты-скриншоты ─────────────────────────────────────────────────────────
#
# `_remove_session_file` уносит только `.sqlite3`, а снимки лежат рядом в
# `screenshots/`. Каждая удалённая сессия оставляла их навсегда, и найти
# виновного было нельзя: имя файла хранилось в уже удалённой базе.

def _session_with_image(directory, name: str, image: str):
    from core.racefeed.models import Post, Story

    path = str(directory / f"{name}.sqlite3")
    storage.init_db(path)
    story = Story(id="s1", story_key=("incident", "x"), category="incident",
                  session_type="race")
    post = Post(id=f"p-{name}", session_id=name, story_id="s1",
                reporter_id="r", category="incident", text="текст",
                created_at=1.0, published_at=1.0, driver="Игрок",
                is_player_story=True, image=image)
    storage.save_publication(path, story, post)
    return path


def test_an_orphaned_screenshot_is_removed(tmp_path):
    shots = tmp_path / "screenshots"
    shots.mkdir()
    kept, orphan = shots / "keep.png", shots / "orphan.png"
    kept.write_bytes(b"\x89PNG")
    orphan.write_bytes(b"\x89PNG")
    _session_with_image(tmp_path, "20260814_120000", "keep.png")

    removed = storage.prune_screenshots(str(tmp_path), grace_s=0.0)

    assert removed == 1
    assert kept.exists()
    assert not orphan.exists()


def test_a_fresh_screenshot_survives_its_own_publication_delay(tmp_path):
    """Снимок делается асинхронно в момент события, пост публикуется на 2-35
    секунд позже. Файл, родившийся секунду назад, сиротой не является."""
    shots = tmp_path / "screenshots"
    shots.mkdir()
    fresh = shots / "fresh.png"
    fresh.write_bytes(b"\x89PNG")
    _session_with_image(tmp_path, "20260814_120000", "other.png")

    removed = storage.prune_screenshots(str(tmp_path))   # штатная отсрочка

    assert removed == 0
    assert fresh.exists()


def test_a_screenshot_of_an_archived_race_is_kept_however_old(tmp_path):
    """Считаем от ЖИВЫХ ссылок, а не от возраста: пост годовалой сессии, ещё
    лежащей в архиве, обязан сохранить свою картинку."""
    import os

    shots = tmp_path / "screenshots"
    shots.mkdir()
    old = shots / "old.png"
    old.write_bytes(b"\x89PNG")
    os.utime(old, (0, 0))                       # 1970 год
    _session_with_image(tmp_path, "20260101_100000", "old.png")

    assert storage.prune_screenshots(str(tmp_path), grace_s=0.0) == 0
    assert old.exists()


def test_a_broken_database_makes_the_prune_do_nothing(tmp_path):
    """Удалить лишнее хуже, чем оставить лишнее: нечитаемая база означает
    неизвестный набор ссылок, а не пустой."""
    shots = tmp_path / "screenshots"
    shots.mkdir()
    shot = shots / "a.png"
    shot.write_bytes(b"\x89PNG")
    (tmp_path / "broken.sqlite3").write_bytes(b"not a database at all")

    assert storage.prune_screenshots(str(tmp_path), grace_s=0.0) == 0
    assert shot.exists()


def test_no_screenshots_directory_is_not_an_error(tmp_path):
    assert storage.prune_screenshots(str(tmp_path)) == 0
