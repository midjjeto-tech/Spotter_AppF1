"""RainAdvisoryTracker — однократный heads-up "дождь через N минут".
См. docs/superpowers/specs/2026-07-10-rain-advisory-design.md.
"""
from core.strategy_ai import weather_advisory
from core.strategy_ai.weather_advisory import (
    RAIN_ADVISORY_HORIZON_MIN, RainAdvisoryTracker,
)


def test_rain_in_horizon_announces_once():
    t = RainAdvisoryTracker()
    code = t.check({"minutes": 15, "rain_pct": 60, "weather": 3})
    assert code is not None
    # Число в текст не попадает: горизонт волатилен и подставляется резолвером.
    assert code == weather_advisory.CODE_RAIN_SOON


def test_does_not_repeat_same_episode():
    t = RainAdvisoryTracker()
    t.check({"minutes": 15, "rain_pct": 60, "weather": 3})
    phrase2 = t.check({"minutes": 14, "rain_pct": 60, "weather": 3})
    assert phrase2 is None


def test_no_forecast_returns_none_and_resets():
    t = RainAdvisoryTracker()
    t.check({"minutes": 15, "rain_pct": 60, "weather": 3})
    phrase = t.check(None)
    assert phrase is None


def test_new_episode_after_dry_gap_announces_again():
    t = RainAdvisoryTracker()
    t.check({"minutes": 15, "rain_pct": 60, "weather": 3})
    t.check(None)                                       # прогноз стал сухим
    phrase = t.check({"minutes": 20, "rain_pct": 70, "weather": 4})
    assert phrase is not None


def test_beyond_horizon_does_not_announce():
    t = RainAdvisoryTracker()
    phrase = t.check({"minutes": RAIN_ADVISORY_HORIZON_MIN + 1, "rain_pct": 80, "weather": 4})
    assert phrase is None


def test_exactly_at_horizon_announces():
    t = RainAdvisoryTracker()
    phrase = t.check({"minutes": RAIN_ADVISORY_HORIZON_MIN, "rain_pct": 80, "weather": 4})
    assert phrase is not None


def test_leaving_horizon_resets_for_new_episode():
    t = RainAdvisoryTracker()
    t.check({"minutes": 15, "rain_pct": 60, "weather": 3})
    t.check({"minutes": RAIN_ADVISORY_HORIZON_MIN + 5, "rain_pct": 60, "weather": 3})  # ушёл за горизонт
    phrase = t.check({"minutes": 25, "rain_pct": 60, "weather": 3})  # снова в горизонте
    assert phrase is not None


def test_manual_reset():
    t = RainAdvisoryTracker()
    t.check({"minutes": 15, "rain_pct": 60, "weather": 3})
    t.reset()
    phrase = t.check({"minutes": 15, "rain_pct": 60, "weather": 3})
    assert phrase is not None


def test_check_returns_the_bank_code_not_a_sentence():
    """Трекер решает «пора предупредить», формулировку даёт банк
    (core/radio/phrases.py::weather.rain_soon)."""
    t = RainAdvisoryTracker()
    assert t.check({"minutes": 5, "rain_pct": 90, "weather": 4}) ==         weather_advisory.CODE_RAIN_SOON


def test_the_returned_code_exists_in_the_bank():
    """Иначе трекер молча отдавал бы код, на который банк не отвечает."""
    from core.radio import phrases

    assert weather_advisory.CODE_RAIN_SOON in phrases.codes()


def test_horizon_is_not_baked_into_the_text():
    """Согласование числительного и само число переехали в резолвер: горизонт
    ВОЛАТИЛЕН, и «через 5 минут» через двадцать секунд уже неправда. Грамматика
    («1 минуту» / «3 минуты» / «15 минут») проверяется там же, в
    tests/test_radio_resolver.py."""
    from core.radio import phrases

    spec = phrases.spec_for(weather_advisory.CODE_RAIN_SOON)
    assert "minutes" in spec.volatile_fields
    assert not spec.required_fields
