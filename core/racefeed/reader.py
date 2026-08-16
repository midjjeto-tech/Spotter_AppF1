"""core/racefeed/reader.py — the write side of RaceFeed: what the person
reading the channel does to it (a reaction, a poll choice, a reply in
a thread). Kept apart from ui_bridge, which is read-only by contract.

Everything lands in the session's own SQLite file, so an action survives a
restart and is still there when the race shows up in the archive months later.
The session file is located by the session_id the post carries — that value
comes from the browser, which is why session_file() validates it instead of
trusting it.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from pathlib import Path

from core.racefeed import storage
from core.racefeed.models import Comment

_log = logging.getLogger(__name__)

# Session files are named by RaceFeedEngine._open_session with
# time.strftime("%Y%m%d_%H%M%S") — nothing else is a valid session id.
_SESSION_ID_RE = re.compile(r"^\d{8}_\d{6}$")

MAX_COMMENT_CHARS = 500

PLAYER_AUTHOR_ID = "player"
PLAYER_AUTHOR_NAME = "Ты"
PLAYER_AVATAR = "Я"
PLAYER_BADGE = "читатель"

REACTION = "reaction"
VOTE = "vote"


class ReaderError(ValueError):
    """Rejected request — bad session id, unknown post, empty text."""


def session_file(data_dir: str, session_id: str) -> Path:
    """Path of a session database inside data_dir.

    session_id arrives from the browser, so this is the one place where the
    front end influences which file gets written. Anything that is not a bare
    timestamp is rejected, and the resolved path must still sit directly inside
    data_dir — otherwise "../../settings" would be a writable target.
    """
    if not _SESSION_ID_RE.match(str(session_id or "")):
        raise ReaderError("bad session id")
    root = Path(data_dir).resolve()
    path = (root / f"{session_id}.sqlite3").resolve()
    if path.parent != root:
        raise ReaderError("session file outside the feed directory")
    if not path.is_file():
        raise ReaderError("no such session")
    return path


def _apply(data_dir: str, session_id: str, post_id: str, kind: str,
           value: str) -> None:
    path = session_file(data_dir, session_id)
    if not str(post_id or "").strip():
        raise ReaderError("no post id")
    storage.save_reader_action(str(path), post_id, kind, value)


def react(data_dir: str, session_id: str, post_id: str, emoji: str) -> None:
    """Set (or, with an empty emoji, clear) the reader's reaction to a post."""
    _apply(data_dir, session_id, post_id, REACTION, str(emoji or "")[:8])


def vote(data_dir: str, session_id: str, post_id: str, driver: str) -> None:
    """Record one local poll choice (DOTD driver or a race-moment id).

    The simulated DOTD result itself is not rewritten —
    core/driver_of_the_day.py reports shares, not a ballot count, so adding one
    vote to a percentage would be invented arithmetic.
    """
    _apply(data_dir, session_id, post_id, VOTE, str(driver or "")[:64])


def add_comment(data_dir: str, session_id: str, post_id: str,
                text: str) -> dict:
    """Store the reader's own line in the thread and return it, so the UI can
    show it immediately instead of waiting for the next poll. Replies from the
    personas are generated afterwards by the worker (see
    RaceFeedEngine.submit_reader_comment) — a provider timeout must never hang
    the reader's own request."""
    body = str(text or "").strip()[:MAX_COMMENT_CHARS]
    if not body:
        raise ReaderError("empty comment")
    path = session_file(data_dir, session_id)
    if not str(post_id or "").strip():
        raise ReaderError("no post id")
    comment = Comment(
        id=uuid.uuid4().hex, post_id=post_id, parent_id=None,
        author_id=PLAYER_AUTHOR_ID, author_name=PLAYER_AUTHOR_NAME,
        avatar=PLAYER_AVATAR, author_badge=PLAYER_BADGE, text=body,
        created_at=time.time(), likes=0,
    )
    storage.save_comments(str(path), [comment])
    return {
        "id": comment.id, "post_id": comment.post_id,
        "parent_id": comment.parent_id, "author_id": comment.author_id,
        "author_name": comment.author_name, "author_badge": comment.author_badge,
        "avatar": comment.avatar, "text": comment.text,
        "created_at": comment.created_at, "likes": comment.likes,
    }


def thread_of(data_dir: str, session_id: str, post_id: str) -> tuple[str, list[dict]]:
    """(post text, existing comments) — context the personas need to answer the
    reader without inventing anything that is not already in the thread."""
    path = session_file(data_dir, session_id)
    for post in storage.get_posts(str(path), limit=500):
        if post["id"] == post_id:
            return post.get("text", ""), post.get("comments", [])
    raise ReaderError("no such post")
