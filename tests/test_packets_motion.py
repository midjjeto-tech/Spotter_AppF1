"""PACKET_MOTION (id 0) — мировые координаты + вектор "право" для всех 22
машин. Golden-master раскладка CarMotionData (60 байт/машина) — офсеты
реконструированы по публичному формату F1 UDP (стабилен с F1 2020), требуют
живой сверки через SPOTTER_DIAG=1 (не сделана в рамках этой задачи).
См. docs/superpowers/specs/2026-07-18-real-spotter-motion-design.md.
"""
import struct

import pytest

from core import packets
from core.packets import HEADER_SIZE, MOTION_SIZE


def _buf(size: int) -> bytearray:
    return bytearray(size)


def test_motion_fields_world_position_and_right_vector():
    buf = _buf(HEADER_SIZE + MOTION_SIZE)
    base = HEADER_SIZE
    struct.pack_into("<f", buf, base + 0, 100.5)     # world_x
    struct.pack_into("<f", buf, base + 8, -50.25)    # world_z
    struct.pack_into("<h", buf, base + 30, 32767)    # right_x -> 1.0
    struct.pack_into("<h", buf, base + 34, -16383)   # right_z -> ~-0.5

    out = packets.parse_motion_all(bytes(buf))
    assert out[0]["world_x"] == pytest.approx(100.5)
    assert out[0]["world_z"] == pytest.approx(-50.25)
    assert out[0]["right_x"] == pytest.approx(1.0, abs=1e-4)
    assert out[0]["right_z"] == pytest.approx(-0.5, abs=1e-3)


def test_motion_all_reads_multiple_cars_at_correct_stride():
    buf = _buf(HEADER_SIZE + 3 * MOTION_SIZE)
    base1 = HEADER_SIZE + 1 * MOTION_SIZE
    struct.pack_into("<f", buf, base1 + 0, 7.0)

    out = packets.parse_motion_all(bytes(buf))
    assert out[0]["world_x"] == pytest.approx(0.0)
    assert out[1]["world_x"] == pytest.approx(7.0)
    assert 2 in out


def test_motion_all_truncated_buffer_stops_early_without_error():
    buf = _buf(HEADER_SIZE + MOTION_SIZE + 10)   # вторая машина неполная
    out = packets.parse_motion_all(bytes(buf))
    assert list(out.keys()) == [0]


def test_motion_all_empty_data_returns_empty_dict():
    assert packets.parse_motion_all(b"") == {}


def test_motion_diag_throttle_skips_second_call_within_window(monkeypatch):
    """DIAG-лог на КАЖДЫЙ Motion-пакет (20-60 Гц) захлестнул бы лог — сводная
    строка "parsed=N/22 cars" троттлится раз в 2с (тот же приём, что
    _last_ers_diag_t в test_packets_gaps_tyre.py). Троттлинг относится
    ТОЛЬКО к сводной строке — построчный per-car DIAG (idx=...) намеренно
    нетроттлирован (см. docstring parse_motion_all), поэтому здесь считаем
    вызовы _log.warning, отфильтрованные по "parsed=" в формат-строке, а не
    все подряд."""
    import time as time_mod
    from core import packets as pk

    monkeypatch.setattr(pk, "_DIAG", True)
    monkeypatch.setattr(pk, "_last_motion_diag_t", 0.0)
    calls = []
    monkeypatch.setattr(pk._log, "warning", lambda *a, **kw: calls.append(a))

    buf = _buf(HEADER_SIZE + MOTION_SIZE)

    def summary_calls():
        return [c for c in calls if "parsed=" in c[0]]

    pk.parse_motion_all(bytes(buf))                 # первый вызов — логирует
    assert len(summary_calls()) == 1

    pk.parse_motion_all(bytes(buf))                 # сразу второй — троттлинг молчит
    assert len(summary_calls()) == 1

    monkeypatch.setattr(pk, "_last_motion_diag_t", time_mod.time() - 3.0)  # "прошло" 3с
    pk.parse_motion_all(bytes(buf))
    assert len(summary_calls()) == 2


# --------------------------------------------------------------------------- #
# Golden-master раскладка CarMotionData — см. docstring выше про статус
# верификации. Сумма = 60 = MOTION_SIZE.
# --------------------------------------------------------------------------- #
_MOTION_LAYOUT = [
    ("m_worldPositionX",     0,  "f"),
    ("m_worldPositionY",     4,  "f"),
    ("m_worldPositionZ",     8,  "f"),
    ("m_worldVelocityX",     12, "f"),
    ("m_worldVelocityY",     16, "f"),
    ("m_worldVelocityZ",     20, "f"),
    ("m_worldForwardDirX",   24, "h"),
    ("m_worldForwardDirY",   26, "h"),
    ("m_worldForwardDirZ",   28, "h"),
    ("m_worldRightDirX",     30, "h"),
    ("m_worldRightDirY",     32, "h"),
    ("m_worldRightDirZ",     34, "h"),
    ("m_gForceLateral",      36, "f"),
    ("m_gForceLongitudinal", 40, "f"),
    ("m_gForceVertical",     44, "f"),
    ("m_yaw",                48, "f"),
    ("m_pitch",              52, "f"),
    ("m_roll",               56, "f"),
]


def test_motion_layout_sums_to_motion_size():
    total = _MOTION_LAYOUT[-1][1] + struct.calcsize(_MOTION_LAYOUT[-1][2])
    assert total == MOTION_SIZE == 60
