import time

import pytest

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


def test_prediction_is_fixed_before_start_and_resolved_after_finish(tmp_path, monkeypatch):
    import core.track_return as track_return
    from core.racefeed import predictions

    monkeypatch.setattr(track_return, "build", lambda *args: {"finish_position": 8})
    monkeypatch.setattr(predictions.archive, "list_season_results", lambda limit=5: [])
    monkeypatch.setattr(predictions.archive, "list_game_sessions", lambda: [])
    snapshot = {
        "session_type": "race", "track_id": 13, "track_name": "Спа",
        "player_driver": "Артём", "teammate_driver": "Леклер",
        "player_position": 4, "teammate_position": 7,
        "rain_forecast": {"minutes": 10, "rain_pct": 60},
    }
    rf = RaceFeedEngine(
        ai_provider=_FakeAI(), state_provider=lambda: snapshot,
        data_dir=str(tmp_path),
    )
    rf.reset(session_type="race")
    initial = rf.get_prediction_state()
    fixed_forecast = initial["model_forecast"]
    assert initial["status"] == "open"
    assert rf.submit_prediction({
        "finish": "podium", "teammate": "player", "risk": "rain",
    })["ok"] is True

    rf.lock_prediction()
    assert rf.get_prediction_state()["status"] == "locked"
    assert rf.submit_prediction({
        "finish": "points", "teammate": "teammate", "risk": "penalty",
    })["reason"] == "prediction_locked"

    grid = [
        {"vehicle_idx": 0, "position": 2, "grid_position": 4,
         "best_lap_time_ms": 80_000, "points": 18},
        {"vehicle_idx": 1, "position": 6, "grid_position": 7,
         "best_lap_time_ms": 81_000, "points": 8},
    ]
    drivers = {
        0: {"name": "Артём", "team": "Ferrari"},
        1: {"name": "Леклер", "team": "Ferrari"},
    }
    rf.resolve_prediction(
        grid, drivers.get, 0,
        actual_risks={"safety_car": False, "rain": True, "penalty": False},
    )
    final = rf.get_prediction_state()
    assert final["status"] == "resolved"
    assert final["model_forecast"] == fixed_forecast
    assert final["result"]["reader_score"] == 3
    assert final["scoreboard"]["races"] == 1


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

    # +30s: past the "incident" priority's publish_after window (2-5s) but
    # comfortably under reporters.py's _EXPIRY_S (60s) staleness cutoff, so the
    # candidate is due without also being dropped as expired by Scheduler.due()
    # (see test_scheduler.py::test_expired_candidate_is_dropped for that guard).
    fake_now = [time.time() + 30]
    import core.racefeed.engine as engine_mod
    monkeypatch.setattr(engine_mod.time, "time", lambda: fake_now[0])
    rf._publish_due()

    from core.racefeed import storage
    posts = storage.get_posts(rf.current_db_path())
    assert len(posts) == 1
    assert posts[0]["driver"] == "Norris"
    assert "post about" in posts[0]["text"]


def test_driver_of_the_day_post_persists_structured_poll_metadata(
    tmp_path, monkeypatch
):
    from core.racefeed import storage
    from core.racefeed.models import Event
    from core.racefeed.scheduler import PUBLISH_DELAY_S

    monkeypatch.setitem(PUBLISH_DELAY_S, "analysis", (0.0, 0.0))
    rf = RaceFeedEngine(
        ai_provider=_FakeAI(), state_provider=_snapshot, data_dir=str(tmp_path)
    )
    rf.reset()
    candidates = [
        {
            "driver": "Alonso", "vote_pct": 51, "score": 42,
            "positions_gained": 7, "overtakes": 5,
        },
        {
            "driver": "Leclerc", "vote_pct": 49, "score": 40,
            "positions_gained": 2, "overtakes": 3,
        },
    ]
    rf.ingest(Event(
        event_code="RACEFEED_DOTD", session_type="race",
        driver="Alonso", team="Aston Martin", vehicle_idx=7,
        is_player=False, importance=88, laps_remaining=0,
        description="Driver of the Day",
        extra={
            "dotd_driver": "Alonso", "dotd_pct": 51,
            "dotd_gained": 7, "dotd_overtakes": 5,
            "dotd_candidates": candidates,
        },
        enqueued_at=time.time(),
    ))
    rf._drain_queue()
    rf._publish_due()

    posts = storage.get_posts(rf.current_db_path())
    assert len(posts) == 1
    assert posts[0]["category"] == "driver_of_the_day"
    assert posts[0]["metadata"]["poll"] == candidates


def test_recap_and_championship_posts_persist_visual_metadata(tmp_path, monkeypatch):
    from core.racefeed import storage
    from core.racefeed.models import Event
    from core.racefeed.scheduler import PUBLISH_DELAY_S

    monkeypatch.setitem(PUBLISH_DELAY_S, "statistics", (0.0, 0.0))
    monkeypatch.setitem(PUBLISH_DELAY_S, "analysis", (0.0, 0.0))
    rf = RaceFeedEngine(
        ai_provider=_FakeAI(), state_provider=_snapshot, data_dir=str(tmp_path)
    )
    rf.reset()
    recap = {
        "driver": "You", "finish_position": 2, "grid_position": 10,
        "positions_gained": 8, "overtakes": 6, "points": 18,
        "pit_stops": 2, "fastest_lap": True, "penalties": 0,
    }
    weekend_duel = {
        "team": "Ferrari",
        "player": {"driver": "You", "start_position": 10, "finish_position": 2, "best_lap_time_ms": 79_000, "points": 18},
        "teammate": {"driver": "Leclerc", "start_position": 4, "finish_position": 5, "best_lap_time_ms": 79_500, "points": 10},
        "player_score": 3, "teammate_score": 1, "winner": "player",
    }
    rf.ingest(Event(
        event_code="RACE_RECAP", session_type="race", driver="You", team="Ferrari",
        vehicle_idx=4, is_player=True, importance=86, laps_remaining=0,
        description="Race recap", extra={
            "race_recap": recap, "weekend_duel": weekend_duel, **recap,
        },
        enqueued_at=time.time(),
    ))
    rf.ingest(Event(
        event_code="CHAMPIONSHIP", session_type="race", driver="You", team="Ferrari",
        vehicle_idx=4, is_player=True, importance=85, laps_remaining=0,
        description="Championship", extra={
            "player_position": 2, "player_points": 40,
            "rival": "Max", "rival_position": 1, "rival_points": 50,
            "gap_to_rival": 10, "player_race_position": 2,
            "rival_race_position": 1, "rival_ahead": True,
            "storylines": [{
                "id": "rivalry", "title": "Дуэль с Max", "value": "1:1",
                "detail": "Последние 2 очные гонки", "tone": "amber",
            }],
            "return_hook": {
                "title": "До Max — 10 очков",
                "detail": "Следующая гонка продолжит эту дуэль.",
            },
        },
        enqueued_at=time.time(),
    ))
    rf._drain_queue()
    rf._publish_due()

    posts = storage.get_posts(rf.current_db_path())
    by_category = {post["category"]: post for post in posts}
    assert by_category["race_recap"]["metadata"]["recap"] == recap
    assert by_category["race_recap"]["metadata"]["weekend_duel"] == weekend_duel
    assert by_category["championship"]["metadata"]["comparison"] == {
        "driver": "You", "player_position": 2, "player_points": 40,
        "rival": "Max", "rival_position": 1, "rival_points": 50,
        "gap_to_rival": 10, "player_race_position": 2,
        "rival_race_position": 1, "rival_ahead": True,
    }
    assert by_category["championship"]["metadata"]["storylines"][0]["id"] == "rivalry"
    assert by_category["championship"]["metadata"]["return_hook"]["title"] == "До Max — 10 очков"


def test_published_story_is_persisted_at_its_advanced_stage(tmp_path, monkeypatch):
    from core.racefeed import storage
    from core.racefeed.models import Event
    from core.racefeed.scheduler import PUBLISH_DELAY_S

    monkeypatch.setitem(PUBLISH_DELAY_S, "incident", (0.0, 0.0))
    rf = RaceFeedEngine(
        ai_provider=_FakeAI(), state_provider=_snapshot, data_dir=str(tmp_path)
    )
    rf.reset()
    rf.start()
    rf.ingest(Event(
        event_code="PENA", session_type="race", driver="Norris", team="McLaren",
        vehicle_idx=4, is_player=True, importance=90, laps_remaining=20,
        description="5s penalty", extra={"lap": 12}, enqueued_at=time.time(),
    ))

    deadline = time.time() + 3.0
    story = None
    while time.time() < deadline:
        story = storage.get_story(rf.current_db_path(), "penalty|Norris")
        if story is not None:
            break
        time.sleep(0.05)
    rf.stop()

    assert (story.status, story.stage, len(story.history)) == ("published", 1, 1)


def test_stats_track_ingest_schedule_publish_and_comment_generation(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                         data_dir=str(tmp_path))
    rf.reset()

    from core.racefeed.models import Event
    rf.ingest(Event(
        event_code="PENA", session_type="race", driver="Norris", team="McLaren",
        vehicle_idx=4, is_player=False, importance=90, laps_remaining=20,
        description="5s penalty", extra={"lap": 12}, enqueued_at=time.time(),
    ))
    assert rf.get_stats()["events_ingested"] == 1

    rf._drain_queue()
    fake_now = [time.time() + 30]
    import core.racefeed.engine as engine_mod
    monkeypatch.setattr(engine_mod.time, "time", lambda: fake_now[0])
    rf._publish_due()
    # comments are generated one worker iteration after the post — see
    # engine.py::_generate_pending_comments
    rf._generate_pending_comments()

    stats = rf.get_stats()
    assert stats["candidates_proposed"] == 1
    assert stats["candidates_scheduled"] == 1
    assert stats["candidates_suppressed"] == 0
    assert stats["posts_published"] == 1
    assert stats["renders_failed"] == 0
    # PENA (incident category) keeps comments — see comments.py's deny-list.
    assert stats["comments_generated"] == 1
    assert stats["comments_skipped"] == 0


def test_stats_count_comments_skipped_for_analytics_tick(tmp_path, monkeypatch):
    rf = RaceFeedEngine(
        ai_provider=_FakeAI(),
        state_provider=lambda: {"session_type": "race", "gap_front_ms": 1500},
        data_dir=str(tmp_path),
    )
    rf.reset()
    rf._maybe_tick()  # reset() left _last_tick=0 + _session_active=True → tick fires

    fake_now = [time.time() + 30]
    import core.racefeed.engine as engine_mod
    monkeypatch.setattr(engine_mod.time, "time", lambda: fake_now[0])
    rf._publish_due()

    stats = rf.get_stats()
    assert stats["posts_published"] == 1
    # gap_trend is an analytics category → comments gated off, no LLM comment call.
    assert stats["comments_skipped"] == 1
    assert stats["comments_generated"] == 0


def test_stats_count_editor_suppression(tmp_path):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                         data_dir=str(tmp_path))
    rf.reset()

    from core.racefeed.models import Event
    rf.ingest(Event(
        event_code="PENA", session_type="race", driver="Norris", team="McLaren",
        vehicle_idx=4, is_player=False, importance=1, laps_remaining=20,
        description="tiny", extra={}, enqueued_at=time.time(),
    ))
    rf._drain_queue()

    stats = rf.get_stats()
    assert stats["candidates_proposed"] == 1
    assert stats["candidates_suppressed"] == 1
    assert stats["candidates_scheduled"] == 0
    assert stats["posts_published"] == 0


def test_stats_reset_when_a_new_session_opens(tmp_path):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                         data_dir=str(tmp_path))
    rf.reset()

    from core.racefeed.models import Event
    rf.ingest(Event(
        event_code="PENA", session_type="race", driver="Norris", team="McLaren",
        vehicle_idx=4, is_player=False, importance=90, laps_remaining=20,
        description="5s penalty", extra={}, enqueued_at=time.time(),
    ))
    rf._drain_queue()
    assert rf.get_stats()["events_ingested"] == 1

    rf.reset()  # new race → counters start fresh
    assert rf.get_stats() == {key: 0 for key in engine_stats_keys()}


def engine_stats_keys():
    import core.racefeed.engine as engine_mod
    return engine_mod._STAT_KEYS


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

    fake_now = [time.time() + 30]
    import core.racefeed.engine as engine_mod
    monkeypatch.setattr(engine_mod.time, "time", lambda: fake_now[0])
    rf._publish_due()

    from core.racefeed import storage
    assert storage.get_posts(rf.current_db_path()) == []


def test_qualifying_event_is_published_by_the_qualifying_reporter(tmp_path, monkeypatch):
    rf = RaceFeedEngine(
        ai_provider=_FakeAI(),
        state_provider=lambda: {"session_type": "qualifying"},
        data_dir=str(tmp_path),
    )
    rf.reset()

    from core.racefeed.models import Event
    rf.ingest(Event(
        event_code="FTLP", session_type="qualifying", driver="Max",
        team="Red Bull Racing", vehicle_idx=1, is_player=True, importance=85,
        laps_remaining=None, description="Personal best lap",
        extra={"lap_time": "1:29.1"}, enqueued_at=time.time(),
    ))
    rf._drain_queue()

    fake_now = [time.time() + 30]
    import core.racefeed.engine as engine_mod
    monkeypatch.setattr(engine_mod.time, "time", lambda: fake_now[0])
    rf._publish_due()

    from core.racefeed import storage
    posts = storage.get_posts(rf.current_db_path())
    assert len(posts) == 1
    assert posts[0]["reporter_id"] == "qualifying_control"


def test_qualifying_event_opens_a_session_even_without_reset(tmp_path):
    """A quali event must self-start a feed the same way a race event does —
    the _drain_queue session-open gate now allows qualifying too."""
    rf = RaceFeedEngine(
        ai_provider=_FakeAI(),
        state_provider=lambda: {"session_type": "qualifying"},
        data_dir=str(tmp_path),
    )
    from core.racefeed.models import Event
    rf.ingest(Event(
        event_code="PENA", session_type="qualifying", driver="Norris",
        team="McLaren", vehicle_idx=4, is_player=False, importance=90,
        laps_remaining=None, description="grid penalty", extra={},
        enqueued_at=time.time(),
    ))
    rf._drain_queue()
    assert rf.current_db_path() is not None


def test_practice_event_does_not_open_a_session(tmp_path):
    rf = RaceFeedEngine(
        ai_provider=_FakeAI(),
        state_provider=lambda: {"session_type": "practice"},
        data_dir=str(tmp_path),
    )
    from core.racefeed.models import Event
    rf.ingest(Event(
        event_code="PENA", session_type="practice", driver="Norris",
        team="McLaren", vehicle_idx=4, is_player=False, importance=90,
        laps_remaining=None, description="practice", extra={},
        enqueued_at=time.time(),
    ))
    rf._drain_queue()
    assert rf.current_db_path() is None


def test_championship_event_is_published_by_the_championship_desk(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                         data_dir=str(tmp_path))
    rf.reset()

    from core.racefeed.models import Event
    rf.ingest(Event(
        event_code="CHAMPIONSHIP", session_type="race", driver="", team=None,
        vehicle_idx=4, is_player=True, importance=85, laps_remaining=None,
        description="", extra={"player_points": 40, "player_position": 2,
                               "rival": "Max", "gap_to_rival": 10},
        enqueued_at=time.time(),
    ))
    rf._drain_queue()

    fake_now = [time.time() + 40]  # past the "analysis" delay (25-35s)
    import core.racefeed.engine as engine_mod
    monkeypatch.setattr(engine_mod.time, "time", lambda: fake_now[0])
    rf._publish_due()

    from core.racefeed import storage
    posts = storage.get_posts(rf.current_db_path())
    assert len(posts) == 1
    assert posts[0]["reporter_id"] == "championship_desk"
    assert posts[0]["is_player_story"] == 1


def test_milestone_event_is_published_by_the_achievements_desk(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                         data_dir=str(tmp_path))
    rf.reset()

    from core.racefeed.models import Event
    rf.ingest(Event(
        event_code="MILESTONE", session_type="race", driver="", team=None,
        vehicle_idx=4, is_player=True, importance=92, laps_remaining=None,
        description="", extra={"milestone": "first_win",
                               "label": "Первая победа в карьере!", "position": 1},
        enqueued_at=time.time(),
    ))
    rf._drain_queue()

    fake_now = [time.time() + 40]  # past the "analysis" delay (25-35s)
    import core.racefeed.engine as engine_mod
    monkeypatch.setattr(engine_mod.time, "time", lambda: fake_now[0])
    rf._publish_due()

    from core.racefeed import storage
    posts = storage.get_posts(rf.current_db_path())
    assert len(posts) == 1
    assert posts[0]["reporter_id"] == "achievements"
    assert posts[0]["is_player_story"] == 1


def test_start_and_stop_manage_a_real_thread(tmp_path):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                         data_dir=str(tmp_path))
    rf.start()
    assert rf._thread is not None
    assert rf._thread.is_alive()
    rf.stop()
    assert rf._thread is None


def test_start_without_a_race_does_not_create_an_empty_session(tmp_path):
    rf = RaceFeedEngine(
        ai_provider=_FakeAI(),
        state_provider=lambda: {"session_type": "unknown"},
        data_dir=str(tmp_path),
    )

    rf.start()
    time.sleep(0.6)
    rf.stop()

    assert rf.current_db_path() is None


def test_start_twice_does_not_spawn_a_second_thread(tmp_path):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot, data_dir=str(tmp_path))
    rf.start()
    first_thread = rf._thread
    rf.start()
    assert rf._thread is first_thread
    rf.stop()


def test_reset_discards_events_queued_by_the_previous_session(tmp_path, monkeypatch):
    """A new session must never publish an event left over from the old one."""
    from core.racefeed import ui_bridge
    from core.racefeed.models import Event
    from core.racefeed.scheduler import PUBLISH_DELAY_S

    monkeypatch.setitem(PUBLISH_DELAY_S, "incident", (0.0, 0.0))
    rf = RaceFeedEngine(
        ai_provider=_FakeAI(), state_provider=_snapshot, data_dir=str(tmp_path)
    )

    rf.reset()
    rf.ingest(Event(
        event_code="SAFETY_CAR_DEPLOYED", session_type="race",
        driver=None, team=None, vehicle_idx=None, is_player=False,
        importance=90, laps_remaining=40, description="old session",
        extra={"lap": 1}, enqueued_at=time.time(),
    ))

    rf.reset()
    rf.ingest(Event(
        event_code="SAFETY_CAR_DEPLOYED", session_type="race",
        driver=None, team=None, vehicle_idx=None, is_player=False,
        importance=90, laps_remaining=39, description="new session",
        extra={"lap": 2}, enqueued_at=time.time(),
    ))
    rf.start()

    deadline = time.time() + 3.0
    posts = []
    while time.time() < deadline:
        posts = ui_bridge.get_posts(rf)["posts"]
        if posts:
            break
        time.sleep(0.05)
    rf.stop()

    assert len(posts) == 1


def test_append_story_stages_render_the_facts_that_were_scheduled(tmp_path, monkeypatch):
    from core.racefeed import ui_bridge
    from core.racefeed.models import Event
    from core.racefeed.scheduler import PUBLISH_DELAY_S

    class FullEchoAI:
        available = True

        def generate_with_system(self, system, user):
            return user

    monkeypatch.setitem(PUBLISH_DELAY_S, "incident", (0.0, 0.0))
    rf = RaceFeedEngine(
        ai_provider=FullEchoAI(), state_provider=_snapshot, data_dir=str(tmp_path)
    )
    rf.reset()
    for code, description in (
        ("SAFETY_CAR_DEPLOYED", "Safety car deployed"),
        ("SAFETY_CAR_ENDING", "Safety car ending"),
    ):
        rf.ingest(Event(
            event_code=code, session_type="race", driver=None, team=None,
            vehicle_idx=None, is_player=False, importance=90, laps_remaining=30,
            description=description, extra={"sc_type": "Safety car"},
            enqueued_at=time.time(),
        ))
    rf.start()

    deadline = time.time() + 3.0
    posts = []
    while time.time() < deadline:
        posts = ui_bridge.get_posts(rf)["posts"]
        if len(posts) == 2:
            break
        time.sleep(0.05)
    rf.stop()

    assert {
        "deployed" if "deployed" in post["text"] else "ending"
        for post in posts
    } == {"deployed", "ending"}


def test_stop_discards_unpublished_events_before_restart(tmp_path, monkeypatch):
    """Disabling RaceFeed must not resume stale work when it is enabled again."""
    from core.racefeed import ui_bridge
    from core.racefeed.models import Event
    from core.racefeed.scheduler import PUBLISH_DELAY_S

    monkeypatch.setitem(PUBLISH_DELAY_S, "incident", (0.0, 0.0))
    rf = RaceFeedEngine(
        ai_provider=_FakeAI(), state_provider=_snapshot, data_dir=str(tmp_path)
    )
    rf.reset()
    rf.ingest(Event(
        event_code="SAFETY_CAR_DEPLOYED", session_type="race",
        driver=None, team=None, vehicle_idx=None, is_player=False,
        importance=90, laps_remaining=40, description="stale",
        extra={}, enqueued_at=time.time(),
    ))

    rf.stop()
    rf.start()
    time.sleep(0.75)
    rf.stop()

    assert ui_bridge.get_posts(rf)["posts"] == []


def test_session_end_stops_periodic_race_analysis(tmp_path, monkeypatch):
    from core.racefeed import ui_bridge
    import core.racefeed.engine as engine_mod
    from core.racefeed.models import Event
    from core.racefeed.scheduler import PUBLISH_DELAY_S

    snapshot = {
        "session_type": "race", "gap_front_ms": 1500,
        "gap_behind_ms": 2200,
    }
    monkeypatch.setattr(engine_mod, "_TICK_INTERVAL_S", 0.1)
    monkeypatch.setitem(PUBLISH_DELAY_S, "statistics", (0.0, 0.0))
    monkeypatch.setitem(PUBLISH_DELAY_S, "incident", (0.0, 0.0))
    rf = RaceFeedEngine(
        ai_provider=_FakeAI(), state_provider=lambda: snapshot,
        data_dir=str(tmp_path),
    )
    rf.reset()
    rf.start()
    initial = []
    deadline = time.time() + 2.0
    while time.time() < deadline:
        initial = ui_bridge.get_posts(rf)["posts"]
        if initial:
            break
        time.sleep(0.05)

    rf.ingest(Event(
        event_code="SEND", session_type="race", driver=None, team=None,
        vehicle_idx=None, is_player=False, importance=90, laps_remaining=0,
        description="Session ended", extra={}, enqueued_at=time.time(),
    ))
    deadline = time.time() + 2.0
    ended = []
    while time.time() < deadline:
        ended = ui_bridge.get_posts(rf)["posts"]
        if len(ended) > len(initial):
            break
        time.sleep(0.05)

    snapshot["gap_front_ms"] = 5000
    time.sleep(0.75)
    after_end = ui_bridge.get_posts(rf)["posts"]
    rf.stop()

    assert len(after_end) == len(ended)


def test_start_ingest_publishes_via_real_thread(tmp_path):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot, data_dir=str(tmp_path))
    rf.start()

    from core.racefeed.models import Event
    event = Event(
        event_code="PENA", session_type="race", driver="Norris", team="McLaren",
        vehicle_idx=4, is_player=False, importance=90, laps_remaining=20,
        description="5s penalty", extra={}, enqueued_at=time.time(),
    )
    rf.ingest(event)

    from core.racefeed import storage
    deadline = time.time() + 10.0
    posts = []
    while time.time() < deadline:
        db_path = rf.current_db_path()
        if db_path:
            posts = storage.get_posts(db_path)
            if posts:
                break
        time.sleep(0.2)
    rf.stop()

    assert len(posts) == 1
    assert posts[0]["driver"] == "Norris"


def test_storage_failure_still_advances_editorial_memory(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                         data_dir=str(tmp_path))
    rf.reset()

    from core.racefeed.models import Event
    event = Event(
        event_code="PENA", session_type="race", driver="Norris", team="McLaren",
        vehicle_idx=4, is_player=False, importance=90, laps_remaining=20,
        description="5s penalty", extra={}, enqueued_at=time.time(),
    )
    rf.ingest(event)
    rf._drain_queue()

    fake_now = [time.time() + 30]
    import core.racefeed.engine as engine_mod
    monkeypatch.setattr(engine_mod.time, "time", lambda: fake_now[0])

    from core.racefeed import storage as storage_mod
    def _boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(storage_mod, "save_publication", _boom)

    rf._publish_due()

    story = rf._editorial.story("penalty|Norris")
    assert story is not None
    assert story.status == "published"


def test_generated_post_remains_visible_during_storage_outage(tmp_path, monkeypatch):
    from core.racefeed import storage as storage_mod, ui_bridge
    from core.racefeed.models import Event
    from core.racefeed.scheduler import PUBLISH_DELAY_S

    monkeypatch.setitem(PUBLISH_DELAY_S, "incident", (0.0, 0.0))
    monkeypatch.setattr(
        storage_mod, "save_publication",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("disk full")),
    )
    rf = RaceFeedEngine(
        ai_provider=_FakeAI(), state_provider=_snapshot, data_dir=str(tmp_path)
    )
    rf.reset()
    rf.start()
    rf.ingest(Event(
        event_code="PENA", session_type="race", driver="Norris", team="McLaren",
        vehicle_idx=4, is_player=True, importance=90, laps_remaining=20,
        description="5s penalty", extra={}, enqueued_at=time.time(),
    ))

    deadline = time.time() + 2.0
    posts = []
    while time.time() < deadline:
        posts = ui_bridge.get_posts(rf)["posts"]
        if posts:
            break
        time.sleep(0.05)
    rf.stop()

    assert len(posts) == 1


def test_failed_publication_is_retried_without_regeneration(tmp_path, monkeypatch):
    from core.racefeed import storage as storage_mod
    from core.racefeed.models import Event
    from core.racefeed.scheduler import PUBLISH_DELAY_S

    class CountingAI(_FakeAI):
        def __init__(self):
            self.calls = 0

        def generate_with_system(self, system, user):
            self.calls += 1
            return super().generate_with_system(system, user)

    real_save = storage_mod.save_publication
    attempts = {"count": 0}

    def flaky_save(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary disk error")
        return real_save(*args, **kwargs)

    monkeypatch.setitem(PUBLISH_DELAY_S, "incident", (0.0, 0.0))
    monkeypatch.setattr(storage_mod, "save_publication", flaky_save)
    ai = CountingAI()
    rf = RaceFeedEngine(ai_provider=ai, state_provider=_snapshot, data_dir=str(tmp_path))
    rf.reset()
    rf.start()
    rf.ingest(Event(
        event_code="PENA", session_type="race", driver="Norris", team="McLaren",
        vehicle_idx=4, is_player=True, importance=90, laps_remaining=20,
        description="5s penalty", extra={}, enqueued_at=time.time(),
    ))

    deadline = time.time() + 3.0
    stored = []
    while time.time() < deadline:
        stored = storage_mod.get_posts(rf.current_db_path())
        # the thread lands an iteration after the post — wait for both
        if stored and stored[0]["comments"]:
            break
        time.sleep(0.05)
    rf.stop()

    assert len(stored) == 1
    # New posts get one or two explicit AI expert notes, never a fake crowd.
    assert 1 <= len(stored[0]["comments"]) <= 2
    # One call renders the post and one renders its comment batch. A storage
    # retry must not regenerate either artifact.
    assert ai.calls == 2


def test_post_carries_image_from_story_facts(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                         data_dir=str(tmp_path))
    rf.reset()
    from core.racefeed.models import Event
    rf.ingest(Event(
        event_code="OVTK", session_type="race", driver="You", team="Ferrari",
        vehicle_idx=4, is_player=True, importance=90, laps_remaining=None,
        description="overtake", extra={"image": "shot.png"}, enqueued_at=time.time()))
    rf._drain_queue()
    fake_now = [time.time() + 30]
    import core.racefeed.engine as engine_mod
    monkeypatch.setattr(engine_mod.time, "time", lambda: fake_now[0])
    rf._publish_due()
    from core.racefeed import storage
    posts = storage.get_posts(rf.current_db_path())
    assert posts[0]["image"] == "shot.png"


# --- комментарии генерируются отдельно от публикации поста ------------------

def _publish_one(rf, monkeypatch, **event_kwargs):
    from core.racefeed.models import Event
    defaults = dict(
        event_code="PENA", session_type="race", driver="Норрис", team="McLaren",
        vehicle_idx=4, is_player=True, importance=90, laps_remaining=20,
        description="5s penalty", extra={}, enqueued_at=time.time(),
    )
    defaults.update(event_kwargs)
    rf.ingest(Event(**defaults))
    rf._drain_queue()
    fake_now = [time.time() + 30]
    import core.racefeed.engine as engine_mod
    monkeypatch.setattr(engine_mod.time, "time", lambda: fake_now[0])
    rf._publish_due()


def test_post_is_stored_before_its_comment_thread(tmp_path, monkeypatch):
    """A slow provider must not hold the post back: the publication lands
    immediately, the thread catches up on the next worker iteration."""
    from core.racefeed import storage as storage_mod
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                        data_dir=str(tmp_path))
    rf.reset()
    _publish_one(rf, monkeypatch)

    posts = storage_mod.get_posts(rf.current_db_path())
    assert len(posts) == 1
    assert posts[0]["comments"] == []
    assert rf.get_stats()["comments_generated"] == 0

    rf._generate_pending_comments()

    posts = storage_mod.get_posts(rf.current_db_path())
    assert 1 <= len(posts[0]["comments"]) <= 2
    assert rf.get_stats()["comments_generated"] == 1


def test_only_one_thread_is_generated_per_iteration(tmp_path, monkeypatch):
    """Post throughput must not depend on how many threads are outstanding."""
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                        data_dir=str(tmp_path))
    rf.reset()
    _publish_one(rf, monkeypatch, event_code="PENA")
    _publish_one(rf, monkeypatch, event_code="RTMT", description="retired")

    assert len(rf._pending_comments) == 2
    rf._generate_pending_comments()
    assert len(rf._pending_comments) == 1
    rf._generate_pending_comments()
    assert rf._pending_comments == []
    assert rf.get_stats()["comments_generated"] == 2


def test_analytics_posts_never_enter_the_comment_queue(tmp_path, monkeypatch):
    """The category gate is applied at publish time, so a gated post costs
    nothing later — and never occupies a generation slot."""
    rf = RaceFeedEngine(
        ai_provider=_FakeAI(),
        state_provider=lambda: {"session_type": "race", "gap_front_ms": 1500},
        data_dir=str(tmp_path),
    )
    rf.reset()
    rf._maybe_tick()
    fake_now = [time.time() + 30]
    import core.racefeed.engine as engine_mod
    monkeypatch.setattr(engine_mod.time, "time", lambda: fake_now[0])
    rf._publish_due()

    assert rf._pending_comments == []
    assert rf.get_stats()["comments_skipped"] == 1


def test_session_reset_drops_pending_comment_threads(tmp_path, monkeypatch):
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                        data_dir=str(tmp_path))
    rf.reset()
    _publish_one(rf, monkeypatch)
    assert rf._pending_comments

    rf.reset()

    assert rf._pending_comments == []


def test_comment_thread_gets_the_facts_of_its_own_event(tmp_path, monkeypatch):
    """Regression for threads that read as generic: the facts snapshot the post
    was built from must reach comment generation (see comments.py)."""
    seen = {}

    class _FactCapturingAI:
        available = True

        def generate_with_system(self, system, user):
            seen.setdefault("prompts", []).append(user)
            return "post text"

    rf = RaceFeedEngine(ai_provider=_FactCapturingAI(), state_provider=_snapshot,
                        data_dir=str(tmp_path))
    rf.reset()
    _publish_one(rf, monkeypatch, event_code="RTMT", driver="Норрис",
                 description="retired")
    rf._generate_pending_comments()

    comment_prompt = seen["prompts"][-1]
    assert "Факты события" in comment_prompt
    assert "Норрис" in comment_prompt


# --- метаданные сессии пишутся движком --------------------------------------

def test_session_meta_is_written_when_the_session_opens(tmp_path):
    from core.racefeed import storage as storage_mod
    rf = RaceFeedEngine(
        ai_provider=_FakeAI(),
        state_provider=lambda: {"session_type": "race", "track_name": "Монца"},
        data_dir=str(tmp_path),
    )
    rf.reset()

    meta = storage_mod.get_session_meta(rf.current_db_path())
    assert meta["track_name"] == "Монца"


def test_reset_session_type_overrides_stale_state_snapshot(tmp_path):
    """SSTA knows the new type even when the last snapshot is qualifying."""
    from core.racefeed import storage as storage_mod

    rf = RaceFeedEngine(
        ai_provider=_FakeAI(),
        state_provider=lambda: {"session_type": "qualifying", "track_name": "Джидда"},
        data_dir=str(tmp_path),
    )

    rf.reset(session_type="race")

    meta = storage_mod.get_session_meta(rf.current_db_path())
    assert meta["session_type"] == "race"
    assert meta["session_type"] == "race"
    assert meta["started_at"] > 0


def test_track_name_is_filled_in_later_when_it_resolves(tmp_path):
    """На SSTA трасса часто ещё неизвестна — тик дописывает её, когда она
    появилась, и не трогает БД на каждом тике."""
    from core.racefeed import storage as storage_mod
    snapshot = {"session_type": "race", "track_name": None, "gap_front_ms": 1200}
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=lambda: snapshot,
                        data_dir=str(tmp_path))
    rf.reset()

    assert storage_mod.get_session_meta(rf.current_db_path())["track_name"] == ""
    assert rf._meta_track_written is False

    snapshot["track_name"] = "Спа"
    rf._maybe_tick()

    assert storage_mod.get_session_meta(rf.current_db_path())["track_name"] == "Спа"
    assert rf._meta_track_written is True


def test_session_meta_failure_never_breaks_the_session(tmp_path, monkeypatch):
    from core.racefeed import storage as storage_mod

    def boom(*args, **kwargs):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(storage_mod, "save_session_meta", boom)
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                        data_dir=str(tmp_path))
    rf.reset()

    assert rf.current_db_path() is not None


def test_state_provider_failure_still_opens_the_session(tmp_path):
    def exploding():
        raise RuntimeError("engine lock held")

    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=exploding,
                        data_dir=str(tmp_path))
    rf.reset()

    assert rf.current_db_path() is not None


# --- реплика читателя и ответы персонажей -----------------------------------

def _session_with_post(tmp_path, session_id="20260726_202326", post_id="p1"):
    from core.racefeed import storage
    from core.racefeed.models import Post
    path = str(tmp_path / f"{session_id}.sqlite3")
    storage.init_db(path)
    storage.save_post(path, Post(
        id=post_id, session_id=session_id, story_id="st",
        reporter_id="race_control", category="incident", text="Контакт в повороте.",
        created_at=1.0, published_at=2.0, driver="Норрис", is_player_story=False,
    ))
    return path


def test_reader_comment_is_saved_immediately_and_queues_an_answer(tmp_path):
    """Реплика должна попасть в БД до возврата из вызова — иначе кнопка
    «отправить» выглядит сломанной, пока провайдер думает."""
    from core.racefeed import storage
    path = _session_with_post(tmp_path)
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                        data_dir=str(tmp_path))

    saved = rf.submit_reader_comment("20260726_202326", "p1", "чистый манёвр")

    assert saved["author_name"] == "Ты"
    assert [c["text"] for c in storage.get_posts(path)[0]["comments"]] == ["чистый манёвр"]
    assert len(rf._pending_replies) == 1


def test_personas_answer_the_reader_on_the_next_worker_iteration(tmp_path):
    from core.racefeed import storage
    path = _session_with_post(tmp_path)
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                        data_dir=str(tmp_path))
    saved = rf.submit_reader_comment("20260726_202326", "p1", "чистый манёвр")

    rf._generate_pending_replies()

    comments = storage.get_posts(path)[0]["comments"]
    answers = [c for c in comments if c["parent_id"] == saved["id"]]
    assert answers
    assert all(c["author_id"] != "player" for c in answers)
    assert rf._pending_replies == []


def test_reader_replies_survive_a_session_reset(tmp_path):
    """Читатель мог писать под архивной гонкой — новая сессия не повод терять
    его ответ."""
    _session_with_post(tmp_path)
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                        data_dir=str(tmp_path))
    rf.submit_reader_comment("20260726_202326", "p1", "реплика")

    rf.reset()

    assert len(rf._pending_replies) == 1


def test_bad_session_id_is_rejected_before_anything_is_written(tmp_path):
    from core.racefeed.reader import ReaderError
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                        data_dir=str(tmp_path))

    with pytest.raises(ReaderError):
        rf.submit_reader_comment("../../evil", "p1", "текст")
    assert rf._pending_replies == []


def test_unreadable_thread_drops_the_answer_not_the_reader_line(tmp_path):
    from core.racefeed import storage
    path = _session_with_post(tmp_path)
    rf = RaceFeedEngine(ai_provider=_FakeAI(), state_provider=_snapshot,
                        data_dir=str(tmp_path))
    rf.submit_reader_comment("20260726_202326", "p1", "реплика")
    # файл исчез между отправкой и обработкой
    from pathlib import Path
    saved_bytes = Path(path).read_bytes()
    Path(path).unlink()

    rf._generate_pending_replies()  # не должно бросить

    Path(path).write_bytes(saved_bytes)
    assert [c["text"] for c in storage.get_posts(path)[0]["comments"]] == ["реплика"]


def test_the_feed_stays_readable_while_the_worker_renders(tmp_path):
    """Опрос ленты не должен ждать провайдера.

    `_pipeline_lock` воркер держит ВСЮ итерацию, а внутри неё лежат рендер
    каждого созревшего поста, пачка комментариев и ответ читателю — всё это
    вызовы LLM. Браузер при этом опрашивает `/api/racefeed` раз в 3 секунды
    (NewSpotterUI/lib/use-racefeed.ts), и пока чтение ленты брало тот же лок,
    запросы вставали в очередь за GigaChat — за гонку 2026-08-11 у него было 31
    отвал по таймауту. Проверяем не результат, а именно НЕЗАВИСИМОСТЬ.
    """
    import threading

    engine = RaceFeedEngine(ai_provider=None, state_provider=lambda: {},
                            data_dir=str(tmp_path))
    released = threading.Event()
    finished = threading.Event()

    def hold_pipeline():
        with engine._pipeline_lock:
            released.set()
            finished.wait(timeout=5.0)

    holder = threading.Thread(target=hold_pipeline, daemon=True)
    holder.start()
    assert released.wait(timeout=5.0), "фикстура не захватила pipeline lock"

    # ДЕДЛАЙН обязателен: без него тест просто дождался бы освобождения лока и
    # прошёл бы на сломанном коде — только медленно.
    done = threading.Event()

    def read_feed():
        engine.get_volatile_posts()
        done.set()

    threading.Thread(target=read_feed, daemon=True).start()
    try:
        assert done.wait(timeout=1.0), (
            "чтение ленты ждёт pipeline lock — HTTP-поток встанет за LLM")
    finally:
        finished.set()
        holder.join(timeout=5.0)


def test_a_reader_reply_is_queued_without_the_pipeline_lock(tmp_path, monkeypatch):
    """То же для отправки реплики: докстринг `submit_reader_comment` прямо
    требует, чтобы провайдерский вызов не сидел внутри HTTP-запроса читателя, —
    через общий лок он там и сидел."""
    import threading

    from core.racefeed import reader as reader_mod

    engine = RaceFeedEngine(ai_provider=None, state_provider=lambda: {},
                            data_dir=str(tmp_path))
    monkeypatch.setattr(
        reader_mod, "add_comment",
        lambda *a, **k: {"id": "c1", "text": "привет", "created_at": 1.0})

    released = threading.Event()
    finished = threading.Event()

    def hold_pipeline():
        with engine._pipeline_lock:
            released.set()
            finished.wait(timeout=5.0)

    holder = threading.Thread(target=hold_pipeline, daemon=True)
    holder.start()
    assert released.wait(timeout=5.0)

    done = threading.Event()
    result: list = []

    def send():
        result.append(engine.submit_reader_comment("s1", "p1", "привет"))
        done.set()

    threading.Thread(target=send, daemon=True).start()
    try:
        assert done.wait(timeout=1.0), (
            "отправка реплики ждёт pipeline lock — кнопка выглядит сломанной")
        assert result[0]["id"] == "c1"
        assert len(engine._pending_replies) == 1
    finally:
        finished.set()
        holder.join(timeout=5.0)
