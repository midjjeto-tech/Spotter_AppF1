"""core/racefeed/ui_bridge.py — read-only API consumed by web_server.py. Never
imports core.engine; takes a RaceFeedEngine instance (or None, when
racefeed_enabled is off) and returns JSON-serializable dicts."""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from core.racefeed import predictions, storage

if TYPE_CHECKING:
    from core.racefeed.engine import RaceFeedEngine

_log = logging.getLogger(__name__)

# Feed files of finished sessions never change, so a parsed session is cached
# under its (path, mtime_ns, size) identity. Without this the channel — which
# shows every saved race at once — would re-read up to 20 SQLite files on every
# poll. Entries for files the GC removed are dropped on the next call.
_ARCHIVE_CACHE: dict[str, tuple[tuple[int, int], dict]] = {}
MAX_ARCHIVE_SESSIONS = 20  # matches storage.prune_sessions' keep_with_posts


def get_posts(race_feed: "RaceFeedEngine | None", limit: int = 200) -> dict:
    if race_feed is None:
        return {"enabled": False, "posts": []}
    db_path = race_feed.current_db_path()
    if db_path is None:
        return {"enabled": True, "posts": []}
    volatile = race_feed.get_volatile_posts(limit=limit)
    try:
        rows = storage.get_posts(db_path, limit=limit)
    except sqlite3.Error:
        # storage failure: fail open rather than surface an error state to
        # the UI — see design doc's Error handling section (RaceFeed degrades
        # quietly rather than breaking the pipeline/UI on a storage hiccup).
        _log.warning("RaceFeed ui_bridge failed to read posts", exc_info=True)
        rows = []
    seen = {row["id"] for row in volatile}
    merged = volatile + [row for row in rows if row["id"] not in seen]
    merged.sort(key=lambda row: row["published_at"], reverse=True)
    result = {"enabled": True, "posts": merged[:limit]}
    prediction = race_feed.get_prediction_state()
    if prediction is not None:
        result["prediction"] = prediction
    return result


def _session_label(path: Path, meta: dict | None) -> dict:
    """Session identity for the archive divider. Files written before
    session_meta existed have no track — they fall back to the timestamp that
    is their filename (see engine._open_session)."""
    session_id = path.stem
    started_at = 0.0
    if meta:
        started_at = float(meta.get("started_at") or 0.0)
    if not started_at:
        try:
            started_at = datetime.strptime(session_id, "%Y%m%d_%H%M%S").timestamp()
        except ValueError:
            started_at = path.stat().st_mtime
    return {
        "session_id": session_id,
        "track_name": (meta or {}).get("track_name") or "",
        "session_type": (meta or {}).get("session_type") or "",
        "started_at": started_at,
    }


def _read_archive_session(path: Path, limit: int) -> dict | None:
    posts = storage.get_posts(str(path), limit=limit)
    prediction = storage.get_prediction(str(path))
    if not posts and not (prediction and prediction.get("status") == "resolved"):
        return None
    session = _session_label(path, storage.get_session_meta(str(path)))
    session["post_count"] = len(posts)
    session["posts"] = posts
    if prediction is not None:
        session["prediction"] = prediction
    return session


def get_archive(race_feed: "RaceFeedEngine | None",
                max_sessions: int = MAX_ARCHIVE_SESSIONS,
                limit_per_session: int = 200) -> dict:
    """Previously finished feeds, newest race first. The live session is left
    out — get_posts() already serves it, and it is the only one that changes.

    This is why the channel survives between races: RaceFeedEngine.reset()
    opens a brand new SQLite file per session, so without reading the older
    ones the channel is empty whenever a race isn't running."""
    if race_feed is None:
        return {"enabled": False, "sessions": []}
    data_dir = Path(race_feed.data_dir())
    if not data_dir.is_dir():
        return {"enabled": True, "sessions": []}
    current = race_feed.current_db_path()
    current_resolved = Path(current).resolve() if current else None

    # File names are timestamps (engine._open_session), so name order is
    # chronological — newest race first.
    candidates = [
        path for path in sorted(data_dir.glob("*.sqlite3"),
                                key=lambda p: p.name, reverse=True)
        if current_resolved is None or path.resolve() != current_resolved
    ]
    seen = {str(path) for path in candidates}

    sessions: list[dict] = []
    for path in candidates:
        if len(sessions) >= max_sessions:
            break
        key = str(path)
        try:
            stat = path.stat()
            identity = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            continue
        cached = _ARCHIVE_CACHE.get(key)
        if cached is not None and cached[0] == identity:
            sessions.append(cached[1])
            continue
        try:
            session = _read_archive_session(path, limit_per_session)
        except sqlite3.Error:
            # Same fail-open contract as get_posts: a damaged old file must not
            # take the whole channel down with it.
            _log.warning("RaceFeed archive skipped unreadable %s", path,
                         exc_info=True)
            continue
        if session is None:
            continue
        _ARCHIVE_CACHE[key] = (identity, session)
        sessions.append(session)

    for stale in [key for key in _ARCHIVE_CACHE if key not in seen]:
        _ARCHIVE_CACHE.pop(stale, None)
    score = predictions.scoreboard(storage.list_predictions(str(data_dir)))
    for session in sessions:
        if session.get("prediction") is not None:
            session["prediction"]["scoreboard"] = score
    return {"enabled": True, "sessions": sessions}


def get_standings(race_feed: "RaceFeedEngine | None") -> dict:
    """Sliding-window championship table for the pinned UI card. Independent of
    the posts feed (shows even with an empty channel). Empty until the first
    finished race is recorded in the season store."""
    if race_feed is None:
        return {"enabled": False, "standings": [], "races_counted": 0, "profile": None}
    import core.season as season
    import core.career_stats as career_stats
    result = season.compute_standings()
    if result is None:
        return {"enabled": True, "standings": [], "races_counted": 0, "profile": None}
    summary = season.season_summary()
    profile = {
        "championship_position": (summary or {}).get("player_position"),
        "championship_points": (summary or {}).get("player_points"),
        "best_result": season.best_result(),
        "career": career_stats.compute_career_stats(),
    }
    standings = result["standings"]
    rival = season.pick_rival(standings)
    if rival is not None:
        rival["is_rival"] = True  # same dict object as in `standings` — tags the row
    return {"enabled": True, "standings": standings,
            "races_counted": result["races_counted"], "profile": profile}


def get_stats(race_feed: "RaceFeedEngine | None") -> dict:
    """Diagnostic pipeline counters for the current session. Read-only, cheap —
    lets the feed be tuned empirically (why is it empty: no events / all
    suppressed / LLM failing) without attaching a debugger. See design doc: the
    Editor's thresholds are meant to be tuned against real races."""
    if race_feed is None:
        return {"enabled": False, "stats": {}}
    return {
        "enabled": True,
        "session_active": race_feed.current_db_path() is not None,
        "stats": race_feed.get_stats(),
    }
