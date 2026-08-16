"""core/racefeed/storage.py — SQLite persistence for RaceFeed posts and stories.
One file per race session (see core/racefeed/engine.py::RaceFeedEngine.reset()).
Short-lived connections per call — this is what makes it safe to call from both
the worker thread (writes) and the Bottle request thread (reads via ui_bridge)
without a shared connection or manual locking; at Phase 1 volumes (a few writes
per second at most) this is more than sufficient."""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

from core.racefeed.models import Comment, Post, Story

_log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
    id TEXT PRIMARY KEY,
    story_key TEXT,
    category TEXT,
    session_type TEXT,
    stage INTEGER,
    facts TEXT,
    history TEXT,
    created_at REAL,
    last_update REAL,
    last_publish REAL,
    status TEXT
);
CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    story_id TEXT,
    story_stage INTEGER NOT NULL DEFAULT 0,
    format_id TEXT NOT NULL DEFAULT 'live_update',
    angle_id TEXT NOT NULL DEFAULT '',
    claim_fingerprint TEXT NOT NULL DEFAULT '',
    image TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}',
    session_phase TEXT NOT NULL DEFAULT 'live',
    reporter_id TEXT,
    category TEXT,
    text TEXT,
    created_at REAL,
    published_at REAL,
    driver TEXT,
    is_player_story INTEGER
);
CREATE TABLE IF NOT EXISTS comments (
    id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL,
    parent_id TEXT,
    author_id TEXT NOT NULL,
    author_name TEXT NOT NULL,
    author_badge TEXT NOT NULL DEFAULT '',
    avatar TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at REAL NOT NULL,
    likes INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_comments_post_id
    ON comments(post_id, created_at);
CREATE TABLE IF NOT EXISTS reader_actions (
    post_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (post_id, kind)
);
CREATE TABLE IF NOT EXISTS session_meta (
    session_id TEXT PRIMARY KEY,
    track_name TEXT NOT NULL DEFAULT '',
    session_type TEXT NOT NULL DEFAULT '',
    started_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS race_predictions (
    session_id TEXT PRIMARY KEY,
    track_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    model_forecast TEXT NOT NULL DEFAULT '{}',
    reader_ticket TEXT NOT NULL DEFAULT '{}',
    result TEXT NOT NULL DEFAULT '{}',
    track_return TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL DEFAULT 0,
    locked_at REAL NOT NULL DEFAULT 0,
    resolved_at REAL NOT NULL DEFAULT 0
);
"""


def _insert_comments(con: sqlite3.Connection, comments: list[Comment]) -> None:
    con.executemany(
        """INSERT OR IGNORE INTO comments
           (id, post_id, parent_id, author_id, author_name, author_badge,
            avatar, text, created_at, likes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(comment.id, comment.post_id, comment.parent_id, comment.author_id,
          comment.author_name, comment.author_badge, comment.avatar,
          comment.text, comment.created_at, comment.likes)
         for comment in comments],
    )


def init_db(path: str) -> None:
    con = sqlite3.connect(path, timeout=5)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(_SCHEMA)
        columns = {row[1] for row in con.execute("PRAGMA table_info(posts)")}
        if "session_id" not in columns:
            con.execute("ALTER TABLE posts ADD COLUMN session_id TEXT")
        if "story_stage" not in columns:
            con.execute(
                "ALTER TABLE posts ADD COLUMN story_stage INTEGER NOT NULL DEFAULT 0"
            )
        if "format_id" not in columns:
            con.execute(
                "ALTER TABLE posts ADD COLUMN format_id TEXT NOT NULL DEFAULT 'live_update'"
            )
        if "angle_id" not in columns:
            con.execute(
                "ALTER TABLE posts ADD COLUMN angle_id TEXT NOT NULL DEFAULT ''"
            )
        if "claim_fingerprint" not in columns:
            con.execute(
                "ALTER TABLE posts ADD COLUMN claim_fingerprint TEXT NOT NULL DEFAULT ''"
            )
        if "image" not in columns:
            con.execute(
                "ALTER TABLE posts ADD COLUMN image TEXT NOT NULL DEFAULT ''"
            )
        if "metadata" not in columns:
            con.execute(
                "ALTER TABLE posts ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'"
            )
        if "session_phase" not in columns:
            con.execute(
                "ALTER TABLE posts ADD COLUMN session_phase TEXT NOT NULL "
                "DEFAULT 'live'"
            )
        con.commit()
    finally:
        con.close()


def save_reader_action(path: str, post_id: str, kind: str, value: str, *,
                       created_at: float = 0.0) -> None:
    """What the reader did to a post: their reaction emoji or a poll choice.
    One row per (post, kind) — a second reaction
    replaces the first. An empty value removes the row, which is how clicking
    the same emoji again clears it."""
    con = sqlite3.connect(path, timeout=5)
    try:
        with con:
            if not value:
                con.execute(
                    "DELETE FROM reader_actions WHERE post_id = ? AND kind = ?",
                    (post_id, kind),
                )
                return
            con.execute(
                """INSERT INTO reader_actions (post_id, kind, value, created_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(post_id, kind) DO UPDATE SET
                       value=excluded.value, created_at=excluded.created_at""",
                (post_id, kind, value, float(created_at or time.time())),
            )
    finally:
        con.close()


def save_session_meta(path: str, session_id: str, *, track_name: str = "",
                      session_type: str = "", started_at: float = 0.0) -> None:
    """Label the session file so the archive can say «Гран-при Монцы · 26 июля»
    instead of a bare timestamp. UPSERT: the track is often still unknown at
    SSTA, so the periodic tick fills it in later (see engine._maybe_tick).
    An empty value never overwrites a known one."""
    con = sqlite3.connect(path, timeout=5)
    try:
        with con:
            con.execute(
                """INSERT INTO session_meta
                   (session_id, track_name, session_type, started_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                       track_name=CASE WHEN excluded.track_name != ''
                                       THEN excluded.track_name
                                       ELSE session_meta.track_name END,
                       session_type=CASE WHEN excluded.session_type != ''
                                         THEN excluded.session_type
                                         ELSE session_meta.session_type END""",
                (session_id, track_name or "", session_type or "",
                 float(started_at or 0.0)),
            )
    finally:
        con.close()


def get_session_meta(path: str) -> dict | None:
    """Meta row of a session file, or None for files written before this table
    existed (they are labelled by their timestamp filename instead)."""
    con = sqlite3.connect(path, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT * FROM session_meta ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row is not None else None
    except sqlite3.Error:
        return None
    finally:
        con.close()


def create_prediction(path: str, session_id: str, *, track_name: str,
                      model_forecast: dict, track_return: dict | None,
                      created_at: float = 0.0) -> None:
    """Persist the model's first forecast; later reads never regenerate it."""
    con = sqlite3.connect(path, timeout=5)
    try:
        with con:
            con.execute(
                """INSERT OR IGNORE INTO race_predictions
                   (session_id, track_name, status, model_forecast,
                    reader_ticket, result, track_return, created_at)
                   VALUES (?, ?, 'open', ?, '{}', '{}', ?, ?)""",
                (session_id, track_name or "",
                 json.dumps(model_forecast, ensure_ascii=False),
                 json.dumps(track_return or {}, ensure_ascii=False),
                 float(created_at or time.time())),
            )
    finally:
        con.close()


def get_prediction(path: str) -> dict | None:
    con = sqlite3.connect(path, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT * FROM race_predictions ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        for key in ("model_forecast", "reader_ticket", "result", "track_return"):
            try:
                value = json.loads(result.get(key) or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                value = {}
            result[key] = value if isinstance(value, dict) else {}
        return result
    except sqlite3.Error:
        return None
    finally:
        con.close()


def save_prediction_ticket(path: str, session_id: str, ticket: dict) -> bool:
    con = sqlite3.connect(path, timeout=5)
    try:
        with con:
            cursor = con.execute(
                """UPDATE race_predictions SET reader_ticket = ?
                   WHERE session_id = ? AND status = 'open'""",
                (json.dumps(ticket, ensure_ascii=False), session_id),
            )
        return cursor.rowcount == 1
    finally:
        con.close()


def lock_prediction(path: str, session_id: str, *, locked_at: float = 0.0) -> bool:
    con = sqlite3.connect(path, timeout=5)
    try:
        with con:
            cursor = con.execute(
                """UPDATE race_predictions SET status = 'locked', locked_at = ?
                   WHERE session_id = ? AND status = 'open'""",
                (float(locked_at or time.time()), session_id),
            )
        return cursor.rowcount == 1
    finally:
        con.close()


def resolve_prediction(path: str, session_id: str, result: dict, *,
                       resolved_at: float = 0.0) -> bool:
    con = sqlite3.connect(path, timeout=5)
    try:
        with con:
            cursor = con.execute(
                """UPDATE race_predictions
                   SET status = 'resolved', result = ?, resolved_at = ?
                   WHERE session_id = ? AND status != 'resolved'""",
                (json.dumps(result, ensure_ascii=False),
                 float(resolved_at or time.time()), session_id),
            )
        return cursor.rowcount == 1
    finally:
        con.close()


def list_predictions(data_dir: str) -> list[dict]:
    rows: list[dict] = []
    directory = Path(data_dir)
    if not directory.is_dir():
        return rows
    for path in sorted(directory.glob("*.sqlite3"), reverse=True):
        prediction = get_prediction(str(path))
        if prediction is not None:
            rows.append(prediction)
    return rows


def upsert_story(path: str, story: Story) -> None:
    con = sqlite3.connect(path, timeout=5)
    try:
        con.execute(
            """INSERT INTO stories
               (id, story_key, category, session_type, stage, facts, history,
                created_at, last_update, last_publish, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   stage=excluded.stage, facts=excluded.facts, history=excluded.history,
                   last_update=excluded.last_update, last_publish=excluded.last_publish,
                   status=excluded.status""",
            (story.id, json.dumps(list(story.story_key)), story.category,
             story.session_type, story.stage, json.dumps(story.facts),
             json.dumps(story.history), story.created_at, story.last_update,
             story.last_publish, story.status),
        )
        con.commit()
    finally:
        con.close()


def save_post(path: str, post: Post) -> None:
    con = sqlite3.connect(path, timeout=5)
    try:
        with con:
            con.execute(
                """INSERT OR IGNORE INTO posts
                   (id, session_id, story_id, story_stage, format_id, angle_id,
                    claim_fingerprint, image, metadata, session_phase,
                    reporter_id, category, text, created_at, published_at,
                    driver, is_player_story)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (post.id, post.session_id, post.story_id, post.story_stage,
                 post.format_id, post.angle_id, post.claim_fingerprint, post.image,
                 json.dumps(post.metadata, ensure_ascii=False), post.session_phase,
                 post.reporter_id, post.category, post.text,
                 post.created_at, post.published_at, post.driver,
                 int(post.is_player_story)),
            )
            _insert_comments(con, post.comments)
    finally:
        con.close()


def save_publication(path: str, story: Story, post: Post) -> None:
    """Persist an advanced Story and its Post in one SQLite transaction."""
    con = sqlite3.connect(path, timeout=5)
    try:
        with con:
            con.execute(
                """INSERT INTO stories
                   (id, story_key, category, session_type, stage, facts, history,
                    created_at, last_update, last_publish, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       stage=excluded.stage, facts=excluded.facts,
                       history=excluded.history, last_update=excluded.last_update,
                       last_publish=excluded.last_publish, status=excluded.status""",
                (story.id, json.dumps(list(story.story_key)), story.category,
                 story.session_type, story.stage, json.dumps(story.facts),
                 json.dumps(story.history), story.created_at, story.last_update,
                 story.last_publish, story.status),
            )
            con.execute(
                """INSERT OR IGNORE INTO posts
                   (id, session_id, story_id, story_stage, format_id, angle_id,
                    claim_fingerprint, image, metadata, session_phase,
                    reporter_id, category, text, created_at, published_at,
                    driver, is_player_story)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (post.id, post.session_id, post.story_id, post.story_stage,
                 post.format_id, post.angle_id, post.claim_fingerprint, post.image,
                 json.dumps(post.metadata, ensure_ascii=False), post.session_phase,
                 post.reporter_id, post.category, post.text,
                 post.created_at, post.published_at, post.driver,
                 int(post.is_player_story)),
            )
            _insert_comments(con, post.comments)
    finally:
        con.close()


def save_comments(path: str, comments: list[Comment]) -> None:
    """Attach a comment thread to a post that is already persisted. Comments are
    generated a worker iteration after the post so a slow provider call can't
    hold up the next publication (see engine.py::_generate_pending_comments)."""
    if not comments:
        return
    con = sqlite3.connect(path, timeout=5)
    try:
        with con:
            _insert_comments(con, comments)
    finally:
        con.close()


def get_posts(path: str, limit: int = 200) -> list[dict]:
    con = sqlite3.connect(path, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT * FROM posts ORDER BY published_at DESC LIMIT ?", (limit,)
        ).fetchall()
        posts = [dict(r) for r in rows]
        for post in posts:
            try:
                metadata = json.loads(post.get("metadata") or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
            post["metadata"] = metadata if isinstance(metadata, dict) else {}
        if not posts:
            return posts
        placeholders = ",".join("?" for _ in posts)
        comment_rows = con.execute(
            f"SELECT * FROM comments WHERE post_id IN ({placeholders}) "
            "ORDER BY created_at ASC",
            tuple(post["id"] for post in posts),
        ).fetchall()
        by_post: dict[str, list[dict]] = {post["id"]: [] for post in posts}
        for row in comment_rows:
            by_post[row["post_id"]].append(dict(row))
        # Reader state travels with the post, so the live feed and the archive
        # both get it without a second round trip (see reader.py for writes).
        has_reader_actions = con.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'reader_actions'"
        ).fetchone()
        reader_rows = []
        if has_reader_actions:
            reader_rows = con.execute(
                f"SELECT * FROM reader_actions WHERE post_id IN ({placeholders})",
                tuple(post["id"] for post in posts),
            ).fetchall()
        reader_by_post: dict[str, dict] = {post["id"]: {} for post in posts}
        for row in reader_rows:
            reader_by_post[row["post_id"]][row["kind"]] = row["value"]
        for post in posts:
            post["comments"] = by_post[post["id"]]
            post["reader"] = reader_by_post[post["id"]]
        return posts
    finally:
        con.close()


def post_count(path: Path) -> int | None:
    """Number of posts in a session file, or None if it isn't a readable
    RaceFeed database (never guess from file size: an empty WAL database is
    exactly as large as a corrupt one)."""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None
    try:
        posts = con.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        has_predictions = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='race_predictions'"
        ).fetchone()
        predictions = (
            con.execute("SELECT COUNT(*) FROM race_predictions").fetchone()[0]
            if has_predictions else 0
        )
        return posts + predictions
    except sqlite3.Error:
        return None
    finally:
        con.close()


def _remove_session_file(path: Path) -> bool:
    """Delete a session database with its WAL sidecars (journal_mode=WAL leaves
    -wal/-shm next to the file; dropping only the .sqlite3 leaks them)."""
    removed = False
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            candidate.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            _log.warning("RaceFeed prune could not remove %s", candidate,
                         exc_info=True)
            continue
        if candidate == path:
            removed = True
    return removed


def prune_sessions(data_dir: str, keep_with_posts: int = 20,
                   protect: str | None = None) -> tuple[int, int]:
    """Housekeeping for the per-session database files. Every SSTA opens a new
    one, and a session that never produced a post (practice, an abandoned
    restart) leaves an empty file behind forever — the directory had grown to
    ~150 of them before this existed.

    Deletes every empty file and all but the newest `keep_with_posts` non-empty
    ones. `protect` (the currently open database) is never touched, and neither
    is anything that doesn't read as a RaceFeed database. Returns
    (empty removed, old removed)."""
    directory = Path(data_dir)
    if not directory.is_dir():
        return 0, 0
    protected = Path(protect).resolve() if protect else None

    empty: list[Path] = []
    with_posts: list[Path] = []
    for path in directory.glob("*.sqlite3"):
        if protected is not None and path.resolve() == protected:
            continue
        count = post_count(path)
        if count is None:
            continue
        (with_posts if count else empty).append(path)

    removed_empty = sum(_remove_session_file(path) for path in empty)
    # File names are timestamps (see engine._open_session), so a plain sort is
    # chronological.
    stale = sorted(with_posts, key=lambda path: path.name)[:-keep_with_posts or None]
    removed_old = sum(_remove_session_file(path) for path in stale)
    if removed_empty or removed_old:
        _log.info("RaceFeed pruned %d empty and %d old session files",
                  removed_empty, removed_old)
    return removed_empty, removed_old


#: Сколько скриншот живёт, пока его пост ещё не записан. Снимок делается
#: АСИНХРОННО в момент события (`core/engine.py::_capture_hero_screenshot`), а
#: пост публикуется на 2-35 секунд позже — файл, родившийся секунду назад,
#: сиротой не является. Час с запасом.
SCREENSHOT_GRACE_S = 3600.0


def prune_screenshots(data_dir: str, grace_s: float = SCREENSHOT_GRACE_S,
                      now: float | None = None) -> int:
    """Удалить PNG-и, на которые не ссылается ни одна уцелевшая сессия.

    Зачем отдельно от `prune_sessions`. Скриншоты лежат не в базе, а рядом
    (`racefeed/screenshots/`), и `_remove_session_file` уносит только `.sqlite3`.
    То есть каждая удалённая сессия оставляла свои снимки НАВСЕГДА, и никакой
    другой код на них уже не смотрел: имя файла хранилось в удалённой базе.
    Папка росла бесконечно, а найти виновного по её содержимому было нельзя.

    Считаем от ЖИВЫХ ссылок, а не от возраста файла: пост годовалой сессии, ещё
    лежащей в архиве, обязан сохранить свою картинку, а снимок вчерашней
    удалённой — нет. Возраст участвует лишь как отсрочка для файлов, чей пост ещё
    не успел записаться (см. `SCREENSHOT_GRACE_S`).
    """
    directory = Path(data_dir)
    shots = directory / "screenshots"
    if not shots.is_dir():
        return 0

    referenced: set[str] = set()
    for path in directory.glob("*.sqlite3"):
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        except sqlite3.Error:
            continue
        try:
            rows = con.execute(
                "SELECT image FROM posts WHERE image IS NOT NULL AND image != ''"
            ).fetchall()
            referenced.update(str(row[0]) for row in rows)
        except sqlite3.Error:
            # Битая или чужая база — считаем, что она ссылается на всё: удалить
            # лишнее хуже, чем оставить лишнее.
            return 0
        finally:
            con.close()

    moment = time.time() if now is None else now
    removed = 0
    for shot in shots.glob("*.png"):
        if shot.name in referenced:
            continue
        try:
            if moment - shot.stat().st_mtime < grace_s:
                continue
            shot.unlink()
        except OSError:
            continue
        removed += 1
    if removed:
        _log.info("RaceFeed pruned %d orphaned screenshot(s)", removed)
    return removed


def get_story(path: str, story_id: str) -> Story | None:
    con = sqlite3.connect(path, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT * FROM stories WHERE id = ?", (story_id,)
        ).fetchone()
        if row is None:
            return None
        return Story(
            id=row["id"], story_key=tuple(json.loads(row["story_key"])),
            category=row["category"], session_type=row["session_type"],
            stage=row["stage"], facts=json.loads(row["facts"]),
            history=json.loads(row["history"]), created_at=row["created_at"],
            last_update=row["last_update"], last_publish=row["last_publish"],
            status=row["status"],
            post_ids=[],  # not persisted — StoryMemory (in-memory) owns this field
        )
    finally:
        con.close()
