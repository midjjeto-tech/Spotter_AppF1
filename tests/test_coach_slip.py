"""Детекторы срывов сцепления (core/coach_ai/slip.py).

Кадры синтетические: детектор обязан быть чистой функцией от потока
телеметрии, без обращений к движку.
"""
import pytest

from core.coach_ai.slip import SlipDetector


def _frame(**kw):
    """Один кадр MotionEx + вводов пилота. Всё нейтрально, если не переопределено."""
    base = {
        "slip_ratio": {"rl": 0.0, "rr": 0.0, "fl": 0.0, "fr": 0.0},
        "slip_angle": {"rl": 0.0, "rr": 0.0, "fl": 0.0, "fr": 0.0},
        "yaw_rate": 0.0,
        "front_wheels_angle": 0.0,
        "throttle_pct": 0.0,
        "brake_pct": 0.0,
        "steer": 0.0,
        "speed_kmh": 200,
        "surface": {"rl": "tarmac", "rr": "tarmac", "fl": "tarmac", "fr": "tarmac"},
    }
    base.update(kw)
    return base


class _Clock:
    """Монотонное время между вызовами _feed — иначе второй прогон начинался бы
    с нуля и длительность события считалась бы отрицательной."""

    def __init__(self) -> None:
        self.t = 0.0


def _feed(detector, frame, seconds, clock, step=0.05, lap=1,
          corner=(3, "Turn 3"), phase="braking"):
    """Прогнать один и тот же кадр `seconds` секунд. Возвращает все события."""
    out = []
    end = clock.t + seconds
    while clock.t < end:
        out.extend(detector.tick(
            frame, now=clock.t, lap=lap,
            corner_id=corner[0], corner_name=corner[1], phase=phase))
        clock.t += step
    return out


def test_sustained_front_lockup_under_braking_is_reported_on_release():
    d, c = SlipDetector(), _Clock()
    braking = _frame(brake_pct=100.0,
                     slip_ratio={"rl": 0.0, "rr": 0.0, "fl": -0.5, "fr": -0.05})

    during = _feed(d, braking, seconds=0.4, clock=c)
    assert during == [], "событие не должно публиковаться, пока срыв идёт"

    after = _feed(d, _frame(), seconds=0.1, clock=c)
    assert len(after) == 1
    ev = after[0]
    assert ev.kind == "lockup"
    assert ev.wheel == "fl"
    assert ev.corner_id == 3
    assert ev.phase == "braking"
    assert ev.peak == pytest.approx(0.5)
    assert ev.duration_s >= 0.3


def test_brief_slip_below_duration_threshold_is_ignored():
    d, c = SlipDetector(), _Clock()
    _feed(d, _frame(brake_pct=100.0,
                    slip_ratio={"rl": 0.0, "rr": 0.0, "fl": -0.5, "fr": 0.0}),
          seconds=0.05, clock=c)
    assert _feed(d, _frame(), seconds=0.1, clock=c) == []


def test_lockup_requires_brake_pressed():
    d, c = SlipDetector(), _Clock()
    _feed(d, _frame(brake_pct=0.0,
                    slip_ratio={"rl": 0.0, "rr": 0.0, "fl": -0.5, "fr": 0.0}),
          seconds=0.4, clock=c)
    assert _feed(d, _frame(), seconds=0.1, clock=c) == []


def test_rear_wheelspin_on_throttle_is_reported():
    d, c = SlipDetector(), _Clock()
    _feed(d, _frame(throttle_pct=90.0,
                    slip_ratio={"rl": 0.35, "rr": 0.30, "fl": 0.0, "fr": 0.0}),
          seconds=0.4, clock=c, phase="exit")
    events = _feed(d, _frame(), seconds=0.1, clock=c)
    assert len(events) == 1
    assert events[0].kind == "wheelspin"
    assert events[0].wheel == "rl"
    assert events[0].phase == "exit"


def test_front_slip_under_throttle_is_not_wheelspin():
    """Пробуксовка — про ведущую ось. Передние колёса под газом не буксуют."""
    d, c = SlipDetector(), _Clock()
    _feed(d, _frame(throttle_pct=90.0,
                    slip_ratio={"rl": 0.0, "rr": 0.0, "fl": 0.35, "fr": 0.35}),
          seconds=0.4, clock=c)
    assert _feed(d, _frame(), seconds=0.1, clock=c) == []


def test_understeer_needs_steering_and_missing_yaw():
    d, c = SlipDetector(), _Clock()
    frame = _frame(steer=0.6, yaw_rate=0.02,
                   slip_angle={"rl": 0.02, "rr": 0.02, "fl": 0.18, "fr": 0.17})
    _feed(d, frame, seconds=0.5, clock=c, phase="entry")
    events = _feed(d, _frame(), seconds=0.1, clock=c)
    assert len(events) == 1
    assert events[0].kind == "understeer"
    assert events[0].wheel is None


def test_high_front_slip_without_steering_is_not_understeer():
    d, c = SlipDetector(), _Clock()
    frame = _frame(steer=0.0, yaw_rate=0.0,
                   slip_angle={"rl": 0.02, "rr": 0.02, "fl": 0.18, "fr": 0.17})
    _feed(d, frame, seconds=0.5, clock=c)
    assert _feed(d, _frame(), seconds=0.1, clock=c) == []


def test_oversteer_reported_on_counter_steer():
    d, c = SlipDetector(), _Clock()
    # Руль вправо, кузов разворачивает влево — контр-руление.
    frame = _frame(steer=0.5, yaw_rate=-0.6,
                   slip_angle={"rl": 0.22, "rr": 0.21, "fl": 0.03, "fr": 0.03})
    _feed(d, frame, seconds=0.4, clock=c, phase="exit")
    events = _feed(d, _frame(), seconds=0.1, clock=c)
    assert len(events) == 1
    assert events[0].kind == "oversteer"


def test_rear_slip_while_steering_into_the_turn_is_not_oversteer():
    """Задняя ось скользит, но кузов идёт туда же, куда руль — это обычный
    поворот на пределе, а не занос."""
    d, c = SlipDetector(), _Clock()
    frame = _frame(steer=0.5, yaw_rate=0.6,
                   slip_angle={"rl": 0.22, "rr": 0.21, "fl": 0.03, "fr": 0.03})
    _feed(d, frame, seconds=0.4, clock=c)
    assert _feed(d, _frame(), seconds=0.1, clock=c) == []


def test_reset_drops_event_in_progress():
    d, c = SlipDetector(), _Clock()
    _feed(d, _frame(brake_pct=100.0,
                    slip_ratio={"rl": 0.0, "rr": 0.0, "fl": -0.5, "fr": 0.0}),
          seconds=0.4, clock=c)
    d.reset()
    assert _feed(d, _frame(), seconds=0.1, clock=c) == []


def test_two_wheels_off_track_is_reported():
    d, c = SlipDetector(), _Clock()
    off = _frame(surface={"rl": "grass", "rr": "tarmac",
                          "fl": "grass", "fr": "tarmac"})
    _feed(d, off, seconds=0.4, clock=c, phase="exit")
    events = _feed(d, _frame(), seconds=0.1, clock=c)
    assert len(events) == 1
    assert events[0].kind == "offtrack"
    assert events[0].wheel is None


def test_one_wheel_off_track_is_not_reported():
    d, c = SlipDetector(), _Clock()
    off = _frame(surface={"rl": "tarmac", "rr": "tarmac",
                          "fl": "grass", "fr": "tarmac"})
    _feed(d, off, seconds=0.4, clock=c)
    assert _feed(d, _frame(), seconds=0.1, clock=c) == []


def test_rumble_strip_is_not_off_track():
    d, c = SlipDetector(), _Clock()
    kerb = _frame(surface={"rl": "rumble_strip", "rr": "rumble_strip",
                           "fl": "rumble_strip", "fr": "rumble_strip"})
    _feed(d, kerb, seconds=0.5, clock=c)
    assert _feed(d, _frame(), seconds=0.1, clock=c) == []


def test_lockup_and_understeer_are_tracked_independently():
    """Разные виды ошибок могут идти одновременно и не должны гасить друг
    друга: заблокировать переднее на входе и снести машину там же — две разные
    проблемы с разными указаниями пилоту."""
    d, c = SlipDetector(), _Clock()
    both = _frame(brake_pct=100.0, steer=0.6, yaw_rate=0.02,
                  slip_ratio={"rl": 0.0, "rr": 0.0, "fl": -0.5, "fr": 0.0},
                  slip_angle={"rl": 0.02, "rr": 0.02, "fl": 0.18, "fr": 0.17})
    _feed(d, both, seconds=0.5, clock=c)
    events = _feed(d, _frame(), seconds=0.3, clock=c)
    assert {e.kind for e in events} == {"lockup", "understeer"}


# --------------------------------------------------------------------------- #
# Зависшие срывы.
# Разбор живого заезда 2026-08-11: в карте ошибок лежал `lockup` длиной 9,7 с и
# `oversteer` 3,2 с. Автомат не закрывался, а место и фаза пишутся на НАЧАЛЕ
# срыва — поэтому девятисекундное событие получало прописку на прямой и уносило
# с собой привязку всех поворотов, через которые проехало.
# --------------------------------------------------------------------------- #

def test_slip_longer_than_the_cap_is_discarded():
    from core.coach_ai.slip import MAX_EVENT_DURATION_S
    d, c = SlipDetector(), _Clock()
    braking = _frame(brake_pct=100.0,
                     slip_ratio={"rl": 0.0, "rr": 0.0, "fl": -0.5, "fr": -0.05})

    during = _feed(d, braking, seconds=MAX_EVENT_DURATION_S + 1.0, clock=c)
    after = _feed(d, _frame(), seconds=0.3, clock=c)

    assert during == []
    assert after == [], "девятисекундная «блокировка» — сбитый замер, не ошибка"


def test_slip_is_discarded_when_the_lap_changes_under_it():
    """Событие не имеет права переползти через линию старта на чужой круг."""
    d, c = SlipDetector(), _Clock()
    braking = _frame(brake_pct=100.0,
                     slip_ratio={"rl": 0.0, "rr": 0.0, "fl": -0.5, "fr": -0.05})

    _feed(d, braking, seconds=0.4, clock=c, lap=1)
    after = _feed(d, _frame(), seconds=0.3, clock=c, lap=2)

    assert after == []


def test_a_normal_slip_still_survives_both_guards():
    """Предохранители не должны съесть обычную ошибку."""
    d, c = SlipDetector(), _Clock()
    braking = _frame(brake_pct=100.0,
                     slip_ratio={"rl": 0.0, "rr": 0.0, "fl": -0.5, "fr": -0.05})

    _feed(d, braking, seconds=0.5, clock=c, lap=4)
    after = _feed(d, _frame(), seconds=0.1, clock=c, lap=4)

    assert len(after) == 1
    assert after[0].kind == "lockup"
    assert after[0].corner_id == 3


def test_a_stuck_signal_produces_one_discard_not_a_stream():
    """Отброшенный срыв не должен тут же порождать следующий из того же
    залипшего сигнала — иначе вместо одной мусорной записи будет поток."""
    from core.coach_ai.slip import MAX_EVENT_DURATION_S
    d, c = SlipDetector(), _Clock()
    braking = _frame(brake_pct=100.0,
                     slip_ratio={"rl": 0.0, "rr": 0.0, "fl": -0.5, "fr": -0.05})

    # Сигнал держится втрое дольше предела и не отпускает.
    events = _feed(d, braking, seconds=MAX_EVENT_DURATION_S * 3, clock=c)
    assert events == []

    # Отпустил — подавление снимается, следующая настоящая ошибка проходит.
    _feed(d, _frame(), seconds=0.3, clock=c)
    _feed(d, braking, seconds=0.5, clock=c)
    after = _feed(d, _frame(), seconds=0.1, clock=c)
    assert len(after) == 1
    assert after[0].kind == "lockup"
