"""tests/test_coach_ai.py — Driver Performance Coach unit tests."""
from core.coach_ai.models import LapData, DriverReport


def test_lap_data_fields():
    lap = LapData(
        lap_number=5,
        lap_time_ms=90_000,
        s1_ms=28_000,
        s2_ms=32_000,
        s3_ms=30_000,
        tyre_compound="M",
        tyre_age=5,
        tyre_wear=20.0,
    )
    assert lap.lap_number == 5
    assert lap.lap_time_ms == 90_000
    assert lap.s1_ms == 28_000


def test_driver_report_fields():
    report = DriverReport(
        weak_sector=2,
        lost_time_ms=350,
        consistency_score=0.85,
        pace_delta_ms=420,
        tyre_advice="ok",
        lap_count=5,
        advice="Второй сектор — слабое место.",
    )
    assert report.weak_sector == 2
    assert report.consistency_score == 0.85
    assert report.tyre_advice == "ok"


from core.coach_ai.analyzer import DriverCoach


def _make_coach_with_laps(lap_times: list[int],
                           s1s: list[int] | None = None,
                           s2s: list[int] | None = None,
                           s3s: list[int] | None = None) -> DriverCoach:
    coach = DriverCoach()
    for i, ms in enumerate(lap_times):
        s1 = (s1s[i] if s1s else ms // 3)
        s2 = (s2s[i] if s2s else ms // 3)
        s3 = (s3s[i] if s3s else ms - s1 - s2)
        coach.add_lap(
            lap_number=i + 1,
            lap_time_ms=ms,
            s1_ms=s1,
            s2_ms=s2,
            s3_ms=s3,
        )
    return coach


# --- consistency ---

def test_consistency_perfect():
    coach = _make_coach_with_laps([90_000, 90_000, 90_000, 90_000])
    r = coach.get_report()
    assert r.consistency_score == 1.0


def test_consistency_low_on_varied_laps():
    coach = _make_coach_with_laps([88_000, 92_000, 87_000, 93_000])
    r = coach.get_report()
    assert r.consistency_score < 0.5


def test_consistency_default_before_3_laps():
    coach = _make_coach_with_laps([90_000, 91_000])
    r = coach.get_report()
    assert r.consistency_score == 1.0


# --- pace delta ---

def test_pace_delta_none_on_single_lap():
    coach = DriverCoach()
    coach.add_lap(1, 90_000, 28_000, 32_000, 30_000)
    assert coach.get_report().pace_delta_ms is None


def test_pace_delta_positive_when_slowing():
    coach = _make_coach_with_laps([90_000, 91_000, 92_000, 93_000])
    r = coach.get_report()
    assert r.pace_delta_ms is not None
    assert r.pace_delta_ms > 0


def test_pace_delta_nonpositive_when_improving():
    coach = _make_coach_with_laps([93_000, 92_000, 91_000, 90_000])
    r = coach.get_report()
    assert r.pace_delta_ms is not None
    assert r.pace_delta_ms <= 0


# --- weak sector ---

def test_weak_sector_detected():
    coach = DriverCoach()
    for i in range(5):
        s1 = 28_000
        s2 = 32_500 if i < 4 else 32_000
        s3 = 30_000
        coach.add_lap(i + 1, s1 + s2 + s3, s1, s2, s3)
    r = coach.get_report()
    assert r.weak_sector == 2
    assert r.lost_time_ms is not None and r.lost_time_ms > 0


def test_no_weak_sector_when_consistent():
    coach = DriverCoach()
    for i in range(5):
        coach.add_lap(i + 1, 90_000, 28_050, 32_000, 29_950)
    r = coach.get_report()
    assert r.weak_sector is None


def test_weak_sector_needs_3_valid_laps():
    coach = DriverCoach()
    coach.add_lap(1, 90_000, 28_000, 32_000, 30_000)
    coach.add_lap(2, 91_000, 28_500, 32_500, 30_000)
    r = coach.get_report()
    assert r.weak_sector is None


# --- tyre advice ---

def test_tyre_cliff_on_rapid_pace_rise_with_old_tyres():
    coach = DriverCoach()
    coach.add_lap(1, 90_000, 28_000, 32_000, 30_000, tyre_age=28)
    coach.add_lap(2, 90_400, 28_100, 32_200, 30_100, tyre_age=29)
    coach.add_lap(3, 90_800, 28_200, 32_400, 30_200, tyre_age=30)
    assert coach.get_report().tyre_advice == "cliff"


def test_tyre_ok_on_stable_pace():
    coach = _make_coach_with_laps([90_000, 90_100, 90_050])
    assert coach.get_report().tyre_advice == "ok"


# --- get_state contract ---

def test_get_state_has_all_keys():
    coach = DriverCoach()
    s = coach.get_state()
    for key in ("weak_sector", "lost_time_ms", "consistency_score",
                "pace_delta_ms", "tyre_advice", "lap_count", "advice"):
        assert key in s


def test_get_state_lap_count():
    coach = _make_coach_with_laps([90_000, 91_000, 92_000])
    assert coach.get_state()["lap_count"] == 3
