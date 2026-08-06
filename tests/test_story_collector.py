from core.race_story import RaceStoryCollector


def test_start_position_set_once():
    c = RaceStoryCollector()
    c.note_start_position(6)
    c.note_start_position(4)                      # игнор — старт уже зафиксирован
    f = c.facts(final_position=4, laps=[])
    assert f["start_position"] == 6
    assert f["positions_gained"] == 2            # 6 - 4


def test_only_notable_events_kept():
    c = RaceStoryCollector()
    c.note_event("DRSE", 5)                       # не значимое — игнор
    c.note_event("OVTK", 12, driver="player", target="Албон")
    f = c.facts(final_position=3, laps=[])
    assert len(f["overtakes"]) == 1
    assert f["overtakes"][0]["target"] == "Албон"


def test_best_lap_picks_min_positive():
    c = RaceStoryCollector()
    laps = [{"lap": 1, "last_lap_ms": 95000},
            {"lap": 2, "last_lap_ms": 93200},
            {"lap": 3, "last_lap_ms": 0}]        # 0 игнор
    f = c.facts(final_position=1, laps=laps)
    assert f["best_lap_ms"] == 93200
    assert f["best_lap_number"] == 2


def test_incidents_collected():
    c = RaceStoryCollector()
    c.note_event("PENA", 22, driver="player")
    f = c.facts(final_position=5, laps=[])
    assert f["incidents"][0]["code"] == "PENA"
    assert f["incidents"][0]["lap"] == 22


def test_coach_state_merged():
    c = RaceStoryCollector()
    f = c.facts(final_position=4, laps=[],
                coach_state={"weak_sector": 2, "consistency_score": 0.9})
    assert f["weak_sector"] == 2
    assert f["consistency"] == 0.9


def test_event_cap():
    c = RaceStoryCollector()
    for i in range(20):
        c.note_event("OVTK", i, target=f"D{i}")
    f = c.facts(final_position=1, laps=[])
    assert len(f["overtakes"]) <= 12


def test_reset_clears():
    c = RaceStoryCollector()
    c.note_start_position(6)
    c.note_event("OVTK", 1, target="X")
    c.reset()
    f = c.facts(final_position=2, laps=[])
    assert f["start_position"] is None
    assert f["overtakes"] == []


def test_facts_includes_weak_sector_vs_f1():
    from core.race_story import RaceStoryCollector
    c = RaceStoryCollector()
    facts = c.facts(final_position=4, laps=[], weak_sector_vs_f1=2)
    assert facts["weak_sector_vs_f1"] == 2


def test_facts_weak_sector_vs_f1_defaults_to_none():
    from core.race_story import RaceStoryCollector
    c = RaceStoryCollector()
    facts = c.facts(final_position=4, laps=[])
    assert facts["weak_sector_vs_f1"] is None


def test_facts_includes_vs_last_visit():
    from core.race_story import RaceStoryCollector
    c = RaceStoryCollector()
    vlv = {"laptime_delta_ms": -500, "position_delta": 2, "last_visit_date": "2026-01-01"}
    facts = c.facts(final_position=4, laps=[], vs_last_visit=vlv)
    assert facts["vs_last_visit"] == vlv


def test_facts_vs_last_visit_defaults_to_none():
    from core.race_story import RaceStoryCollector
    c = RaceStoryCollector()
    facts = c.facts(final_position=4, laps=[])
    assert facts["vs_last_visit"] is None


def test_facts_includes_career_stats():
    from core.race_story import RaceStoryCollector
    c = RaceStoryCollector()
    cs = {"total_races": 10, "wins": 1, "podiums": 3, "avg_position": 7.5}
    facts = c.facts(final_position=4, laps=[], career_stats=cs)
    assert facts["career_stats"] == cs


def test_facts_career_stats_defaults_to_none():
    from core.race_story import RaceStoryCollector
    c = RaceStoryCollector()
    facts = c.facts(final_position=4, laps=[])
    assert facts["career_stats"] is None


def test_facts_qualifying_suppresses_start_position_and_gained_but_keeps_final():
    c = RaceStoryCollector()
    c.note_start_position(6)
    f = c.facts(final_position=4, laps=[], session_type="qualifying")
    assert f["start_position"] is None
    assert f["positions_gained"] is None
    assert f["final_position"] == 4
    assert f["session_type"] == "qualifying"


def test_facts_practice_suppresses_all_position_facts():
    c = RaceStoryCollector()
    c.note_start_position(6)
    f = c.facts(final_position=4, laps=[], session_type="practice")
    assert f["start_position"] is None
    assert f["positions_gained"] is None
    assert f["final_position"] is None
    assert f["session_type"] == "practice"


def test_facts_qualifying_and_practice_suppress_career_facts():
    cs = {"total_races": 10, "wins": 1, "podiums": 3, "avg_position": 7.5}
    vlv = {"laptime_delta_ms": -500, "position_delta": 2, "last_visit_date": "2026-01-01"}
    for session_type in ("qualifying", "practice"):
        c = RaceStoryCollector()
        f = c.facts(final_position=4, laps=[], session_type=session_type,
                    career_stats=cs, vs_last_visit=vlv)
        assert f["career_stats"] is None
        assert f["vs_last_visit"] is None


def test_facts_race_session_type_unchanged():
    c = RaceStoryCollector()
    c.note_start_position(6)
    f = c.facts(final_position=4, laps=[], session_type="race")
    assert f["start_position"] == 6
    assert f["positions_gained"] == 2
    assert f["final_position"] == 4
    assert f["session_type"] == "race"
