"""Проводка коуча целиком: MotionEx -> детектор -> буфер -> реплика.

Зелёный юнит-тест детектора ничего не говорит о том, доехало ли до эфира —
самые дорогие баги этого проекта живут между корректным ядром и тем, что
реально уезжает наружу. Поэтому здесь проверяется именно путь наружу.
"""
import pytest

import core.engine as eng_mod
from core.coach_ai.models import CornerMistake
from core.engine import F1Engine
from core.telemetry_adapters import TelemetryDelta


@pytest.fixture
def engine():
    """Тот же приём, что в tests/test_engine_damage.py: подменяем загрузку
    креденшелов, чтобы конструктор не лез в сеть. Фикстура функциональная, а не
    модульная — тесты ниже мутируют settings и буфер коуча.

    Сигнал сразу помечается ЗДОРОВЫМ: с 2026-08-15 коуч не открывает рот, пока
    `CoachHealth` не подтвердит, что данные о проскальзывании похожи на правду
    (см. tests/test_coach_signal_gate.py — там проверяется сам гейт). В проде
    это выполняется само собой: срывы приходят из тех же кадров MotionEx,
    которые кормят здоровье, и к третьему кругу их набираются тысячи. Здесь же
    `_emit_coach_advice` зовут напрямую, без кадров, поэтому здоровье надо
    подать явно — иначе эти тесты проверяли бы гейт, а не то, ради чего
    написаны."""
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        engine = F1Engine({})
        _warm_up_signal(engine)
        yield engine
    finally:
        eng_mod.yc.load = orig


def _warm_up_signal(engine):
    """Довести `CoachHealth` до вердикта «сигнал в порядке»."""
    from core.coach_ai.health import MIN_FRAMES_FOR_VERDICT

    for _ in range(MIN_FRAMES_FOR_VERDICT + 10):
        engine.coach_health.observe_frame({
            "speed_kmh": 200.0,
            "slip_ratio": {"rl": 0.05, "rr": 0.05, "fl": 0.0, "fr": 0.0},
            "slip_angle": {"rl": 0.02, "rr": 0.02, "fl": 0.01, "fr": 0.01},
            "throttle_pct": 50.0, "brake_pct": 0.0,
        })


def _mistake(lap, kind="lockup", wheel="fl", corner_id=3, phase="braking"):
    return CornerMistake(kind=kind, wheel=wheel, corner_id=corner_id,
                         corner_name=f"Turn {corner_id}", phase=phase, lap=lap,
                         peak=0.5, duration_s=0.3, speed_kmh=180)


def _capture(engine, monkeypatch):
    """Перехватить и публикацию, и рендер фразы.

    Черновик события НЕ несёт `phrase_code`: движок сразу превращает код в
    готовый текст через `_render_engineer_phrase` (тот же путь, что у
    споттера), поэтому проверять надо, с каким кодом позвали рендер."""
    drafts, codes = [], []
    monkeypatch.setattr(engine._commentary_events, "publish", drafts.append)
    monkeypatch.setattr(
        engine, "_render_engineer_phrase",
        lambda draft, code, *a, **kw: (codes.append(code), "фраза")[1])
    return drafts, codes


def test_motion_ex_delta_reaches_the_coach_tick(engine, monkeypatch):
    seen = []
    monkeypatch.setattr(engine, "_coach_tick", seen.append)

    engine._consume_telemetry_delta(
        TelemetryDelta("motion_ex", {"slip_ratio": {}}, 0, 25))

    assert seen == [{"slip_ratio": {}}]


def test_disabled_coach_publishes_nothing(engine, monkeypatch):
    engine.settings["driving_coach_enabled"] = False
    drafts, _ = _capture(engine, monkeypatch)

    for lap in (1, 2, 3):
        engine._emit_coach_advice(_mistake(lap))

    assert drafts == []


def test_disabled_coach_still_fills_the_debrief_map(engine, monkeypatch):
    """Тумблер выключает ЭФИР, а не сбор данных: экран после сессии никого не
    перебивает и должен работать всегда."""
    engine.settings["driving_coach_enabled"] = False
    _capture(engine, monkeypatch)

    for lap in (1, 2, 3):
        engine._emit_coach_advice(_mistake(lap))

    assert len(engine.coach_log.map_rows()) == 3


def test_repeated_mistake_publishes_expected_phrase_code(engine, monkeypatch):
    engine.settings["driving_coach_enabled"] = True
    drafts, codes = _capture(engine, monkeypatch)

    for lap in (1, 2, 3):
        engine._emit_coach_advice(_mistake(lap))

    assert codes == ["coach.lockup_front_left"]
    assert len(drafts) == 1
    assert drafts[0]["speaker"] == eng_mod.SPEAKER_ENGINEER
    assert drafts[0].get("priority") != "critical"
    assert drafts[0].get("bypass_speak_threshold") is not True


def test_single_mistake_publishes_nothing(engine, monkeypatch):
    engine.settings["driving_coach_enabled"] = True
    drafts, _ = _capture(engine, monkeypatch)

    engine._emit_coach_advice(_mistake(1))

    assert drafts == []


def test_unknown_wheel_combination_stays_silent(engine, monkeypatch):
    """Блокировка ЗАДНЕГО колеса банку не знакома. Промолчать безопаснее, чем
    сказать не то."""
    engine.settings["driving_coach_enabled"] = True
    drafts, _ = _capture(engine, monkeypatch)

    for lap in (1, 2, 3):
        engine._emit_coach_advice(_mistake(lap, wheel="rl"))

    assert drafts == []


def test_offtrack_counted_as_track_limits_is_left_to_the_existing_tracker(
        engine, monkeypatch):
    """Засчитанная игрой срезка принадлежит TrackLimitsTracker. Коуч про неё
    молчит — иначе два объявления об одном инциденте, ровно то, что уже
    один раз чинили односторонней проверкой."""
    engine.settings["driving_coach_enabled"] = True
    drafts, _ = _capture(engine, monkeypatch)
    engine._note_track_limits_announcement(100.0)

    for lap in (1, 2, 3):
        engine._emit_coach_advice(
            _mistake(lap, kind="offtrack", wheel=None), now=100.5)

    assert drafts == []


def test_offtrack_speaks_again_once_the_suppression_window_passed(
        engine, monkeypatch):
    """Глушение — окно вокруг ОДНОГО инцидента, а не выключатель на сессию."""
    engine.settings["driving_coach_enabled"] = True
    drafts, _ = _capture(engine, monkeypatch)
    engine._note_track_limits_announcement(100.0)

    for lap in (1, 2, 3):
        engine._emit_coach_advice(
            _mistake(lap, kind="offtrack", wheel=None), now=200.0)

    assert len(drafts) == 1


def test_slip_mistakes_are_not_suppressed_by_track_limits(engine, monkeypatch):
    """Глушение относится ТОЛЬКО к выезду. Блокировка рядом с трек-лимитом —
    другая проблема и должна прозвучать."""
    engine.settings["driving_coach_enabled"] = True
    drafts, _ = _capture(engine, monkeypatch)
    engine._note_track_limits_announcement(100.0)

    for lap in (1, 2, 3):
        engine._emit_coach_advice(_mistake(lap), now=100.5)

    assert len(drafts) == 1


def test_coach_tick_survives_missing_track_data(engine, monkeypatch):
    """Трасса без разметки поворотов не должна ронять тик: коуч просто не
    сможет назвать место."""
    engine.settings["driving_coach_enabled"] = True
    _capture(engine, monkeypatch)
    engine._track_manager = None

    engine._coach_tick({
        "slip_ratio": {"rl": 0.0, "rr": 0.0, "fl": -0.5, "fr": 0.0},
        "slip_angle": {"rl": 0.0, "rr": 0.0, "fl": 0.0, "fr": 0.0},
        "yaw_rate": 0.0, "front_wheels_angle": 0.0,
    })


def test_empty_motion_ex_payload_is_ignored(engine):
    engine._coach_tick({})
    assert engine.coach_log.map_rows() == []


# ── Подсказка обязана называть место ─────────────────────────────────────────

def test_advice_carries_the_corner_number_into_the_phrase(engine, monkeypatch):
    """Без места пилот идёт искать ошибку по всему кругу. Номер поворота уходит
    в банк отдельным полем — проверяем именно то, что уехало в рендер, а не то,
    что лежит в черновике для UI."""
    engine.settings["driving_coach_enabled"] = True
    seen = {}
    monkeypatch.setattr(engine._commentary_events, "publish", lambda d: None)
    monkeypatch.setattr(
        engine, "_render_engineer_phrase",
        lambda draft, code, fields=None, *a, **kw: (seen.update(
            code=code, fields=fields), "фраза")[1])

    engine._publish_coach_advice(_mistake(lap=5, corner_id=7))

    assert seen["code"] == "coach.lockup_front_left"
    assert seen["fields"] == {"corner_no": "седьмом"}


def test_a_mistake_outside_any_corner_stays_silent(engine, monkeypatch):
    """Срыв на прямой — не привычка в повороте, и назвать место нечем. В эфир
    он не идёт, но в карте дебрифа остаётся (её пишет corner_log, не этот путь)."""
    engine.settings["driving_coach_enabled"] = True
    drafts, codes = _capture(engine, monkeypatch)

    engine._publish_coach_advice(_mistake(lap=5, corner_id=None))

    assert drafts == []
    assert codes == []
