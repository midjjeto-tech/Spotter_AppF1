import pytest

from core.racefeed.generators import render, render_with_source
from core.racefeed.models import Candidate, Story


def _story_and_candidate():
    story = Story(id="s1", story_key=("penalty", "Norris"), category="penalty",
                   session_type="race", facts={"driver": "Norris", "seconds": 5})
    candidate = Candidate(
        story_id="s1", story_key=("penalty", "Norris"), category="penalty",
        reporter_id="race_control", base_importance=80, priority="incident",
        publish_after=(2.0, 5.0), expires_at=0.0, update_policy="supersede",
    )
    return story, candidate


class _FakeAI:
    def __init__(self, available=True, text="Norris receives a 5s penalty."):
        self.available = available
        self._text = text
        self.calls = []

    def generate_with_system(self, system, user):
        self.calls.append((system, user))
        return self._text


def test_render_returns_none_when_ai_unavailable():
    story, candidate = _story_and_candidate()
    ai = _FakeAI(available=False)
    assert render(candidate, story, ai) is None
    assert ai.calls == []


def test_render_returns_none_when_llm_returns_empty():
    story, candidate = _story_and_candidate()
    ai = _FakeAI(text="")
    assert render(candidate, story, ai) is None


def test_render_returns_none_when_llm_returns_none():
    story, candidate = _story_and_candidate()
    ai = _FakeAI(text=None)
    assert render(candidate, story, ai) is None


def test_render_returns_text_and_uses_reporter_system_prompt():
    story, candidate = _story_and_candidate()
    ai = _FakeAI(text="Norris receives a 5s penalty.")
    result = render(candidate, story, ai)
    assert result == "Norris receives a 5s penalty."
    assert len(ai.calls) == 1
    system, user = ai.calls[0]
    assert "Race Control" in system
    assert "penalty" in user


def test_paddock_vote_has_deterministic_fallback_when_ai_is_unavailable():
    story = Story(
        id="dotd|Alonso",
        story_key=("driver_of_the_day", "Alonso"),
        category="driver_of_the_day",
        session_type="race",
        facts={
            "dotd_driver": "Alonso",
            "dotd_pct": 47,
            "dotd_overtakes": 6,
            "dotd_gained": 8,
        },
    )
    candidate = Candidate(
        story_id=story.id,
        story_key=story.story_key,
        category=story.category,
        reporter_id="paddock",
        base_importance=88,
        priority="analysis",
        publish_after=(0.0, 0.0),
        expires_at=100.0,
        update_policy="ignore_if_pending",
    )

    text = render(candidate, story, _FakeAI(available=False))

    assert "Alonso" in text
    assert "47%" in text
    assert "6 обгонов" in text


def test_race_recap_has_deterministic_fact_fallback():
    candidate, story = _critical(
        "race_recap",
        {
            "driver": "Норрис", "finish_position": 2, "grid_position": 10,
            "overtakes": 6, "points": 18,
        },
        reporter_id="paddock",
    )

    text, source = render_with_source(candidate, story, _FakeAI(available=False))

    assert "P2 с P10" in text
    assert "6 обгонов" in text
    assert "18 очков" in text
    assert source == "fallback"


def _critical(category, facts, reporter_id="race_control"):
    story = Story(id="s1", story_key=(category, "x"), category=category,
                  session_type="race", facts=facts)
    candidate = Candidate(
        story_id="s1", story_key=story.story_key, category=category,
        reporter_id=reporter_id, base_importance=80, priority="incident",
        publish_after=(0.0, 0.0), expires_at=0.0, update_policy="supersede",
    )
    return candidate, story


@pytest.mark.parametrize("category,facts,expected", [
    ("flag", {"event_code": "CHQF"}, "Клетчатый флаг"),
    ("flag", {"event_code": "RDFL"}, "Красный флаг"),
    ("retirement", {"event_code": "RTMT", "driver": "Норрис"}, "Норрис сходит"),
    ("safety_car", {"event_code": "SAFETY_CAR_DEPLOYED",
                    "sc_type": "Virtual Safety Car"}, "Виртуальная машина"),
    ("safety_car", {"event_code": "SAFETY_CAR_CLEAR"}, "Трасса чиста"),
    ("championship", {"event_code": "CHAMPIONSHIP", "driver": "Норрис",
                      "player_position": 2, "player_points": 40,
                      "rival": "Ферстаппен", "gap_to_rival": 12},
     "Разрыв с Ферстаппен"),
    ("milestone", {"event_code": "MILESTONE", "driver": "Норрис",
                   "label": "Первая победа в карьере!", "position": 1},
     "Первая победа в карьере!"),
])
def test_critical_categories_fall_back_to_a_template_without_llm(
        category, facts, expected):
    candidate, story = _critical(category, facts)
    text, source = render_with_source(candidate, story, _FakeAI(available=False))
    assert expected in text
    assert source == "fallback"


@pytest.mark.parametrize("category,facts,expected", [
    ("penalty", {"driver": "Норрис", "is_player": True, "time_seconds": 5,
                 "lap_num": 12}, "5 секунд"),
    ("player_overtake", {"driver": "Норрис", "is_player": True,
                         "target": "Пиастри"}, "проходит Пиастри"),
    ("player_pit_stop", {"driver": "", "is_player": True,
                         "tyre_compound": "Medium"}, "пилот возвращается"),
    ("player_fastest_lap", {"driver": "Норрис", "is_player": True,
                            "lap_time": 91.234}, "1:31.234"),
])
def test_player_critical_categories_fall_back_to_a_template(
        category, facts, expected):
    candidate, story = _critical(category, facts, reporter_id="players_garage")
    text, source = render_with_source(candidate, story, _FakeAI(available=False))
    assert expected in text
    assert source == "fallback"


def test_same_player_category_has_no_fallback_for_another_driver():
    """PENA without is_player isn't a critical publication (see
    editorial.is_critical_story) — it stays LLM-only and is dropped silently."""
    candidate, story = _critical("penalty", {"driver": "Норрис", "time_seconds": 5})
    assert render_with_source(candidate, story, _FakeAI(available=False)) == (None, "")


@pytest.mark.parametrize("category", ["gap_trend", "tyre_status", "fuel_status",
                                      "ers_status"])
def test_analytics_categories_stay_llm_only(category):
    candidate, story = _critical(category, {"is_player": True, "gap_front_ms": 1200},
                                 reporter_id="spotter_analytics")
    assert render(candidate, story, _FakeAI(available=False)) is None


def test_fallback_also_covers_a_failing_provider_not_just_an_offline_one():
    class _ExplodingAI:
        available = True

        def generate_with_system(self, system, user):
            raise RuntimeError("provider down")

    candidate, story = _critical("flag", {"event_code": "CHQF"})
    text, source = render_with_source(candidate, story, _ExplodingAI())
    assert "Гонка завершена" in text
    assert source == "fallback"


def test_llm_path_reports_its_source():
    story, candidate = _story_and_candidate()
    assert render_with_source(candidate, story, _FakeAI())[1] == "llm"
