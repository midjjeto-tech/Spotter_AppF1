"""Вердикт о сигнале обязывает коуча молчать, а не украшает экран.

До 2026-08-15 `CoachHealth` считал `signal` и показывал его пилоту, но детектор
публиковал подсказки независимо. Разбор архива показал цену: в реальных заездах
Майами пики `wheelspin` доходили до 5.4 при `SANE_MAX_SLIP_RATIO = 3.0` — то есть
приложение СВОИМИ ЖЕ порогами объявляло данные невозможными и всё равно по ним
советовало. Это ровно то, ради чего коуча держат выключенным по умолчанию.
"""
from __future__ import annotations

import pytest

from core.coach_ai.health import (
    CoachHealth, MIN_FRAMES_FOR_VERDICT, SANE_MAX_SLIP_RATIO, SIGNAL_IMPLAUSIBLE,
    SIGNAL_OK, SIGNAL_WARMING_UP,
)


def _drive(health: CoachHealth, frames: int, *, ratio: float = 0.05) -> None:
    for _ in range(frames):
        health.observe_frame({
            "speed_kmh": 200.0,
            "slip_ratio": {"rl": ratio, "rr": ratio, "fl": 0.0, "fr": 0.0},
            "slip_angle": {"rl": 0.02, "rr": 0.02, "fl": 0.01, "fr": 0.01},
            "throttle_pct": 50.0, "brake_pct": 0.0,
        })


def test_a_healthy_signal_is_trusted():
    health = CoachHealth()
    _drive(health, MIN_FRAMES_FOR_VERDICT + 10)

    assert health.signal == SIGNAL_OK
    assert health.trusted is True


def test_an_impossible_slip_ratio_is_not_trusted():
    """Значение выше физического потолка означает, что раскладка пакета не
    сходится, — по такому сигналу нельзя называть колесо."""
    health = CoachHealth()
    _drive(health, MIN_FRAMES_FOR_VERDICT + 10, ratio=SANE_MAX_SLIP_RATIO + 2.0)

    assert health.signal == SIGNAL_IMPLAUSIBLE
    assert health.trusted is False
    assert health.silence_reason_for_signal == "signal_not_trusted"


def test_the_coach_stays_quiet_until_the_signal_is_verified():
    """`warming_up` тоже молчит: правило простое — не говорить, пока не
    убедились, что сигнал настоящий. Это первые ~10 секунд движения."""
    health = CoachHealth()
    _drive(health, 10)

    assert health.signal == SIGNAL_WARMING_UP
    assert health.trusted is False
    assert health.silence_reason_for_signal == "signal_warming_up"


def test_every_signal_reason_has_words_for_the_pilot():
    """Причина молчания обязана быть выполнимой фразой, а не именем ключа."""
    from core.coach_ai.health import SILENCE_RU

    for key in ("signal_not_trusted", "signal_warming_up"):
        assert key in SILENCE_RU and SILENCE_RU[key].strip()


# ── Проводка: гейт стоит на пути публикации ──────────────────────────────────

@pytest.fixture
def engine(monkeypatch):
    import core.engine as eng_mod
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    return eng_mod.F1Engine({})


def _mistake(lap: int, kind: str = "lockup"):
    from core.coach_ai.models import CornerMistake
    return CornerMistake(kind=kind, wheel="fl", corner_id=3, corner_name="T3",
                         phase="braking", lap=lap, peak=1.0, duration_s=0.4,
                         speed_kmh=180)


def _repeat_on_laps(engine, laps=range(1, 6)):
    """Правило повтора считает РАЗНЫЕ круги: одна и та же ошибка на одном круге
    привычкой не становится (core/coach_ai/repeat.py)."""
    for lap in laps:
        engine._emit_coach_advice(_mistake(lap), now=1000.0 + lap)


def test_an_untrusted_signal_blocks_the_advice(engine):
    engine.settings["driving_coach_enabled"] = True
    _drive(engine.coach_health, MIN_FRAMES_FOR_VERDICT + 10,
           ratio=SANE_MAX_SLIP_RATIO + 2.0)
    while not engine._commentary_events.empty():
        engine._commentary_events.get_nowait()

    # Правило повтора должно быть пройдено, иначе замолчит оно, а не гейт.
    _repeat_on_laps(engine)

    assert engine._commentary_events.empty()
    assert engine.coach_health.silence["signal_not_trusted"] > 0


def test_a_trusted_signal_lets_the_advice_through(engine):
    """Обратная сторона: гейт не должен превратиться в цензуру."""
    engine.settings["driving_coach_enabled"] = True
    _drive(engine.coach_health, MIN_FRAMES_FOR_VERDICT + 10)
    while not engine._commentary_events.empty():
        engine._commentary_events.get_nowait()

    _repeat_on_laps(engine)

    assert engine.coach_health.silence.get("signal_not_trusted", 0) == 0
