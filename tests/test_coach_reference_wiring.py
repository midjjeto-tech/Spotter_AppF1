"""Проводка эталонного сравнения: круг -> дельты -> реплика.

Как и в фазе 1, зелёные юнит-тесты сравнения ничего не говорят о том, доехало
ли до эфира — здесь проверяется именно путь наружу.
"""
import pytest

import core.engine as eng_mod
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


def _lap(duration_by_corner: dict[int, int]) -> dict[int, CornerMetrics]:
    return {cid: CornerMetrics(cid, 100.0 * cid, 120.0, 100.0 * cid + 40, ms)
            for cid, ms in duration_by_corner.items()}


def _flat(ms: int) -> dict[int, int]:
    return {i: ms for i in range(1, 9)}


def _capture(engine, monkeypatch):
    drafts, codes = [], []
    monkeypatch.setattr(engine._commentary_events, "publish", drafts.append)
    monkeypatch.setattr(engine, "_render_engineer_phrase",
                        lambda draft, code, *a, **kw: (codes.append(code), "ф")[1])
    return drafts, codes


def test_repeated_local_loss_publishes_reference_advice(engine, monkeypatch):
    engine.settings["driving_coach_enabled"] = True
    drafts, codes = _capture(engine, monkeypatch)
    engine.coach_reference = ReferenceLap(90000, _lap(_flat(4000)), "career")

    slow = _flat(4000)
    slow[3] = 6000
    for lap in (1, 2, 3):
        engine._compare_lap_to_reference(_lap(slow), lap=lap)

    assert codes == ["coach.ref_losing_time"]
    assert len(drafts) == 1
    assert drafts[0]["corner_id"] == 3
    assert drafts[0]["speaker"] == eng_mod.SPEAKER_ENGINEER
    assert drafts[0].get("priority") != "critical"
    assert drafts[0].get("bypass_speak_threshold") is not True


def test_single_lap_never_speaks(engine, monkeypatch):
    engine.settings["driving_coach_enabled"] = True
    drafts, _ = _capture(engine, monkeypatch)
    engine.coach_reference = ReferenceLap(90000, _lap(_flat(4000)), "career")

    slow = _flat(4000)
    slow[3] = 6000
    engine._compare_lap_to_reference(_lap(slow), lap=1)

    assert drafts == []


def test_uniform_slowness_never_speaks(engine, monkeypatch):
    """Тяжёлый бак делает медленнее весь круг. Об этом коуч говорить не должен
    ни на каком круге."""
    engine.settings["driving_coach_enabled"] = True
    drafts, _ = _capture(engine, monkeypatch)
    engine.coach_reference = ReferenceLap(90000, _lap(_flat(4000)), "career")

    for lap in (1, 2, 3, 4, 5):
        engine._compare_lap_to_reference(_lap(_flat(5000)), lap=lap)

    assert drafts == []


def test_no_reference_means_silence(engine, monkeypatch):
    engine.settings["driving_coach_enabled"] = True
    drafts, _ = _capture(engine, monkeypatch)
    engine.coach_reference = None

    for lap in (1, 2, 3):
        engine._compare_lap_to_reference(_lap(_flat(4000)), lap=lap)

    assert drafts == []


def test_disabled_coach_stays_silent(engine, monkeypatch):
    engine.settings["driving_coach_enabled"] = False
    drafts, _ = _capture(engine, monkeypatch)
    engine.coach_reference = ReferenceLap(90000, _lap(_flat(4000)), "career")

    slow = _flat(4000)
    slow[3] = 6000
    for lap in (1, 2, 3):
        engine._compare_lap_to_reference(_lap(slow), lap=lap)

    assert drafts == []


def test_delta_table_is_built_even_when_silent(engine, monkeypatch):
    """Дебриф не зависит от тумблера и от правила повтора."""
    engine.settings["driving_coach_enabled"] = False
    _capture(engine, monkeypatch)
    engine.coach_reference = ReferenceLap(90000, _lap(_flat(4000)), "career")

    engine._compare_lap_to_reference(_lap(_flat(4200)), lap=1)

    assert len(engine._coach_last_deltas) == 8
    assert engine._coach_last_deltas[0]["duration_ms"] == 200


def test_fastest_lap_of_the_session_becomes_the_reference(engine):
    """Пока карьерного эталона нет, эталоном служит лучший круг сессии."""
    engine.coach_reference = None
    engine._note_lap_reference(_lap(_flat(4000)), lap_time_ms=95000)
    engine._note_lap_reference(_lap(_flat(3800)), lap_time_ms=91000)

    assert engine.coach_reference is not None
    assert engine.coach_reference.lap_time_ms == 91000
    assert engine.coach_reference.source == "session"


def test_slower_session_lap_does_not_replace_the_reference(engine):
    engine.coach_reference = None
    engine._note_lap_reference(_lap(_flat(3800)), lap_time_ms=91000)
    engine._note_lap_reference(_lap(_flat(4000)), lap_time_ms=95000)

    assert engine.coach_reference.lap_time_ms == 91000


def test_career_reference_is_not_replaced_by_a_slower_session_lap(engine):
    engine.coach_reference = ReferenceLap(89000, _lap(_flat(3500)), "career")
    engine._note_lap_reference(_lap(_flat(4000)), lap_time_ms=95000)

    assert engine.coach_reference.source == "career"
    assert engine.coach_reference.lap_time_ms == 89000


def test_empty_lap_metrics_are_ignored(engine):
    engine.coach_reference = None
    engine._note_lap_reference({}, lap_time_ms=91000)
    assert engine.coach_reference is None


def test_reference_advice_names_the_corner_it_is_about(engine, monkeypatch):
    """Здесь место критичнее, чем в фазе 1: сравнение считается на пересечении
    линии старт/финиш, поэтому прежние «здесь» и «в этом повороте» звучали на
    прямой и указывали в никуда — поворот мог остаться почти круг назад."""
    engine.settings["driving_coach_enabled"] = True
    engine.coach_reference = ReferenceLap(90000, _lap(_flat(4000)), "career")
    seen = {}
    monkeypatch.setattr(engine._commentary_events, "publish", lambda d: None)
    monkeypatch.setattr(
        engine, "_render_engineer_phrase",
        lambda draft, code, fields=None, *a, **kw: (seen.update(fields=fields),
                                                    "фраза")[1])

    metrics = _lap(_flat(4000))
    metrics[4] = CornerMetrics(4, 400.0, 120.0, 440.0, 5200)
    for lap in (1, 2, 3):
        engine._compare_lap_to_reference(metrics, lap)

    assert seen["fields"] == {"corner_no": "четвёртом"}


# ── Фоновая загрузка карьерного эталона ──────────────────────────────────────
# Чтение архива ушло с потока телеметрии в фон (перебирается ВЕСЬ архив заездов
# с диска). Вместе с фоном появились две гонки, которых у синхронного вызова
# быть не могло, — обе проверяются ниже.

def _join_last_task(engine, timeout: float = 5.0) -> None:
    engine._task_threads[-1].join(timeout=timeout)


def test_background_load_installs_the_career_reference(engine, monkeypatch):
    monkeypatch.setattr(eng_mod, "load_career_reference",
                        lambda tid: ReferenceLap(88000, _lap(_flat(3400)), "career"))
    engine._track_id = 7
    engine.coach_reference = None

    engine._start_coach_reference_load(7)
    _join_last_task(engine)

    assert engine.coach_reference is not None
    assert engine.coach_reference.lap_time_ms == 88000


def test_background_load_is_dropped_if_the_track_changed_meanwhile(engine, monkeypatch):
    """Пилот успел выйти в меню и выбрать другую трассу, пока читался диск.
    Эталон с прошлой трассы — не просто устаревший, а прямо вредный: коуч начнёт
    сравнивать повороты Монцы с повортами Спа."""
    monkeypatch.setattr(eng_mod, "load_career_reference",
                        lambda tid: ReferenceLap(88000, _lap(_flat(3400)), "career"))
    engine._track_id = 9          # трасса уже другая
    engine.coach_reference = None

    engine._start_coach_reference_load(7)
    _join_last_task(engine)

    assert engine.coach_reference is None


def test_background_load_does_not_roll_the_target_back(engine, monkeypatch):
    """Пилот проехал круг быстрее карьерного рекорда, пока читался диск.
    Поставить карьерный эталон поверх — откатить цель НАЗАД, к более медленному
    кругу; `_note_lap_reference` обещает обратное."""
    monkeypatch.setattr(eng_mod, "load_career_reference",
                        lambda tid: ReferenceLap(95000, _lap(_flat(4200)), "career"))
    engine._track_id = 7
    engine._note_lap_reference(_lap(_flat(3600)), lap_time_ms=90000)

    engine._start_coach_reference_load(7)
    _join_last_task(engine)

    assert engine.coach_reference.lap_time_ms == 90000
    assert engine.coach_reference.source == "session"


def test_background_load_failure_leaves_the_coach_without_a_reference(engine, monkeypatch):
    """Битый архив не должен ронять поток и не должен оставлять мусор: коуч без
    эталона просто ждёт лучший круг сессии."""
    def _boom(_tid):
        raise OSError("archive unreadable")

    monkeypatch.setattr(eng_mod, "load_career_reference", _boom)
    engine._track_id = 7
    engine.coach_reference = None

    engine._start_coach_reference_load(7)
    _join_last_task(engine)

    assert engine.coach_reference is None
