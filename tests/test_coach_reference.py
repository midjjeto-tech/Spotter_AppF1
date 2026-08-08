"""Захват метрик поворота (core/coach_ai/reference.py)."""
import pytest

from core.coach_ai.reference import LapTracer


def _drive(tracer, samples):
    """samples: (corner_id, phase, dist_m, time_ms, brake, throttle, speed)."""
    for s in samples:
        tracer.tick(corner_id=s[0], phase=s[1], lap_distance_m=s[2],
                    lap_time_ms=s[3], brake_pct=s[4], throttle_pct=s[5],
                    speed_kmh=s[6])


def test_brake_point_is_first_sample_over_threshold():
    t = LapTracer()
    _drive(t, [
        (3, "braking", 100.0, 1000, 0.0, 100.0, 300),
        (3, "braking", 110.0, 1100, 60.0, 0.0, 290),   # тормоз здесь
        (3, "braking", 120.0, 1200, 90.0, 0.0, 250),
        (3, "apex",    130.0, 1400, 10.0, 0.0, 120),
        (3, "exit",    140.0, 1600, 0.0, 80.0, 150),
        (None, "straight", 200.0, 1800, 0.0, 100.0, 250),
    ])
    m = t.finish_lap()[3]
    assert m.brake_point_m == pytest.approx(110.0)


def test_min_speed_is_taken_inside_the_corner_body_only():
    """Скорость на подходе ещё падает — минимумом считается точка ВНУТРИ
    поворота, иначе эталон запомнил бы конец прямой."""
    t = LapTracer()
    _drive(t, [
        (3, "braking", 100.0, 1000, 90.0, 0.0, 90),    # ниже, но это подход
        (3, "entry",   120.0, 1200, 50.0, 0.0, 160),
        (3, "apex",    130.0, 1400, 0.0, 20.0, 120),
        (3, "exit",    140.0, 1600, 0.0, 80.0, 150),
        (None, "straight", 200.0, 1800, 0.0, 100.0, 250),
    ])
    assert t.finish_lap()[3].min_speed_kmh == pytest.approx(120)


def test_throttle_point_is_after_the_minimum_not_before():
    t = LapTracer()
    _drive(t, [
        (3, "braking", 100.0, 1000, 0.0, 90.0, 300),   # газ ДО поворота
        (3, "entry",   120.0, 1200, 80.0, 0.0, 160),
        (3, "apex",    130.0, 1400, 0.0, 10.0, 120),
        (3, "exit",    140.0, 1600, 0.0, 70.0, 150),   # настоящее открытие
        (None, "straight", 200.0, 1800, 0.0, 100.0, 250),
    ])
    assert t.finish_lap()[3].throttle_point_m == pytest.approx(140.0)


def test_duration_is_zone_exit_minus_entry():
    t = LapTracer()
    _drive(t, [
        (3, "braking", 100.0, 1000, 90.0, 0.0, 300),
        (3, "apex",    130.0, 1400, 0.0, 20.0, 120),
        (3, "exit",    140.0, 1700, 0.0, 80.0, 150),
        (None, "straight", 200.0, 1800, 0.0, 100.0, 250),
    ])
    assert t.finish_lap()[3].duration_ms == 700


def test_corner_without_speed_sample_is_dropped():
    t = LapTracer()
    _drive(t, [(3, "braking", 100.0, 1000, 90.0, 0.0, 300)])
    assert t.finish_lap() == {}


def test_flashback_drops_the_corner_in_progress():
    """Дистанция прыгнула назад — это флэшбек. Запись обрывка эталону вредна."""
    t = LapTracer()
    _drive(t, [
        (3, "braking", 100.0, 1000, 90.0, 0.0, 300),
        (3, "apex",    130.0, 1400, 0.0, 20.0, 120),
        (3, "apex",     40.0, 1500, 0.0, 20.0, 120),   # откат
        (None, "straight", 200.0, 1800, 0.0, 100.0, 250),
    ])
    assert t.finish_lap() == {}


def test_two_corners_recorded_separately():
    t = LapTracer()
    _drive(t, [
        (3, "braking", 100.0, 1000, 90.0, 0.0, 300),
        (3, "apex",    130.0, 1400, 0.0, 20.0, 120),
        (7, "braking", 300.0, 2000, 90.0, 0.0, 280),
        (7, "apex",    330.0, 2400, 0.0, 20.0, 100),
        (None, "straight", 400.0, 2600, 0.0, 100.0, 250),
    ])
    out = t.finish_lap()
    assert set(out) == {3, 7}
    assert out[7].min_speed_kmh == pytest.approx(100)


def test_finish_lap_closes_the_corner_still_in_progress():
    """Финишная черта внутри поворота — обычное дело на многих трассах."""
    t = LapTracer()
    _drive(t, [
        (3, "braking", 100.0, 1000, 90.0, 0.0, 300),
        (3, "apex",    130.0, 1400, 0.0, 20.0, 120),
    ])
    assert 3 in t.finish_lap()


def test_finish_lap_resets_state():
    t = LapTracer()
    _drive(t, [
        (3, "braking", 100.0, 1000, 90.0, 0.0, 300),
        (3, "apex",    130.0, 1400, 0.0, 20.0, 120),
    ])
    t.finish_lap()
    assert t.finish_lap() == {}


def test_reset_drops_everything():
    t = LapTracer()
    _drive(t, [
        (3, "braking", 100.0, 1000, 90.0, 0.0, 300),
        (3, "apex",    130.0, 1400, 0.0, 20.0, 120),
        (None, "straight", 200.0, 1800, 0.0, 100.0, 250),
    ])
    t.reset()
    assert t.finish_lap() == {}
