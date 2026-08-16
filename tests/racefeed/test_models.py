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


def test_event_from_engine_dict_does_not_leak_enqueued_at_into_extra():
    raw = {"event_code": "PENA", "enqueued_at": 999.0, "extra_field": "keep"}
    e = Event.from_engine_dict(raw, session_type="race", is_player=False)
    assert e.enqueued_at == 999.0
    assert "enqueued_at" not in e.extra
    assert e.extra == {"extra_field": "keep"}


def test_radio_plumbing_never_reaches_the_llm_facts():
    """`extra` уходит в `facts` и оттуда в промпт репортёра, а также в
    `claim_fingerprint`. Счётчикам ситуаций из core/radio там не место: сказать
    репортёру им нечего, а изменение отпечатка тихо влияет на дедуп RaceFeed.

    Счётчики живут в ОДНОМ вложенном пространстве, поэтому фильтр — один ключ, и
    шестой счётчик не потребует правки ни фильтра, ни этого теста."""
    from core.radio.plumbing import attach

    raw = {
        "event_code": "SAFETY_CAR_DEPLOYED", "sc_type": "Safety car",
        "created_at": 111.0, "created_mono": 42.0,
        **attach(sc_episode=2, neighbour_idx=7, box_call_window=12,
                 rain_front_id=1, asked_at=999.0),
    }
    e = Event.from_engine_dict(raw, session_type="race", is_player=False)

    assert e.extra == {"sc_type": "Safety car"}


def test_a_future_plumbing_field_needs_no_filter_change():
    """Регрессия на саму конструкцию namespace: новое служебное поле не должно
    протечь только потому, что его забыли внести в список исключений."""
    from core.radio.plumbing import attach

    raw = {"event_code": "OVTK", "lap": 12,
           **attach(some_future_counter=5)}
    e = Event.from_engine_dict(raw, session_type="race", is_player=False)

    assert e.extra == {"lap": 12}


def test_damage_severity_is_a_journalistic_fact_and_stays():
    raw = {"event_code": "DAMAGE_WING", "damage_severity": 45}
    e = Event.from_engine_dict(raw, session_type="race", is_player=True)

    assert e.extra == {"damage_severity": 45}


def test_event_from_engine_dict_marks_the_players_team():
    raw = {
        "event_code": "OVTK", "driver": "Piastri", "team": "McLaren",
        "overtaking_idx": 5, "being_overtaken_idx": 6,
    }

    event = Event.from_engine_dict(
        raw, session_type="race", is_player=False, player_team="McLaren"
    )

    assert event.is_player_team is True


# --- имя игрока на событиях, которые публикуются без driver -----------------

def test_player_event_without_driver_gets_the_player_name():
    """PIT_EXIT / CAREER_PB are published with driver="" because the radio line
    addresses the player directly. RaceFeed writes in the third person, so it
    fills the name here — otherwise every post and thread says "пилот"."""
    event = Event.from_engine_dict(
        {"event_code": "PIT_EXIT", "driver": "", "vehicle_idx": 4},
        "race", True, player_name="Ландо Норрис",
    )
    assert event.driver == "Ландо Норрис"


def test_explicit_driver_is_never_overwritten():
    event = Event.from_engine_dict(
        {"event_code": "OVTK", "driver": "Пиастри"},
        "race", True, player_name="Ландо Норрис",
    )
    assert event.driver == "Пиастри"


def test_non_player_event_is_not_given_the_player_name():
    """Someone else's event keeps whatever the engine sent (unchanged
    behaviour) — the player's name must never be attached to it."""
    event = Event.from_engine_dict(
        {"event_code": "RTMT", "driver": ""},
        "race", False, player_name="Ландо Норрис",
    )
    assert event.driver == ""


def test_missing_player_name_stays_none_instead_of_empty_string():
    """"" would reach the LLM as a blank driver fact; None drops the fact."""
    event = Event.from_engine_dict(
        {"event_code": "PIT_EXIT", "driver": ""}, "race", True, player_name="",
    )
    assert event.driver is None
