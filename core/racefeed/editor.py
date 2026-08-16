"""core/racefeed/editor.py — deterministic editorial decisions. The LLM is NEVER
consulted here — see the design doc for why: this codebase already has a
documented bug class where letting an LLM judge "is this the same story as
before" caused repetitive spam (core/situation_dedup.py exists because of it)."""
from __future__ import annotations

import hashlib
import json
import time

from core.racefeed.models import Candidate, Story

PUBLISH_THRESHOLD = 60  # tunable — see design doc's Editor algorithm section

_FORMAT_CYCLES = {
    "incident": ("breaking", "official_update", "live_update"),
    "pit_stop": ("garage_update", "tactical_note"),
    "statistics": ("stat_brief", "trend_watch"),
    "analysis": ("analysis", "tactical_note"),
    "default": ("live_update", "analysis"),
}

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

    def mark_published(self, story: Story, post_id: str,
                       published_at: float | None = None,
                       facts_snapshot: dict | None = None) -> None:
        """Call only after a candidate for this story has actually been rendered
        and published — never speculatively. See engine.py::_publish_due()."""
        story.history.append(dict(
            facts_snapshot if facts_snapshot is not None else story.facts
        ))
        story.stage += 1
        story.status = "published"
        story.last_publish = published_at if published_at is not None else time.time()
        story.post_ids.append(post_id)

    def clear(self) -> None:
        self._stories.clear()


class Editor:
    """Decides new/update/suppress for a Candidate given its Story's current
    state. Never mutates the Story — StoryMemory.mark_published() is the caller's
    job, and only after a successful render (see engine.py)."""

    def __init__(self):
        self._format_cursor: dict[str, int] = {}

    def evaluate(self, candidate: Candidate, story: Story) -> str:
        if story.status == "developing":
            if candidate.base_importance >= PUBLISH_THRESHOLD:
                self._decorate(candidate, story, "new")
                return "new"
            return "suppress"
        old_facts = story.history[-1] if story.history else {}
        if facts_materially_changed(old_facts, story.facts):
            self._decorate(candidate, story, "update")
            return "update"
        return "suppress"

    def _decorate(self, candidate: Candidate, story: Story, decision: str) -> None:
        cycle = _FORMAT_CYCLES.get(
            candidate.priority, _FORMAT_CYCLES["default"]
        )
        cursor = self._format_cursor.get(candidate.priority, 0)
        candidate.format_id = cycle[cursor % len(cycle)]
        self._format_cursor[candidate.priority] = cursor + 1
        candidate.angle_id = f"{candidate.category}:{decision}"
        facts = (candidate.facts_snapshot
                 if candidate.facts_snapshot is not None else story.facts)
        payload = json.dumps(
            [story.id, facts], ensure_ascii=False, sort_keys=True, default=str
        )
        candidate.claim_fingerprint = hashlib.sha256(
            payload.encode("utf-8")
        ).hexdigest()[:20]

    def reset(self) -> None:
        self._format_cursor.clear()
