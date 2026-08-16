from core.racefeed.editor import StoryMemory
from core.racefeed.engine import StoryBuilder
from core.racefeed.models import Event


def _event(event_code, driver="Norris", vehicle_idx=4, is_player=False,
           importance=80, is_player_team=False):
    return Event(
        event_code=event_code, session_type="race", driver=driver, team="McLaren",
        vehicle_idx=vehicle_idx, is_player=is_player, importance=importance,
        laps_remaining=20, description=f"{event_code} for {driver}",
        extra={"lap": 12}, enqueued_at=100.0,
        is_player_team=is_player_team,
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


def test_championship_code_maps_to_championship_category():
    builder = StoryBuilder(StoryMemory())
    story = builder.from_event(_event("CHAMPIONSHIP", driver="", is_player=True))
    assert story is not None
    assert story.category == "championship"


def test_milestone_code_maps_to_milestone_category():
    builder = StoryBuilder(StoryMemory())
    story = builder.from_event(_event("MILESTONE", driver="", is_player=True))
    assert story is not None
    assert story.category == "milestone"


def test_post_race_paddock_codes_map_to_distinct_categories():
    builder = StoryBuilder(StoryMemory())

    vote = builder.from_event(_event("RACEFEED_DOTD", driver="Alonso"))
    interview = builder.from_event(
        _event("POST_RACE_INTERVIEW", driver=None, vehicle_idx=None)
    )
    recap = builder.from_event(_event("RACE_RECAP", driver="You", is_player=True))

    assert vote.category == "driver_of_the_day"
    assert interview.category == "post_race_interview"
    assert recap.category == "race_recap"
    assert len({vote.id, interview.id, recap.id}) == 3


def test_from_event_maps_player_only_codes_when_is_player():
    builder = StoryBuilder(StoryMemory())
    story = builder.from_event(_event("PIT_EXIT", is_player=True))
    assert story is not None
    assert story.category == "player_pit_stop"
    assert story.facts["is_player"] is True


def test_from_event_ignores_player_only_codes_when_not_player():
    builder = StoryBuilder(StoryMemory())
    assert builder.from_event(_event("PIT_EXIT", is_player=False)) is None


def test_from_event_maps_garage_codes_for_the_players_team():
    builder = StoryBuilder(StoryMemory())

    story = builder.from_event(_event("OVTK", is_player_team=True))

    assert story.category == "player_overtake"


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


def test_from_event_session_lifecycle_codes_get_distinct_story_ids():
    builder = StoryBuilder(StoryMemory())
    ssta = _event("SSTA", driver=None, vehicle_idx=None)
    chqf = _event("CHQF", driver=None, vehicle_idx=None)
    send = _event("SEND", driver=None, vehicle_idx=None)
    s1 = builder.from_event(ssta)
    s2 = builder.from_event(chqf)
    s3 = builder.from_event(send)
    assert len({s1.id, s2.id, s3.id}) == 3


def test_safety_car_stages_evolve_one_story():
    builder = StoryBuilder(StoryMemory())
    deployed = _event(
        "SAFETY_CAR_DEPLOYED", driver=None, vehicle_idx=None, importance=90
    )
    deployed.extra["sc_type"] = "Safety car"
    ending = _event(
        "SAFETY_CAR_ENDING", driver=None, vehicle_idx=None, importance=90
    )
    ending.extra["sc_type"] = "Safety car"

    first = builder.from_event(deployed)
    second = builder.from_event(ending)

    assert first is second


def test_from_event_merges_extra_fields_into_facts():
    builder = StoryBuilder(StoryMemory())
    event = Event(
        event_code="PENA", session_type="race", driver="Norris", team="McLaren",
        vehicle_idx=4, is_player=False, importance=85, laps_remaining=20,
        description="5s penalty", extra={"infringement_type": 7, "time_seconds": 5},
        enqueued_at=100.0,
    )
    story = builder.from_event(event)
    assert story.facts["infringement_type"] == 7
    assert story.facts["time_seconds"] == 5


def test_from_event_maps_career_pb_codes_to_player_progression():
    builder = StoryBuilder(StoryMemory())
    story = builder.from_event(_event("CAREER_PB", is_player=True))
    assert story is not None
    assert story.category == "player_progression"


def test_from_event_maps_career_sector_pb_to_player_progression():
    builder = StoryBuilder(StoryMemory())
    story = builder.from_event(_event("CAREER_SECTOR_PB", is_player=True))
    assert story is not None
    assert story.category == "player_progression"


def test_from_event_maps_career_recap_to_player_progression():
    builder = StoryBuilder(StoryMemory())
    story = builder.from_event(_event("CAREER_RECAP", is_player=True))
    assert story is not None
    assert story.category == "player_progression"


def test_from_event_ignores_career_codes_when_not_player():
    builder = StoryBuilder(StoryMemory())
    assert builder.from_event(_event("CAREER_PB", is_player=False)) is None
    assert builder.from_event(_event("CAREER_SECTOR_PB", is_player=False)) is None
    assert builder.from_event(_event("CAREER_RECAP", is_player=False)) is None


def test_from_event_career_codes_for_same_driver_get_distinct_story_ids():
    memory = StoryMemory()
    builder = StoryBuilder(memory)
    s1 = builder.from_event(_event("CAREER_PB", is_player=True))
    s2 = builder.from_event(_event("CAREER_SECTOR_PB", is_player=True))
    s3 = builder.from_event(_event("CAREER_RECAP", is_player=True))
    assert len({s1.id, s2.id, s3.id}) == 3


def test_from_event_repeated_career_pb_for_same_driver_still_evolves_as_one_story():
    memory = StoryMemory()
    builder = StoryBuilder(memory)
    s1 = builder.from_event(_event("CAREER_PB", is_player=True))
    s2 = builder.from_event(_event("CAREER_PB", is_player=True))
    assert s1 is s2


def test_two_safety_car_episodes_are_two_stories():
    """Второй выезд машины безопасности — не продолжение первого.

    Номер эпизода движок считает только на деплое и проставляет всем трём кодам
    (core/engine.py). Пока ключ строился по одному `sc_type`, обе развязки
    склеивались: второй эпизод получал стадию и накопленные факты первого, и
    репортёр писал новую развязку, глядя на старые факты.
    """
    from core.radio.plumbing import attach

    builder = StoryBuilder(StoryMemory())

    def sc(code: str, episode: int) -> Event:
        return Event.from_engine_dict(
            {"event_code": code, "sc_type": "Safety car", "importance": 90,
             **attach(sc_episode=episode)},
            session_type="race", is_player=False)

    first = builder.from_event(sc("SAFETY_CAR_DEPLOYED", 1))
    first_clear = builder.from_event(sc("SAFETY_CAR_CLEAR", 1))
    second = builder.from_event(sc("SAFETY_CAR_DEPLOYED", 2))

    # Стадии ОДНОГО эпизода по-прежнему делят историю.
    assert first is first_clear
    # А разные эпизоды — нет.
    assert second is not first
    assert second.id != first.id


def test_a_safety_car_without_an_episode_number_keeps_the_old_key():
    """Событие без служебного номера (старый архив, чужой источник) не должно
    ронять ключ в `...:eNone` — оно возвращается к прежнему поведению."""
    builder = StoryBuilder(StoryMemory())
    event = Event.from_engine_dict(
        {"event_code": "SAFETY_CAR_DEPLOYED", "sc_type": "Safety car",
         "importance": 90},
        session_type="race", is_player=False)

    story = builder.from_event(event)

    assert story.story_key == ("safety_car", "Safety car")


def test_the_episode_number_never_reaches_the_reporter():
    """Ключ уточнили — факты не тронули. Иначе номер эпизода уехал бы в промпт
    LLM и сдвинул `claim_fingerprint`."""
    from core.radio.plumbing import attach

    builder = StoryBuilder(StoryMemory())
    story = builder.from_event(Event.from_engine_dict(
        {"event_code": "SAFETY_CAR_DEPLOYED", "sc_type": "Safety car",
         "importance": 90, **attach(sc_episode=3)},
        session_type="race", is_player=False))

    assert "sc_episode" not in story.facts
    assert "radio" not in story.facts
