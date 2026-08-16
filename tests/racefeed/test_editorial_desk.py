from __future__ import annotations

import time

import pytest

from core.racefeed.editorial import EditorialDesk
from core.racefeed.models import Event
from core.racefeed.scheduler import PUBLISH_DELAY_S


@pytest.fixture(autouse=True)
def no_publish_delay(monkeypatch):
    for priority in PUBLISH_DELAY_S:
        monkeypatch.setitem(PUBLISH_DELAY_S, priority, (0.0, 0.0))


def _event(code: str, driver: str | None = None, *, is_player: bool = False,
           importance: int = 85, vehicle_idx: int | None = None, **extra) -> Event:
    return Event(
        event_code=code,
        session_type="race",
        driver=driver,
        team=extra.pop("team", "Team"),
        vehicle_idx=vehicle_idx,
        is_player=is_player,
        importance=importance,
        laps_remaining=extra.pop("laps_remaining", 20),
        description=extra.pop("description", f"{code}: {driver or 'race'}"),
        extra=extra,
        enqueued_at=time.time(),
    )


def _publish_all(desk: EditorialDesk) -> list:
    ready = desk.due(time.time() + 1.0)
    for index, publication in enumerate(ready):
        desk.mark_published(
            publication,
            post_id=f"post-{publication.story.id}-{publication.story.stage}-{index}",
            published_at=time.time(),
        )
    return ready


def test_analytics_budget_caps_semantic_updates_at_six():
    desk = EditorialDesk()

    published = []
    for step in range(8):
        desk.observe_snapshot({
            "gap_front_ms": 5000 - step * 1200,
            "gap_behind_ms": 2000 + step * 1200,
            "player_tyre_wear": 10.0 + step * 11.0,
            "player_tyre_age": step * 2,
            "player_tyre_compound": "M",
            "player_fuel": 30.0 - step * 3.0,
            "player_ers_percent": 95.0 - step * 16.0,
        }, "race")
        published.extend(_publish_all(desk))

    categories = [item.story.category for item in published]
    assert categories.count("gap_trend") == 2
    assert categories.count("tyre_status") == 2
    assert categories.count("fuel_status") == 1
    assert categories.count("ers_status") == 1
    assert len(categories) == 6


def test_battle_story_uses_unordered_pair_and_allows_only_one_update():
    desk = EditorialDesk()
    published = []

    exchanges = [
        _event("OVTK", "Player", is_player=True, vehicle_idx=4,
               overtaking_idx=4, being_overtaken_idx=7, target="Rival"),
        _event("OVTK", "Rival", is_player=True, vehicle_idx=7,
               overtaking_idx=7, being_overtaken_idx=4, target="Player"),
        _event("OVTK", "Player", is_player=True, vehicle_idx=4,
               overtaking_idx=4, being_overtaken_idx=7, target="Rival"),
        _event("OVTK", "Rival", is_player=True, vehicle_idx=7,
               overtaking_idx=7, being_overtaken_idx=4, target="Player"),
    ]
    for event in exchanges:
        desk.observe_event(event)
        published.extend(_publish_all(desk))

    assert len(published) == 2
    assert len({item.story.id for item in published}) == 1

    desk.observe_event(_event(
        "OVTK", "Player", is_player=True, vehicle_idx=4,
        overtaking_idx=4, being_overtaken_idx=9, target="Other rival",
    ))
    other_pair = _publish_all(desk)
    assert len(other_pair) == 1
    assert other_pair[0].story.id != published[0].story.id


def test_non_player_incident_waits_for_consequence_and_deduplicates_contact_burst():
    desk = EditorialDesk()
    for _ in range(3):
        desk.observe_event(_event(
            "COLL", "Driver A", vehicle_idx=2,
            vehicle1_idx=2, vehicle2_idx=3, target="Driver B",
        ))

    assert _publish_all(desk) == []

    desk.observe_event(_event("PENA", "Driver A", vehicle_idx=2, importance=90))
    published = _publish_all(desk)
    assert [item.story.category for item in published] == ["incident", "penalty"]
    assert sum(item.story.category == "incident" for item in published) == 1


def test_safety_car_ending_does_not_release_an_unrelated_deferred_incident():
    desk = EditorialDesk()
    desk.observe_event(_event(
        "COLL", "Driver A", vehicle_idx=2,
        vehicle1_idx=2, vehicle2_idx=3, target="Driver B",
    ))

    desk.observe_event(_event(
        "SAFETY_CAR_ENDING",
        description="Safety car ending",
        sc_type="Safety car",
    ))

    published = _publish_all(desk)
    assert [item.story.category for item in published] == ["safety_car"]


def test_player_incident_is_immediately_critical():
    desk = EditorialDesk()
    desk.observe_event(_event(
        "COLL", "Player", is_player=True, vehicle_idx=4,
        vehicle1_idx=4, vehicle2_idx=3, target="Driver B",
    ))

    published = _publish_all(desk)
    assert len(published) == 1
    assert published[0].story.category == "incident"


def test_action_category_cap_stops_penalty_spam_but_finish_always_passes():
    desk = EditorialDesk()
    for index in range(35):
        desk.observe_event(_event(
            "PENA", f"Driver {index}", vehicle_idx=index,
            importance=90,
        ))
    desk.observe_event(_event("CHQF", importance=50))

    published = _publish_all(desk)
    assert sum(item.story.category == "penalty" for item in published) == 4
    assert sum(item.story.category == "flag" for item in published) == 1


def test_post_race_ritual_always_passes_after_noncritical_ceiling():
    """The two promised paddock posts must survive a noisy race."""
    desk = EditorialDesk()
    desk._accepted_total = desk._noncritical_ceiling

    desk.observe_event(_event(
        "POST_RACE_INTERVIEW", "Winner", importance=82,
        interview_quotes=[{"driver": "Winner", "position": 1, "quote": "Text"}],
    ))
    desk.observe_event(_event(
        "RACEFEED_DOTD", "Winner", importance=88,
        dotd_candidates=[{"driver": "Winner", "vote_pct": 100}],
    ))

    published = _publish_all(desk)
    assert [item.story.category for item in published] == [
        "post_race_interview", "driver_of_the_day",
    ]


def test_short_race_caps_unique_player_action_bursts_and_keeps_ritual():
    """Flashbacks and noisy telemetry must not turn a sprint into 50 posts."""
    desk = EditorialDesk()
    desk.observe_snapshot({"total_laps": 13, "gap_front_ms": 1200}, "race")
    published = _publish_all(desk)

    for index in range(15):
        desk.observe_event(_event(
            "OVTK", "Player", is_player=True, vehicle_idx=4,
            overtaking_idx=4, being_overtaken_idx=5 + index,
            target=f"Rival {index}", importance=90,
        ))
        published.extend(_publish_all(desk))

    for index in range(12):
        desk.observe_event(_event(
            "COLL", "Player", is_player=True, vehicle_idx=4,
            vehicle1_idx=4, vehicle2_idx=5 + index,
            target=f"Rival {index}", importance=90,
        ))
        published.extend(_publish_all(desk))

    for index in range(8):
        desk.observe_event(_event(
            "PENA", "Player", is_player=True, vehicle_idx=4,
            penalty_index=index, importance=90,
        ))
        published.extend(_publish_all(desk))

    desk.observe_event(_event("CHQF", importance=90))
    desk.observe_event(_event("POST_RACE_INTERVIEW", "Winner", importance=82))
    desk.observe_event(_event("RACEFEED_DOTD", "Winner", importance=88))
    published.extend(_publish_all(desk))

    categories = [item.story.category for item in published]
    assert len(published) <= 20
    assert categories.count("player_overtake") <= 5
    assert categories.count("incident") <= 3
    assert categories.count("penalty") <= 3
    assert "post_race_interview" in categories
    assert "driver_of_the_day" in categories


def test_working_budget_suppresses_low_importance_after_twenty():
    desk = EditorialDesk()
    desk._accepted_total = desk._working_budget
    desk.observe_event(_event(
        "PENA", "Low importance", vehicle_idx=1,
        importance=70,
    ))

    published = _publish_all(desk)
    assert published == []


def test_full_race_replay_stays_inside_editorial_target():
    desk = EditorialDesk()
    published = []

    desk.observe_event(_event("SSTA", importance=70))
    published.extend(_publish_all(desk))

    for step in range(12):
        desk.observe_snapshot({
            "gap_front_ms": 6000 - step * 1200,
            "gap_behind_ms": 1500 + step * 1200,
            "player_tyre_wear": 5.0 + step * 11.0,
            "player_tyre_age": step * 2,
            "player_tyre_compound": "M",
            "player_fuel": 35.0 - step * 3.0,
            "player_ers_percent": 95.0 - step * 16.0,
        }, "race")
        published.extend(_publish_all(desk))

    for exchange in range(12):
        if exchange % 2 == 0:
            overtaker, overtaken, driver, target = 4, 7, "Player", "Rival"
        else:
            overtaker, overtaken, driver, target = 7, 4, "Rival", "Player"
        desk.observe_event(_event(
            "OVTK", driver, is_player=True, vehicle_idx=overtaker,
            overtaking_idx=overtaker, being_overtaken_idx=overtaken,
            target=target,
        ))
        published.extend(_publish_all(desk))

    for index in range(12):
        desk.observe_event(_event(
            "COLL", f"Driver {index}", vehicle_idx=index,
            vehicle1_idx=index, vehicle2_idx=index + 1,
            target=f"Driver {index + 1}",
        ))

    for index in range(5):
        desk.observe_event(_event(
            "PENA", f"Penalized {index}", vehicle_idx=12 + index,
            importance=90,
        ))
        published.extend(_publish_all(desk))

    for index in range(2):
        desk.observe_event(_event(
            "RTMT", f"Retired {index}", vehicle_idx=18 + index,
            importance=90,
        ))
        published.extend(_publish_all(desk))

    desk.observe_event(_event(
        "CHAMPIONSHIP", "Player", is_player=True, vehicle_idx=4,
        importance=85,
    ))
    desk.observe_event(_event(
        "MILESTONE", "Player", is_player=True, vehicle_idx=4,
        importance=90,
    ))
    desk.observe_event(_event("CHQF", importance=90))
    published.extend(_publish_all(desk))

    assert 15 <= len(published) <= 25
    assert sum(item.story.category in {
        "gap_trend", "tyre_status", "fuel_status", "ers_status",
    } for item in published) <= 6
    assert sum(item.story.category == "player_overtake" for item in published) == 2


# --- бюджет от дистанции гонки ---------------------------------------------

def test_scale_budgets_keeps_the_designed_range_for_a_full_race():
    from core.racefeed.editorial import (NONCRITICAL_CEILING, WORKING_BUDGET,
                                         ANALYTICS_BUDGET, scale_budgets)

    for laps in (None, 0, 25, 44, 78):
        working, ceiling, analytics = scale_budgets(laps)
        assert (working, ceiling) == (WORKING_BUDGET, NONCRITICAL_CEILING)
        assert analytics == ANALYTICS_BUDGET


@pytest.mark.parametrize("laps,expected_working,expected_ceiling", [
    (24, 24, 36),
    (10, 10, 15),
    (5, 6, 9),     # floor at MIN_WORKING_BUDGET
    (1, 6, 9),
])
def test_short_races_get_at_most_one_post_per_lap(laps, expected_working,
                                                  expected_ceiling):
    from core.racefeed.editorial import scale_budgets

    working, ceiling, _ = scale_budgets(laps)
    assert (working, ceiling) == (expected_working, expected_ceiling)


def test_analytics_caps_shrink_with_the_distance():
    from core.racefeed.editorial import scale_budgets

    _, _, half = scale_budgets(10)
    assert half == {"gap_trend": 1, "tyre_status": 1,
                    "fuel_status": 0, "ers_status": 0}
    _, _, sprint = scale_budgets(5)
    assert sum(sprint.values()) == 0


def test_desk_takes_the_distance_from_the_tick_snapshot():
    desk = EditorialDesk()
    assert desk._working_budget == 20

    desk.observe_snapshot({"total_laps": 8, "gap_front_ms": 1200}, "race")

    assert desk._working_budget == 8
    assert desk._noncritical_ceiling == 12


def test_distance_is_locked_in_for_the_session_and_cleared_on_reset():
    """Re-scaling mid-race would move the goalposts under publications already
    counted against the old budget."""
    desk = EditorialDesk()
    desk.observe_snapshot({"total_laps": 8, "gap_front_ms": 1200}, "race")
    desk.observe_snapshot({"total_laps": 50, "gap_front_ms": 1300}, "race")

    assert desk._working_budget == 8

    desk.clear()

    assert desk._working_budget == 20
    assert desk._race_distance is None


def test_short_race_stops_publishing_non_critical_stories_earlier():
    desk = EditorialDesk()
    desk.observe_snapshot({"total_laps": 6, "gap_front_ms": 1200}, "race")

    published = []
    for index in range(30):
        desk.observe_event(_event(
            "PENA", f"Driver {index}", vehicle_idx=index % 20, importance=70,
        ))
        published.extend(_publish_all(desk))

    # working budget 6, ceiling 9 — importance 70 is below
    # HIGH_IMPORTANCE_AFTER_BUDGET (80), so publishing stops at the budget
    assert len(published) <= 9

    # a critical publication still gets through afterwards
    desk.observe_event(_event("CHQF", importance=90))
    assert _publish_all(desk)


def test_graded_heavy_contact_still_reaches_the_feed():
    """Контакт игрока приезжает УЖЕ ОЦЕНЁННЫМ (core/engine.py::_grade_contact).

    Пока `COLL_HEAVY` не был перечислен в `_RACE_CONTROL_CODES`, самая тяжёлая
    авария заезда получала `category=None` и вылетала из ленты целиком — при том
    что средний `COLL` публиковался как раньше. То есть терялось ровно то
    событие, которое ценнее всех прочих.
    """
    desk = EditorialDesk()
    desk.observe_event(_event(
        "COLL_HEAVY", "Player", is_player=True, vehicle_idx=4,
        vehicle1_idx=4, vehicle2_idx=3, target="Driver B", importance=100,
    ))

    published = _publish_all(desk)
    assert [item.story.category for item in published] == ["incident"]


def test_light_contact_is_deliberately_not_a_feed_story():
    """Притирка без последствий — не новость.

    Обратная сторона предыдущего теста: градация существует, чтобы 32 COLL за
    гонку не превращались в 32 публикации. `COLL_LIGHT` по построению означает
    «прирост повреждений ниже порога и позиция не потеряна», и Incident Story на
    него заводить нельзя.
    """
    desk = EditorialDesk()
    desk.observe_event(_event(
        "COLL_LIGHT", "Player", is_player=True, vehicle_idx=4,
        vehicle1_idx=4, vehicle2_idx=3, target="Driver B", importance=25,
    ))

    assert _publish_all(desk) == []


def test_grades_of_one_contact_share_a_single_incident_story():
    """Три кода — один эпизод, если пара та же и окно то же.

    Иначе градация давала бы «контакт» и «аварию» об одном и том же ударе
    двумя постами.
    """
    desk = EditorialDesk()
    for code in ("COLL", "COLL_HEAVY"):
        desk.observe_event(_event(
            code, "Player", is_player=True, vehicle_idx=4,
            vehicle1_idx=4, vehicle2_idx=3, target="Driver B", importance=100,
        ))

    published = _publish_all(desk)
    assert len({item.story.id for item in published}) == 1
