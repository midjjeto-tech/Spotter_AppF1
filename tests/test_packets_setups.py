"""Car Setups (packet 5) + поколёсный износ резины (packet 10).

Golden-master раскладка CarSetupData: офсеты реконструированы по публичному
формату F1 UDP, требуют живой сверки через SPOTTER_DIAG=1 — тот же класс риска,
что был у MotionEx. См. docs/superpowers/specs/2026-08-07-driving-coach-phase3-garage.md.

Порядок колёс везде RL, RR, FL, FR — как и во всех массивах F1.
"""
import struct

from core import packets
from core.packets import CAR_TELEMETRY_SIZE, HEADER_SIZE

# Размеры структур НЕ импортируются из packets: и damage, и setups выводят шаг
# из длины пакета (тот же приём, что спас парсер участников после патча игры).
# Здесь берём реальные размеры F1 25 как входные данные для теста.
_SETUP_STRIDE_F1_25 = 50   # с m_engineBraking
_SETUP_STRIDE_F1_23 = 49   # без него — давления сдвинуты на байт назад
_DAMAGE_STRIDE = 42


def _setup_buf(stride: int = _SETUP_STRIDE_F1_25) -> bytearray:
    return bytearray(HEADER_SIZE + 22 * stride)


def test_brake_bias_and_diff_read_for_player():
    buf = _setup_buf()
    base = HEADER_SIZE + 3 * _SETUP_STRIDE_F1_25
    buf[base + packets._SETUP_ON_THROTTLE_OFF] = 75
    buf[base + packets._SETUP_BRAKE_BIAS_OFF] = 54

    out = packets.parse_player_setup(bytes(buf), 3)

    assert out["brake_bias"] == 54
    assert out["diff_on_throttle"] == 75


def test_tyre_pressures_follow_the_stride_when_engine_braking_is_absent():
    """F1 23 не имеет m_engineBraking, и давления в его структуре сдвинуты на
    байт. Шаг выводится из длины пакета, поэтому офсет давлений должен
    подстраиваться сам, а не быть захардкоженным под одну версию игры."""
    buf = _setup_buf(_SETUP_STRIDE_F1_23)
    struct.pack_into("<ffff", buf, HEADER_SIZE + packets._SETUP_TYRE_PRESSURE_OFF - 1,
                     21.0, 21.1, 22.0, 22.1)

    out = packets.parse_player_setup(bytes(buf), 0)

    assert out["tyre_pressure"]["rl"] == 21.0
    assert out["tyre_pressure"]["fr"] == 22.1


def test_wings_read_for_player():
    buf = _setup_buf()
    base = HEADER_SIZE
    buf[base + packets._SETUP_FRONT_WING_OFF] = 8
    buf[base + packets._SETUP_REAR_WING_OFF] = 11

    out = packets.parse_player_setup(bytes(buf), 0)

    assert out["front_wing"] == 8
    assert out["rear_wing"] == 11


def test_tyre_pressures_read_per_wheel():
    buf = _setup_buf()
    base = HEADER_SIZE
    struct.pack_into("<ffff", buf, base + packets._SETUP_TYRE_PRESSURE_OFF,
                     22.5, 22.6, 23.1, 23.2)

    out = packets.parse_player_setup(bytes(buf), 0)

    assert out["tyre_pressure"]["rl"] == 22.5
    assert out["tyre_pressure"]["fr"] == 23.2


def test_setup_truncated_buffer_returns_empty_dict():
    assert packets.parse_player_setup(bytes(bytearray(HEADER_SIZE + 4)), 0) == {}


def test_setup_player_index_out_of_range_returns_empty_dict():
    assert packets.parse_player_setup(bytes(_setup_buf()), 99) == {}


# ── Поколёсный износ (packet 10) ─────────────────────────────────────────────

def _damage_buf() -> bytearray:
    return bytearray(HEADER_SIZE + 22 * _DAMAGE_STRIDE)


def test_per_wheel_wear_is_exposed_alongside_the_average():
    """Среднее нужно стратегии, поколёсное — коучу. Раньше поколёсное
    распаковывалось и тут же выбрасывалось."""
    buf = _damage_buf()
    struct.pack_into("<ffff", buf, HEADER_SIZE, 10.0, 12.0, 30.0, 20.0)

    out = packets.parse_player_damage(bytes(buf), 0)

    assert out["tyre_wear"] == 18.0
    assert out["tyre_wear_per_wheel"] == {"rl": 10.0, "rr": 12.0,
                                          "fl": 30.0, "fr": 20.0}


# ── Внутренние температуры резины (packet 6) ─────────────────────────────────

def test_inner_tyre_temperature_read_per_wheel():
    buf = bytearray(HEADER_SIZE + 22 * CAR_TELEMETRY_SIZE)
    base = HEADER_SIZE + packets._CAR_TELEMETRY_TYRE_INNER_TEMP_OFF
    buf[base:base + 4] = bytes([95, 97, 108, 110])

    out = packets.parse_player_telemetry(bytes(buf), 0)

    assert out["tyre_inner_temp"] == {"rl": 95, "rr": 97, "fl": 108, "fr": 110}
