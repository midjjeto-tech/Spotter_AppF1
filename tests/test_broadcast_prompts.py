"""tests/test_broadcast_prompts.py — track fact injection into LLM prompt."""
from core.broadcast.prompts import _format_facts, _format_track_facts, build_prompt


def _event(track=None):
    return {
        "race_ai_type": "attack",
        "driver": "VER",
        "race_ai_data": {
            "gap": 0.5,
            "drs": True,
            "closing": True,
            "confidence": 0.9,
            "track": track,
        },
    }


# --- _format_track_facts unit tests ---

def test_no_track_returns_empty():
    assert _format_track_facts({}) == []


def test_sector_always_included():
    lines = _format_track_facts({"sector": 2, "phase": "straight", "defense_advice": "none"})
    assert any("Сектор: 2" in l for l in lines)


def test_corner_with_type_label():
    lines = _format_track_facts({"corner": "Turn 1", "corner_type": "slow",
                                  "phase": "entry", "sector": 1, "defense_advice": "none"})
    joined = " ".join(lines)
    assert "Turn 1" in joined
    assert "медленный" in joined


def test_straight_phase_not_shown():
    lines = _format_track_facts({"corner": None, "phase": "straight",
                                  "sector": 1, "defense_advice": "none"})
    assert not any("Фаза" in l for l in lines)


def test_non_straight_phase_shown():
    lines = _format_track_facts({"phase": "braking", "sector": 1, "defense_advice": "none"})
    assert any("торможение" in l for l in lines)


def test_advice_none_not_shown():
    lines = _format_track_facts({"phase": "straight", "sector": 1, "defense_advice": "none"})
    assert not any("Линия" in l for l in lines)


def test_advice_cover_inside_shown():
    lines = _format_track_facts({"phase": "entry", "sector": 1, "defense_advice": "cover_inside"})
    assert any("закрыть изнутри" in l for l in lines)


def test_advice_hold_line_shown():
    lines = _format_track_facts({"phase": "apex", "sector": 2, "defense_advice": "hold_line"})
    assert any("держать линию" in l for l in lines)


# --- _format_facts integration tests ---

def test_no_track_no_track_lines():
    facts = _format_facts(_event(track=None))
    assert "Поворот" not in facts
    assert "Фаза" not in facts
    assert "Линия" not in facts


def test_track_corner_in_facts():
    track = {"corner": "Turn 1", "corner_type": "slow", "phase": "entry",
             "sector": 1, "defense_advice": "inside"}
    facts = _format_facts(_event(track=track))
    assert "Turn 1" in facts
    assert "медленный" in facts


def test_track_phase_in_facts():
    track = {"corner": "La Source", "corner_type": "hairpin", "phase": "braking",
             "sector": 1, "defense_advice": "cover_inside"}
    facts = _format_facts(_event(track=track))
    assert "торможение" in facts


def test_track_advice_in_facts():
    track = {"corner": "Turn 3", "corner_type": "fast", "phase": "apex",
             "sector": 2, "defense_advice": "hold_line"}
    facts = _format_facts(_event(track=track))
    assert "держать линию" in facts


def test_straight_no_phase_line_in_facts():
    track = {"corner": None, "corner_type": None, "phase": "straight",
             "sector": 2, "defense_advice": "none"}
    facts = _format_facts(_event(track=track))
    assert "Фаза" not in facts
    assert "Линия" not in facts
    assert "Сектор: 2" in facts


# --- build_prompt integration ---

def test_build_prompt_contains_track():
    track = {"corner": "Maggots", "corner_type": "fast", "phase": "apex",
             "sector": 2, "defense_advice": "hold_line"}
    prompt = build_prompt(_event(track=track), persona="tv", recent_phrases=[])
    assert "Maggots" in prompt
    assert "держать линию" in prompt


def test_build_prompt_no_track_no_corner():
    prompt = build_prompt(_event(track=None), persona="tv", recent_phrases=[])
    assert "Поворот" not in prompt
