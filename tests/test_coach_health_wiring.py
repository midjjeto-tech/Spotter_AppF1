"""Проводка состояния коуча: одна точка молчания -> журнал И экран.

Причина молчания раньше существовала только в полевом журнале, то есть была
видна разработчику при `SPOTTER_DIAG=1` и не видна пилоту никогда. Здесь
проверяется, что теперь она доезжает до обоих — и что разойтись они не могут.
"""
import pytest

import core.engine as eng_mod
from core.coach_ai.health import SIGNAL_NO_FRAMES, SIGNAL_OK
from core.coach_ai.models import CornerMetrics
from core.coach_ai.reference_store import ReferenceLap
from core.engine import F1Engine


@pytest.fixture
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _lap(ms: int = 4000) -> dict[int, CornerMetrics]:
    return {i: CornerMetrics(i, 100.0 * i, 120.0, 100.0 * i + 40, ms)
            for i in range(1, 9)}


def _frame(speed: float = 200.0, ratio: float = 0.05) -> dict:
    wheels = {"rl": ratio, "rr": ratio, "fl": ratio, "fr": ratio}
    return {"speed_kmh": speed, "slip_ratio": wheels,
            "slip_angle": {k: 0.02 for k in wheels}}


def test_one_silence_feeds_both_the_journal_and_the_screen(engine, monkeypatch):
    records = []
    monkeypatch.setattr(engine._field, "record",
                        lambda name, **kw: records.append((name, kw)))

    engine._coach_silent("off_focus", lap=4, corner_id=7)

    assert engine.coach_health.silence == {"off_focus": 1}
    assert records == [("coach_silent", {"why": "off_focus", "lap": 4,
                                         "corner_id": 7})]


def test_a_silent_reference_hint_explains_itself(engine, monkeypatch):
    """Тумблер выключен — коуч молчит, и теперь говорит, почему.

    Кадры движения подаём намеренно: без них верх взяла бы диагностика повыше
    рангом («телеметрия не приходит»), и она была бы права — сломанный поток
    важнее выключенного тумблера."""
    engine.settings["driving_coach_enabled"] = False
    engine.coach_reference = ReferenceLap(90_000, _lap(), "career")
    monkeypatch.setattr(engine._commentary_events, "publish", lambda d: None)
    monkeypatch.setattr(engine, "_render_engineer_phrase",
                        lambda *a, **kw: "фраза")
    for _ in range(700):
        engine.coach_health.observe_frame(_frame())

    slow = _lap()
    slow[3] = CornerMetrics(3, 300.0, 120.0, 340.0, 6000)
    for lap in (1, 2, 3):
        engine._compare_lap_to_reference(slow, lap)

    health = engine.coach_health.to_dict(coach_enabled=False)
    assert health["silence"]["coach_disabled_in_settings"] >= 1
    assert "выключены в настройках" in health["reason"]


def test_frames_from_the_coach_tick_decide_the_signal(engine):
    assert engine.coach_health.signal == SIGNAL_NO_FRAMES

    for _ in range(700):
        engine.coach_health.observe_frame(_frame())

    assert engine.coach_health.signal == SIGNAL_OK


def test_a_spoken_line_is_counted_and_stops_the_explanation(engine, monkeypatch):
    engine.settings["driving_coach_enabled"] = True
    engine.coach_reference = ReferenceLap(90_000, _lap(), "career")
    monkeypatch.setattr(engine._commentary_events, "publish", lambda d: None)
    monkeypatch.setattr(engine, "_render_engineer_phrase",
                        lambda *a, **kw: "фраза")
    for _ in range(700):
        engine.coach_health.observe_frame(_frame())

    slow = _lap()
    slow[3] = CornerMetrics(3, 300.0, 120.0, 340.0, 6000)
    for lap in (1, 2, 3):
        engine._compare_lap_to_reference(slow, lap)

    assert engine.coach_health.spoken == 1
    assert engine.coach_health.reason(coach_enabled=True) is None


def test_health_reaches_the_ui_state_even_with_the_toggle_off(engine):
    """«Выключен» — это тоже ответ на вопрос, почему коуч молчит, и
    единственный способ его получить, не читая код."""
    engine.settings["driving_coach_enabled"] = False

    engine._ui_state.set_analysis(
        race_ai={}, strategy_ai={},
        coach_ai={"health": engine.coach_health.to_dict(coach_enabled=False)},
        rivals={}, track_ai=None, track_name="Test")

    health = engine.get_coach_ai_state()["health"]
    assert health["enabled"] is False
    assert health["reason"]
    assert "lockup_slip" in health["thresholds"]


def test_session_restart_forgets_the_health(engine):
    from tests.telemetry import consume_f1_event_packet
    from core.packets import HEADER_SIZE

    for _ in range(50):
        engine.coach_health.observe_frame(_frame())
    engine._coach_silent("off_focus", lap=1)
    assert engine.coach_health.frames == 50

    buf = bytearray(HEADER_SIZE + 4)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"SSTA"
    consume_f1_event_packet(engine, bytes(buf))

    assert engine.coach_health.frames == 0
    assert engine.coach_health.silence == {}
