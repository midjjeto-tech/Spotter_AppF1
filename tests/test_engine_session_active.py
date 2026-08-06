# tests/test_engine_session_active.py
"""_session_active: отражает "сессия сейчас реально идёт" (SSTA..CHQF/SEND),
в отличие от "connected" (жив ли UDP-сокет) и "_session_type" (не сбрасывается
на SEND). Баг: _ambient_loop/_maybe_emit_gap_digest продолжали штамповать
реплики на устаревшей телеметрии несколько минут после конца сессии, потому
что гейтились только на connected/session_type.
"""
import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from tests.telemetry import consume_f1_event_packet, set_connection


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _event_buf(code: str) -> bytes:
    from core.packets import HEADER_SIZE
    buf = bytearray(HEADER_SIZE + 4)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = code.encode("ascii")
    return bytes(buf)


def test_session_active_starts_false(engine):
    assert engine._session_active is False


def test_ssta_sets_session_active_true(engine):
    engine._session_active = False
    consume_f1_event_packet(engine, _event_buf("SSTA"))
    assert engine._session_active is True


@pytest.mark.parametrize("code", ["SEND", "CHQF"])
def test_send_chqf_sets_session_active_false(engine, code):
    engine._session_active = True
    consume_f1_event_packet(engine, _event_buf(code))
    assert engine._session_active is False


def test_gap_digest_silent_after_session_end_even_if_connected_and_race(engine):
    """Точное воспроизведение бага: после SEND session_type всё ещё "race"
    (игра не сбрасывает его), connected всё ещё True (игра шлёт пакеты из
    меню/результатов) — раньше это давало ложное "можно говорить"."""
    engine._session_type = "race"
    set_connection(engine, True)
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_active = True
    consume_f1_event_packet(engine, _event_buf("SEND"))  # -> _session_active = False

    assert engine._maybe_emit_gap_digest(__import__("time").time()) is False


def test_gap_digest_resumes_after_new_session_start(engine):
    """Новый SSTA снова включает _session_active — цикл не остаётся заглушённым
    навсегда после одной завершённой сессии."""
    engine._session_type = "unknown"
    engine._session_active = False
    consume_f1_event_packet(engine, _event_buf("SSTA"))
    assert engine._session_active is True
