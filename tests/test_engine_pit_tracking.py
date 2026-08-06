# tests/test_engine_pit_tracking.py
import struct

import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.packets import HEADER_SIZE, LAP_DATA_SIZE, PACKET_LAP_DATA
from tests.telemetry import consume_f1_packet


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _lap_buf(*, current_lap=5, pit_status=0, last_lap_ms=0):
    """Минимальный однокруговой LapData-буфер. position=0 намеренно — см. коммент
    перед этим блоком (пропускаем grid/rival_tracker, не нужные для этих тестов)."""
    buf = bytearray(HEADER_SIZE + LAP_DATA_SIZE)
    base = HEADER_SIZE
    struct.pack_into("<I", buf, base + 0, last_lap_ms)
    buf[base + 33] = current_lap
    buf[base + 34] = pit_status
    return bytes(buf)


def test_current_lap_pit_accumulates_and_live_status_tracked(engine):
    engine._player_car_index = 0
    engine._prev_lap = 5          # совпадает с current_lap ниже -> круг НЕ завершается
    engine._current_lap_pit = False
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(current_lap=5, pit_status=0))
    assert engine._current_lap_pit is False
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(current_lap=5, pit_status=1))
    assert engine._current_lap_pit is True
    assert engine._player_pit_status == 1
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(current_lap=5, pit_status=0))
    assert engine._current_lap_pit is True   # не сбрасывается тиком без pit_status
    assert engine._player_pit_status == 0    # но живой статус обновился


def test_lap_complete_passes_pit_lap_to_recorder_and_skips_coach(engine):
    engine._player_car_index = 0
    engine._prev_lap = 4
    engine._current_lap_pit = True
    engine.recorder.reset()

    calls = []
    class _StubCoach:
        def add_lap(self, **kw):
            calls.append(kw)
        def get_state(self):
            return {}   # _maybe_snapshot() зовёт это безусловно — стаб должен его иметь
    engine.driver_coach = _StubCoach()

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(current_lap=5, pit_status=0, last_lap_ms=125000))

    laps = engine.recorder.laps()
    assert len(laps) == 1 and laps[0]["pit_lap"] is True
    assert engine._current_lap_pit is False        # сброшен для следующего круга
    assert engine._last_completed_lap_was_pit is True
    assert calls == []                             # driver_coach пропущен для пит-круга


def test_driver_coach_called_for_normal_lap(engine):
    engine._player_car_index = 0
    engine._prev_lap = 4
    engine._current_lap_pit = False
    engine.recorder.reset()

    calls = []
    class _StubCoach:
        def add_lap(self, **kw):
            calls.append(kw)
        def get_state(self):
            return {}
    engine.driver_coach = _StubCoach()

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(current_lap=5, pit_status=0, last_lap_ms=91000))

    assert len(calls) == 1
    assert engine.recorder.laps()[-1]["pit_lap"] is False


def test_snapshot_receives_pit_status_and_pit_lap(engine):
    engine._player_car_index = 0
    engine._last_snap_t = 0.0    # снять троттлинг _maybe_snapshot()
    engine._prev_lap = 4
    engine._current_lap_pit = True
    engine.recorder.reset()
    engine.driver_coach = type("_StubCoach", (), {
        "add_lap": lambda self, **kw: None,
        "get_state": lambda self: {},   # _maybe_snapshot() зовёт это безусловно
    })()

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(current_lap=5, pit_status=0, last_lap_ms=125000))

    snap = engine.timeline._snapshots[-1]
    assert snap.get("pit_lap") is True    # ретроспективно — только что завершённый круг был пит-кругом
    assert snap.get("pit_status") == 0    # живой статус — уже выехали из боксов
