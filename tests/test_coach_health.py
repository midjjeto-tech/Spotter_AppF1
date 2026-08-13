"""Почему коуч молчит (core/coach_ai/health.py).

Молчащий коуч выглядит одинаково при выключенном тумблере, при
неповторяющейся ошибке, при не доехавшей телеметрии движения и при завышенном
пороге. Здесь проверяется, что эти четыре случая РАЗЛИЧАЮТСЯ — и что каждый
даёт пилоту разное действие.
"""
from core.coach_ai import health as health_mod
from core.coach_ai.health import (MIN_FRAMES_FOR_VERDICT, MIN_MOVING_KMH,
                                  SIGNAL_FLAT, SIGNAL_IMPLAUSIBLE,
                                  SIGNAL_NO_FRAMES, SIGNAL_OK,
                                  SIGNAL_WARMING_UP, CoachHealth)


def _frame(speed: float = 200.0, ratio: float = 0.05,
           angle: float = 0.03) -> dict:
    return {
        "speed_kmh": speed,
        "slip_ratio": {"rl": ratio, "rr": ratio, "fl": ratio, "fr": ratio},
        "slip_angle": {"rl": angle, "rr": angle, "fl": angle, "fr": angle},
    }


def _drive(health: CoachHealth, frames: int, **kwargs) -> CoachHealth:
    for _ in range(frames):
        health.observe_frame(_frame(**kwargs))
    return health


# ── Здоровье сигнала ─────────────────────────────────────────────────────────

def test_no_frames_means_the_telemetry_never_arrived():
    assert CoachHealth().signal == SIGNAL_NO_FRAMES


def test_a_parked_car_is_not_a_broken_signal():
    """Стоящая машина честно даёт нули — пугать этим на каждой загрузке нельзя."""
    health = _drive(CoachHealth(), MIN_FRAMES_FOR_VERDICT * 2,
                    speed=MIN_MOVING_KMH - 1, ratio=0.0, angle=0.0)

    assert health.signal == SIGNAL_WARMING_UP
    assert health.moving_frames == 0


def test_zeros_at_speed_mean_the_offsets_are_wrong():
    health = _drive(CoachHealth(), MIN_FRAMES_FOR_VERDICT + 1,
                    ratio=0.0, angle=0.0)

    assert health.signal == SIGNAL_FLAT


def test_values_outside_physics_mean_a_misread_packet():
    health = _drive(CoachHealth(), 50, ratio=99.0)

    assert health.signal == SIGNAL_IMPLAUSIBLE


def test_an_absurd_slip_angle_is_caught_too():
    health = _drive(CoachHealth(), 50, angle=3.0)

    assert health.signal == SIGNAL_IMPLAUSIBLE


def test_a_short_stint_is_not_yet_a_verdict():
    health = _drive(CoachHealth(), MIN_FRAMES_FOR_VERDICT - 1)

    assert health.signal == SIGNAL_WARMING_UP


def test_real_looking_data_is_ok():
    health = _drive(CoachHealth(), MIN_FRAMES_FOR_VERDICT + 1)

    assert health.signal == SIGNAL_OK
    assert health.live_frames > 0


def test_a_broken_frame_does_not_crash_the_tick():
    health = CoachHealth()
    for frame in ({}, {"speed_kmh": "быстро"}, {"slip_ratio": None},
                  {"speed_kmh": 200.0, "slip_ratio": {"fl": "нет"}}):
        health.observe_frame(frame)

    assert health.frames == 4


# ── Почему молчит ────────────────────────────────────────────────────────────

def test_missing_telemetry_tells_the_driver_what_to_switch_on():
    reason = CoachHealth().reason(coach_enabled=True)

    assert reason is not None
    assert "UDP" in reason


def test_broken_offsets_beat_the_toggle_in_priority():
    """Порядок проверок — это порядок действий: сначала то, что чинится в игре."""
    health = _drive(CoachHealth(), 50, ratio=99.0)

    assert "диапазона" in health.reason(coach_enabled=False)


def test_disabled_toggle_is_named_plainly():
    health = _drive(CoachHealth(), MIN_FRAMES_FOR_VERDICT + 1)

    assert health.reason(coach_enabled=False) == (
        health_mod.SILENCE_RU["coach_disabled_in_settings"])


def test_a_speaking_coach_explains_nothing():
    """Объяснять молчание, которого нет, — значит сеять сомнение в работающей
    функции."""
    health = _drive(CoachHealth(), MIN_FRAMES_FOR_VERDICT + 1)
    health.note_mistake(repeated=True)
    health.note_spoken()

    assert health.reason(coach_enabled=True) is None


def test_clean_driving_and_high_thresholds_are_named_as_one_pair():
    """Различить их изнутри нельзя, и честнее сказать оба варианта, чем выбрать
    один наугад."""
    health = _drive(CoachHealth(), MIN_FRAMES_FOR_VERDICT + 1)

    reason = health.reason(coach_enabled=True)

    assert "срывов не найдено" in reason
    assert "пороги" in reason


def test_repeated_rule_is_distinguished_from_no_mistakes_at_all():
    health = _drive(CoachHealth(), MIN_FRAMES_FOR_VERDICT + 1)
    for _ in range(4):
        health.note_mistake(repeated=False)

    reason = health.reason(coach_enabled=True)

    assert reason == health_mod.SILENCE_RU["mistake_repeat_rule"]
    assert health.mistakes == 4


def test_the_most_frequent_silence_wins():
    health = _drive(CoachHealth(), MIN_FRAMES_FOR_VERDICT + 1)
    health.note_mistake(repeated=True)
    health.note_silence("no_corner_to_name")
    for _ in range(5):
        health.note_silence("off_focus")

    assert health.reason(coach_enabled=True) == health_mod.SILENCE_RU["off_focus"]


def test_a_tie_between_reasons_is_resolved_stably():
    """Иначе отчёт менялся бы от запуска к запуску на одних и тех же данных."""
    first = _drive(CoachHealth(), MIN_FRAMES_FOR_VERDICT + 1)
    second = _drive(CoachHealth(), MIN_FRAMES_FOR_VERDICT + 1)
    for health in (first, second):
        health.note_mistake(repeated=True)
    first.note_silence("off_focus")
    first.note_silence("no_corner_to_name")
    second.note_silence("no_corner_to_name")
    second.note_silence("off_focus")

    assert first.reason(coach_enabled=True) == second.reason(coach_enabled=True)


def test_an_unknown_silence_reason_never_reaches_the_screen():
    """Ключ без человеческой формулировки — это недосмотр разработчика, и
    показывать его пилоту хуже, чем промолчать."""
    health = _drive(CoachHealth(), MIN_FRAMES_FOR_VERDICT + 1)
    health.note_mistake(repeated=True)
    health.note_silence("какая_то_новая_причина")

    assert health.reason(coach_enabled=True) is None


def test_every_silence_key_used_by_the_engine_has_a_human_sentence():
    """Сторож на будущее: новая причина молчания в движке обязана прийти со
    своей формулировкой, иначе экран промолчит вместе с коучем."""
    import re
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "core" / "engine.py"
    used = set(re.findall(r'_coach_silent\(\s*"([a-z_]+)"',
                          source.read_text(encoding="utf-8")))

    assert used, "движок больше не зовёт _coach_silent — тест устарел"
    assert used <= set(health_mod.SILENCE_RU), sorted(used - set(health_mod.SILENCE_RU))


# ── Форма наружу ─────────────────────────────────────────────────────────────

def test_report_carries_the_thresholds_so_they_can_be_checked():
    health = _drive(CoachHealth(), MIN_FRAMES_FOR_VERDICT + 1)

    data = health.to_dict(coach_enabled=True)

    assert data["signal"] == SIGNAL_OK
    assert data["thresholds"]["lockup_slip"] < 0
    assert data["enabled"] is True
    assert data["peak_slip_ratio"] > 0


def test_reset_forgets_the_session():
    health = _drive(CoachHealth(), 10)
    health.note_mistake(repeated=True)
    health.note_spoken()

    health.reset()

    assert health.frames == 0
    assert health.mistakes == 0
    assert health.spoken == 0
    assert health.silence == {}
    assert health.signal == SIGNAL_NO_FRAMES


# ── Порядок колёс: единственная проверка, не требующая руля ──────────────────

def _throttle_frame(front: float, rear: float) -> dict:
    return {
        "speed_kmh": 150.0, "throttle_pct": 100.0, "brake_pct": 0.0,
        "slip_ratio": {"fl": front, "fr": front, "rl": rear, "rr": rear},
        "slip_angle": {"fl": 0.02, "fr": 0.02, "rl": 0.02, "rr": 0.02},
    }


def test_rear_wheels_spinning_under_power_is_normal():
    """Формула заднеприводная — так и должно быть."""
    health = CoachHealth()
    for _ in range(health_mod.DRIVE_CHECK_MIN_FRAMES * 2):
        health.observe_frame(_throttle_frame(front=0.0, rear=0.18))

    assert health.wheels_swapped is False
    assert health.signal in (SIGNAL_OK, SIGNAL_WARMING_UP)


def test_front_wheels_spinning_under_power_means_the_pairs_are_swapped():
    """Передние колёса ничем не приводятся и буксовать не могут. Если они
    буксуют — переставлены пары, и коуч назвал бы не то колесо."""
    health = CoachHealth()
    for _ in range(health_mod.DRIVE_CHECK_MIN_FRAMES * 2):
        health.observe_frame(_throttle_frame(front=0.18, rear=0.0))

    assert health.wheels_swapped is True
    assert health.signal == health_mod.SIGNAL_SWAPPED
    assert "не то колесо" in health.reason(coach_enabled=True)


def test_a_few_odd_frames_are_not_a_verdict():
    health = CoachHealth()
    for _ in range(health_mod.DRIVE_CHECK_MIN_FRAMES - 1):
        health.observe_frame(_throttle_frame(front=0.18, rear=0.0))

    assert health.wheels_swapped is False


def test_braking_frames_never_judge_the_driven_axle():
    """Под тормозом блокируются любые колёса — о приводе это не говорит ничего."""
    health = CoachHealth()
    for _ in range(health_mod.DRIVE_CHECK_MIN_FRAMES * 2):
        frame = _throttle_frame(front=0.5, rear=0.0)
        frame["brake_pct"] = 60.0
        health.observe_frame(frame)

    assert health.drive_frames == 0
    assert health.wheels_swapped is False


def test_a_swapped_order_outranks_the_disabled_toggle():
    """Коуч, называющий не то колесо, — проблема выше уровнем, чем тумблер."""
    health = CoachHealth()
    for _ in range(health_mod.DRIVE_CHECK_MIN_FRAMES * 2):
        health.observe_frame(_throttle_frame(front=0.18, rear=0.0))

    assert "не то колесо" in health.reason(coach_enabled=False)
