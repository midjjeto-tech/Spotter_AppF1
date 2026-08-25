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


# ── Стоящая машина не ошибается (2026-08-25) ─────────────────────────────────
#
# Свод ВСЕХ срывов архива: пять wheelspin, из них три с пиком 5.386–5.417 при
# собственном потолке достоверности SANE_MAX_SLIP_RATIO = 3.0. Все три — при
# `speed_kmh = 0`, круг 1, поворот 1, то есть старт с решётки трёх разных
# гонок. Оставшиеся два — 0.27 и 0.42 при 49 и 56 км/ч, нормальные значения.
#
# Проскальзывание считается как (скорость колеса − скорость земли) / скорость
# земли. На старте знаменатель около нуля, и величина взлетает: это арифметика,
# а не сбитая раскладка пакета. Запись в CONTEXT.md от 08-15 («сигнал под
# вопросом, проверять пакет 13 живым заездом») читала эти пики как поломку
# телеметрии — и отправляла за ответом в гонку, которого в гонке нет.
#
# Гейт по скорости в `health.py` был с самого начала (MIN_MOVING_KMH) и прямо
# объяснён: нули стоящей машины — правда, а не поломка. До детектора это
# решение не довели.

def test_a_standing_start_is_not_a_driving_mistake():
    """Пик 5.4 при нулевой скорости — это старт, а не ошибка пилотажа."""
    clock = _Clock()
    detector = SlipDetector()
    launch = _frame(speed_kmh=0, throttle_pct=100,
                    slip_ratio={"rl": 5.4, "rr": 5.4, "fl": 0.0, "fr": 0.0})

    events = _feed(detector, launch, 1.0, clock, corner=(1, "Turn 1"))
    events += _feed(detector, _frame(speed_kmh=0), 0.5, clock, corner=(1, "Turn 1"))

    assert events == [], f"старт засчитан как срыв: {events}"


def test_a_mistake_that_began_at_speed_survives_the_car_slowing_down():
    """Обратная сторона: разворот ГАСИТ скорость, и гейт не должен съедать
    срыв, который начался на гоночной скорости. Иначе правка меняла бы один
    ложный вывод на потерю настоящих ошибок."""
    clock = _Clock()
    detector = SlipDetector()
    # Контр-руление обязательно: без него это поворот на пределе, а не занос
    # (см. `counter_steering` в slip.py) — руль в одну сторону, кузов в другую.
    spin = _frame(speed_kmh=180, steer=0.4, yaw_rate=-0.5,
                  slip_angle={"rl": 0.5, "rr": 0.5, "fl": 0.0, "fr": 0.0})

    _feed(detector, spin, 0.6, clock)
    # Машину развернуло и почти остановило.
    events = _feed(detector, _frame(speed_kmh=10), 0.3, clock)

    kinds = [e.kind for e in events]
    assert "oversteer" in kinds, f"настоящий занос потерян: {events}"


def test_slow_corners_are_still_watched():
    """Порог обязан лежать НИЖЕ гоночных скоростей: самый медленный поворот в
    календаре проходится примерно на 45–50 км/ч, и найденные в архиве
    wheelspin при 49 и 56 км/ч — настоящие."""
    clock = _Clock()
    detector = SlipDetector()
    hairpin = _frame(speed_kmh=49, throttle_pct=80,
                     slip_ratio={"rl": 0.4, "rr": 0.4, "fl": 0.0, "fr": 0.0})

    _feed(detector, hairpin, 0.6, clock, corner=(10, "Turn 10"))
    events = _feed(detector, _frame(speed_kmh=49), 0.3, clock, corner=(10, "Turn 10"))

    assert [e.kind for e in events] == ["wheelspin"]


def test_unknown_speed_does_not_silence_the_coach():
    """Источник без скорости в кадре не должен молча выключать детектор.

    Отсутствие данных — не то же самое, что «машина стоит». Гейт закрывается
    только на ИЗМЕРЕННОЙ низкой скорости; иначе адаптер без этого поля
    (iRacing, фазы 2/3) отключил бы коуча целиком и без единого сообщения."""
    clock = _Clock()
    detector = SlipDetector()
    frame = _frame(throttle_pct=80,
                   slip_ratio={"rl": 0.4, "rr": 0.4, "fl": 0.0, "fr": 0.0})
    frame.pop("speed_kmh")

    _feed(detector, frame, 0.6, clock)
    tail = dict(_frame())
    tail.pop("speed_kmh")
    events = _feed(detector, tail, 0.3, clock)

    assert [e.kind for e in events] == ["wheelspin"]


def test_the_moving_threshold_has_one_owner():
    """Здоровье сигнала и детектор обязаны понимать «машина едет» одинаково.
    Два числа в двух модулях однажды разойдутся, и разойдутся молча."""
    from core.coach_ai import health, slip

    assert health.MIN_MOVING_KMH == slip.MIN_MOVING_KMH
