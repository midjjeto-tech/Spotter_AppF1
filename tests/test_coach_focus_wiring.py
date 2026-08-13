"""Проводка работы сессии: круг -> цена -> фокус -> реплика и разбор.

Зелёные юнит-тесты `cost.py`/`focus.py`/`lesson.py` не говорят ничего о том,
доехало ли что-нибудь до пилота. Самое дорогое в этом проекте живёт ровно между
корректным ядром и тем, что реально уезжает наружу, — поэтому здесь проверяются
три выхода целиком: эфир, `/api/state` и файл заезда.
"""
import pytest

import core.engine as eng_mod
from core.coach_ai.models import CornerMetrics
from core.coach_ai.reference_store import ReferenceLap, TrackHistory
from core.engine import F1Engine
from core.telemetry_adapters import TelemetryDelta


def _event_buf(code: str) -> bytes:
    from core.packets import HEADER_SIZE
    buf = bytearray(HEADER_SIZE + 4)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = code.encode("ascii")
    return bytes(buf)


def _session_delta(track_id: int) -> TelemetryDelta:
    """Минимальный пакет сессии: движок читает погоду безусловно, поэтому она
    здесь есть, хотя тест не про неё."""
    return TelemetryDelta("session", {
        "track_id": track_id, "weather": 0, "track_temp": 30, "air_temp": 20,
    }, 0, 2025)


@pytest.fixture
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _lap(duration_by_corner: dict[int, int]) -> dict[int, CornerMetrics]:
    return {cid: CornerMetrics(cid, 100.0 * cid, 120.0, 100.0 * cid + 40, ms)
            for cid, ms in duration_by_corner.items()}


def _flat(ms: int = 4000) -> dict[int, int]:
    return {i: ms for i in range(1, 9)}


def _slow_corner(corner_id: int, ms: int) -> dict[int, CornerMetrics]:
    spec = _flat()
    spec[corner_id] = ms
    return _lap(spec)


def _capture(engine, monkeypatch):
    drafts, calls = [], []
    monkeypatch.setattr(engine._commentary_events, "publish", drafts.append)
    monkeypatch.setattr(
        engine, "_render_engineer_phrase",
        lambda draft, code, fields=None, *a, **kw: (
            calls.append((code, dict(fields or {}))), "фраза")[1])
    return drafts, calls


def _drive(engine, laps: int, metrics, lap_time_ms: int = 90_000,
           first_lap: int = 1) -> None:
    for lap in range(first_lap, first_lap + laps):
        engine._coach_observe_lap(lap, lap_time_ms, metrics)


def _mistakes(engine, corner_id: int, kind: str, times: int) -> None:
    """Подложить повторяющийся срыв в карту сессии — источник ПРИЧИНЫ."""
    rows = [{"lap": i, "corner_id": corner_id, "corner_name": f"Turn {corner_id}",
             "kind": kind, "wheel": "fl", "phase": "braking", "peak": 0.4,
             "duration_s": 0.5, "speed_kmh": 120}
            for i in range(times)]
    engine.coach_log.map_rows = lambda: rows


# ── Эфир ─────────────────────────────────────────────────────────────────────

def test_the_work_is_announced_with_its_price(engine, monkeypatch):
    """Главная реплика фазы 4: без цены пилот не знает, зачем этим заниматься."""
    engine.settings["driving_coach_enabled"] = True
    engine.coach_reference = ReferenceLap(90_000, _lap(_flat()), "career")
    _mistakes(engine, 3, "lockup", 6)
    drafts, calls = _capture(engine, monkeypatch)

    _drive(engine, 4, _slow_corner(3, 4400))

    assert [code for code, _ in calls] == ["coach.focus_set"]
    assert calls[0][1] == {"corner_no": "третьем", "loss": "четыре десятых"}
    assert len(drafts) == 1
    assert drafts[0]["event_code"] == "COACH_FOCUS"
    assert drafts[0]["corner_id"] == 3
    assert drafts[0]["speaker"] == eng_mod.SPEAKER_ENGINEER


def test_the_work_is_never_critical_and_never_bypasses_the_threshold(
        engine, monkeypatch):
    """Подсказка по пилотажу обязана уступать споттеру и box-call."""
    engine.settings["driving_coach_enabled"] = True
    engine.coach_reference = ReferenceLap(90_000, _lap(_flat()), "career")
    _mistakes(engine, 3, "lockup", 6)
    drafts, _ = _capture(engine, monkeypatch)

    _drive(engine, 4, _slow_corner(3, 4400))

    assert drafts[0].get("priority") != "critical"
    assert drafts[0].get("bypass_speak_threshold") is not True


def test_progress_and_closing_are_said_in_order(engine, monkeypatch):
    engine.settings["driving_coach_enabled"] = True
    engine.coach_reference = ReferenceLap(90_000, _lap(_flat()), "career")
    _mistakes(engine, 3, "lockup", 6)
    _, calls = _capture(engine, monkeypatch)

    _drive(engine, 4, _slow_corner(3, 4600))          # взяли в работу
    _drive(engine, 14, _lap(_flat()), first_lap=5)    # исправился

    codes = [code for code, _ in calls]
    assert codes[0] == "coach.focus_set"
    assert "coach.focus_fixed" in codes
    assert codes.index("coach.focus_set") < codes.index("coach.focus_fixed")


def test_disabled_toggle_silences_the_air_but_not_the_debrief(engine, monkeypatch):
    """Тумблер выключает ЭФИР. Разбор собирается всегда — он никого не
    перебивает, а без него экран «Итоги» пуст ровно у того, кто выключил голос."""
    engine.settings["driving_coach_enabled"] = False
    engine.coach_reference = ReferenceLap(90_000, _lap(_flat()), "career")
    _mistakes(engine, 3, "lockup", 6)
    drafts, _ = _capture(engine, monkeypatch)

    _drive(engine, 5, _slow_corner(3, 4400))

    assert drafts == []
    assert engine._coach_lesson is not None
    assert engine._coach_lesson["losses"][0]["corner_id"] == 3
    assert engine.coach_focus.state is not None


def test_a_corner_that_cannot_be_named_is_not_announced(engine, monkeypatch):
    """Работа без места отправляет пилота искать её по всему кругу."""
    engine.settings["driving_coach_enabled"] = True
    engine.coach_reference = ReferenceLap(90_000, _lap(_flat()), "career")
    _mistakes(engine, 99, "lockup", 6)                # номера 99 в таблице нет
    drafts, _ = _capture(engine, monkeypatch)

    spec = _flat()
    spec[99] = 4400
    reference = dict(engine.coach_reference.corners)
    reference[99] = CornerMetrics(99, 9900.0, 120.0, 9940.0, 4000)
    engine.coach_reference = ReferenceLap(90_000, reference, "career")
    _drive(engine, 5, _lap(spec))

    assert drafts == []


# ── Уступка фазы 2 ───────────────────────────────────────────────────────────

def test_reference_hint_about_another_corner_yields_to_the_current_work(
        engine, monkeypatch):
    """Пока в работе один поворот, коуч не рассказывает про другой: каждая такая
    реплика верна по отдельности, а вместе они — тот самый шум."""
    engine.settings["driving_coach_enabled"] = True
    engine.coach_reference = ReferenceLap(90_000, _lap(_flat()), "career")
    _mistakes(engine, 3, "lockup", 6)
    _drive(engine, 4, _slow_corner(3, 4400))          # фокус — третий
    drafts, calls = _capture(engine, monkeypatch)

    other = _flat()
    other[6] = 6000
    for lap in (5, 6, 7):
        engine._compare_lap_to_reference(_lap(other), lap)

    assert drafts == []
    assert calls == []


def test_reference_hint_about_the_focus_corner_still_speaks(engine, monkeypatch):
    """Глушится другой поворот, а не сам коуч: про свой он говорит по-прежнему."""
    engine.settings["driving_coach_enabled"] = True
    engine.coach_reference = ReferenceLap(90_000, _lap(_flat()), "career")
    _mistakes(engine, 3, "lockup", 6)
    _drive(engine, 4, _slow_corner(3, 4400))
    drafts, _ = _capture(engine, monkeypatch)

    for lap in (5, 6, 7):
        engine._compare_lap_to_reference(_slow_corner(3, 6000), lap)

    assert len(drafts) == 1
    assert drafts[0]["corner_id"] == 3


def test_without_a_focus_the_reference_hint_is_untouched(engine, monkeypatch):
    engine.settings["driving_coach_enabled"] = True
    engine.coach_reference = ReferenceLap(90_000, _lap(_flat()), "career")
    drafts, _ = _capture(engine, monkeypatch)

    for lap in (1, 2, 3):
        engine._compare_lap_to_reference(_slow_corner(6, 6000), lap)

    assert len(drafts) == 1
    assert drafts[0]["corner_id"] == 6


# ── /api/state и файл заезда ─────────────────────────────────────────────────

def test_lesson_and_focus_reach_the_ui_state(engine, monkeypatch):
    engine.settings["driving_coach_enabled"] = True
    engine.coach_reference = ReferenceLap(90_000, _lap(_flat()), "career")
    _mistakes(engine, 3, "lockup", 6)
    _capture(engine, monkeypatch)

    _drive(engine, 5, _slow_corner(3, 4400))
    engine._ui_state.set_analysis(
        race_ai={}, strategy_ai={},
        coach_ai={"lesson": engine._coach_lesson,
                  "focus": engine.coach_focus.to_dict()},
        rivals={}, track_ai=None, track_name="Test")

    section = engine.get_coach_ai_state()
    assert section["lesson"]["losses"][0]["corner_id"] == 3
    assert section["lesson"]["next_step"]
    assert section["focus"]["corner_id"] == 3


def test_lesson_is_saved_into_the_session_file(engine):
    """Разбор читает не только экран, но и следующий визит на эту трассу."""
    engine._coach_lesson = {"headline": "тест", "losses": []}
    engine.recorder.set_coach_lesson(engine._coach_lesson)
    engine.recorder.on_lap_complete(1, 90_000, 1, 1, 1)

    path = engine.recorder.finalize(track_id=7, track_name="Test",
                                    session_type="race", final_position=1,
                                    events=[])

    assert path is not None
    import json
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["coach_lesson"]["headline"] == "тест"


def test_previous_lesson_arrives_with_the_track_reference(engine, monkeypatch):
    monkeypatch.setattr(
        eng_mod, "load_track_history",
        lambda tid: TrackHistory(ReferenceLap(88_000, _lap(_flat(3400)), "career"),
                                 {"best_lap_ms": 93_000,
                                  "focus": {"corner_id": 7, "current_ms": 400}}))
    engine._track_id = 7

    engine._start_coach_reference_load(7)
    engine._task_threads[-1].join(timeout=5.0)

    assert engine._coach_previous_lesson["best_lap_ms"] == 93_000


def test_previous_lesson_is_dropped_when_the_track_changed_meanwhile(
        engine, monkeypatch):
    monkeypatch.setattr(
        eng_mod, "load_track_history",
        lambda tid: TrackHistory(None, {"best_lap_ms": 93_000}))
    engine._track_id = 9

    engine._start_coach_reference_load(7)
    engine._task_threads[-1].join(timeout=5.0)

    assert engine._coach_previous_lesson is None


def test_progress_against_the_previous_visit_reaches_the_lesson(engine, monkeypatch):
    engine.settings["driving_coach_enabled"] = False
    engine.coach_reference = ReferenceLap(90_000, _lap(_flat()), "career")
    engine._coach_previous_lesson = {"best_lap_ms": 93_000,
                                     "focus": {"corner_id": 3, "current_ms": 900}}
    _mistakes(engine, 3, "lockup", 6)
    _capture(engine, monkeypatch)

    _drive(engine, 5, _slow_corner(3, 4400), lap_time_ms=92_000)

    progress = engine._coach_lesson["progress"]
    assert progress["best_delta_ms"] == -1000
    assert "Быстрее прошлого визита" in progress["text"]
    assert progress["focus_corner_id"] == 3


# ── Границы сессии и трассы ──────────────────────────────────────────────────

def _complete_lap(engine, from_lap: int, to_lap: int, lap_time_ms: int) -> None:
    """Пересечение линии старт/финиш ЧЕРЕЗ настоящий обработчик пакета.

    Через `_apply_telemetry_delta`, а не прямым вызовом `_coach_observe_lap`:
    проверяемое здесь условие (пит-круг не кормит цену) живёт именно в
    обработчике, и вызов внутреннего метода мимо него проверял бы сам тест."""
    engine._player_car_index = 0
    engine._prev_lap = from_lap
    engine._consume_telemetry_delta(TelemetryDelta("lap_data", {
        "lap_info": {},
        "player_lap": {"current_lap": to_lap, "last_lap_ms": lap_time_ms,
                       "s1_ms": 1, "s2_ms": 1, "s3_ms": 1},
    }, 0, 2025))


def test_pit_lap_never_feeds_the_price_of_a_corner(engine, monkeypatch):
    """После въезда на пит-лейн метрики оставшихся поворотов описывают проезд по
    другой траектории — цена, посчитанная по ним, назначила бы главной проблемой
    сессии пит-лейн."""
    engine.coach_reference = ReferenceLap(90_000, _lap(_flat()), "career")
    monkeypatch.setattr(engine.coach_tracer, "finish_lap",
                        lambda: _slow_corner(3, 9000))

    engine._current_lap_pit = True
    _complete_lap(engine, from_lap=4, to_lap=5, lap_time_ms=110_000)
    assert engine.coach_history.lap_count == 0

    engine._current_lap_pit = False
    _complete_lap(engine, from_lap=5, to_lap=6, lap_time_ms=90_000)
    assert engine.coach_history.lap_count == 1


def test_no_reference_means_no_lesson_yet(engine):
    engine.coach_reference = None

    _drive(engine, 5, _slow_corner(3, 4400))

    assert engine.coach_history.lap_count == 5     # копится всё равно
    assert engine._coach_lesson is None


def test_session_restart_forgets_the_work_but_keeps_the_track_reference(engine):
    """Круги квалификации и круги гонки в одну медиану складывать нельзя: у них
    разное топливо и разная задача. А эталон переживает смену сессии — он про
    трассу."""
    from tests.telemetry import consume_f1_event_packet

    engine.coach_reference = ReferenceLap(90_000, _lap(_flat()), "career")
    _mistakes(engine, 3, "lockup", 6)
    _drive(engine, 5, _slow_corner(3, 4400))
    assert engine.coach_focus.state is not None

    consume_f1_event_packet(engine, _event_buf("SSTA"))

    assert engine.coach_history.lap_count == 0
    assert engine.coach_focus.state is None
    assert engine._coach_lesson is None
    assert engine.coach_reference is not None      # эталон привязан к трассе


def test_track_change_forgets_the_work_and_the_track_reference(engine, monkeypatch):
    """Седьмой поворот на новой трассе — другое место, и его цена с прошлой
    трассы означала бы не то."""
    monkeypatch.setattr(eng_mod, "load_track_history", lambda tid: TrackHistory())
    engine.coach_reference = ReferenceLap(90_000, _lap(_flat()), "career")
    engine._coach_previous_lesson = {"best_lap_ms": 1}
    _mistakes(engine, 3, "lockup", 6)
    _drive(engine, 5, _slow_corner(3, 4400))

    engine._consume_telemetry_delta(_session_delta(track_id=13))

    assert engine.coach_history.lap_count == 0
    assert engine.coach_focus.state is None
    assert engine._coach_lesson is None
    assert engine._coach_previous_lesson is None
    assert engine.coach_reference is None
