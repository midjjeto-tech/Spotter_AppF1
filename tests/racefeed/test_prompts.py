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
    assert ctx.index("rain_expected") < ctx.index("rain_started")


def _candidate(story):
    return Candidate(
        story_id=story.id, story_key=story.story_key, category=story.category,
        reporter_id="players_garage", base_importance=70, priority="incident",
        publish_after=(0.0, 0.0), expires_at=0.0, update_policy="supersede",
    )


def test_placeholder_team_is_hidden_from_the_llm():
    # An unresolved team_id degrades to "Команда #227" upstream; feeding it to
    # the LLM is exactly how "Макс из команды 227" happened. It must be dropped.
    story = Story(
        id="ovtk|Max", story_key=("ovtk", "Max"), category="player_overtake",
        session_type="race",
        facts={"driver": "Макс", "team": "Команда #227", "target": "Норрис"},
    )
    ctx = build_context(story, _candidate(story))
    assert "227" not in ctx
    assert "Команда #" not in ctx
    assert "Макс" in ctx and "Норрис" in ctx  # real narrative facts survive


def test_technical_fields_never_reach_the_prompt():
    story = Story(
        id="ovtk|Max", story_key=("ovtk", "Max"), category="player_overtake",
        session_type="race",
        facts={"driver": "Макс", "team": "Red Bull Racing", "team_id": 227,
               "color": "#3671C6", "vehicle1_idx": 4, "is_player": True},
    )
    ctx = build_context(story, _candidate(story))
    assert "Red Bull Racing" in ctx      # the resolved name is fine
    assert "team_id" not in ctx and "227" not in ctx
    assert "#3671C6" not in ctx and "vehicle1_idx" not in ctx


def test_context_carries_a_guard_against_inventing_teams():
    story = Story(id="s", story_key=("x",), category="incident",
                   session_type="race", facts={"driver": "Макс"})
    ctx = build_context(story, _candidate(story))
    assert "Не выдумывай" in ctx


def test_context_tells_the_llm_to_use_the_drivers_name_not_igrok():
    story = Story(id="champ|1", story_key=("championship", 1), category="championship",
                   session_type="race", facts={"driver": "Ферстаппен", "player_points": 40})
    ctx = build_context(story, _candidate(story))
    assert "Ферстаппен" in ctx           # the real name reaches the prompt
    assert "по имени" in ctx and "«игрок»" in ctx  # guard against the generic word


def test_build_context_tells_the_llm_which_editorial_format_to_use():
    story = Story(
        id="gap|player", story_key=("gap", "player"), category="gap_trend",
        session_type="race", facts={"gap_front_ms": 1800},
    )
    candidate = Candidate(
        story_id=story.id, story_key=story.story_key, category=story.category,
        reporter_id="spotter_analytics", base_importance=70,
        priority="statistics", publish_after=(0.0, 0.0), expires_at=0.0,
        update_policy="ignore_if_pending", format_id="stat_brief",
    )

    context = build_context(story, candidate)

    assert "Начни с ключевой цифры" in context


def test_image_filename_never_reaches_the_prompt():
    story = Story(id="s", story_key=("x",), category="player_overtake",
                   session_type="race", facts={"driver": "Макс", "image": "shot.png"})
    ctx = build_context(story, _candidate(story))
    assert "shot.png" not in ctx and "image" not in ctx
