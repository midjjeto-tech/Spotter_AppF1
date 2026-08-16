"""Промер трассы по своей телеметрии (core/track_ai/survey.py).

Тесты строят СИНТЕТИЧЕСКИЙ круг с заранее известными поворотами и проверяют, что
промер находит именно их. Это единственный способ проверить измеритель без игры:
на живой телеметрии «правильный ответ» неизвестен, ради него всё и затевалось.
"""
from __future__ import annotations

import math

from core.track_ai.survey import (
    CORNER_MIN_LAT_ACCEL, MIN_SAMPLES, SurveyedCorner, TrackSurvey, coverage,
)

LENGTH_M = 5000.0
SAMPLES_PER_LAP = 2000


def _drive(corners: list[dict], *, length_m: float = LENGTH_M,
           samples: int = SAMPLES_PER_LAP, straight_speed: float = 300.0,
           ) -> TrackSurvey:
    """Проехать круг, на котором повороты стоят ровно там, где сказано.

    `corners`: [{"at": доля, "half": полуширина, "apex": км/ч, "dir": +1|-1}].
    Между поворотами — прямая на `straight_speed` с нулевым рысканием.
    """
    survey = TrackSurvey()
    for i in range(samples):
        fraction = i / samples
        speed = straight_speed
        yaw = 0.0
        for corner in corners:
            offset = abs(fraction - corner["at"])
            if offset > corner["half"]:
                continue
            # Треугольный профиль: в апексе скорость минимальна, боковое
            # ускорение максимально.
            depth = 1.0 - offset / corner["half"]
            speed = straight_speed - (straight_speed - corner["apex"]) * depth
            lat = corner.get("lat", 30.0) * depth
            yaw = corner["dir"] * lat / max(1.0, speed / 3.6)
            break
        survey.observe(lap_distance_m=fraction * length_m, length_m=length_m,
                       speed_kmh=speed, yaw_rate=yaw)
    return survey


def test_a_clean_lap_finds_exactly_the_corners_that_are_there():
    survey = _drive([
        {"at": 0.10, "half": 0.02, "apex": 80.0, "dir": -1},    # шпилька влево
        {"at": 0.40, "half": 0.02, "apex": 160.0, "dir": +1},   # средний вправо
        {"at": 0.75, "half": 0.02, "apex": 250.0, "dir": +1},   # быстрый вправо
    ])

    found = survey.finish_lap()

    assert found is not None
    assert len(found) == 3
    assert [c.type for c in found] == ["hairpin", "medium", "fast"]
    assert [c.direction for c in found] == ["left", "right", "right"]


def test_the_apex_lands_on_the_slowest_point_not_the_entry():
    """Апекс — точка минимума скорости. Привяжи ошибку ко входу, и коуч отправит
    пилота чинить не то место (та же причина, что в slip.py)."""
    survey = _drive([{"at": 0.30, "half": 0.03, "apex": 90.0, "dir": +1}])

    found = survey.finish_lap()

    assert found is not None and len(found) == 1
    assert abs(found[0].fraction - 0.30) < 0.005


def test_a_straight_is_not_a_corner():
    """Круг без поворотов обязан дать пустой список, а не выдумать дуги из
    шума — иначе промер испортит карту ровно так же, как выдуманные цифры."""
    survey = _drive([])

    assert survey.finish_lap() == []


def test_steering_on_a_straight_does_not_invent_a_corner():
    """Ключевая причина, по которой мерим рысканием, а не рулём: руль можно
    крутить и на прямой, кузов на прямой не доворачивает."""
    survey = TrackSurvey()
    for i in range(SAMPLES_PER_LAP):
        fraction = i / SAMPLES_PER_LAP
        # Заметное рыскание, но на скорости, дающей ускорение ниже порога.
        yaw = 0.02 * math.sin(fraction * 40.0)
        survey.observe(lap_distance_m=fraction * LENGTH_M, length_m=LENGTH_M,
                       speed_kmh=120.0, yaw_rate=yaw)

    found = survey.finish_lap()
    assert found == []


def test_two_opposite_arcs_close_together_are_a_chicane():
    survey = _drive([
        {"at": 0.500, "half": 0.006, "apex": 120.0, "dir": +1},
        {"at": 0.508, "half": 0.006, "apex": 120.0, "dir": -1},
    ])

    found = survey.finish_lap()

    assert found is not None and len(found) == 2
    assert [c.type for c in found] == ["chicane", "chicane"]
    # Апексы остаются раздельными: ошибиться можно на любой из двух дуг.
    assert found[0].direction != found[1].direction


def test_two_same_way_corners_close_together_are_not_a_chicane():
    """Шикана — это ПЕРЕКЛАДКА. Две дуги одного направления подряд — связка, и
    объединять их в шикану значит соврать про тип."""
    survey = _drive([
        {"at": 0.500, "half": 0.006, "apex": 120.0, "dir": +1},
        {"at": 0.508, "half": 0.006, "apex": 120.0, "dir": +1},
    ])

    found = survey.finish_lap()

    assert found is not None
    assert all(c.type != "chicane" for c in found)


def test_a_torn_lap_is_refused_rather_than_half_measured():
    """None, а не короткий список: половина круга даёт карту, в которой вторая
    половина «без поворотов», и это хуже отсутствия промера."""
    survey = TrackSurvey()
    for i in range(MIN_SAMPLES + 50):
        fraction = 0.4 * i / (MIN_SAMPLES + 50)      # проехали 40% круга
        survey.observe(lap_distance_m=fraction * LENGTH_M, length_m=LENGTH_M,
                       speed_kmh=200.0, yaw_rate=0.0)

    assert survey.finish_lap() is None


def test_too_few_frames_is_refused():
    survey = _drive([{"at": 0.3, "half": 0.02, "apex": 90.0, "dir": +1}],
                    samples=MIN_SAMPLES - 10)

    assert survey.finish_lap() is None


def test_the_pit_lane_does_not_enter_the_survey():
    """На пит-лейне рыскание большое, а поворотом трассы это не является."""
    survey = TrackSurvey()
    for i in range(SAMPLES_PER_LAP):
        fraction = i / SAMPLES_PER_LAP
        survey.observe(lap_distance_m=fraction * LENGTH_M, length_m=LENGTH_M,
                       speed_kmh=50.0, yaw_rate=0.5)

    # Ни одного кадра не принято -> круг негодный, а не «трасса из поворотов».
    assert survey.sample_count == 0
    assert survey.finish_lap() is None


def test_garbage_frames_never_raise():
    """Промер обязан быть тише того, что измеряет: ошибка здесь не имеет права
    ронять тик телеметрии."""
    survey = TrackSurvey()
    for bad in (None, float("nan"), float("inf"), "быстро"):
        survey.observe(lap_distance_m=bad, length_m=LENGTH_M,
                       speed_kmh=200.0, yaw_rate=0.1)
        survey.observe(lap_distance_m=100.0, length_m=LENGTH_M,
                       speed_kmh=bad, yaw_rate=0.1)
        survey.observe(lap_distance_m=100.0, length_m=LENGTH_M,
                       speed_kmh=200.0, yaw_rate=bad)
    survey.observe(lap_distance_m=100.0, length_m=0, speed_kmh=200.0, yaw_rate=0.1)

    assert survey.sample_count == 0


def test_reset_forgets_the_previous_lap():
    survey = _drive([{"at": 0.3, "half": 0.02, "apex": 90.0, "dir": +1}])
    assert survey.sample_count > 0

    survey.reset()

    assert survey.sample_count == 0
    assert survey.finish_lap() is None


def test_the_map_entry_carries_only_what_the_loader_reads():
    """Диагностические поля промера в `tracks/*.json` попасть не должны — схема
    там компактная по построению (см. core/track_ai/loader.py)."""
    corner = SurveyedCorner(
        fraction=0.1234, type="slow", direction="left", apex_speed_kmh=95.0,
        entry_fraction=0.11, exit_fraction=0.14, peak_lat_accel=32.0)

    entry = corner.to_map_entry(7)

    assert set(entry) == {"id", "name", "fraction", "type", "direction"}
    assert entry["fraction"] == 0.123
    assert entry["id"] == 7


def test_coverage_matches_what_the_audit_measures():
    """Промер и аудит обязаны говорить об одном числе, иначе сравнивать их
    нельзя."""
    corners = [
        SurveyedCorner(0.1, "slow", "left", 90.0, 0.08, 0.12, 30.0),
        SurveyedCorner(0.5, "fast", "right", 250.0, 0.48, 0.52, 30.0),
    ]

    assert abs(coverage(corners) - 0.08) < 1e-9
    assert coverage([]) == 0.0


def test_overlapping_arcs_are_not_counted_twice():
    corners = [
        SurveyedCorner(0.10, "slow", "left", 90.0, 0.08, 0.14, 30.0),
        SurveyedCorner(0.12, "slow", "left", 92.0, 0.12, 0.16, 30.0),
    ]

    assert abs(coverage(corners) - 0.08) < 1e-9


def test_the_threshold_is_what_separates_a_corner_from_a_wobble():
    """Регрессия на сам порог: если его поднять, пропадут медленные повороты,
    если уронить — прямые станут дугами. Тест держит смысл числа, а не число."""
    below = _drive([{"at": 0.3, "half": 0.02, "apex": 200.0, "dir": +1,
                     "lat": CORNER_MIN_LAT_ACCEL * 0.5}])
    above = _drive([{"at": 0.3, "half": 0.02, "apex": 200.0, "dir": +1,
                     "lat": CORNER_MIN_LAT_ACCEL * 3.0}])

    assert below.finish_lap() == []
    assert len(above.finish_lap() or []) == 1
