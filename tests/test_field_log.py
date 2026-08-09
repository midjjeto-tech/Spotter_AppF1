"""Полевой журнал живого заезда (core/field_log.py).

Главное свойство, ради которого он существует: заезд, в котором коуч ПРОМОЛЧАЛ,
должен остаться разбираемым. Событийный лог на такой вопрос не отвечает — там
просто нет строк, — поэтому половина тестов здесь про распределения сигналов, а
не про события.
"""
from __future__ import annotations

import json

import pytest

from core.field_log import DISABLED, FieldLog, create


def _log(tmp_path, **kw):
    fl = FieldLog(enabled=True, path=str(tmp_path / "diag.jsonl"), **kw)
    fl.start()
    return fl


def _lines(fl) -> list[dict]:
    with open(fl.path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ── Выключенное состояние ────────────────────────────────────────────────────

def test_disabled_log_writes_nothing_and_never_raises(tmp_path):
    """Выключен — значит бесплатен и безвреден: ни файла, ни исключений."""
    fl = FieldLog(enabled=False, path=str(tmp_path / "nope.jsonl"))
    fl.start()
    fl.record("anything", a=1)
    fl.observe("channel", 1.0, (0.5,))
    fl.flush_stats(lap=1)
    fl.stop()

    assert not (tmp_path / "nope.jsonl").exists()


def test_module_level_stub_is_safe_to_call():
    """DISABLED существует, чтобы вызывающим не приходилось проверять None на
    каждом кадре."""
    DISABLED.record("x", y=1)
    DISABLED.observe("c", 1.0)
    assert DISABLED.enabled is False


@pytest.mark.parametrize("settings,expected", [
    ({}, False),
    ({"field_diagnostics": False}, False),
    ({"field_diagnostics": True}, True),
])
def test_settings_switch(settings, expected, monkeypatch):
    monkeypatch.delenv("SPOTTER_DIAG", raising=False)
    assert create(settings).enabled is expected


def test_env_switch_works_without_settings(monkeypatch):
    """В собранном приложении переменную окружения выставить неоткуда, а в
    дереве разработки она удобнее правки JSON — поэтому переключателя два."""
    monkeypatch.setenv("SPOTTER_DIAG", "1")
    assert create({}).enabled is True


# ── События ──────────────────────────────────────────────────────────────────

def test_event_name_survives_a_field_of_the_same_name(tmp_path):
    """Регрессия на молчаливую порчу журнала.

    `record("coach_mistake", kind="lockup")` раньше подменял ИМЯ СОБЫТИЯ полем:
    запись уезжала в лог как "lockup", и восстановить по ней, что это была
    ошибка коуча, было уже нельзя. Тихая порча диагностики хуже падения —
    падение хотя бы заметно."""
    fl = _log(tmp_path)
    fl.record("coach_mistake", kind="lockup", t="перезапись служебного поля")
    fl.stop()

    entry = next(e for e in _lines(fl) if e["kind"] == "coach_mistake")
    assert entry["kind_"] == "lockup", "значение поля потерялось"
    assert entry["t_"] == "перезапись служебного поля"
    assert isinstance(entry["t"], float)


def test_unserialisable_values_do_not_break_the_log(tmp_path):
    """В поля попадают dataclass'ы и Path. Падать из-за них журнал не имеет
    права: заезд бывает один раз."""
    class Odd:
        def __repr__(self):
            return "<odd>"

    fl = _log(tmp_path)
    fl.record("weird", value=Odd())
    fl.stop()

    assert any(e.get("value") == "<odd>" for e in _lines(fl))


def test_session_start_carries_the_environment(tmp_path):
    fl = FieldLog(enabled=True, path=str(tmp_path / "d.jsonl"))
    fl.start(app_version="0.1.0", driving_coach_enabled=True)
    fl.stop()

    start = _lines(fl)[0]
    assert start["kind"] == "session_start"
    assert start["app_version"] == "0.1.0"
    assert start["driving_coach_enabled"] is True


# ── Распределения ────────────────────────────────────────────────────────────

def test_signals_are_summarised_per_flush(tmp_path):
    fl = _log(tmp_path)
    for value in (-0.18, -0.23, -0.20):
        fl.observe("lockup.slip_fl", value, (-0.25,))
    fl.flush_stats(lap=1)
    fl.stop()

    channels = next(e for e in _lines(fl) if e["kind"] == "signals")["channels"]
    stat = channels["lockup.slip_fl"]
    assert stat["n"] == 3
    assert stat["min"] == -0.23
    assert stat["max"] == -0.18


def test_a_silent_lap_still_shows_how_close_the_signal_came(tmp_path):
    """САМЫЙ ВАЖНЫЙ случай: порог не перейдён ни разу. Событий нет, но по
    минимуму видно, что пилот подошёл к -0.25 на две сотых — то есть порог надо
    двигать, а не искать ошибку в сигнале."""
    fl = _log(tmp_path)
    for value in (-0.18, -0.23, -0.19):
        fl.observe("lockup.slip_fl", value, (-0.25,))
    fl.flush_stats(lap=4)
    fl.stop()

    stat = next(e for e in _lines(fl)
                if e["kind"] == "signals")["channels"]["lockup.slip_fl"]
    assert stat["over"] == {}, "порог не переходили — превышений быть не должно"
    assert stat["min"] == -0.23


def test_threshold_crossings_are_counted_for_both_signs(tmp_path):
    """Порог блокировки отрицательный, порог пробуксовки положительный —
    «превышение» у них в разные стороны."""
    fl = _log(tmp_path)
    for value in (-0.30, -0.10, -0.26):
        fl.observe("lockup", value, (-0.25,))
    for value in (0.30, 0.10, 0.26):
        fl.observe("wheelspin", value, (0.20,))
    fl.flush_stats(lap=2)
    fl.stop()

    channels = next(e for e in _lines(fl) if e["kind"] == "signals")["channels"]
    assert channels["lockup"]["over"]["-0.25"] == 2
    assert channels["wheelspin"]["over"]["0.2"] == 2


def test_flush_resets_the_counters(tmp_path):
    """Иначе сводка круга включала бы всю сессию и стала бы бесполезной."""
    fl = _log(tmp_path)
    fl.observe("c", 1.0)
    fl.flush_stats(lap=1)
    fl.observe("c", 5.0)
    fl.flush_stats(lap=2)
    fl.stop()

    summaries = [e for e in _lines(fl) if e["kind"] == "signals"]
    assert summaries[0]["channels"]["c"]["n"] == 1
    assert summaries[1]["channels"]["c"] == {"n": 1, "min": 5.0, "max": 5.0,
                                             "avg": 5.0, "over": {}}


def test_flush_without_observations_writes_nothing(tmp_path):
    fl = _log(tmp_path)
    fl.flush_stats(lap=1)
    fl.stop()

    assert not [e for e in _lines(fl) if e["kind"] == "signals"]


def test_non_numeric_observation_is_ignored(tmp_path):
    fl = _log(tmp_path)
    fl.observe("c", None)
    fl.observe("c", "быстро")
    fl.observe("c", 2.0)
    fl.flush_stats(lap=1)
    fl.stop()

    stat = next(e for e in _lines(fl) if e["kind"] == "signals")["channels"]["c"]
    assert stat["n"] == 1


def test_stop_flushes_the_tail(tmp_path):
    """Заезд обычно заканчивается не на границе круга — незакрытая сводка не
    должна пропасть."""
    fl = _log(tmp_path)
    fl.observe("c", 3.0)
    fl.stop()

    assert any(e["kind"] == "signals" for e in _lines(fl))
    assert _lines(fl)[-1]["kind"] == "session_end"
