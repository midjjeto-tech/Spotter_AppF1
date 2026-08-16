"""core/racefeed/engine.py — RaceFeedEngine owns the ingest queue, the worker
thread, rendering and persistence. Editorial decisions live behind
EditorialDesk; the runtime only feeds it Events/state snapshots and publishes
due Candidates. See the design doc for the module seam."""
from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from core.racefeed.generators import render_with_source
from core.racefeed import predictions, reader
from core.racefeed.comments import (
    comments_enabled_for,
    generate_comments,
    generate_replies,
)
from core.racefeed.editorial import (
    EditorialDesk,
    EditorialResult,
    StoryBuilder,
)
from core.racefeed.models import Post, Story
from core.racefeed import storage

_log = logging.getLogger(__name__)

_TICK_INTERVAL_S = 20.0
_WORKER_SLEEP_S = 0.5
_MAX_QUEUE = 200
_STOP_JOIN_TIMEOUT_S = 20.0  # a worker iteration can hold several provider calls
                              # (every due post render, then one comment batch,
                              # then one reader reply) — allow the one in flight
                              # to finish cleanly instead of killing it.

# Диагностические счётчики за текущую сессию (сбрасываются при открытии новой,
# см. _discard_pending). Цель — отвечать на вопрос "почему лента пустая": нет
# событий / всё подавил Editor / отвалился LLM. Пороги Editor'а по дизайну
# подбираются эмпирически (см. design doc), а без этих чисел тюнить их вслепую.
_STAT_KEYS: tuple[str, ...] = (
    "events_ingested",        # успешно поставлено в очередь ingest()
    "events_dropped_full",    # выброшено из-за переполнения очереди
    "candidates_proposed",    # репортёр предложил кандидата
    "candidates_suppressed",  # Editor вернул "suppress"
    "candidates_deferred",    # non-player COLL ждёт подтверждённого последствия
    "candidates_scheduled",   # кандидат ушёл в Scheduler
    "posts_published",        # пост создан и дошёл до UI (SQLite или volatile)
    "renders_failed",         # LLM недоступен/пустой ответ — кандидат отброшен
    "renders_fallback",       # пост собран шаблоном, а не LLM (критичная категория)
    "comments_generated",     # пост получил компактные AI-заметки
    "comments_skipped",       # AI-заметки не нужны для этой категории
)


def _new_stats() -> dict[str, int]:
    return {key: 0 for key in _STAT_KEYS}


class RaceFeedEngine:
    """Owns the ingest queue and the single worker thread that runs the whole
    pipeline (EditorialDesk -> Generator -> storage). Constructing an instance
    does no work — start() spins up the
    thread, stop() tears it down. See core/engine.py's apply_settings() for the
    hot enable/disable wiring that owns this lifecycle."""

    def __init__(self, ai_provider, state_provider: Callable[[], dict],
                 data_dir: str | None = None):
        self._ai = ai_provider
        self._state_provider = state_provider
        self._data_dir = Path(data_dir) if data_dir else _default_data_dir()
        self._queue: "queue.Queue" = queue.Queue(maxsize=_MAX_QUEUE)
        self._editorial = EditorialDesk()
        self._db_path: str | None = None
        self._session_id: str | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_tick = 0.0
        self._session_active = False
        # "live" until the chequered flag; every Post carries it so comment
        # generation knows whether the race is still undecided (see comments.py).
        self._session_phase = "live"
        # False until the session file has a track name — see _write_session_meta
        self._meta_track_written = False
        self._state_lock = threading.Lock()
        self._pipeline_lock = threading.RLock()
        # ── Два маленьких лока для входов С ЧУЖОГО ПОТОКА ────────────────────
        # `_pipeline_lock` воркер держит ВСЮ итерацию, а внутри неё лежат
        # провайдерские вызовы: рендер каждого созревшего поста, затем пачка
        # комментариев, затем ответ читателю. При живом GigaChat это доли
        # секунды, при отвале — таймаут за таймаутом (за гонку 2026-08-11 их
        # было 31).
        #
        # Пока ленту и отправку реплики обслуживал тот же лок, HTTP-поток вставал
        # в очередь за LLM: браузер опрашивает `/api/racefeed` раз в 3 секунды
        # (NewSpotterUI/lib/use-racefeed.ts), запросы копятся и занимают потоки
        # HTTP-сервера. Докстринг `submit_reader_comment` прямо требует, чтобы
        # провайдерский вызов не сидел внутри запроса читателя, — через лок он
        # там и сидел.
        #
        # Порядок захвата строгий и односторонний: держа `_pipeline_lock`, можно
        # взять любой из этих двух; наоборот — никогда. Поэтому у входов с чужого
        # потока `_pipeline_lock` не появляется вовсе.
        self._volatile_lock = threading.Lock()
        self._replies_lock = threading.Lock()
        self._prediction_lock = threading.RLock()
        self._stats_lock = threading.Lock()
        self._stats = _new_stats()
        self._volatile_posts: dict[str, Post] = {}
        self._pending_publications: list[tuple[Story, Post]] = []
        # Published posts still awaiting their comment thread, with the facts
        # the thread is about (facts are not persisted on the Post itself).
        self._pending_comments: list[tuple[Post, dict]] = []
        # Reader replies awaiting answers from the personas:
        # (session_id, post_id, player comment dict).
        self._pending_replies: list[tuple[str, str, dict]] = []
        # Once the start lights fire, a forecast may no longer be created or
        # edited. This guard also prevents late telemetry from producing a
        # conveniently hindsight-aware prediction mid-race.
        self._prediction_lock_requested = False

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="race-feed")
        self._thread.start()

    def stop(self, timeout: float = _STOP_JOIN_TIMEOUT_S) -> bool:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, timeout))
            if self._thread.is_alive():
                _log.warning(
                    "RaceFeed worker thread did not stop within %.1fs; leaving it "
                    "to finish on its own (start()'s re-entrancy guard prevents a "
                    "duplicate until it actually exits)", _STOP_JOIN_TIMEOUT_S)
                return False
        self._thread = None
        with self._pipeline_lock:
            self._discard_pending()
        return True

    def reset(self, *, session_type: str = "") -> None:
        """Starts a new session: fresh SQLite file, cleared Story Memory. Call on
        SSTA (see core/engine.py's SSTA handling)."""
        self._open_session(discard_pending=True, session_type=session_type)

    def _open_session(self, *, discard_pending: bool,
                      session_type: str = "") -> None:
        session_id = time.strftime("%Y%m%d_%H%M%S")
        self._data_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(self._data_dir / f"{session_id}.sqlite3")
        storage.init_db(db_path)
        with self._pipeline_lock:
            if discard_pending:
                self._discard_pending()
            self._last_tick = 0.0
            self._session_active = True
            self._session_phase = "live"
            self._meta_track_written = False
            with self._prediction_lock:
                self._prediction_lock_requested = False
            with self._state_lock:
                self._session_id = session_id
                self._db_path = db_path
        self._write_session_meta(db_path, session_id, session_type=session_type,
                                 started_at=time.time())

    def _write_session_meta(self, db_path: str, session_id: str, *,
                            session_type: str = "",
                            started_at: float = 0.0) -> None:
        """Label the file so the archive can name the race. The track is usually
        still unknown at SSTA — _maybe_tick calls this again until it resolves
        (save_session_meta never overwrites a known value with an empty one)."""
        track_name = ""
        try:
            snapshot = self._state_provider() or {}
            track_name = str(snapshot.get("track_name") or "")
            session_type = session_type or str(snapshot.get("session_type") or "")
        except Exception:  # noqa: BLE001 - labelling is never critical
            _log.debug("RaceFeed could not read state for session meta",
                       exc_info=True)
        try:
            storage.save_session_meta(
                db_path, session_id, track_name=track_name,
                session_type=session_type, started_at=started_at,
            )
        except Exception:
            _log.warning("RaceFeed session meta write failed", exc_info=True)
            return
        if track_name:
            self._meta_track_written = True

    def _discard_pending(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._editorial.clear()
        self._session_active = False
        self._session_phase = "live"
        with self._volatile_lock:
            self._volatile_posts.clear()
        self._pending_publications.clear()
        self._pending_comments.clear()
        # Reader replies are NOT dropped on a session reset: they belong to
        # whichever race file the reader was reading, which may well be an
        # archived one, and the answer should still arrive.
        with self._stats_lock:
            self._stats = _new_stats()

    def _bump(self, key: str, n: int = 1) -> None:
        with self._stats_lock:
            self._stats[key] += n

    def _record_editorial_result(self, result: EditorialResult) -> None:
        if result.proposed:
            self._bump("candidates_proposed", result.proposed)
        if result.suppressed:
            self._bump("candidates_suppressed", result.suppressed)
        if result.deferred:
            self._bump("candidates_deferred", result.deferred)
        if result.scheduled:
            self._bump("candidates_scheduled", result.scheduled)

    def get_stats(self) -> dict[str, int]:
        """Snapshot of the current session's pipeline counters. Safe to call from
        the Bottle request thread (see ui_bridge) while the worker mutates them."""
        with self._stats_lock:
            return dict(self._stats)

    def ingest(self, event) -> None:
        if self._stop_event.is_set():
            return
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self._bump("events_dropped_full")
            _log.debug("RaceFeed ingest queue full, dropping event %s", event.event_code)
        else:
            self._bump("events_ingested")

    def current_db_path(self) -> str | None:
        with self._state_lock:
            return self._db_path

    def data_dir(self) -> str:
        """Where session files live. Read-only accessor for ui_bridge's archive
        listing — it must scan the same directory the engine writes to,
        including the test-only override passed to __init__."""
        return str(self._data_dir)

    def _ensure_prediction(self) -> dict | None:
        db_path = self.current_db_path()
        with self._state_lock:
            session_id = self._session_id
        if db_path is None or not session_id:
            return None
        existing = storage.get_prediction(db_path)
        if existing is not None:
            return existing
        if self._prediction_lock_requested:
            return None
        snapshot = self._state_provider() or {}
        if snapshot.get("session_type") != "race":
            return None
        forecast = predictions.build_model_forecast(snapshot)
        if forecast is None:
            return None
        import core.track_return as track_return
        return_card = track_return.build(
            snapshot.get("track_id"), str(snapshot.get("track_name") or "")
        )
        storage.create_prediction(
            db_path,
            session_id,
            track_name=str(snapshot.get("track_name") or ""),
            model_forecast=forecast,
            track_return=return_card,
        )
        return storage.get_prediction(db_path)

    def get_prediction_state(self) -> dict | None:
        """Current fixed forecast plus the season-long player-vs-model score."""
        with self._prediction_lock:
            row = self._ensure_prediction()
            if row is None:
                return None
            return {
                **row,
                "scoreboard": predictions.scoreboard(
                    storage.list_predictions(str(self._data_dir))
                ),
            }

    def submit_prediction(self, ticket: dict) -> dict:
        with self._prediction_lock:
            try:
                normalized = predictions.normalize_ticket(ticket)
            except ValueError as exc:
                return {"ok": False, "reason": str(exc)}
            row = self._ensure_prediction()
            if row is None:
                return {"ok": False, "reason": "prediction_unavailable"}
            if row.get("status") != "open":
                return {"ok": False, "reason": "prediction_locked",
                        "prediction": self.get_prediction_state()}
            if not storage.save_prediction_ticket(
                    self.current_db_path() or "", self._session_id or "", normalized):
                return {"ok": False, "reason": "prediction_locked"}
            return {"ok": True, "prediction": self.get_prediction_state()}

    def lock_prediction(self) -> None:
        """Called exactly at the first STLG event; safe to call repeatedly."""
        with self._prediction_lock:
            row = self._ensure_prediction()
            self._prediction_lock_requested = True
            if row is None or row.get("status") != "open":
                return
            storage.lock_prediction(
                self.current_db_path() or "", self._session_id or ""
            )

    def resolve_prediction(self, grid: list[dict], driver_lookup, player_idx: int,
                           *, actual_risks: dict) -> None:
        """Resolve the fixed forecast from Final Classification facts."""
        with self._prediction_lock:
            db_path = self.current_db_path()
            row = storage.get_prediction(db_path) if db_path else None
            if row is None or row.get("status") == "resolved":
                return
            self._prediction_lock_requested = True
            result = predictions.resolve(
                row.get("model_forecast") or {},
                row.get("reader_ticket") or {},
                grid,
                driver_lookup,
                player_idx,
                actual_risks=actual_risks,
            )
            if result is None:
                return
            storage.resolve_prediction(
                db_path, self._session_id or row.get("session_id") or "", result
            )

    def get_volatile_posts(self, limit: int = 200) -> list[dict]:
        """Посты, которые не удалось записать в SQLite. Читается ИЗ HTTP-потока
        на каждом опросе ленты, поэтому берётся только `_volatile_lock` — с
        `_pipeline_lock` этот вызов ждал бы столько же, сколько идёт рендер
        через LLM."""
        with self._volatile_lock:
            posts = sorted(
                self._volatile_posts.values(),
                key=lambda post: post.published_at,
                reverse=True,
            )
            return [asdict(post) for post in posts[:limit]]

    def set_ai_provider(self, ai_provider) -> None:
        """Called by core.engine when Yandex credentials rotate (see
        F1Engine.apply_yandex_credentials) — keeps RaceFeed's LLM calls using
        the current client instead of a stale, closed one."""
        self._ai = ai_provider

    def _run(self) -> None:
        self._prune_old_sessions()
        while not self._stop_event.is_set():
            try:
                with self._pipeline_lock:
                    self._drain_queue()
                    self._maybe_tick()
                    self._retry_pending_publications()
                    self._publish_due()
                    self._generate_pending_comments()
                    self._generate_pending_replies()
            except Exception:
                _log.exception("RaceFeed worker iteration failed; continuing")
            time.sleep(_WORKER_SLEEP_S)

    def _prune_old_sessions(self) -> None:
        """Once per worker start — off the caller's thread and never during a
        race (SSTA opens a session on the hot path; this runs long before)."""
        try:
            storage.prune_sessions(str(self._data_dir),
                                   protect=self.current_db_path())
        except Exception:
            _log.warning("RaceFeed session pruning failed", exc_info=True)
        # ПОСЛЕ сессий, а не до: сироты определяются по ссылкам из уцелевших
        # баз, и снимки только что удалённых сессий должны попасть под чистку
        # этим же проходом, а не ждать следующего запуска.
        try:
            storage.prune_screenshots(str(self._data_dir))
        except Exception:
            _log.warning("RaceFeed screenshot pruning failed", exc_info=True)

    def _drain_queue(self) -> None:
        while True:
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                return
            if self.current_db_path() is None:
                # Open a fresh feed for race OR qualifying (see reporters.py's
                # QualifyingReporter). Practice/unknown produce no covered
                # stories, so don't spin up a session file for them.
                if event.session_type not in ("race", "qualifying"):
                    continue
                self._open_session(discard_pending=False,
                                   session_type=event.session_type)
            self._record_editorial_result(self._editorial.observe_event(event))
            if event.event_code in {"CHQF", "SEND"}:
                self._session_active = False
                # Posts published from here on (including the chequered-flag
                # post itself and anything still scheduled from the last laps)
                # are read after the result is final.
                self._session_phase = "finished"

    def _maybe_tick(self) -> None:
        if not self._session_active:
            return
        now = time.time()
        if now - self._last_tick < _TICK_INTERVAL_S:
            return
        self._last_tick = now
        snapshot = self._state_provider()
        session_type = snapshot.get("session_type", "unknown")
        if session_type != "race":
            return
        db_path = self.current_db_path()
        if db_path is None:
            self._open_session(discard_pending=False, session_type=session_type)
            db_path = self.current_db_path()
        elif not self._meta_track_written and snapshot.get("track_name"):
            # The track usually resolves a few packets after SSTA, so the label
            # is written on the first tick that knows it — once, not every tick.
            self._write_session_meta(db_path, self._session_id or "",
                                     session_type=session_type)
        self._record_editorial_result(
            self._editorial.observe_snapshot(snapshot, session_type, now=now)
        )

    def _publish_due(self) -> None:
        db_path = self.current_db_path()
        if db_path is None:
            return
        for publication in self._editorial.due(time.time()):
            candidate = publication.candidate
            story = publication.story
            text, source = render_with_source(candidate, story, self._ai)
            if not text:
                self._bump("renders_failed")
                continue
            if source == "fallback":
                self._bump("renders_fallback")
            published_at = time.time()
            facts = candidate.facts_snapshot or story.facts
            metadata: dict = {}
            if candidate.category == "driver_of_the_day":
                metadata["poll"] = facts.get("dotd_candidates") or []
            elif candidate.category == "post_race_interview":
                metadata["interview"] = facts.get("interview_quotes") or []
            elif candidate.category == "race_recap":
                metadata["recap"] = facts.get("race_recap") or {}
                metadata["weekend_duel"] = facts.get("weekend_duel") or {}
            elif candidate.category == "championship":
                metadata["comparison"] = {
                    key: facts[key]
                    for key in (
                        "driver", "player_position", "player_points",
                        "rival", "rival_position", "rival_points", "gap_to_rival",
                        "player_race_position", "rival_race_position",
                        "rival_ahead",
                    )
                    if facts.get(key) is not None
                }
                metadata["storylines"] = facts.get("storylines") or []
                metadata["return_hook"] = facts.get("return_hook") or {}
            post = Post(
                id=uuid.uuid4().hex, session_id=self._session_id or "unknown",
                story_id=story.id, reporter_id=candidate.reporter_id,
                category=candidate.category, text=text,
                created_at=(candidate.story_last_update
                            if candidate.story_last_update is not None
                            else story.last_update),
                published_at=published_at,
                driver=facts.get("driver"),
                is_player_story=bool(
                    facts.get("is_player", False)
                ),
                image=facts.get("image", ""),
                metadata=metadata,
                session_phase=self._session_phase,
                story_stage=(
                    candidate.story_stage
                    if candidate.story_stage is not None
                    else story.stage
                ),
                format_id=candidate.format_id or "live_update",
                angle_id=candidate.angle_id,
                claim_fingerprint=candidate.claim_fingerprint,
            )
            # The comment batch is a second provider call. Publishing the post
            # first and queueing the thread for the next worker iteration keeps
            # a slow provider from delaying every other due publication —
            # invisible to the reader, since comments.py's reveal schedule
            # already trickles a thread in over 3-5 minutes.
            if comments_enabled_for(post):
                self._pending_comments.append((post, dict(facts)))
            else:
                self._bump("comments_skipped")
            self._bump("posts_published")
            persisted_story = self._editorial.advanced_story(
                publication,
                post.id,
                published_at=published_at,
            )
            try:
                storage.save_publication(db_path, persisted_story, post)
            except Exception:
                _log.warning("RaceFeed storage write failed", exc_info=True)
                with self._volatile_lock:
                    self._volatile_posts[post.id] = post
                self._pending_publications.append((persisted_story, post))
                self._editorial.mark_published(
                    publication,
                    post.id,
                    published_at=published_at,
                )
                continue
            self._editorial.mark_published(
                publication,
                post.id,
                published_at=published_at,
            )

    def _generate_pending_comments(self) -> None:
        """One thread per worker iteration (the loop sleeps 0.5s), so a queue of
        posts keeps flowing while threads fill in behind them. A post whose
        thread never gets generated — session reset, shutdown — simply stays
        without comments; nothing downstream requires them."""
        if not self._pending_comments:
            return
        db_path = self.current_db_path()
        if db_path is None:
            return
        post, facts = self._pending_comments.pop(0)
        comments = generate_comments(post, self._ai, facts)
        if not comments:
            # comments_enabled_for() was checked before queueing, so an empty
            # batch here means generation itself produced nothing.
            self._bump("comments_skipped")
            return
        post.comments = comments  # same object as in _volatile_posts, if any
        self._bump("comments_generated")
        try:
            storage.save_comments(db_path, comments)
        except Exception:
            _log.warning("RaceFeed comment write failed", exc_info=True)

    def submit_reader_comment(self, session_id: str, post_id: str,
                              text: str) -> dict:
        """Store the reader's line right away and queue the personas' answer for
        the worker. The provider call must not sit inside the reader's HTTP
        request — a slow LLM would look like a broken send button.

        Raises reader.ReaderError on a bad session id, unknown post or empty
        text (see core/racefeed/reader.py)."""
        comment = reader.add_comment(str(self._data_dir), session_id, post_id, text)
        # `_replies_lock`, а не `_pipeline_lock`: последний воркер держит вместе
        # со всеми провайдерскими вызовами итерации, и ожидание на нём выглядело
        # бы ровно тем сломанным «Отправить», о котором предупреждает абзац выше.
        with self._replies_lock:
            self._pending_replies.append((session_id, post_id, comment))
        return comment

    def _generate_pending_replies(self) -> None:
        """One reader reply answered per worker iteration, like comment threads.
        A failure here costs the answer, never the reader's own line — that is
        already persisted by the time this runs."""
        with self._replies_lock:
            if not self._pending_replies:
                return
            session_id, post_id, parent = self._pending_replies.pop(0)
        try:
            post_text, thread = reader.thread_of(
                str(self._data_dir), session_id, post_id)
        except Exception:
            _log.warning("RaceFeed could not read the thread for a reader reply",
                         exc_info=True)
            return
        replies = generate_replies(
            post_id=post_id, parent_id=parent["id"], post_text=post_text,
            thread=[item for item in thread if item["id"] != parent["id"]],
            player_text=parent["text"], ai_provider=self._ai,
            parent_created_at=parent.get("created_at"),
        )
        if not replies:
            return
        try:
            storage.save_comments(
                str(reader.session_file(str(self._data_dir), session_id)), replies)
        except Exception:
            _log.warning("RaceFeed reply write failed", exc_info=True)

    def _retry_pending_publications(self) -> None:
        if not self._pending_publications:
            return
        db_path = self.current_db_path()
        if db_path is None:
            return
        remaining: list[tuple[Story, Post]] = []
        for story, post in self._pending_publications:
            try:
                storage.save_publication(db_path, story, post)
            except Exception:
                remaining.append((story, post))
            else:
                with self._volatile_lock:
                    self._volatile_posts.pop(post.id, None)
        self._pending_publications = remaining


def _default_data_dir() -> Path:
    import config
    return Path(config.DATA_DIR) / "racefeed"
