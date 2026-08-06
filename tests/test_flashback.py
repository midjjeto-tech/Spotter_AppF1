"""Флэшбек (перемотка): слив очереди до-флэшбековых событий + сброс состояния.

Bug: комментатор не видел перемотку и продолжал озвучивать события «до флэшбека».
"""
import queue
import time

import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.race_ai.analyzer import RaceAnalyzer
import config


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None      # без Yandex-клиента / сети
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


# --------------------------------------------------------------------------- #
# RaceAnalyzer.reset_transient
# --------------------------------------------------------------------------- #

def test_race_analyzer_reset_transient_clears_history():
    a = RaceAnalyzer()
    for _ in range(5):
        a.update({"gap_behind_ms": 500, "driver_behind": "Албон"})
    assert len(a.battle_detector._history) > 0
    assert a._prev_gap_behind is not None

    a.reset_transient()
    assert len(a.battle_detector._history) == 0
    assert a._prev_gap_behind is None
    assert a.get_state()["mode"] == "CALM"


# --------------------------------------------------------------------------- #
# F1Engine._handle_flashback
# --------------------------------------------------------------------------- #

def test_flashback_drains_pending_event_queue(engine):
    for _ in range(4):
        engine._commentary_events.publish({"event_code": "OVTK", "priority": "normal"})
    assert not engine._commentary_events.empty()

    engine._handle_flashback()

    assert engine._commentary_events.empty()          # до-флэшбековые события выброшены


def test_flashback_resets_situation_dedup(engine):
    engine._situation_dedup._last_sig = ("front", "Албон", "vclose")
    engine._situation_dedup._last_t = time.time()

    engine._handle_flashback()

    assert engine._situation_dedup._last_sig is None


def test_flashback_sets_silence_window(engine):
    engine._flashback_until = 0.0
    engine._handle_flashback()
    # тишина действует FLASHBACK_SILENCE секунд вперёд
    assert engine._flashback_until > time.time()
    assert engine._flashback_until <= time.time() + config.FLASHBACK_SILENCE + 0.5


def test_flashback_empty_queue_is_safe(engine):
    # очередь уже пуста — не должно бросать queue.Empty
    while not engine._commentary_events.empty():
        engine._commentary_events.get_nowait()
    engine._handle_flashback()   # без исключений
    assert engine._commentary_events.empty()
