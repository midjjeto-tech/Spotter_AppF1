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


def test_editor_rotates_formats_for_consecutive_incident_posts():
    mem = StoryMemory()
    editor = Editor()
    first_story = mem.upsert(
        ("incident", "Norris"), "incident", "race", {"importance": 90}
    )
    second_story = mem.upsert(
        ("incident", "Piastri"), "incident", "race", {"importance": 90}
    )
    first = _candidate(first_story.id, first_story.story_key, 90)
    second = _candidate(second_story.id, second_story.story_key, 90)

    editor.evaluate(first, first_story)
    editor.evaluate(second, second_story)

    assert first.format_id != second.format_id


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


def test_editor_multi_cycle_diffs_against_most_recent_publish_not_first():
    mem = StoryMemory()
    editor = Editor()
    story = mem.upsert(("gap", "player"), "gap_trend", "race", {"gap_ms": 1000.0})

    # cycle 1: first mention, high importance -> new, then actually publish
    c1 = _candidate(story.id, story.story_key, base_importance=90)
    assert editor.evaluate(c1, story) == "new"
    mem.mark_published(story, "post-1")

    # small change, below noise threshold -> suppress (must diff against post-1's facts)
    story.facts = {"gap_ms": 1500.0}
    c2 = _candidate(story.id, story.story_key, base_importance=90)
    assert editor.evaluate(c2, story) == "suppress"

    # real change -> update, then actually publish
    story.facts = {"gap_ms": 4000.0}
    c3 = _candidate(story.id, story.story_key, base_importance=90)
    assert editor.evaluate(c3, story) == "update"
    mem.mark_published(story, "post-2")
    assert story.history == [{"gap_ms": 1000.0}, {"gap_ms": 4000.0}]

    # settled again relative to post-2 (not post-1!) -> suppress
    story.facts = {"gap_ms": 4400.0}
    c4 = _candidate(story.id, story.story_key, base_importance=90)
    assert editor.evaluate(c4, story) == "suppress"
