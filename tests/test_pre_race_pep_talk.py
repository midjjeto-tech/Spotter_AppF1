from core.pre_race_pep_talk import facts, PODIUM, POINTS, STRUGGLED


def test_facts_none_when_no_last_race():
    assert facts(None) is None


def test_facts_podium_tier_for_positions_1_to_3():
    for pos in (1, 2, 3):
        result = facts({"final_position": pos, "track_name": "Monza"})
        assert result["tier"] == PODIUM
        assert result["position"] == pos
        assert result["track"] == "Monza"


def test_facts_points_tier_for_positions_4_to_10():
    for pos in (4, 7, 10):
        assert facts({"final_position": pos})["tier"] == POINTS


def test_facts_struggled_tier_for_position_11_plus():
    for pos in (11, 15, 20):
        assert facts({"final_position": pos})["tier"] == STRUGGLED


def test_facts_struggled_tier_when_no_final_position():
    result = facts({"final_position": None, "track_name": "Baku"})
    assert result["tier"] == STRUGGLED
    assert result["position"] is None


def test_facts_track_defaults_to_none_when_missing():
    result = facts({"final_position": 1})
    assert result["track"] is None
