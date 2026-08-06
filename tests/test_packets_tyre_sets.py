"""Синтетические тесты parse_tyre_sets (packet 12) из core/packets.py.

Без сети и без живой игры — вручную собираем байтовый буфер по офсетам,
которые читает код (см. docs/superpowers/plans/2026-07-19-tyre-sets-final-
classification.md). Пакет ПОЦИКЛОВОЙ — на один car_idx за раз, не все 22
машины разом (в отличие от большинства пакетов этого файла).
"""
import struct

from core import packets
from core.packets import HEADER_SIZE, TYRE_SET_SIZE


def _buf(size: int) -> bytearray:
    return bytearray(size)


def _set_offset(idx: int) -> int:
    return HEADER_SIZE + 1 + idx * TYRE_SET_SIZE


def test_parse_tyre_sets_counts_available_by_compound():
    buf = _buf(HEADER_SIZE + 1 + 20 * TYRE_SET_SIZE + 1)
    buf[HEADER_SIZE] = 5   # m_carIdx

    # Комплект 0: софт (16), доступен, износ 15%, зафитован
    s0 = _set_offset(0)
    buf[s0 + 0] = 16   # actual compound
    buf[s0 + 1] = 16   # visual compound = S
    buf[s0 + 2] = 15   # wear
    buf[s0 + 3] = 1    # available

    # Комплект 1: медиум (17), доступен
    s1 = _set_offset(1)
    buf[s1 + 1] = 17
    buf[s1 + 3] = 1

    # Комплект 2: медиум (17), НЕ доступен (уже использован) — не должен войти в счёт
    s2 = _set_offset(2)
    buf[s2 + 1] = 17
    buf[s2 + 3] = 0

    buf[HEADER_SIZE + 1 + 20 * TYRE_SET_SIZE] = 0   # m_fittedIdx = комплект 0

    out = packets.parse_tyre_sets(bytes(buf))
    assert out["car_idx"] == 5
    assert out["available_by_compound"] == {"S": 1, "M": 1}
    assert out["fitted_compound"] == "S"
    assert out["fitted_wear"] == 15


def test_parse_tyre_sets_unavailable_sets_excluded():
    buf = _buf(HEADER_SIZE + 1 + 20 * TYRE_SET_SIZE + 1)
    buf[HEADER_SIZE] = 0
    s0 = _set_offset(0)
    buf[s0 + 1] = 18   # hard, but not available
    buf[s0 + 3] = 0
    out = packets.parse_tyre_sets(bytes(buf))
    assert out["available_by_compound"] == {}


def test_parse_tyre_sets_short_data_returns_empty():
    assert packets.parse_tyre_sets(_buf(HEADER_SIZE)) == {}
    assert packets.parse_tyre_sets(_buf(0)) == {}


def test_parse_tyre_sets_second_car():
    buf = _buf(HEADER_SIZE + 1 + 20 * TYRE_SET_SIZE + 1)
    buf[HEADER_SIZE] = 11
    s3 = _set_offset(3)
    buf[s3 + 1] = 7    # intermediate
    buf[s3 + 3] = 1
    buf[HEADER_SIZE + 1 + 20 * TYRE_SET_SIZE] = 3
    out = packets.parse_tyre_sets(bytes(buf))
    assert out["car_idx"] == 11
    assert out["available_by_compound"] == {"I": 1}
    assert out["fitted_compound"] == "I"
