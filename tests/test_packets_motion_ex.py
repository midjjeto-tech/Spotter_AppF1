"""PACKET_MOTION_EX (id 13) — проскальзывание по колёсам.

Golden-master раскладка PacketMotionExData: офсеты реконструированы по
публичному формату F1 UDP, требуют живой сверки через SPOTTER_DIAG=1
(Task 13 плана docs/superpowers/plans/2026-08-06-driving-coach-phase1.md).

Порядок колёс во ВСЕХ массивах: RL, RR, FL, FR. Отдельный тест ниже стоит
именно на порядке — перепутанный порядок даёт правдоподобные, но неверные
числа, и коуч начинает называть не то колесо.
"""
import struct

import pytest

from core import packets
from core.packets import HEADER_SIZE, WHEEL_ORDER


def _buf(size: int) -> bytearray:
    return bytearray(size)


def _motion_ex_buf() -> bytearray:
    return _buf(HEADER_SIZE + packets.MOTION_EX_MIN_SIZE)


def test_slip_ratio_read_per_wheel_in_rl_rr_fl_fr_order():
    buf = _motion_ex_buf()
    base = HEADER_SIZE + packets._MOTION_EX_SLIP_RATIO_OFF
    struct.pack_into("<ffff", buf, base, -0.4, -0.1, 0.0, 0.25)

    out = packets.parse_motion_ex(bytes(buf))

    assert out["slip_ratio"]["rl"] == pytest.approx(-0.4)
    assert out["slip_ratio"]["rr"] == pytest.approx(-0.1)
    assert out["slip_ratio"]["fl"] == pytest.approx(0.0)
    assert out["slip_ratio"]["fr"] == pytest.approx(0.25)


def test_wheel_order_constant_is_rear_first():
    assert WHEEL_ORDER == ("rl", "rr", "fl", "fr")


def test_slip_angle_read_per_wheel():
    buf = _motion_ex_buf()
    base = HEADER_SIZE + packets._MOTION_EX_SLIP_ANGLE_OFF
    struct.pack_into("<ffff", buf, base, 0.01, 0.02, 0.12, 0.13)

    out = packets.parse_motion_ex(bytes(buf))

    assert out["slip_angle"]["rl"] == pytest.approx(0.01)
    assert out["slip_angle"]["fr"] == pytest.approx(0.13)


def test_yaw_rate_and_front_wheels_angle():
    buf = _motion_ex_buf()
    struct.pack_into("<f", buf, HEADER_SIZE + packets._MOTION_EX_ANG_VEL_Y_OFF, 0.75)
    struct.pack_into("<f", buf, HEADER_SIZE + packets._MOTION_EX_FRONT_ANGLE_OFF, -0.2)

    out = packets.parse_motion_ex(bytes(buf))

    assert out["yaw_rate"] == pytest.approx(0.75)
    assert out["front_wheels_angle"] == pytest.approx(-0.2)


def test_slip_arrays_do_not_overlap():
    """Массивы идут подряд по 16 байт: запись в один не должна протекать в
    соседний. Ловит сдвиг офсета на один массив — самую вероятную ошибку в
    реконструированной раскладке."""
    buf = _motion_ex_buf()
    struct.pack_into("<ffff", buf, HEADER_SIZE + packets._MOTION_EX_SLIP_RATIO_OFF,
                     -0.4, -0.4, -0.4, -0.4)

    out = packets.parse_motion_ex(bytes(buf))

    assert all(v == pytest.approx(0.0) for v in out["slip_angle"].values())


def test_truncated_buffer_returns_empty_dict_without_error():
    assert packets.parse_motion_ex(bytes(_buf(HEADER_SIZE + 8))) == {}


def test_empty_data_returns_empty_dict():
    assert packets.parse_motion_ex(b"") == {}
