"""Буфер ошибок по кругам (core/coach_ai/corner_log.py).

Два потребителя с намеренно разными правилами: дебриф получает всё, эфир —
только повтор.
"""
from core.coach_ai.corner_log import CornerLog
from core.coach_ai.models import CornerMistake


def _m(lap, kind="lockup", corner_id=3, phase="braking", wheel="fl", peak=0.5):
    return CornerMistake(kind=kind, wheel=wheel, corner_id=corner_id,
                         corner_name=f"Turn {corner_id}", phase=phase, lap=lap,
                         peak=peak, duration_s=0.3, speed_kmh=180)


def test_single_mistake_never_triggers_live_advice():
    log = CornerLog()
    assert log.add(_m(1)) is None


def test_three_of_last_five_laps_triggers_advice():
    log = CornerLog()
    assert log.add(_m(1)) is None
    assert log.add(_m(2)) is None
    advice = log.add(_m(3))
    assert advice is not None
    assert advice.kind == "lockup"
    assert advice.corner_id == 3
    assert advice.wheel == "fl"


def test_same_lap_repeats_do_not_count_as_separate_laps():
    """Три блокировки на одном круге — это один круг, а не три."""
    log = CornerLog()
    log.add(_m(1))
    log.add(_m(1))
    assert log.add(_m(1)) is None


def test_mistakes_spread_beyond_five_laps_do_not_trigger():
    log = CornerLog()
    log.add(_m(1))
    log.add(_m(4))
    assert log.add(_m(9)) is None


def test_different_corners_are_tracked_separately():
    log = CornerLog()
    log.add(_m(1, corner_id=3))
    log.add(_m(2, corner_id=7))
    assert log.add(_m(3, corner_id=3)) is None


def test_different_phases_in_one_corner_are_tracked_separately():
    """Блокировка на торможении и снос в апексе третьего — разные проблемы."""
    log = CornerLog()
    log.add(_m(1, phase="braking"))
    log.add(_m(2, phase="apex"))
    assert log.add(_m(3, phase="braking")) is None


def test_advice_is_not_repeated_for_the_same_signature_too_soon():
    log = CornerLog()
    log.add(_m(1))
    log.add(_m(2))
    assert log.add(_m(3)) is not None
    assert log.add(_m(4)) is None, "подряд второй раз о том же — молчим"


def test_advice_returns_after_the_cooldown():
    log = CornerLog()
    for lap in (1, 2, 3):
        log.add(_m(lap))
    for lap in (4, 5, 6, 7):
        log.add(_m(lap))
    assert log.add(_m(8)) is not None


def test_all_mistakes_are_kept_for_the_debrief_map():
    log = CornerLog()
    log.add(_m(1))
    log.add(_m(1))
    log.add(_m(2, corner_id=7))
    rows = log.map_rows()
    assert len(rows) == 3
    assert {r["corner_id"] for r in rows} == {3, 7}


def test_top_corners_ranked_by_count():
    log = CornerLog()
    for lap in (1, 2, 3):
        log.add(_m(lap, corner_id=3))
    log.add(_m(1, corner_id=7))
    top = log.top_corners(limit=2)
    assert top[0]["corner_id"] == 3
    assert top[0]["count"] == 3
    assert top[0]["kinds"] == {"lockup": 3}
    assert top[1]["corner_id"] == 7


def test_reset_clears_everything():
    log = CornerLog()
    log.add(_m(1))
    log.reset()
    assert log.map_rows() == []
    assert log.top_corners() == []
