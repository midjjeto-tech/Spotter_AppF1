"""Golden-race contract for RaceFeed's public pipeline.

The fixture intentionally mixes race phases and story types.  It is not a raw
event-volume benchmark: it proves that editorial curation produces a readable
15-25 post race while still allowing material stories to evolve.
"""
from __future__ import annotations

import time

from core.racefeed import ui_bridge
from core.racefeed.engine import RaceFeedEngine
from core.racefeed.models import Event
from core.racefeed.scheduler import PUBLISH_DELAY_S


class _FactEchoAI:
    available = True

    def generate_with_system(self, system, user):
        return user


def _event(code, driver=None, *, importance=85, is_player=False, team="Team",
           vehicle_idx=None, description=None, **extra):
    return Event(
        event_code=code, session_type="race", driver=driver, team=team,
        vehicle_idx=vehicle_idx, is_player=is_player, importance=importance,
        laps_remaining=extra.pop("laps_remaining", 30),
        description=description or f"{code}: {driver or 'race'}",
        extra=extra, enqueued_at=time.time(),
    )


def _wait_for_posts(feed, minimum, timeout=4.0):
    deadline = time.time() + timeout
    posts = []
    while time.time() < deadline:
        posts = ui_bridge.get_posts(feed, limit=1000)["posts"]
        if len(posts) >= minimum:
            return posts
        time.sleep(0.05)
    return posts


def test_golden_race_meets_editorial_volume_and_evolution_contract(tmp_path, monkeypatch):
    for priority in PUBLISH_DELAY_S:
        monkeypatch.setitem(PUBLISH_DELAY_S, priority, (0.0, 0.0))

    snapshot = {
        "session_type": "race", "gap_front_ms": 1800,
        "gap_behind_ms": 2400, "player_tyre_wear": 35.0,
        "player_tyre_age": 8, "player_tyre_compound": "M",
    }
    feed = RaceFeedEngine(
        ai_provider=_FactEchoAI(), state_provider=lambda: snapshot,
        data_dir=str(tmp_path),
    )
    feed.reset()
    feed.start()

    opening = [_event("SSTA", description="Race started")]
    opening += [
        _event("PENA", name, vehicle_idx=i, description=f"Penalty for {name}")
        for i, name in enumerate(("Norris", "Piastri", "Leclerc", "Hamilton", "Russell"))
    ]
    opening += [
        _event("COLL", name, vehicle_idx=10 + i, description=f"Collision for {name}")
        for i, name in enumerate(("Verstappen", "Alonso", "Sainz"))
    ]
    opening += [
        _event("RTMT", name, vehicle_idx=15 + i, description=f"Retirement for {name}")
        for i, name in enumerate(("Gasly", "Tsunoda"))
    ]
    opening += [
        _event(
            "SAFETY_CAR_DEPLOYED", description="Safety car deployed",
            sc_type="Safety car",
        ),
        _event(
            "PIT_EXIT", "Norris", vehicle_idx=4, is_player=True,
            description="Norris leaves the pits", tyre_compound="H",
        ),
        _event(
            "FTLP", "Norris", vehicle_idx=4, is_player=True,
            description="Norris sets fastest lap", lap_time_ms=81234,
        ),
    ]
    for event in opening:
        feed.ingest(event)

    # Non-player collisions stay deferred until a consequence confirms that
    # they mattered. The safety-car deployment releases only the latest one.
    posts = _wait_for_posts(feed, 13)
    assert len(posts) >= 13

    feed.ingest(_event(
        "OVTK", "Norris", vehicle_idx=4, is_player=True,
        description="Norris passes Russell", lap=18, target="Russell",
    ))
    posts = _wait_for_posts(feed, 14)
    assert len(posts) >= 14

    feed.ingest(_event(
        "OVTK", "Norris", vehicle_idx=4, is_player=True,
        description="Norris later passes Hamilton", lap=31, target="Hamilton",
    ))
    posts = _wait_for_posts(feed, 15)
    assert len(posts) >= 15

    feed.ingest(_event(
        "SAFETY_CAR_ENDING", description="Safety car ending",
        sc_type="Safety car",
    ))
    feed.ingest(_event("CHQF", description="Chequered flag"))
    posts = _wait_for_posts(feed, 17)
    feed.stop()

    assert 15 <= len(posts) <= 25
    assert {post["reporter_id"] for post in posts} == {
        "race_control", "spotter_analytics", "players_garage",
    }
    assert len({post["format_id"] for post in posts}) >= 5
    story_stages = [(post["story_id"], post["story_stage"]) for post in posts]
    assert len(story_stages) == len(set(story_stages))
    assert sum(post["story_id"].startswith("safety_car|") for post in posts) == 2
    assert sum(post["story_id"].startswith("player_overtake|") for post in posts) == 2
    assert sum(post["story_id"].startswith("incident|") for post in posts) == 1
