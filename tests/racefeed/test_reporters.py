from core.racefeed.models import Story
from core.racefeed.reporters import (
    PaddockReporter, PlayersGarageReporter, QualifyingReporter, RaceControlReporter,
    SpotterAnalyticsReporter,
)


def _story(category, facts=None, session_type="race"):
    return Story(id=f"{category}|x", story_key=(category, "x"), category=category,
                 session_type=session_type, facts=facts or {})


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


def test_players_garage_covers_events_involving_the_players_team():
    story = _story(
        "player_overtake", {"is_player": False, "is_player_team": True}
    )

    assert PlayersGarageReporter().propose(story) is not None


def test_players_garage_propose_pit_stop_priority():
    story = _story("player_pit_stop", {"is_player": True, "importance": 80})
    candidate = PlayersGarageReporter().propose(story)
    assert candidate is not None
    assert candidate.priority == "pit_stop"
    assert candidate.update_policy == "supersede"
    assert candidate.base_importance == 80


def test_phase_one_reporters_ignore_non_race_sessions():
    story = _story("penalty", {"importance": 90})
    story.session_type = "qualifying"

    assert RaceControlReporter().propose(story) is None


def test_race_control_propose_defaults_importance_to_70_when_missing():
    story = _story("penalty")  # no "importance" fact
    candidate = RaceControlReporter().propose(story)
    assert candidate.base_importance == 70


def test_spotter_analytics_propose_defaults_importance_to_65_when_missing():
    story = _story("gap_trend")  # no "importance" fact
    candidate = SpotterAnalyticsReporter().propose(story)
    assert candidate.base_importance == 65


def test_players_garage_propose_defaults_importance_to_75_when_missing():
    story = _story("player_overtake", {"is_player": True})  # no "importance" fact
    candidate = PlayersGarageReporter().propose(story)
    assert candidate.base_importance == 75


def test_reporters_list_has_one_of_each_with_unique_ids():
    from core.racefeed.reporters import REPORTERS
    assert len(REPORTERS) == 7
    ids = [r.id for r in REPORTERS]
    assert len(ids) == len(set(ids))
    assert set(ids) == {
        "race_control", "spotter_analytics", "players_garage",
        "qualifying_control", "championship_desk", "achievements", "paddock",
    }


def test_paddock_reporter_covers_post_race_vote_and_interview():
    reporter = PaddockReporter()

    vote = reporter.propose(_story(
        "driver_of_the_day", {"importance": 88}, session_type="race"
    ))
    interview = reporter.propose(_story(
        "post_race_interview", {"importance": 82}, session_type="race"
    ))
    recap = reporter.propose(_story(
        "race_recap", {"importance": 86}, session_type="race"
    ))

    assert vote is not None and vote.reporter_id == "paddock"
    assert vote.priority == "analysis"
    assert interview is not None and interview.priority == "default"
    assert recap is not None and recap.priority == "statistics"
    assert reporter.propose(_story(
        "driver_of_the_day", session_type="qualifying"
    )) is None


def test_achievements_reporter_covers_only_milestone_in_race():
    from core.racefeed.reporters import AchievementsReporter
    r = AchievementsReporter()
    assert r.covers(_story("milestone", session_type="race")) is True
    assert r.covers(_story("milestone", session_type="qualifying")) is False
    assert r.covers(_story("penalty", session_type="race")) is False


def test_achievements_reporter_propose_id_and_priority():
    from core.racefeed.reporters import AchievementsReporter
    candidate = AchievementsReporter().propose(
        _story("milestone", {"importance": 92}, session_type="race"))
    assert candidate is not None
    assert candidate.reporter_id == "achievements"
    assert candidate.priority == "analysis"
    assert candidate.base_importance == 92


def test_championship_reporter_covers_only_championship_in_race():
    from core.racefeed.reporters import ChampionshipReporter
    r = ChampionshipReporter()
    assert r.covers(_story("championship", session_type="race")) is True
    assert r.covers(_story("championship", session_type="qualifying")) is False
    assert r.covers(_story("penalty", session_type="race")) is False


def test_championship_reporter_propose_priority_and_id():
    from core.racefeed.reporters import ChampionshipReporter
    candidate = ChampionshipReporter().propose(
        _story("championship", {"importance": 85}, session_type="race"))
    assert candidate is not None
    assert candidate.reporter_id == "championship_desk"
    assert candidate.priority == "analysis"
    assert candidate.update_policy == "supersede"


def test_qualifying_reporter_covers_quali_categories_not_race():
    r = QualifyingReporter()
    # covered only when the session is actually qualifying
    assert r.covers(_story("penalty", session_type="qualifying")) is True
    assert r.covers(_story("player_fastest_lap", session_type="qualifying")) is True
    assert r.covers(_story("flag", session_type="qualifying")) is True
    # not a quali-covered category, and not during race/practice
    assert r.covers(_story("gap_trend", session_type="qualifying")) is False
    assert r.covers(_story("penalty", session_type="race")) is False
    assert r.covers(_story("penalty", session_type="practice")) is False


def test_qualifying_reporter_propose_sets_id_and_priority():
    story = _story("player_fastest_lap", {"importance": 88}, session_type="qualifying")
    candidate = QualifyingReporter().propose(story)
    assert candidate is not None
    assert candidate.reporter_id == "qualifying_control"
    assert candidate.priority == "incident"
    assert candidate.base_importance == 88


def test_race_reporters_never_cover_qualifying_stories():
    quali = _story("penalty", {"importance": 90, "is_player": True},
                   session_type="qualifying")
    assert RaceControlReporter().propose(quali) is None
    assert PlayersGarageReporter().propose(
        _story("player_fastest_lap", {"is_player": True}, session_type="qualifying")
    ) is None
