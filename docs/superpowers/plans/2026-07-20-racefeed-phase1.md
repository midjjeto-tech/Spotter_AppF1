# RaceFeed Phase 1 (Core Pipeline) Implementation Plan

> **Status 2026-07-21:** code-complete. Tasks 1–18 and all automated parts of Task 19
> are implemented and green. Production UI is built/synced. The only remaining step is
> live F1 25 verification of editorial feel and timing; see `CODEX_CLAUDE_HANDOFF.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build RaceFeed's core pipeline — telemetry events become journalist-style
posts through a deterministic editorial loop (StoryBuilder → Reporter → Editor →
Scheduler → Generator), persisted to SQLite and surfaced on a new text-only
"RaceFeed" tab, gated behind a `racefeed_enabled` setting that truly starts/stops
the subsystem's worker thread (no idle threads or LLM calls while disabled).

**Architecture:** New isolated package `core/racefeed/` (9 files) hooked into
`core/engine.py` at exactly one point (`_enqueue_event`'s existing fan-out) plus a
`state_provider` pull-callback for periodic/analytical stories. The Editor is
deterministic — the LLM is only ever asked to render already-approved facts into
prose, never to decide what's worth publishing (this codebase has a documented
history of LLM-driven duplicate-story spam; see `core/situation_dedup.py`).
Storage is SQLite (one file per race session), consistent with the full spec's
`World/career_x/feed.db`/`posts.db` naming. Frontend follows this app's existing
single-page view-switch pattern (no router) with its own 3s polling hook, separate
from the existing 1s `/api/state` poll.

**Tech Stack:** Python 3.12, `sqlite3` (stdlib), `pytest`; Next.js/React/TypeScript
(static export), existing `fetch`-based polling pattern, no new dependencies on
either side.

**Full design doc:** [docs/superpowers/specs/2026-07-20-racefeed-phase1-design.md](../specs/2026-07-20-racefeed-phase1-design.md)

**Note on commits:** This repo has no git (`git status` confirmed to fail,
`.git` does not exist, 2026-07-20). Every task ends with a **Checkpoint** step
(mark the task done) instead of `git add`/`git commit` — do not run git commands
in this plan. If real per-task commit safety is wanted, `git init` first (ask the
user explicitly — this project's convention is to never do that unprompted) and
swap Checkpoint steps for Commit steps yourself.

**Test runner:** `py -3.12 -u -m pytest <path> -v` (matches this project's existing
convention; do not use bare `pytest` or `python -m pytest`).

---

## Task 1: `models.py` — Event, Story, Candidate, Post

**Files:**
- Create: `core/racefeed/__init__.py`
- Create: `core/racefeed/models.py`
- Test: `tests/racefeed/__init__.py`
- Test: `tests/racefeed/test_models.py`

- [ ] **Step 1: Create empty package init files**

`core/racefeed/__init__.py`:
```python
"""core/racefeed — RaceFeed: AI-powered paddock feed. Isolated subsystem; the
only coupling to core.engine is the ingest boundary (see engine.py) and a
state_provider pull-callback. See docs/superpowers/specs/2026-07-20-racefeed-phase1-design.md."""
```

`tests/racefeed/__init__.py`: empty file (makes `tests/racefeed` a package so
`pytest`'s `testpaths = tests` in `pytest.ini` discovers it).

- [ ] **Step 2: Write the failing test**

`tests/racefeed/test_models.py`:
```python
import time

from core.racefeed.models import Candidate, Event, Post, Story


def test_event_construction():
    e = Event(
        event_code="PENA", session_type="race", driver="Norris", team="McLaren",
        vehicle_idx=4, is_player=False, importance=80, laps_remaining=20,
        description="5s penalty", extra={"lap": 12}, enqueued_at=123.0,
    )
    assert e.event_code == "PENA"
    assert e.is_player is False
    assert e.extra == {"lap": 12}


def test_event_from_engine_dict_fills_extra_from_leftover_keys():
    raw = {
        "event_code": "OVTK", "driver": "Piastri", "team": "McLaren",
        "vehicle_idx": 3, "importance": 70, "laps_remaining": 10,
        "description": "Piastri overtakes", "lap": 15, "target": "Hamilton",
    }
    e = Event.from_engine_dict(raw, session_type="race", is_player=True)
    assert e.session_type == "race"
    assert e.is_player is True
    assert e.extra == {"lap": 15, "target": "Hamilton"}
    assert e.enqueued_at > 0


def test_story_defaults():
    s = Story(id="pit_strategy|Norris", story_key=("pit_strategy", "Norris"),
               category="pit_strategy", session_type="race")
    assert s.stage == 0
    assert s.facts == {}
    assert s.history == []
    assert s.status == "developing"
    assert s.post_ids == []


def test_candidate_construction():
    c = Candidate(
        story_id="pit_strategy|Norris", story_key=("pit_strategy", "Norris"),
        category="pit_strategy", reporter_id="race_control", base_importance=70,
        priority="pit_stop", publish_after=(5.0, 10.0), expires_at=time.time() + 60,
        update_policy="supersede",
    )
    assert c.decision == ""


def test_post_construction():
    p = Post(
        id="abc123", session_id="20260720_120000", story_id="pit_strategy|Norris",
        reporter_id="race_control", category="pit_strategy", text="Norris pits.",
        created_at=100.0, published_at=105.0, driver="Norris", is_player_story=False,
    )
    assert p.text == "Norris pits."
```

- [ ] **Step 3: Run test to verify it fails**

Run: `py -3.12 -u -m pytest tests/racefeed/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.racefeed.models'`

- [ ] **Step 4: Write `core/racefeed/models.py`**

```python
"""core/racefeed/models.py — RaceFeed's own data model. Isolated from engine
internals: Event.from_engine_dict() is the ONLY place that reads engine-shaped
dicts; every other module in core.racefeed only ever sees these dataclasses."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

_EVENT_KNOWN_KEYS = {
    "event_code", "driver", "team", "vehicle_idx", "importance",
    "laps_remaining", "description",
}


@dataclass
class Event:
    event_code: str
    session_type: str
    driver: str | None
    team: str | None
    vehicle_idx: int | None
    is_player: bool
    importance: int
    laps_remaining: int | None
    description: str
    extra: dict
    enqueued_at: float

    @classmethod
    def from_engine_dict(cls, d: dict, session_type: str, is_player: bool) -> "Event":
        return cls(
            event_code=d.get("event_code", ""),
            session_type=session_type,
            driver=d.get("driver"),
            team=d.get("team"),
            vehicle_idx=d.get("vehicle_idx"),
            is_player=is_player,
            importance=int(d.get("importance", 50)),
            laps_remaining=d.get("laps_remaining"),
            description=d.get("description", d.get("event_code", "")),
            extra={k: v for k, v in d.items() if k not in _EVENT_KNOWN_KEYS},
            enqueued_at=d.get("enqueued_at", time.time()),
        )


@dataclass
class Story:
    id: str
    story_key: tuple
    category: str
    session_type: str
    stage: int = 0
    facts: dict = field(default_factory=dict)
    history: list = field(default_factory=list)
    created_at: float = 0.0
    last_update: float = 0.0
    last_publish: float | None = None
    status: str = "developing"          # "developing" | "published"
    post_ids: list = field(default_factory=list)


@dataclass
class Candidate:
    story_id: str
    story_key: tuple
    category: str
    reporter_id: str
    base_importance: int
    priority: str                        # "incident"|"pit_stop"|"statistics"|"analysis"|"default"
    publish_after: tuple                 # (min_s, max_s)
    expires_at: float
    update_policy: str                   # "supersede"|"append"|"ignore_if_pending"
    decision: str = ""                   # "new"|"update" — set by Editor.evaluate()


@dataclass
class Post:
    id: str
    session_id: str
    story_id: str
    reporter_id: str
    category: str
    text: str
    created_at: float
    published_at: float
    driver: str | None
    is_player_story: bool
```

- [ ] **Step 5: Run test to verify it passes**

Run: `py -3.12 -u -m pytest tests/racefeed/test_models.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Checkpoint** — Task 1 done, no git commit (see note above).

---

## Task 2: Additive AIProvider method for custom system prompts

**Why:** `AIProvider.generate(context, persona)` hardcodes
`commentator/personas.py::system_prompt(persona)` as the system message — it
falls back to the `"tv"` voice-commentary persona for any unrecognized string
(confirmed by reading `commentator/personas.py:116-119`), which has the wrong
tone, a `<=15-word` TTS contract, and a "may return ТИШИНА" convention. None of
that is right for RaceFeed's journalism posts. Rather than repurpose `.generate()`
(used live by voice commentary — do not touch its behavior), add a new,
purely-additive method.

**Files:**
- Modify: `yandex_ai/gpt.py`
- Modify: `commentator/ai_provider.py`
- Test: `tests/test_ai_provider.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ai_provider.py`:
```python
def test_generate_with_system_unavailable_without_client():
    ai = AIProvider(None)
    assert ai.generate_with_system("SYS", "USER") is None


def test_generate_with_system_delegates_to_gpt(monkeypatch):
    class FakeGPT:
        def __init__(self, *a, **k):
            pass
        def generate_raw(self, system, user):
            return f"raw:{system}:{user}"

    import commentator.ai_provider as mod
    monkeypatch.setattr(mod, "YandexGPT", FakeGPT)
    ai = AIProvider(object())
    assert ai.generate_with_system("SYS", "USER") == "raw:SYS:USER"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -u -m pytest tests/test_ai_provider.py -v`
Expected: FAIL — `AttributeError: 'AIProvider' object has no attribute 'generate_with_system'`

- [ ] **Step 3: Add `YandexGPT.generate_raw`**

In `yandex_ai/gpt.py`, add this method to the `YandexGPT` class, right after the
existing `generate` method (after the line `return _sanitize(text) if text else ""`
that ends `generate`, before the module-level `def _sanitize(...)`):

```python
    def generate_raw(self, system: str, user: str) -> str | None:
        """Like .generate(), but takes a caller-supplied system prompt instead of
        resolving one via commentator.personas.system_prompt(persona). Used by
        core.racefeed, whose reporters are not one of the four voice personas.
        Same swallow-exceptions-return-None contract as .generate()."""
        try:
            fut = self._client.submit(self.acomplete(system, user, max_tokens=200))
            text = fut.result(timeout=config.YANDEX_GPT_TOTAL_TIMEOUT + 1.0)
        except Exception as exc:  # noqa: BLE001 — сеть/HTTP -> caller drops the candidate
            _log.warning("YandexGPT generate_raw failed: %s", exc)
            return None
        return _sanitize(text) if text else ""
```

- [ ] **Step 4: Add `AIProvider.generate_with_system`**

In `commentator/ai_provider.py`, add this method to the `AIProvider` class, right
after the existing `generate` method:

```python
    def generate_with_system(self, system: str, user: str) -> str | None:
        """Like .generate(), but with a caller-supplied system prompt instead of a
        persona lookup. Used by core.racefeed (see core/racefeed/prompts.py for
        its reporter-specific system prompts)."""
        if self._gpt is None:
            return None
        return self._gpt.generate_raw(system, user)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -3.12 -u -m pytest tests/test_ai_provider.py -v`
Expected: PASS (all tests in the file, including the 2 new ones)

- [ ] **Step 6: Checkpoint** — Task 2 done.

---

## Task 3: `storage.py` — SQLite persistence

**Files:**
- Create: `core/racefeed/storage.py`
- Test: `tests/racefeed/test_storage.py`

- [ ] **Step 1: Write the failing test**

`tests/racefeed/test_storage.py`:
```python
from core.racefeed import storage
from core.racefeed.models import Post, Story


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -u -m pytest tests/racefeed/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.racefeed.storage'`

- [ ] **Step 3: Write `core/racefeed/storage.py`**

```python
"""core/racefeed/storage.py — SQLite persistence for RaceFeed posts and stories.
One file per race session (see core/racefeed/engine.py::RaceFeedEngine.reset()).
Short-lived connections per call — this is what makes it safe to call from both
the worker thread (writes) and the Bottle request thread (reads via ui_bridge)
without a shared connection or manual locking; at Phase 1 volumes (a few writes
per second at most) this is more than sufficient."""
from __future__ import annotations

import json
import sqlite3

from core.racefeed.models import Post, Story

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
    story_id TEXT,
    reporter_id TEXT,
    category TEXT,
    text TEXT,
    created_at REAL,
    published_at REAL,
    driver TEXT,
    is_player_story INTEGER
);
"""


def init_db(path: str) -> None:
    con = sqlite3.connect(path, timeout=5)
    try:
        con.executescript(_SCHEMA)
        con.commit()
    finally:
        con.close()


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
        con.execute(
            """INSERT INTO posts
               (id, story_id, reporter_id, category, text, created_at, published_at,
                driver, is_player_story)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (post.id, post.story_id, post.reporter_id, post.category, post.text,
             post.created_at, post.published_at, post.driver,
             int(post.is_player_story)),
        )
        con.commit()
    finally:
        con.close()


def get_posts(path: str, limit: int = 200) -> list[dict]:
    con = sqlite3.connect(path, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT * FROM posts ORDER BY published_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


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
            status=row["status"], post_ids=[],
        )
    finally:
        con.close()
```

**Note:** tests use `tmp_path` (a real file), not `sqlite3.connect(":memory:")` —
each `sqlite3.connect(":memory:")` call opens a *separate* in-memory database, so
the short-lived-connection-per-call pattern above would silently lose all data
between calls if tests used `:memory:`.

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -u -m pytest tests/racefeed/test_storage.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Checkpoint** — Task 3 done.

---

## Task 4: `editor.py` — StoryMemory + deterministic Editor

**Files:**
- Create: `core/racefeed/editor.py`
- Test: `tests/racefeed/test_editor.py`

- [ ] **Step 1: Write the failing test**

`tests/racefeed/test_editor.py`:
```python
import time

from core.racefeed.editor import Editor, PUBLISH_THRESHOLD, StoryMemory, facts_materially_changed
from core.racefeed.models import Candidate


def _candidate(story_id, story_key, base_importance):
    return Candidate(
        story_id=story_id, story_key=story_key, category="incident",
        reporter_id="race_control", base_importance=base_importance,
        priority="incident", publish_after=(2.0, 5.0),
        expires_at=time.time() + 60, update_policy="supersede",
    )


def test_story_memory_upsert_creates_then_updates_same_id():
    mem = StoryMemory()
    s1 = mem.upsert(("pit", "Norris"), "pit", "race", {"lap": 1})
    assert s1.id == "pit|Norris"
    assert s1.facts == {"lap": 1}

    s2 = mem.upsert(("pit", "Norris"), "pit", "race", {"lap": 2})
    assert s2 is s1
    assert s2.facts == {"lap": 2}
    assert mem.get("pit|Norris") is s1


def test_story_memory_mark_published_advances_stage_and_history():
    mem = StoryMemory()
    story = mem.upsert(("pit", "Norris"), "pit", "race", {"lap": 1})
    mem.mark_published(story, "post-1")

    assert story.stage == 1
    assert story.status == "published"
    assert story.history == [{"lap": 1}]
    assert story.post_ids == ["post-1"]
    assert story.last_publish is not None


def test_facts_materially_changed_numeric_noise_threshold():
    assert facts_materially_changed({"gap_ms": 1000.0}, {"gap_ms": 1100.0}) is False
    assert facts_materially_changed({"gap_ms": 1000.0}, {"gap_ms": 2500.0}) is True


def test_facts_materially_changed_non_numeric_any_change():
    assert facts_materially_changed({"driver": "Norris"}, {"driver": "Norris"}) is False
    assert facts_materially_changed({"driver": "Norris"}, {"driver": "Piastri"}) is True


def test_editor_new_story_above_threshold_is_new():
    mem = StoryMemory()
    story = mem.upsert(("pen", "Norris"), "pen", "race", {"importance": 90})
    candidate = _candidate(story.id, story.story_key, base_importance=PUBLISH_THRESHOLD + 1)

    assert Editor().evaluate(candidate, story) == "new"


def test_editor_new_story_below_threshold_is_suppressed():
    mem = StoryMemory()
    story = mem.upsert(("pen", "Norris"), "pen", "race", {"importance": 10})
    candidate = _candidate(story.id, story.story_key, base_importance=PUBLISH_THRESHOLD - 1)

    assert Editor().evaluate(candidate, story) == "suppress"


def test_editor_published_story_no_material_change_is_suppressed():
    mem = StoryMemory()
    story = mem.upsert(("gap", "player"), "gap_trend", "race", {"gap_ms": 1000.0})
    mem.mark_published(story, "post-1")
    # facts identical to what's already in history -> no material change
    candidate = _candidate(story.id, story.story_key, base_importance=90)

    assert Editor().evaluate(candidate, story) == "suppress"


def test_editor_published_story_material_change_is_update():
    mem = StoryMemory()
    story = mem.upsert(("gap", "player"), "gap_trend", "race", {"gap_ms": 1000.0})
    mem.mark_published(story, "post-1")
    story.facts = {"gap_ms": 4000.0}  # StoryBuilder would do this on the next tick
    candidate = _candidate(story.id, story.story_key, base_importance=90)

    assert Editor().evaluate(candidate, story) == "update"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -u -m pytest tests/racefeed/test_editor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.racefeed.editor'`

- [ ] **Step 3: Write `core/racefeed/editor.py`**

```python
"""core/racefeed/editor.py — deterministic editorial decisions. The LLM is NEVER
consulted here — see the design doc for why: this codebase already has a
documented bug class where letting an LLM judge "is this the same story as
before" caused repetitive spam (core/situation_dedup.py exists because of it)."""
from __future__ import annotations

import time

from core.racefeed.models import Candidate, Story

PUBLISH_THRESHOLD = 60  # tunable — see design doc's Editor algorithm section

_NUMERIC_NOISE_THRESHOLD = {
    "gap_ms": 1000.0,
    "gap_front_ms": 1000.0,
    "gap_behind_ms": 1000.0,
    "tyre_wear": 10.0,
    "fuel": 2.0,
    "ers_percent": 15.0,
}
_DEFAULT_NUMERIC_THRESHOLD = 0.0001  # any change counts for un-tuned numeric facts


def facts_materially_changed(old_facts: dict, new_facts: dict) -> bool:
    for key, new_val in new_facts.items():
        old_val = old_facts.get(key)
        if isinstance(new_val, (int, float)) and isinstance(old_val, (int, float)):
            threshold = _NUMERIC_NOISE_THRESHOLD.get(key, _DEFAULT_NUMERIC_THRESHOLD)
            if abs(new_val - old_val) >= threshold:
                return True
        elif new_val != old_val:
            return True
    return False


class StoryMemory:
    """In-memory registry of Story objects for the current session. NOT durable
    persistence — see storage.py, written only when a post actually publishes."""

    def __init__(self):
        self._stories: dict[str, Story] = {}

    def get(self, story_id: str) -> Story | None:
        return self._stories.get(story_id)

    def upsert(self, story_key: tuple, category: str, session_type: str,
               facts: dict) -> Story:
        story_id = "|".join(str(p) for p in story_key)
        now = time.time()
        story = self._stories.get(story_id)
        if story is None:
            story = Story(
                id=story_id, story_key=story_key, category=category,
                session_type=session_type, facts=dict(facts),
                created_at=now, last_update=now,
            )
            self._stories[story_id] = story
        else:
            story.facts = dict(facts)
            story.last_update = now
        return story

    def mark_published(self, story: Story, post_id: str) -> None:
        """Call only after a candidate for this story has actually been rendered
        and published — never speculatively. See engine.py::_publish_due()."""
        story.history.append(dict(story.facts))
        story.stage += 1
        story.status = "published"
        story.last_publish = time.time()
        story.post_ids.append(post_id)

    def clear(self) -> None:
        self._stories.clear()


class Editor:
    """Decides new/update/suppress for a Candidate given its Story's current
    state. Never mutates the Story — StoryMemory.mark_published() is the caller's
    job, and only after a successful render (see engine.py)."""

    def evaluate(self, candidate: Candidate, story: Story) -> str:
        if story.status == "developing":
            if candidate.base_importance >= PUBLISH_THRESHOLD:
                return "new"
            return "suppress"
        old_facts = story.history[-1] if story.history else {}
        if facts_materially_changed(old_facts, story.facts):
            return "update"
        return "suppress"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -u -m pytest tests/racefeed/test_editor.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Checkpoint** — Task 4 done.

---

## Task 5: `scheduler.py` — delay heap + update_policy

**Files:**
- Create: `core/racefeed/scheduler.py`
- Test: `tests/racefeed/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

`tests/racefeed/test_scheduler.py`:
```python
import time

from core.racefeed.models import Candidate
from core.racefeed.scheduler import PUBLISH_DELAY_S, Scheduler


def _candidate(story_id, update_policy, base_importance=1, priority="default",
                delay=(0.0, 0.0), expires_in=60.0):
    now = time.time()
    return Candidate(
        story_id=story_id, story_key=(story_id,), category="x",
        reporter_id="r", base_importance=base_importance, priority=priority,
        publish_after=delay, expires_at=now + expires_in,
        update_policy=update_policy,
    )


def test_not_due_before_publish_at():
    sched = Scheduler()
    now = time.time()
    sched.schedule(_candidate("s1", "supersede", delay=(1000.0, 1000.0)), now)
    assert sched.due(now) == []


def test_due_after_publish_at():
    sched = Scheduler()
    now = time.time()
    sched.schedule(_candidate("s1", "supersede", delay=(0.0, 0.0)), now)
    due = sched.due(now + 0.01)
    assert len(due) == 1
    assert due[0].story_id == "s1"


def test_supersede_cancels_pending_and_replaces():
    sched = Scheduler()
    now = time.time()
    sched.schedule(_candidate("s1", "supersede", base_importance=1, delay=(0.0, 0.0)), now)
    sched.schedule(_candidate("s1", "supersede", base_importance=2, delay=(0.0, 0.0)), now)

    due = sched.due(now + 0.01)
    assert len(due) == 1
    assert due[0].base_importance == 2


def test_ignore_if_pending_drops_the_new_one():
    sched = Scheduler()
    now = time.time()
    sched.schedule(_candidate("s1", "ignore_if_pending", base_importance=1, delay=(0.0, 0.0)), now)
    sched.schedule(_candidate("s1", "ignore_if_pending", base_importance=2, delay=(0.0, 0.0)), now)

    due = sched.due(now + 0.01)
    assert len(due) == 1
    assert due[0].base_importance == 1


def test_append_publishes_both():
    sched = Scheduler()
    now = time.time()
    sched.schedule(_candidate("s1", "append", base_importance=1, delay=(0.0, 0.0)), now)
    sched.schedule(_candidate("s1", "append", base_importance=2, delay=(0.0, 0.0)), now)

    due = sched.due(now + 0.01)
    assert sorted(c.base_importance for c in due) == [1, 2]


def test_expired_candidate_is_dropped():
    sched = Scheduler()
    now = time.time()
    sched.schedule(_candidate("s1", "supersede", delay=(0.0, 0.0), expires_in=-1.0), now)
    assert sched.due(now + 0.01) == []


def test_publish_delay_s_has_all_priority_buckets():
    for key in ("incident", "pit_stop", "statistics", "analysis", "default"):
        assert key in PUBLISH_DELAY_S
        lo, hi = PUBLISH_DELAY_S[key]
        assert 0 <= lo <= hi
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -u -m pytest tests/racefeed/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.racefeed.scheduler'`

- [ ] **Step 3: Write `core/racefeed/scheduler.py`**

```python
"""core/racefeed/scheduler.py — publish-time delay heap + update_policy
enforcement. Runs entirely inside RaceFeedEngine's single worker thread loop
(see engine.py) — not designed to be called from multiple threads concurrently."""
from __future__ import annotations

import heapq
import itertools
import random

from core.racefeed.models import Candidate

PUBLISH_DELAY_S: dict[str, tuple[float, float]] = {
    "incident":   (2.0, 5.0),
    "pit_stop":   (5.0, 10.0),
    "statistics": (15.0, 25.0),
    "analysis":   (25.0, 35.0),
    "default":    (5.0, 10.0),
}


class Scheduler:
    def __init__(self):
        self._heap: list[tuple[float, int, Candidate]] = []
        self._counter = itertools.count()
        self._pending: dict[str, tuple[float, int, Candidate]] = {}

    def schedule(self, candidate: Candidate, now: float) -> None:
        delay_min, delay_max = candidate.publish_after
        publish_at = now + random.uniform(delay_min, delay_max)
        pending = self._pending.get(candidate.story_id)

        if pending is not None:
            if candidate.update_policy == "ignore_if_pending":
                return
            if candidate.update_policy == "supersede":
                self._remove(pending)

        entry = (publish_at, next(self._counter), candidate)
        heapq.heappush(self._heap, entry)
        if candidate.update_policy == "append":
            self._pending.pop(candidate.story_id, None)
        else:
            self._pending[candidate.story_id] = entry

    def _remove(self, entry: tuple[float, int, Candidate]) -> None:
        try:
            self._heap.remove(entry)
            heapq.heapify(self._heap)
        except ValueError:
            pass

    def due(self, now: float) -> list[Candidate]:
        """Pop and return every candidate whose publish_at <= now, dropping any
        that expired while waiting."""
        result: list[Candidate] = []
        while self._heap and self._heap[0][0] <= now:
            _, _, candidate = heapq.heappop(self._heap)
            existing = self._pending.get(candidate.story_id)
            if existing is not None and existing[2] is candidate:
                del self._pending[candidate.story_id]
            if candidate.expires_at >= now:
                result.append(candidate)
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -u -m pytest tests/racefeed/test_scheduler.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Checkpoint** — Task 5 done.

---

## Task 6: `reporters.py` — Race Control, Spotter Analytics, Player's Garage

**Files:**
- Create: `core/racefeed/reporters.py`
- Test: `tests/racefeed/test_reporters.py`

- [ ] **Step 1: Write the failing test**

`tests/racefeed/test_reporters.py`:
```python
from core.racefeed.models import Story
from core.racefeed.reporters import (
    PlayersGarageReporter, RaceControlReporter, SpotterAnalyticsReporter,
)


def _story(category, facts=None):
    return Story(id=f"{category}|x", story_key=(category, "x"), category=category,
                 session_type="race", facts=facts or {})


def test_race_control_covers_incident_categories_only():
    r = RaceControlReporter()
    assert r.covers(_story("penalty")) is True
    assert r.covers(_story("safety_car")) is True
    assert r.covers(_story("gap_trend")) is False


def test_race_control_propose_returns_none_when_not_covered():
    assert RaceControlReporter().propose(_story("gap_trend")) is None


def test_race_control_propose_uses_facts_importance():
    story = _story("penalty", {"importance": 85})
    candidate = RaceControlReporter().propose(story)
    assert candidate is not None
    assert candidate.reporter_id == "race_control"
    assert candidate.base_importance == 85
    assert candidate.priority == "incident"
    assert candidate.update_policy == "supersede"


def test_spotter_analytics_covers_statistics_categories():
    r = SpotterAnalyticsReporter()
    assert r.covers(_story("gap_trend")) is True
    assert r.covers(_story("tyre_status")) is True
    assert r.covers(_story("penalty")) is False


def test_spotter_analytics_propose_priority_is_statistics():
    candidate = SpotterAnalyticsReporter().propose(_story("fuel_status"))
    assert candidate is not None
    assert candidate.priority == "statistics"
    assert candidate.update_policy == "ignore_if_pending"


def test_players_garage_requires_is_player_fact():
    r = PlayersGarageReporter()
    covered_but_not_player = _story("player_pit_stop", {"is_player": False})
    covered_and_player = _story("player_pit_stop", {"is_player": True})
    assert r.covers(covered_but_not_player) is False
    assert r.covers(covered_and_player) is True
    assert r.propose(covered_but_not_player) is None


def test_players_garage_propose_pit_stop_priority():
    story = _story("player_pit_stop", {"is_player": True, "importance": 80})
    candidate = PlayersGarageReporter().propose(story)
    assert candidate is not None
    assert candidate.priority == "pit_stop"
    assert candidate.update_policy == "supersede"
    assert candidate.base_importance == 80
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -u -m pytest tests/racefeed/test_reporters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.racefeed.reporters'`

- [ ] **Step 3: Write `core/racefeed/reporters.py`**

```python
"""core/racefeed/reporters.py — reporter personalities: a coverage filter plus
propose(). Deliberately cheap and LLM-free; only Story objects (never raw
Events) reach a reporter — see StoryBuilder in engine.py. Actual text generation
happens later, in generators.py, only for candidates the Editor has approved
(see design doc for why LLM calls are deferred to publish time)."""
from __future__ import annotations

import time

from core.racefeed.models import Candidate, Story
from core.racefeed.scheduler import PUBLISH_DELAY_S

_EXPIRY_S = 60.0

RACE_CONTROL_CATEGORIES = {
    "penalty":     ("incident", "supersede"),
    "retirement":  ("incident", "supersede"),
    "incident":    ("incident", "supersede"),
    "safety_car":  ("incident", "append"),
    "flag":        ("incident", "append"),
}

SPOTTER_ANALYTICS_CATEGORIES = {
    "gap_trend":   ("statistics", "ignore_if_pending"),
    "tyre_status": ("statistics", "ignore_if_pending"),
    "fuel_status": ("statistics", "ignore_if_pending"),
    "ers_status":  ("statistics", "ignore_if_pending"),
}

PLAYERS_GARAGE_CATEGORIES = {
    "player_pit_stop":     ("pit_stop", "supersede"),
    "player_overtake":     ("incident", "supersede"),
    "player_fastest_lap":  ("incident", "supersede"),
    "player_progression":  ("analysis", "ignore_if_pending"),
}


def _make_candidate(story: Story, reporter_id: str, priority: str,
                     update_policy: str, base_importance: int) -> Candidate:
    now = time.time()
    return Candidate(
        story_id=story.id, story_key=story.story_key, category=story.category,
        reporter_id=reporter_id, base_importance=base_importance, priority=priority,
        publish_after=PUBLISH_DELAY_S.get(priority, PUBLISH_DELAY_S["default"]),
        expires_at=now + _EXPIRY_S, update_policy=update_policy,
    )


class RaceControlReporter:
    id = "race_control"

    def covers(self, story: Story) -> bool:
        return story.category in RACE_CONTROL_CATEGORIES

    def propose(self, story: Story) -> Candidate | None:
        if not self.covers(story):
            return None
        priority, update_policy = RACE_CONTROL_CATEGORIES[story.category]
        base_importance = int(story.facts.get("importance", 70))
        return _make_candidate(story, self.id, priority, update_policy, base_importance)


class SpotterAnalyticsReporter:
    id = "spotter_analytics"

    def covers(self, story: Story) -> bool:
        return story.category in SPOTTER_ANALYTICS_CATEGORIES

    def propose(self, story: Story) -> Candidate | None:
        if not self.covers(story):
            return None
        priority, update_policy = SPOTTER_ANALYTICS_CATEGORIES[story.category]
        base_importance = int(story.facts.get("importance", 65))
        return _make_candidate(story, self.id, priority, update_policy, base_importance)


class PlayersGarageReporter:
    id = "players_garage"

    def covers(self, story: Story) -> bool:
        return (story.category in PLAYERS_GARAGE_CATEGORIES
                and bool(story.facts.get("is_player", False)))

    def propose(self, story: Story) -> Candidate | None:
        if not self.covers(story):
            return None
        priority, update_policy = PLAYERS_GARAGE_CATEGORIES[story.category]
        base_importance = int(story.facts.get("importance", 75))
        return _make_candidate(story, self.id, priority, update_policy, base_importance)


REPORTERS = [RaceControlReporter(), SpotterAnalyticsReporter(), PlayersGarageReporter()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -u -m pytest tests/racefeed/test_reporters.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Checkpoint** — Task 6 done.

---

## Task 7: `prompts.py` — reporter system prompts + fact-only context

**Files:**
- Create: `core/racefeed/prompts.py`
- Test: `tests/racefeed/test_prompts.py`

- [ ] **Step 1: Write the failing test**

`tests/racefeed/test_prompts.py`:
```python
from core.racefeed.models import Candidate, Story
from core.racefeed.prompts import SYSTEM_PROMPTS, build_context
from core.racefeed.reporters import REPORTERS


def test_every_reporter_has_a_system_prompt():
    for reporter in REPORTERS:
        assert reporter.id in SYSTEM_PROMPTS
        assert len(SYSTEM_PROMPTS[reporter.id]) > 20


def test_build_context_includes_category_stage_and_facts():
    story = Story(id="s1", story_key=("pit", "Norris"), category="pit_strategy",
                   session_type="race", stage=0, facts={"lap": 12, "driver": "Norris"})
    candidate = Candidate(
        story_id="s1", story_key=("pit", "Norris"), category="pit_strategy",
        reporter_id="race_control", base_importance=70, priority="pit_stop",
        publish_after=(5.0, 10.0), expires_at=0.0, update_policy="supersede",
    )
    ctx = build_context(story, candidate)
    assert "pit_strategy" in ctx
    assert "Norris" in ctx
    assert "12" in ctx


def test_build_context_includes_previous_facts_when_story_has_history():
    story = Story(id="s1", story_key=("weather",), category="weather",
                   session_type="race", stage=1,
                   facts={"status": "rain_started"},
                   history=[{"status": "rain_expected"}])
    candidate = Candidate(
        story_id="s1", story_key=("weather",), category="weather",
        reporter_id="race_control", base_importance=70, priority="analysis",
        publish_after=(25.0, 35.0), expires_at=0.0, update_policy="append",
    )
    ctx = build_context(story, candidate)
    assert "rain_expected" in ctx
    assert "rain_started" in ctx
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -u -m pytest tests/racefeed/test_prompts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.racefeed.prompts'`

- [ ] **Step 3: Write `core/racefeed/prompts.py`**

```python
"""core/racefeed/prompts.py — per-reporter system prompts + fact-only context
builder. The LLM never receives raw telemetry — only this structured,
human-readable fact summary (see design doc's AI Rules section)."""
from __future__ import annotations

from core.racefeed.models import Candidate, Story

SYSTEM_PROMPTS: dict[str, str] = {
    "race_control": (
        "Ты — Race Control, официальный источник новостей Гран-при. Пиши строго "
        "по фактам, без юмора и предположений. Один короткий абзац (1-2 "
        "предложения), по-русски, в духе официального пресс-релиза FIA."
    ),
    "spotter_analytics": (
        "Ты — аналитик Spotter Analytics. Пишешь короткие заметки на основе цифр: "
        "разрывы, темп, состояние шин/топлива/ERS, аккуратные прогнозы. Без "
        "лишних эмоций, но живым языком. Один короткий абзац, по-русски."
    ),
    "players_garage": (
        "Ты — журналист боксов команды игрока. Освещаешь действия игрока от "
        "третьего лица, как настоящий журналист, а не инженер по радио — не "
        "повторяй фразы инженера дословно. Один короткий абзац, по-русски."
    ),
}


def build_context(story: Story, candidate: Candidate) -> str:
    lines = [f"Категория: {story.category}", f"Стадия истории: {story.stage}"]
    if story.history:
        lines.append(f"Ранее сообщалось: {story.history[-1]}")
    lines.append(f"Текущие факты: {story.facts}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -u -m pytest tests/racefeed/test_prompts.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Checkpoint** — Task 7 done.

---

## Task 8: `generators.py` — the only place RaceFeed calls the LLM

**Files:**
- Create: `core/racefeed/generators.py`
- Test: `tests/racefeed/test_generators.py`

- [ ] **Step 1: Write the failing test**

`tests/racefeed/test_generators.py`:
```python
from core.racefeed.generators import render
from core.racefeed.models import Candidate, Story


def _story_and_candidate():
    story = Story(id="s1", story_key=("penalty", "Norris"), category="penalty",
                   session_type="race", facts={"driver": "Norris", "seconds": 5})
    candidate = Candidate(
        story_id="s1", story_key=("penalty", "Norris"), category="penalty",
        reporter_id="race_control", base_importance=80, priority="incident",
        publish_after=(2.0, 5.0), expires_at=0.0, update_policy="supersede",
    )
    return story, candidate


class _FakeAI:
    def __init__(self, available=True, text="Norris receives a 5s penalty."):
        self.available = available
        self._text = text
        self.calls = []

    def generate_with_system(self, system, user):
        self.calls.append((system, user))
        return self._text


def test_render_returns_none_when_ai_unavailable():
    story, candidate = _story_and_candidate()
    ai = _FakeAI(available=False)
    assert render(candidate, story, ai) is None
    assert ai.calls == []


def test_render_returns_none_when_llm_returns_empty():
    story, candidate = _story_and_candidate()
    ai = _FakeAI(text="")
    assert render(candidate, story, ai) is None


def test_render_returns_text_and_uses_reporter_system_prompt():
    story, candidate = _story_and_candidate()
    ai = _FakeAI(text="Norris receives a 5s penalty.")
    result = render(candidate, story, ai)
    assert result == "Norris receives a 5s penalty."
    assert len(ai.calls) == 1
    system, user = ai.calls[0]
    assert "Race Control" in system
    assert "penalty" in user
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -u -m pytest tests/racefeed/test_generators.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.racefeed.generators'`

- [ ] **Step 3: Write `core/racefeed/generators.py`**

```python
"""core/racefeed/generators.py — the only place RaceFeed calls the LLM, and only
for candidates the Editor has already approved for publication (see design doc:
this ordering means a cancelled/superseded candidate never pays for an LLM call)."""
from __future__ import annotations

from typing import Protocol

from core.racefeed.models import Candidate, Story
from core.racefeed.prompts import SYSTEM_PROMPTS, build_context


class _AIProviderLike(Protocol):
    available: bool
    def generate_with_system(self, system: str, user: str) -> str | None: ...


def render(candidate: Candidate, story: Story, ai_provider: _AIProviderLike) -> str | None:
    """Returns rendered post text, or None if the LLM is unavailable or fails —
    the caller (engine.py) drops the candidate silently on None (see design
    doc's Error handling: RaceFeed is not safety-critical, unlike voice)."""
    if not ai_provider.available:
        return None
    system_prompt = SYSTEM_PROMPTS.get(candidate.reporter_id, "")
    context = build_context(story, candidate)
    text = ai_provider.generate_with_system(system_prompt, context)
    return text or None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -u -m pytest tests/racefeed/test_generators.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Checkpoint** — Task 8 done.

---

## Task 9: `engine.py` — StoryBuilder

**Files:**
- Create: `core/racefeed/engine.py` (StoryBuilder only in this task; RaceFeedEngine in Task 10)
- Test: `tests/racefeed/test_story_builder.py`

- [ ] **Step 1: Write the failing test**

`tests/racefeed/test_story_builder.py`:
```python
from core.racefeed.editor import StoryMemory
from core.racefeed.engine import StoryBuilder
from core.racefeed.models import Event


def _event(event_code, driver="Norris", vehicle_idx=4, is_player=False, importance=80):
    return Event(
        event_code=event_code, session_type="race", driver=driver, team="McLaren",
        vehicle_idx=vehicle_idx, is_player=is_player, importance=importance,
        laps_remaining=20, description=f"{event_code} for {driver}",
        extra={"lap": 12}, enqueued_at=100.0,
    )


def test_from_event_maps_race_control_codes():
    builder = StoryBuilder(StoryMemory())
    story = builder.from_event(_event("PENA"))
    assert story is not None
    assert story.category == "penalty"
    assert story.story_key == ("penalty", "Norris")
    assert story.facts["importance"] == 80
    assert story.facts["lap"] == 12


def test_from_event_returns_none_for_unrecognized_non_player_code():
    builder = StoryBuilder(StoryMemory())
    assert builder.from_event(_event("UNKNOWNCODE")) is None


def test_from_event_maps_player_only_codes_when_is_player():
    builder = StoryBuilder(StoryMemory())
    story = builder.from_event(_event("PIT", is_player=True))
    assert story is not None
    assert story.category == "player_pit_stop"
    assert story.facts["is_player"] is True


def test_from_event_ignores_player_only_codes_when_not_player():
    builder = StoryBuilder(StoryMemory())
    assert builder.from_event(_event("PIT", is_player=False)) is None


def test_from_event_reuses_existing_story_for_same_key():
    memory = StoryMemory()
    builder = StoryBuilder(memory)
    s1 = builder.from_event(_event("PENA"))
    s2 = builder.from_event(_event("PENA"))
    assert s1 is s2


def test_from_tick_builds_gap_and_tyre_and_fuel_and_ers_stories():
    builder = StoryBuilder(StoryMemory())
    snapshot = {
        "gap_front_ms": 1200, "gap_behind_ms": 3400,
        "player_tyre_wear": 55.0, "player_tyre_age": 12, "player_tyre_compound": "M",
        "player_fuel": 22.5,
        "player_ers_percent": 40.0,
    }
    stories = builder.from_tick(snapshot, "race")
    categories = {s.category for s in stories}
    assert categories == {"gap_trend", "tyre_status", "fuel_status", "ers_status"}


def test_from_tick_skips_missing_fields():
    builder = StoryBuilder(StoryMemory())
    stories = builder.from_tick({"player_fuel": 10.0}, "race")
    categories = {s.category for s in stories}
    assert categories == {"fuel_status"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -u -m pytest tests/racefeed/test_story_builder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.racefeed.engine'`

- [ ] **Step 3: Write `core/racefeed/engine.py` (StoryBuilder section)**

```python
"""core/racefeed/engine.py — RaceFeedEngine owns the ingest queue, the worker
thread, and StoryBuilder (turns raw Events/state snapshots into Story upserts).
Fully isolated from core.engine: the only inputs are Event objects passed to
ingest() and a state_provider() callback given at construction — see design doc."""
from __future__ import annotations

from core.racefeed.editor import StoryMemory
from core.racefeed.models import Event, Story

_RACE_CONTROL_CODES: dict[str, str] = {
    "PENA": "penalty", "PENS": "penalty",
    "RTMT": "retirement",
    "COLL": "incident", "SPIN": "incident", "OFFT": "incident",
    "SCAR": "safety_car", "VSCA": "safety_car",
    "CHQF": "flag", "SSTA": "flag", "SEND": "flag", "LGOT": "flag",
}

_PLAYER_ONLY_CODES: dict[str, str] = {
    "PIT": "player_pit_stop", "PITS": "player_pit_stop",
    "OVTK": "player_overtake", "FTLP": "player_fastest_lap",
}


class StoryBuilder:
    """Turns raw Events (and periodic state snapshots) into Story upserts in a
    shared StoryMemory. Reporters never see raw Events — only the Story objects
    this produces (see reporters.py)."""

    def __init__(self, story_memory: StoryMemory):
        self._memory = story_memory

    def from_event(self, event: Event) -> Story | None:
        category = _RACE_CONTROL_CODES.get(event.event_code)
        if category is None and event.is_player:
            category = _PLAYER_ONLY_CODES.get(event.event_code)
        if category is None:
            return None

        story_key = (category, event.driver or event.vehicle_idx)
        facts = {
            "importance": event.importance,
            "driver": event.driver,
            "team": event.team,
            "description": event.description,
            "is_player": event.is_player,
            "lap": event.extra.get("lap"),
        }
        return self._memory.upsert(story_key, category, event.session_type, facts)

    def from_tick(self, snapshot: dict, session_type: str) -> list[Story]:
        stories: list[Story] = []

        if snapshot.get("gap_front_ms") is not None or snapshot.get("gap_behind_ms") is not None:
            stories.append(self._memory.upsert(
                ("gap_trend", "player"), "gap_trend", session_type,
                {"importance": 65, "is_player": True,
                 "gap_front_ms": snapshot.get("gap_front_ms"),
                 "gap_behind_ms": snapshot.get("gap_behind_ms")},
            ))
        if snapshot.get("player_tyre_wear") is not None:
            stories.append(self._memory.upsert(
                ("tyre_status", "player"), "tyre_status", session_type,
                {"importance": 60, "is_player": True,
                 "tyre_wear": snapshot.get("player_tyre_wear"),
                 "tyre_age": snapshot.get("player_tyre_age"),
                 "tyre_compound": snapshot.get("player_tyre_compound")},
            ))
        if snapshot.get("player_fuel") is not None:
            stories.append(self._memory.upsert(
                ("fuel_status", "player"), "fuel_status", session_type,
                {"importance": 55, "is_player": True, "fuel": snapshot.get("player_fuel")},
            ))
        if snapshot.get("player_ers_percent") is not None:
            stories.append(self._memory.upsert(
                ("ers_status", "player"), "ers_status", session_type,
                {"importance": 55, "is_player": True,
                 "ers_percent": snapshot.get("player_ers_percent")},
            ))
        return stories
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -u -m pytest tests/racefeed/test_story_builder.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Checkpoint** — Task 9 done.

---

## Task 10: `engine.py` — RaceFeedEngine (worker thread, start/stop/reset/ingest)

**Files:**
- Modify: `core/racefeed/engine.py` (append `RaceFeedEngine` below `StoryBuilder`)
- Test: `tests/racefeed/test_race_feed_engine.py`

- [ ] **Step 1: Write the failing tests**

`tests/racefeed/test_race_feed_engine.py`:
```python
import time

from core.racefeed.engine import RaceFeedEngine


class _FakeAI:
    available = True

    def generate_with_system(self, system, user):
        return f"post about {user[:20]}"


def _snapshot():
    return {"session_type": "race"}


def test_reset_creates_db_and_clears_memory(tmp_path):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                         data_dir=str(tmp_path))
    rf.reset()
    assert rf.current_db_path() is not None
    assert rf.current_db_path().endswith(".sqlite3")


def test_ingest_and_drain_produces_a_published_post(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                         data_dir=str(tmp_path))
    rf.reset()

    from core.racefeed.models import Event
    event = Event(
        event_code="PENA", session_type="race", driver="Norris", team="McLaren",
        vehicle_idx=4, is_player=False, importance=90, laps_remaining=20,
        description="5s penalty", extra={"lap": 12}, enqueued_at=time.time(),
    )
    rf.ingest(event)
    rf._drain_queue()

    fake_now = [time.time() + 1000]  # force everything past its publish_after delay
    import core.racefeed.engine as engine_mod
    monkeypatch.setattr(engine_mod.time, "time", lambda: fake_now[0])
    rf._publish_due()

    from core.racefeed import storage
    posts = storage.get_posts(rf.current_db_path())
    assert len(posts) == 1
    assert posts[0]["driver"] == "Norris"
    assert "post about" in posts[0]["text"]


def test_low_importance_event_is_suppressed_not_published(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                         data_dir=str(tmp_path))
    rf.reset()

    from core.racefeed.models import Event
    event = Event(
        event_code="PENA", session_type="race", driver="Norris", team="McLaren",
        vehicle_idx=4, is_player=False, importance=1, laps_remaining=20,
        description="tiny", extra={}, enqueued_at=time.time(),
    )
    rf.ingest(event)
    rf._drain_queue()

    fake_now = [time.time() + 1000]
    import core.racefeed.engine as engine_mod
    monkeypatch.setattr(engine_mod.time, "time", lambda: fake_now[0])
    rf._publish_due()

    from core.racefeed import storage
    assert storage.get_posts(rf.current_db_path()) == []


def test_start_and_stop_manage_a_real_thread(tmp_path):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                         data_dir=str(tmp_path))
    rf.start()
    assert rf._thread is not None
    assert rf._thread.is_alive()
    rf.stop()
    assert rf._thread is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -u -m pytest tests/racefeed/test_race_feed_engine.py -v`
Expected: FAIL with `ImportError: cannot import name 'RaceFeedEngine' from 'core.racefeed.engine'`

- [ ] **Step 3: Append `RaceFeedEngine` to `core/racefeed/engine.py`**

Add these imports at the top of `core/racefeed/engine.py` (alongside the existing
`from core.racefeed.editor import StoryMemory` / `from core.racefeed.models import
Event, Story` lines from Task 9):

```python
import logging
import queue
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from core.racefeed.editor import Editor
from core.racefeed.generators import render
from core.racefeed.models import Post
from core.racefeed.reporters import REPORTERS
from core.racefeed.scheduler import Scheduler
from core.racefeed import storage

_log = logging.getLogger(__name__)

_TICK_INTERVAL_S = 20.0
_WORKER_SLEEP_S = 0.5
_MAX_QUEUE = 200
```

Append this class at the end of the file, after `StoryBuilder`:

```python
class RaceFeedEngine:
    """Owns the ingest queue and the single worker thread that runs the whole
    pipeline (StoryBuilder -> Reporter -> Editor -> Scheduler -> Generator ->
    storage). Constructing an instance does no work — start() spins up the
    thread, stop() tears it down. See core/engine.py's apply_settings() for the
    hot enable/disable wiring that owns this lifecycle."""

    def __init__(self, ai_provider, state_provider: Callable[[], dict],
                 data_dir: str | None = None):
        self._ai = ai_provider
        self._state_provider = state_provider
        self._data_dir = Path(data_dir) if data_dir else _default_data_dir()
        self._queue: "queue.Queue" = queue.Queue(maxsize=_MAX_QUEUE)
        self._story_memory = StoryMemory()
        self._editor = Editor()
        self._scheduler = Scheduler()
        self._builder = StoryBuilder(self._story_memory)
        self._db_path: str | None = None
        self._session_id: str | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_tick = 0.0

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="race-feed")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None

    def reset(self) -> None:
        """Starts a new session: fresh SQLite file, cleared Story Memory. Call on
        SSTA (see core/engine.py's SSTA handling)."""
        self._session_id = time.strftime("%Y%m%d_%H%M%S")
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = str(self._data_dir / f"{self._session_id}.sqlite3")
        storage.init_db(self._db_path)
        self._story_memory.clear()

    def ingest(self, event) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            _log.debug("RaceFeed ingest queue full, dropping event %s", event.event_code)

    def current_db_path(self) -> str | None:
        return self._db_path

    def _run(self) -> None:
        if self._db_path is None:
            self.reset()
        while not self._stop_event.is_set():
            self._drain_queue()
            self._maybe_tick()
            self._publish_due()
            time.sleep(_WORKER_SLEEP_S)

    def _drain_queue(self) -> None:
        while True:
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                return
            story = self._builder.from_event(event)
            if story is None:
                continue
            self._propose_and_schedule(story)

    def _maybe_tick(self) -> None:
        now = time.time()
        if now - self._last_tick < _TICK_INTERVAL_S:
            return
        self._last_tick = now
        snapshot = self._state_provider()
        session_type = snapshot.get("session_type", "unknown")
        if session_type != "race":
            return
        for story in self._builder.from_tick(snapshot, session_type):
            self._propose_and_schedule(story)

    def _propose_and_schedule(self, story) -> None:
        for reporter in REPORTERS:
            candidate = reporter.propose(story)
            if candidate is None:
                continue
            decision = self._editor.evaluate(candidate, story)
            if decision == "suppress":
                continue
            candidate.decision = decision
            self._scheduler.schedule(candidate, time.time())

    def _publish_due(self) -> None:
        if self._db_path is None:
            return
        for candidate in self._scheduler.due(time.time()):
            story = self._story_memory.get(candidate.story_id)
            if story is None:
                continue
            text = render(candidate, story, self._ai)
            if not text:
                continue
            post = Post(
                id=uuid.uuid4().hex, session_id=self._session_id or "unknown",
                story_id=story.id, reporter_id=candidate.reporter_id,
                category=candidate.category, text=text,
                created_at=story.last_update, published_at=time.time(),
                driver=story.facts.get("driver"),
                is_player_story=bool(story.facts.get("is_player", False)),
            )
            self._story_memory.mark_published(story, post.id)
            try:
                storage.upsert_story(self._db_path, story)
                storage.save_post(self._db_path, post)
            except Exception:
                _log.warning("RaceFeed storage write failed", exc_info=True)


def _default_data_dir() -> Path:
    import config
    return Path(config.DATA_DIR) / "racefeed"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -u -m pytest tests/racefeed/test_race_feed_engine.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the entire `core/racefeed` test suite together**

Run: `py -3.12 -u -m pytest tests/racefeed -v`
Expected: PASS (all tests from Tasks 1, 3-10 — Task 2 lives in `tests/test_ai_provider.py`)

- [ ] **Step 6: Checkpoint** — Task 10 done.

---

## Task 11: Integration test — the anti-repetition guarantee, end to end

**Files:**
- Test: `tests/racefeed/test_pipeline_integration.py`

This is the test that proves the spec's core promise: "the same information must
never be published twice," across a full synthetic race, through the real
pipeline (no mocked editor/scheduler — only the LLM is faked).

- [ ] **Step 1: Write the test**

`tests/racefeed/test_pipeline_integration.py`:
```python
import time

from core.racefeed.engine import RaceFeedEngine
from core.racefeed.models import Event
from core.racefeed import storage


class _FakeAI:
    available = True

    def generate_with_system(self, system, user):
        return f"Repored: {user[:40]}"


def _event(event_code, driver, importance, lap, is_player=False, vehicle_idx=1):
    return Event(
        event_code=event_code, session_type="race", driver=driver, team="Team",
        vehicle_idx=vehicle_idx, is_player=is_player, importance=importance,
        laps_remaining=50 - lap, description=f"{event_code} {driver} lap {lap}",
        extra={"lap": lap}, enqueued_at=time.time(),
    )


def _make_synthetic_race():
    """~90 events across a 50-lap synthetic race: a realistic mix of high-
    importance one-off incidents/penalties (should each become exactly one
    'new' post) and repeated identical-fact PENA events for the SAME driver
    (should collapse to at most one post per story, proving anti-repetition)."""
    events = []
    drivers = ["Norris", "Piastri", "Leclerc", "Hamilton", "Verstappen", "Russell"]

    # 6 distinct incidents/penalties, one per driver -> should each yield >=1 post
    for i, driver in enumerate(drivers):
        events.append(_event("PENA", driver, importance=85, lap=5 + i, vehicle_idx=i))

    # Same PENA fact repeated 10x for Norris with IDENTICAL facts (importance/lap
    # constant) -> StoryBuilder upserts the same story repeatedly, but since
    # facts never change after the first publish, Editor must suppress all
    # but the first.
    for _ in range(10):
        events.append(_event("PENA", "Norris", importance=85, lap=5, vehicle_idx=0))

    # 70 low-importance filler events (below PUBLISH_THRESHOLD) -> must never publish
    for i in range(70):
        events.append(_event("SPIN", f"Filler{i % 6}", importance=5, lap=i % 50,
                              vehicle_idx=i % 6))

    return events  # 6 + 10 + 70 = 86 events


def test_full_pipeline_respects_anti_repetition(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=lambda: {"session_type": "race"},
                         data_dir=str(tmp_path))
    rf.reset()

    for event in _make_synthetic_race():
        rf.ingest(event)
    rf._drain_queue()

    fake_now = [time.time() + 1000]  # force every scheduled candidate past its delay
    import core.racefeed.engine as engine_mod
    monkeypatch.setattr(engine_mod.time, "time", lambda: fake_now[0])
    rf._publish_due()

    posts = storage.get_posts(rf.current_db_path(), limit=1000)

    # No two posts share (story_id, and thus no duplicate coverage of the same
    # fact set) — the SPIN filler events never appear, and the 10x-repeated
    # Norris PENA collapses to exactly one post for that story.
    story_ids = [p["story_id"] for p in posts]
    assert len(story_ids) == len(set(story_ids)), "duplicate story_id published twice"

    norris_posts = [p for p in posts if p["driver"] == "Norris"]
    assert len(norris_posts) == 1, "repeated identical PENA facts should collapse to 1 post"

    categories = {p["category"] for p in posts}
    assert "incident" not in categories or all(
        p["driver"] != f"Filler{i}" for p in posts for i in range(6)
    )

    # 6 distinct high-importance incidents in, at most 6 posts out (one per
    # driver's first PENA) -- proves the "100 events -> a much smaller set of
    # posts" curation, not a 1:1 passthrough.
    assert 1 <= len(posts) <= 6
```

- [ ] **Step 2: Run the test**

Run: `py -3.12 -u -m pytest tests/racefeed/test_pipeline_integration.py -v`
Expected: PASS. If it fails, the most likely causes are: (a) `PUBLISH_THRESHOLD`
in `editor.py` needs adjusting relative to the synthetic fixture's importance
values (85 vs 60 threshold should clear it — check first), or (b) the
`update_policy="supersede"` re-scheduling in `scheduler.py` isn't cancelling a
still-pending duplicate before `_publish_due()` runs. Debug by printing
`len(posts)` and `[p['category'] for p in posts]` before the asserts.

- [ ] **Step 3: Checkpoint** — Task 11 done.

---

## Task 12: `ui_bridge.py` — read API for web_server.py

**Files:**
- Create: `core/racefeed/ui_bridge.py`
- Test: `tests/racefeed/test_ui_bridge.py`

- [ ] **Step 1: Write the failing test**

`tests/racefeed/test_ui_bridge.py`:
```python
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
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=lambda: {},
                         data_dir=str(tmp_path))
    rf.reset()
    result = ui_bridge.get_posts(rf)
    assert result["enabled"] is True
    assert result["posts"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -u -m pytest tests/racefeed/test_ui_bridge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.racefeed.ui_bridge'`

- [ ] **Step 3: Write `core/racefeed/ui_bridge.py`**

```python
"""core/racefeed/ui_bridge.py — read-only API consumed by web_server.py. Never
imports core.engine; takes a RaceFeedEngine instance (or None, when
racefeed_enabled is off) and returns JSON-serializable dicts."""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.racefeed import storage

if TYPE_CHECKING:
    from core.racefeed.engine import RaceFeedEngine


def get_posts(race_feed: "RaceFeedEngine | None", limit: int = 200) -> dict:
    if race_feed is None:
        return {"enabled": False, "posts": []}
    db_path = race_feed.current_db_path()
    if db_path is None:
        return {"enabled": True, "posts": []}
    try:
        rows = storage.get_posts(db_path, limit=limit)
    except Exception:
        return {"enabled": True, "posts": []}
    return {"enabled": True, "posts": rows}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -u -m pytest tests/racefeed/test_ui_bridge.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Checkpoint** — Task 12 done.

---

## Task 13: `settings.py` — `racefeed_enabled` default

**Files:**
- Modify: `core/settings.py`
- Test: `tests/test_settings.py` (check this file's exact name via `ls tests/test_settings*.py`
  first — if it doesn't exist, add the test to a new `tests/test_settings_racefeed.py`)

- [ ] **Step 1: Write the failing test**

If `tests/test_settings.py` exists, append this test to it; otherwise create
`tests/test_settings_racefeed.py`:
```python
from core.settings import DEFAULTS


def test_racefeed_enabled_defaults_to_false():
    assert DEFAULTS["racefeed_enabled"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -u -m pytest tests/test_settings_racefeed.py -v` (or the existing
file's path if you appended there)
Expected: FAIL with `KeyError: 'racefeed_enabled'`

- [ ] **Step 3: Add the default**

In `core/settings.py`, add this line to the `DEFAULTS` dict, right after the
`"telemetry_source": "f1",` line (the last entry):
```python
    # RaceFeed: AI paddock feed (core/racefeed/). Off by default — it's an AI
    # content-generation subsystem (LLM calls, background worker thread), not a
    # telemetry feature; see docs/superpowers/specs/2026-07-20-racefeed-phase1-design.md.
    "racefeed_enabled":         False,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -u -m pytest tests/test_settings_racefeed.py -v`
Expected: PASS

- [ ] **Step 5: Checkpoint** — Task 13 done.

---

## Task 14: `core/engine.py` wiring

**Files:**
- Modify: `core/engine.py`
- Test: `tests/test_engine_racefeed.py`

This task wires `RaceFeedEngine` into `F1Engine` at 6 precise points. Each step
below cites the exact anchor text to locate the insertion point.

- [ ] **Step 1: Write the failing tests**

`tests/test_engine_racefeed.py`:
```python
import core.engine as eng_mod
from core.engine import F1Engine


def test_race_feed_starts_disabled_by_default(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    assert e._race_feed is None


def test_apply_settings_racefeed_enabled_true_starts_it(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    e.apply_settings({"racefeed_enabled": True})
    assert e._race_feed is not None
    e.apply_settings({"racefeed_enabled": False})  # cleanup: stop the thread


def test_apply_settings_racefeed_enabled_false_stops_it(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    e.apply_settings({"racefeed_enabled": True})
    assert e._race_feed is not None
    e.apply_settings({"racefeed_enabled": False})
    assert e._race_feed is None


def test_enqueue_event_does_not_touch_racefeed_when_disabled(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    assert e._race_feed is None
    # Should not raise even though racefeed is off — the branch must be skipped.
    e._enqueue_event({"event_code": "PENA", "driver": "Norris", "vehicle_idx": 4})
    assert e._race_feed is None


def test_enqueue_event_forwards_to_racefeed_when_enabled(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    e.apply_settings({"racefeed_enabled": True})
    received = []
    monkeypatch.setattr(e._race_feed, "ingest", lambda event: received.append(event))

    e._enqueue_event({"event_code": "PENA", "driver": "Norris", "vehicle_idx": 4})

    assert len(received) == 1
    assert received[0].event_code == "PENA"
    assert received[0].session_type == e._session_type
    e.apply_settings({"racefeed_enabled": False})  # cleanup


def test_racefeed_state_snapshot_reads_player_fields(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    e._player_fuel = 42.0
    e._player_gap_front = 1500
    snap = e._racefeed_state_snapshot()
    assert snap["player_fuel"] == 42.0
    assert snap["gap_front_ms"] == 1500
    assert snap["session_type"] == e._session_type


def test_get_racefeed_state_disabled_by_default(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    assert e.get_racefeed_state() == {"enabled": False, "posts": []}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -u -m pytest tests/test_engine_racefeed.py -v`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute '_race_feed'`

- [ ] **Step 3: Add the import**

In `core/engine.py`, find this line (part of the existing import block):
```python
from core.broadcast.director import BroadcastDirector
from core.broadcast.context import BroadcastContext
```
Add immediately after it:
```python
from core.racefeed.engine import RaceFeedEngine
from core.racefeed.models import Event as RaceFeedEvent
```

- [ ] **Step 4: Add construction**

Find this line (from `F1Engine.__init__`):
```python
        self._spotter = SpotterTracker()
```
Add immediately after it:
```python
        self._race_feed: RaceFeedEngine | None = None
```

- [ ] **Step 5: Add the `_set_racefeed_enabled` and `_racefeed_state_snapshot` helpers**

Find the end of `apply_settings` (the method whose last statements are the
`_PERSONAS`/`volume` block ending in `pass` under `except Exception:`). Add these
two new methods immediately after `apply_settings` ends (before `_start_yandex`):

```python
    def _racefeed_state_snapshot(self) -> dict:
        """Pull callback given to RaceFeedEngine — read-only snapshot of exactly
        the fields its periodic tick needs (see core/racefeed/engine.py::
        StoryBuilder.from_tick). Never reaches further into engine state than this."""
        with self.state_lock:
            team = None
            if self._player_car_index < 22:
                try:
                    team = self.race_state.driver(self._player_car_index)["team"]
                except Exception:  # noqa: BLE001
                    team = None
            return {
                "session_type": self._session_type,
                "player_team": team,
                "gap_front_ms": self._player_gap_front,
                "gap_behind_ms": self._player_gap_behind,
                "gap_leader_ms": self._player_gap_leader,
                "player_fuel": self._player_fuel,
                "player_ers_percent": self._player_ers_percent,
                "player_tyre_wear": self._player_tyre_wear,
                "player_tyre_age": self._player_tyre_age,
                "player_tyre_compound": self._player_tyre_compound,
            }

    def _set_racefeed_enabled(self, enabled: bool) -> None:
        """Hot start/stop — see docs/superpowers/specs/2026-07-20-racefeed-phase1-design.md
        'Enable/disable': while disabled, self._race_feed is None, so
        _enqueue_event's fan-out branch never runs and no worker thread exists."""
        if enabled and self._race_feed is None:
            self._race_feed = RaceFeedEngine(
                ai_provider=self.ai, state_provider=self._racefeed_state_snapshot,
            )
            self._race_feed.start()
        elif not enabled and self._race_feed is not None:
            self._race_feed.stop()
            self._race_feed = None

    def get_racefeed_state(self) -> dict:
        from core.racefeed import ui_bridge
        return ui_bridge.get_posts(self._race_feed)
```

- [ ] **Step 6: Wire `apply_settings`**

Find this block inside `apply_settings`:
```python
        if "broadcast_mode_enabled" in settings:
            with self.state_lock:
                self.state["broadcast_mode_enabled"] = bool(settings["broadcast_mode_enabled"])
```
Add immediately after it:
```python
        if "racefeed_enabled" in settings:
            enabled = bool(settings["racefeed_enabled"])
            with self.state_lock:
                self.state["racefeed_enabled"] = enabled
            self._set_racefeed_enabled(enabled)
```

- [ ] **Step 7: Wire `start()`**

Find the full body of `start()`:
```python
    def start(self):
        telemetry_loop = (self._iracing_telemetry_loop
                           if self._telemetry_source == "iracing"
                           else self._telemetry_loop)
        threading.Thread(target=telemetry_loop, daemon=True).start()
        threading.Thread(target=self._commentary_loop, daemon=True).start()
        threading.Thread(target=self._yandex_health_loop, daemon=True,
                         name="yandex-health").start()
        threading.Thread(target=self._ambient_loop, daemon=True,
                         name="ambient-tick").start()
        threading.Thread(target=self._engineer_digest_loop, daemon=True,
                         name="engineer-digest").start()
```
Replace it with (only the last line is new — this starts RaceFeed on boot if it
was already enabled in a previously-saved settings.json, without unconditionally
spinning up a thread the way the other loops do):
```python
    def start(self):
        telemetry_loop = (self._iracing_telemetry_loop
                           if self._telemetry_source == "iracing"
                           else self._telemetry_loop)
        threading.Thread(target=telemetry_loop, daemon=True).start()
        threading.Thread(target=self._commentary_loop, daemon=True).start()
        threading.Thread(target=self._yandex_health_loop, daemon=True,
                         name="yandex-health").start()
        threading.Thread(target=self._ambient_loop, daemon=True,
                         name="ambient-tick").start()
        threading.Thread(target=self._engineer_digest_loop, daemon=True,
                         name="engineer-digest").start()
        self._set_racefeed_enabled(bool(self.settings.get("racefeed_enabled", False)))
```

- [ ] **Step 8: Wire the `_enqueue_event` fan-out**

Find:
```python
        event.setdefault("enqueued_at", time.time())
        self.event_queue.put(event)
```
Replace with:
```python
        event.setdefault("enqueued_at", time.time())
        self.event_queue.put(event)
        if self._race_feed is not None:
            self._race_feed.ingest(RaceFeedEvent.from_engine_dict(
                dict(event), self._session_type,
                event.get("vehicle_idx") == self._player_car_index,
            ))
```

- [ ] **Step 9: Wire the SSTA reset**

Find (inside the `if code == "SSTA":` block):
```python
            self._spotter.reset()
            self._safety_car_status = 0
```
Replace with:
```python
            self._spotter.reset()
            if self._race_feed is not None:
                self._race_feed.reset()
            self._safety_car_status = 0
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `py -3.12 -u -m pytest tests/test_engine_racefeed.py -v`
Expected: PASS (7 passed)

- [ ] **Step 11: Run the full existing test suite to confirm no regression**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: All previously-passing tests still pass (no failures introduced by
this wiring). This project's test suite was last confirmed at 1553 passed, 1
skipped as of 2026-07-19 — the new racefeed tests add to that count.

- [ ] **Step 12: Checkpoint** — Task 14 done.

---

## Task 15: `web_server.py` — `/api/racefeed` route

**Files:**
- Modify: `web_server.py`

No dedicated test file — this project's `web_server.py` routes aren't unit
tested (confirmed: they're thin delegations to `engine.*` methods, which Task 14
already tests). Verification is the manual smoke check in Task 19.

- [ ] **Step 1: Add the route**

In `web_server.py`, find:
```python
    @app.route("/api/overlay")
    def api_overlay():
        return _json(engine.get_overlay_state())
```
Add immediately after it:
```python
    @app.route("/api/racefeed")
    def api_racefeed():
        return _json(engine.get_racefeed_state())
```

- [ ] **Step 2: Sanity-check the module still imports cleanly**

Run: `py -3.12 -c "import web_server"`
Expected: no output, exit code 0 (import succeeds — catches any syntax error
from the edit above).

- [ ] **Step 3: Checkpoint** — Task 15 done.

---

## Task 16: Frontend — types, API client, transform, polling hook

**Files:**
- Modify: `NewSpotterUI/lib/spotter-data.ts`
- Modify: `NewSpotterUI/lib/api.ts`
- Create: `NewSpotterUI/lib/racefeed.ts`
- Create: `NewSpotterUI/lib/use-racefeed.ts`

- [ ] **Step 1: Add `"race-feed"` to `ViewId` and the `RaceFeedPost` type**

In `NewSpotterUI/lib/spotter-data.ts`, find:
```ts
export type ViewId =
  | "dashboard"
  | "race"
  | "voice"
  | "events"
  | "settings"
  | "logs"
  | "hotkeys"
  | "archive"
  | "debrief"
  | "broadcast-overlay"
```
Replace with:
```ts
export type ViewId =
  | "dashboard"
  | "race"
  | "voice"
  | "events"
  | "settings"
  | "logs"
  | "hotkeys"
  | "archive"
  | "debrief"
  | "broadcast-overlay"
  | "race-feed"
```

In the same file, find the `RaceEvent`/`LogEntry` type definitions and add
immediately after them:
```ts
export type RaceFeedPost = {
  id: string
  time: string
  reporter: string
  category: string
  text: string
  driver: string | null
  isPlayerStory: boolean
}
```

- [ ] **Step 2: Add the API type and client function**

In `NewSpotterUI/lib/api.ts`, find the `FeedItem` type:
```ts
export type FeedItem = {
  time: string
  event_code: string
  phrase: string
  color: string
}
```
Add immediately after it:
```ts
export type RaceFeedPostRow = {
  id: string
  story_id: string
  reporter_id: string
  category: string
  text: string
  created_at: number
  published_at: number
  driver: string | null
  is_player_story: number
}

export type RaceFeedResponse = {
  enabled: boolean
  posts: RaceFeedPostRow[]
}
```

Find the `getOverlay` function:
```ts
export const getOverlay = () => fetch("/api/overlay").then((r) => asJson<OverlayState>(r))
```
Add immediately after it:
```ts
export const getRaceFeed = () => fetch("/api/racefeed").then((r) => asJson<RaceFeedResponse>(r))
```

- [ ] **Step 3: Write the transform module**

`NewSpotterUI/lib/racefeed.ts`:
```ts
// Преобразование сырых постов бэкенда (/api/racefeed) в RaceFeedPost для UI.
// Отдельно от lib/feed.ts (state.feed) — RaceFeed постит из своей SQLite,
// не из общей телеметрийной ленты.

import type { RaceFeedResponse } from "./api"
import type { RaceFeedPost } from "./spotter-data"

const REPORTER_LABEL: Record<string, string> = {
  race_control: "Race Control",
  spotter_analytics: "Spotter Analytics",
  players_garage: "Боксы игрока",
}

export function toRaceFeedPosts(data: RaceFeedResponse): RaceFeedPost[] {
  return data.posts
    .slice()
    .sort((a, b) => b.published_at - a.published_at)
    .map((p) => ({
      id: p.id,
      time: new Date(p.published_at * 1000).toLocaleTimeString("ru-RU"),
      reporter: REPORTER_LABEL[p.reporter_id] ?? p.reporter_id,
      category: p.category,
      text: p.text,
      driver: p.driver,
      isPlayerStory: Boolean(p.is_player_story),
    }))
}
```

- [ ] **Step 4: Write the polling hook**

`NewSpotterUI/lib/use-racefeed.ts`:
```ts
"use client"

import { useEffect, useState } from "react"
import { getRaceFeed, type RaceFeedResponse } from "./api"

// Отдельный опрос /api/racefeed раз в 3с (не 1с, как useSpotterState) — посты
// публикуются с задержкой в 2-35с по дизайну, чаще опрашивать бессмысленно.
// Тот же паттерн self-rescheduling setTimeout, что и useSpotterState — см.
// комментарий там про накладывающиеся запросы при подвисании.
export function useRaceFeed(intervalMs = 3000) {
  const [data, setData] = useState<RaceFeedResponse | null>(null)

  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined

    const tick = async () => {
      try {
        const d = await getRaceFeed()
        if (!alive) return
        setData(d)
      } catch {
        // молча пропускаем тик — online/offline уже отражает useSpotterState
      } finally {
        if (alive) timer = setTimeout(tick, intervalMs)
      }
    }

    tick()
    return () => {
      alive = false
      if (timer) clearTimeout(timer)
    }
  }, [intervalMs])

  return data
}
```

- [ ] **Step 5: Type-check**

Run: `cd NewSpotterUI && pnpm tsc --noEmit`
Expected: no errors (existing project errors, if any predate this change, are
not this task's concern — only confirm no *new* errors from the 4 files above).

- [ ] **Step 6: Checkpoint** — Task 16 done.

---

## Task 17: Frontend — RaceFeed view component

**Files:**
- Create: `NewSpotterUI/components/spotter/views/race-feed.tsx`

- [ ] **Step 1: Write the component**

`NewSpotterUI/components/spotter/views/race-feed.tsx`:
```tsx
"use client"

import { PageHeader, Panel } from "../ui"
import { useRaceFeed } from "@/lib/use-racefeed"
import { toRaceFeedPosts } from "@/lib/racefeed"
import { Rss } from "lucide-react"

export function RaceFeedView() {
  const data = useRaceFeed()
  const posts = data ? toRaceFeedPosts(data) : []
  const enabled = data?.enabled ?? true

  if (!enabled) {
    return (
      <div>
        <PageHeader title="RaceFeed" subtitle="Живая лента репортажей о гонке" />
        <Panel label="RaceFeed">
          <div className="flex flex-col items-center justify-center gap-3 py-20 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-secondary text-muted-foreground">
              <Rss className="h-6 w-6" />
            </span>
            <h3 className="font-heading text-lg font-semibold text-foreground">RaceFeed выключен</h3>
            <p className="max-w-sm text-sm text-muted-foreground">
              Включите RaceFeed в настройках, чтобы увидеть репортажи о гонке.
            </p>
          </div>
        </Panel>
      </div>
    )
  }

  return (
    <div>
      <PageHeader title="RaceFeed" subtitle="Живая лента репортажей о гонке" />

      {posts.length > 0 ? (
        <Panel
          label="Лента"
          action={
            <span className="font-mono text-[10px] text-muted-foreground">{posts.length} постов</span>
          }
          bodyClassName="p-0"
        >
          <ul>
            {posts.map((p) => (
              <li
                key={p.id}
                className="flex flex-col gap-1 border-b border-border px-5 py-4 last:border-0 hover:bg-secondary/40"
              >
                <div className="flex items-center gap-2">
                  <span className="label-mono text-[10px] font-medium text-primary">{p.reporter}</span>
                  <span className="font-mono text-[10px] text-muted-foreground">· {p.time}</span>
                </div>
                <p className="mt-1 text-sm leading-relaxed text-foreground/90">{p.text}</p>
              </li>
            ))}
          </ul>
        </Panel>
      ) : (
        <Panel label="Лента">
          <div className="flex flex-col items-center justify-center gap-3 py-20 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-secondary text-muted-foreground">
              <Rss className="h-6 w-6" />
            </span>
            <h3 className="font-heading text-lg font-semibold text-foreground">Пока тихо</h3>
            <p className="max-w-sm text-sm text-muted-foreground">
              Первые репортажи появятся, как только начнётся что-то стоящее внимания.
            </p>
          </div>
        </Panel>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

Run: `cd NewSpotterUI && pnpm tsc --noEmit`
Expected: no new errors. If `Rss` isn't exported by the installed `lucide-react`
version, substitute `Newspaper` (also commonly available) in both the import and
JSX usage above.

- [ ] **Step 3: Checkpoint** — Task 17 done.

---

## Task 18: Frontend — sidebar nav entry + page wiring

**Files:**
- Modify: `NewSpotterUI/components/spotter/sidebar.tsx`
- Modify: `NewSpotterUI/app/page.tsx`

- [ ] **Step 1: Add the nav entry**

In `NewSpotterUI/components/spotter/sidebar.tsx`, find the icon imports (near
the top of the file) and add `Rss` to the existing `lucide-react` import list
(e.g. if the file has `import { LayoutDashboard, Flag, Mic, ... } from
"lucide-react"`, add `Rss` to that same import statement).

Find:
```ts
const nav: { id: ViewId; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "race", label: "Race", icon: Flag },
  { id: "voice", label: "Voice", icon: Mic },
  { id: "events", label: "Events", icon: Zap },
  { id: "settings", label: "Settings", icon: Settings },
  { id: "logs", label: "Logs", icon: FileText },
  { id: "hotkeys", label: "Hotkeys", icon: Keyboard },
  { id: "archive", label: "Archive", icon: BarChart3 },
  { id: "debrief", label: "Debrief", icon: BookOpen },
  { id: "broadcast-overlay", label: "Overlay", icon: MonitorPlay },
]
```
Replace with (new entry added after `"events"`, before `"settings"` — feed-like
screens grouped together):
```ts
const nav: { id: ViewId; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "race", label: "Race", icon: Flag },
  { id: "voice", label: "Voice", icon: Mic },
  { id: "events", label: "Events", icon: Zap },
  { id: "race-feed", label: "RaceFeed", icon: Rss },
  { id: "settings", label: "Settings", icon: Settings },
  { id: "logs", label: "Logs", icon: FileText },
  { id: "hotkeys", label: "Hotkeys", icon: Keyboard },
  { id: "archive", label: "Archive", icon: BarChart3 },
  { id: "debrief", label: "Debrief", icon: BookOpen },
  { id: "broadcast-overlay", label: "Overlay", icon: MonitorPlay },
]
```

- [ ] **Step 2: Wire the view into `page.tsx`**

In `NewSpotterUI/app/page.tsx`, find:
```tsx
import { EventsView } from "@/components/spotter/views/events"
```
Add immediately after it:
```tsx
import { RaceFeedView } from "@/components/spotter/views/race-feed"
```

Find:
```tsx
            {view === "events" && <EventsView state={state} />}
```
Add immediately after it:
```tsx
            {view === "race-feed" && <RaceFeedView />}
```

- [ ] **Step 3: Type-check**

Run: `cd NewSpotterUI && pnpm tsc --noEmit`
Expected: no new errors.

- [ ] **Step 4: Full build**

Run: `cd NewSpotterUI && pnpm build`
Expected: build succeeds, produces `NewSpotterUI/out/`. (This does not sync into
`webui/` — that's `build.ps1`'s job for a full EXE build, not needed to verify
this plan.)

- [ ] **Step 5: Checkpoint** — Task 18 done.

---

## Task 19: End-to-end manual verification

**Files:** none — this is a live smoke check, not a code change.

- [ ] **Step 1: Run the full backend test suite one more time**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: 0 failed.

- [ ] **Step 2: Start the app in dev mode and enable RaceFeed**

Run the app (`python app.pyw` or however this project is normally launched in
dev), open the UI, go to Settings, enable RaceFeed (`racefeed_enabled` — the
setting added in Task 13; confirm it's exposed as a toggle in the Settings view
if not already picked up automatically). If F1 25 isn't running, this at least
confirms: (a) the toggle doesn't crash the app, (b) `/api/racefeed` returns
`{"enabled": true, "posts": []}` (check via browser devtools network tab or a
direct `curl http://127.0.0.1:8765/api/racefeed`), (c) the new RaceFeed sidebar
tab renders the empty state without errors.

- [ ] **Step 3: Live race verification (requires F1 25 running)**

With telemetry flowing and `racefeed_enabled` on, drive a session and confirm:
posts appear in the RaceFeed tab within the expected delay windows (2-35s per
category), text reads like journalism (not templated telemetry), and repeated
identical situations (e.g. sitting in the same gap for a while) do not spam
duplicate posts. Tune `PUBLISH_THRESHOLD` (`core/racefeed/editor.py`) and the
`_NUMERIC_NOISE_THRESHOLD` values if posts are too sparse/frequent — these were
explicitly documented as tunable, not fixed, in the design doc.

- [ ] **Step 4: Update CONTEXT.md**

Per this project's CLAUDE.md rule 2, add a short entry to `CONTEXT.md`'s "На чём
остановились" section summarizing: RaceFeed Phase 1 shipped (core pipeline +
minimal UI), what's still open (live-tuning thresholds per Step 3, Phases 2-5
from the design doc's roadmap not started), and any real bugs found during Step
3 that weren't anticipated in this plan.

- [ ] **Step 5: Checkpoint** — Task 19 done. Phase 1 complete.

---

## Self-review notes (completed during plan authoring)

**Spec coverage:** Every Phase 1 design-doc section has a task: models (1),
LLM-integration gap discovered and fixed (2), storage (3), editor (4), scheduler
(5), reporters (6), prompts (7), generators (8), StoryBuilder + RaceFeedEngine
(9-10), anti-repetition guarantee (11), UI read API (12), settings (13), engine
wiring (14), HTTP route (15), frontend (16-18), live verification (19). Phases
2-5 (World persistence, media, comments, full roster) are explicitly out of
scope per the design doc and not included here.

**Placeholder scan:** No TBD/TODO; every code step is complete, runnable code
grounded in citations gathered from the actual codebase (two Explore-agent
research passes plus direct reads of `core/engine.py`, `web_server.py`,
`core/settings.py`, `commentator/ai_provider.py`, `yandex_ai/gpt.py`,
`commentator/personas.py`).

**Type consistency check performed:** `Event`/`Story`/`Candidate`/`Post` field
names introduced in Task 1 are used identically in Tasks 3-12 (spot-checked
`story_id`/`story_key`/`update_policy`/`is_player_story` for drift — none
found). `AIProvider.generate_with_system` (Task 2) is the exact method name used
in `generators.py` (Task 8). `RaceFeedEngine.ingest(event)` (Task 10) matches
the single-argument call in Task 14 Step 8 (an earlier draft of this plan had
`ingest()` taking separate `session_type`/`is_player` params — corrected to take
one pre-built `Event`, produced via `Event.from_engine_dict()`, before finalizing
Task 10 and Task 14 so they'd agree).
