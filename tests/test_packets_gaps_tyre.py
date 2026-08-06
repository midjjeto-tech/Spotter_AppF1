"""Синтетические тесты разбора отрывов (gaps) и шин (tyre) из core/packets.py.

Без сети и без живой игры: вручную собираем байтовый буфер и кладём поля по тем
же офсетам, что читает код (через struct.pack_into), затем проверяем разбор.
Константы импортируются из core.packets, чтобы тесты следовали за кодом, а не
дублировали магические числа.
"""
import struct

import pytest

from core import packets
from core.packets import HEADER_SIZE, LAP_DATA_SIZE, CAR_STATUS_SIZE


def _buf(size: int) -> bytearray:
    """Нулевой буфер нужного размера (имитация UDP-пакета)."""
    return bytearray(size)


# --------------------------------------------------------------------------- #
# _lap_delta_ms — базовая «минуты + мс» математика (как у секторных времён)
# --------------------------------------------------------------------------- #

def test_lap_delta_ms_minutes_plus_ms():
    base = 4
    buf = _buf(base + 32)
    struct.pack_into("<H", buf, base + 14, 23456)   # ms_part
    buf[base + 16] = 1                               # minutes
    assert packets._lap_delta_ms(buf, base, 14, 16) == 1 * 60000 + 23456  # 83456

    buf2 = _buf(base + 32)
    struct.pack_into("<H", buf2, base + 14, 1800)    # < минуты, только мс
    buf2[base + 16] = 0
    assert packets._lap_delta_ms(buf2, base, 14, 16) == 1800


# --------------------------------------------------------------------------- #
# parse_lap_data — позиции, лидер, отрыв до машины впереди для всех машин
# --------------------------------------------------------------------------- #

def test_parse_lap_data_positions_and_gaps():
    buf = _buf(HEADER_SIZE + 22 * LAP_DATA_SIZE)

    base0 = HEADER_SIZE + 0 * LAP_DATA_SIZE          # машина 0 — лидер
    buf[base0 + 32] = 1                               # m_carPosition = P1
    buf[base0 + 33] = 10                              # m_currentLapNum

    base1 = HEADER_SIZE + 1 * LAP_DATA_SIZE          # машина 1 — P2, отрыв 1:00.500
    buf[base1 + 32] = 2
    buf[base1 + 33] = 10
    struct.pack_into("<H", buf, base1 + 14, 500)     # ms_part отрыва впереди
    buf[base1 + 16] = 1                               # minutes

    out = packets.parse_lap_data(buf)
    assert out["positions"][0] == 1
    assert out["positions"][1] == 2
    assert out["laps"][0] == 10
    assert out["leader_idx"] == 0
    assert out["gaps_front"][0] == 0                  # лидер — отрыва нет
    assert out["gaps_front"][1] == 60000 + 500        # 60500 мс


def test_parse_lap_data_pit_status_for_all_cars():
    buf = _buf(HEADER_SIZE + 22 * LAP_DATA_SIZE)

    base0 = HEADER_SIZE + 0 * LAP_DATA_SIZE
    buf[base0 + 32] = 1
    buf[base0 + 34] = 0                                # не в боксах

    base1 = HEADER_SIZE + 1 * LAP_DATA_SIZE
    buf[base1 + 32] = 2
    buf[base1 + 34] = 1                                # в пит-лейне

    out = packets.parse_lap_data(buf)
    assert out["pit_status"][0] == 0
    assert out["pit_status"][1] == 1


def test_parse_lap_data_lap_distance_for_all_cars():
    buf = _buf(HEADER_SIZE + 22 * LAP_DATA_SIZE)

    base0 = HEADER_SIZE + 0 * LAP_DATA_SIZE
    buf[base0 + 32] = 1
    struct.pack_into("<f", buf, base0 + 20, 1234.5)

    base1 = HEADER_SIZE + 1 * LAP_DATA_SIZE
    buf[base1 + 32] = 2
    struct.pack_into("<f", buf, base1 + 20, 999.0)

    out = packets.parse_lap_data(buf)
    assert out["lap_distances"][0] == pytest.approx(1234.5)
    assert out["lap_distances"][1] == pytest.approx(999.0)


def test_parse_lap_data_lap_distance_out_of_range_is_none():
    """Неправдоподобное значение (>10км, как и в parse_player_lap) -> None,
    не мусор дальше в вычисления."""
    buf = _buf(HEADER_SIZE + 22 * LAP_DATA_SIZE)
    base0 = HEADER_SIZE + 0 * LAP_DATA_SIZE
    struct.pack_into("<f", buf, base0 + 20, 99999.0)

    out = packets.parse_lap_data(buf)
    assert out["lap_distances"][0] is None


# --------------------------------------------------------------------------- #
# parse_player_lap — отрывы (впереди/до лидера) + вывод S3 из суммы
# --------------------------------------------------------------------------- #

def test_parse_player_lap_gaps_and_sectors():
    buf = _buf(HEADER_SIZE + LAP_DATA_SIZE)
    base = HEADER_SIZE
    struct.pack_into("<I", buf, base + 0, 92500)     # m_lastLapTimeMs = 1:32.500
    struct.pack_into("<H", buf, base + 8, 30000)     # S1 ms_part
    buf[base + 10] = 0                                # S1 minutes
    struct.pack_into("<H", buf, base + 11, 31000)    # S2 ms_part
    buf[base + 13] = 0                                # S2 minutes
    struct.pack_into("<H", buf, base + 14, 800)      # отрыв впереди ms_part
    buf[base + 16] = 0                                # отрыв впереди minutes
    struct.pack_into("<H", buf, base + 17, 200)      # отрыв до лидера ms_part
    buf[base + 19] = 1                                # отрыв до лидера minutes
    buf[base + 32] = 4                                # позиция
    buf[base + 33] = 12                               # текущий круг

    out = packets.parse_player_lap(buf, 0)
    assert out["last_lap_ms"] == 92500
    assert out["s1_ms"] == 30000
    assert out["s2_ms"] == 31000
    assert out["s3_ms"] == 92500 - 30000 - 31000     # 31500 (выведено, не из байтов)
    assert out["position"] == 4
    assert out["current_lap"] == 12
    assert out["gap_front_ms"] == 800
    assert out["gap_leader_ms"] == 60000 + 200        # 60200 мс


def test_parse_player_lap_zero_sectors():
    """Пока круг не пройден — времён нет; S3 не должен уходить в минус."""
    buf = _buf(HEADER_SIZE + LAP_DATA_SIZE)
    buf[HEADER_SIZE + 32] = 1                         # только позиция
    out = packets.parse_player_lap(buf, 0)
    assert out["last_lap_ms"] == 0
    assert out["s1_ms"] == 0
    assert out["s2_ms"] == 0
    assert out["s3_ms"] == 0                          # не отрицательное


# --------------------------------------------------------------------------- #
# parse_player_status — топливо + маппинг визуального компаунда шин
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("player_idx", [0, 5, 19])
@pytest.mark.parametrize("visual, expected", [
    (16, "S"),    # софт
    (17, "M"),    # медиум
    (18, "H"),    # хард
    (99, "?"),    # неизвестный код -> заглушка
])
def test_parse_player_status_tyre_compound(player_idx, visual, expected):
    # Real PacketCarStatusData = header + CarStatusData[22], NO leading byte
    # (same framing parse_lap_data uses against the live game). Fields placed at
    # their documented struct offsets so a spurious +1 in the parser is caught.
    buf = _buf(HEADER_SIZE + 22 * CAR_STATUS_SIZE)
    base = HEADER_SIZE + player_idx * CAR_STATUS_SIZE
    struct.pack_into("<f", buf, base + 5, 42.5)      # m_fuelInTank @5
    buf[base + 26] = visual                           # m_visualTyreCompound @26
    buf[base + 27] = 14                               # m_tyresAgeLaps @27

    out = packets.parse_player_status(buf, player_idx)
    assert out["fuel"] == 42.5
    assert out["tyre_compound"] == expected
    assert out["tyre_age"] == 14


@pytest.mark.parametrize("deploy_mode", [0, 1, 2, 3])
def test_parse_player_status_ers_fields(deploy_mode):
    buf = _buf(HEADER_SIZE + 22 * CAR_STATUS_SIZE)
    base = HEADER_SIZE + 0 * CAR_STATUS_SIZE
    struct.pack_into("<f", buf, base + 37, 2_000_000.0)   # m_ersStoreEnergy @37 = 50%
    buf[base + 41] = deploy_mode                            # m_ersDeployMode @41

    out = packets.parse_player_status(buf, 0)
    assert out["ers_percent"] == 50.0
    assert out["ers_deploy_mode"] == deploy_mode


# Golden-master раскладка CarStatusData F1 25 — СВЕРЕНА с официальной
# спецификацией EA (Data Output from F1 25 v3.pdf) и независимым парсером
# github.com/MacManley/f1-25-udp. Каждое поле → офсет; сумма = 55 =
# CAR_STATUS_SIZE. Little-endian, packed, без паддинга (гарантия спеки).
# Тест кодирует ВСЮ структуру, чтобы будущий дрейф после патча игры
# (как когда-то с PARTICIPANT_SIZE) поймался тестом, а не на слух в игре.
_CAR_STATUS_LAYOUT = [
    ("m_tractionControl",        0,  "B"),
    ("m_antiLockBrakes",         1,  "B"),
    ("m_fuelMix",                2,  "B"),
    ("m_frontBrakeBias",         3,  "B"),
    ("m_pitLimiterStatus",       4,  "B"),
    ("m_fuelInTank",             5,  "f"),
    ("m_fuelCapacity",           9,  "f"),
    ("m_fuelRemainingLaps",      13, "f"),
    ("m_maxRPM",                 17, "H"),
    ("m_idleRPM",                19, "H"),
    ("m_maxGears",               21, "B"),
    ("m_drsAllowed",             22, "B"),
    ("m_drsActivationDistance",  23, "H"),
    ("m_actualTyreCompound",     25, "B"),
    ("m_visualTyreCompound",     26, "B"),
    ("m_tyresAgeLaps",           27, "B"),
    ("m_vehicleFiaFlags",        28, "b"),
    ("m_enginePowerICE",         29, "f"),
    ("m_enginePowerMGUK",        33, "f"),
    ("m_ersStoreEnergy",         37, "f"),
    ("m_ersDeployMode",          41, "B"),
    ("m_ersHarvestedThisLapMGUK", 42, "f"),
    ("m_ersHarvestedThisLapMGUH", 46, "f"),
    ("m_ersDeployedThisLap",     50, "f"),
    ("m_networkPaused",          54, "B"),
]


def test_car_status_layout_sums_to_car_status_size():
    """Сумма размеров всех полей документированной раскладки == CAR_STATUS_SIZE.
    Если игра сдвинет структуру патчем — эта инварианта первой поймает дрейф."""
    total = _CAR_STATUS_LAYOUT[-1][1] + struct.calcsize(_CAR_STATUS_LAYOUT[-1][2])
    assert total == CAR_STATUS_SIZE == 55


def test_ers_read_from_37_not_adjacent_engine_power_field():
    """Прямая страховка от опасной путаницы (ревью Фазы 3a): m_enginePowerMGUK@33
    стоит ВПЛОТНУЮ перед m_ersStoreEnergy@37, оба float одного порядка. Кладём
    в @33 мощность (правдоподобные ~120кВт), в @37 — заряд (4МДж=100%), и
    проверяем, что парсер читает ИМЕННО @37 (100%), а не @33 (дало бы ~3%)."""
    buf = _buf(HEADER_SIZE + 22 * CAR_STATUS_SIZE)
    base = HEADER_SIZE + 0 * CAR_STATUS_SIZE
    struct.pack_into("<f", buf, base + 33, 120_000.0)      # m_enginePowerMGUK (соседнее)
    struct.pack_into("<f", buf, base + 37, 4_000_000.0)    # m_ersStoreEnergy = 100%
    out = packets.parse_player_status(buf, 0)
    assert out["ers_percent"] == 100.0                     # не ~3.0 (было бы при чтении @33)


def test_parse_player_status_ers_missing_when_packet_too_short():
    # len(buf) = HEADER_SIZE + 41 — на 1 байт короче требуемого base+42, но
    # достаточно для fuel(base+9)/tyre(base+28): проверяем именно ERS-гейт
    # (base+42 <= len), а не более раннюю проверку в parse_player_status.
    buf = _buf(HEADER_SIZE + 41)
    struct.pack_into("<f", buf, HEADER_SIZE + 5, 42.5)
    out = packets.parse_player_status(buf, 0)
    assert out.get("fuel") == 42.5
    assert "ers_percent" not in out
    assert "ers_deploy_mode" not in out


def test_car_status_drs_allowed_true():
    buf = _buf(HEADER_SIZE + CAR_STATUS_SIZE)
    base = HEADER_SIZE
    buf[base + 22] = 1
    out = packets.parse_player_status(buf, 0)
    assert out["drs_allowed"] is True


def test_car_status_drs_allowed_false():
    buf = _buf(HEADER_SIZE + CAR_STATUS_SIZE)
    base = HEADER_SIZE
    buf[base + 22] = 0
    out = packets.parse_player_status(buf, 0)
    assert out["drs_allowed"] is False


def test_car_status_drs_allowed_none_when_packet_too_short():
    buf = _buf(HEADER_SIZE + 22)   # base+23 > len(data) -> поле недоступно
    out = packets.parse_player_status(buf, 0)
    assert "drs_allowed" not in out


def test_ers_diag_throttle_skips_second_call_within_window(monkeypatch):
    """DIAG-лог на КАЖДЫЙ CarStatus-пакет (десятки раз/сек) захлестнул бы лог —
    троттлинг раз в 2с. Проверяем сам факт троттлинга, не завязываясь на
    реальный logging-вывод: считаем вызовы _log.warning через monkeypatch."""
    import time as time_mod
    from core import packets as pk

    monkeypatch.setattr(pk, "_DIAG", True)
    monkeypatch.setattr(pk, "_last_ers_diag_t", 0.0)
    calls = []
    monkeypatch.setattr(pk._log, "warning", lambda *a, **kw: calls.append(a))

    buf = _buf(HEADER_SIZE + 22 * CAR_STATUS_SIZE)
    base = HEADER_SIZE + 0 * CAR_STATUS_SIZE
    struct.pack_into("<f", buf, base + 37, 2_000_000.0)
    buf[base + 41] = 2

    pk.parse_player_status(buf, 0)                 # первый вызов — логирует
    assert len(calls) == 1

    pk.parse_player_status(buf, 0)                 # сразу второй — троттлинг молчит
    assert len(calls) == 1

    monkeypatch.setattr(pk, "_last_ers_diag_t", time_mod.time() - 3.0)  # "прошло" 3с
    pk.parse_player_status(buf, 0)
    assert len(calls) == 2


# --------------------------------------------------------------------------- #
# parse_player_damage — средний износ 4 шин + защита от битого размера пакета
# --------------------------------------------------------------------------- #

def test_parse_player_damage_wear_average():
    stride = 42                                       # правдоподобный размер CarDamageData
    buf = _buf(HEADER_SIZE + 22 * stride)

    struct.pack_into("<ffff", buf, HEADER_SIZE + 0 * stride, 20.0, 24.0, 28.0, 32.0)
    assert packets.parse_player_damage(buf, 0)["tyre_wear"] == 26.0   # среднее

    # вывод stride из длины пакета: машина 1 читается со своим офсетом
    struct.pack_into("<ffff", buf, HEADER_SIZE + 1 * stride, 10.0, 10.0, 10.0, 10.0)
    assert packets.parse_player_damage(buf, 1)["tyre_wear"] == 10.0


def test_parse_player_damage_bad_stride_guard():
    # stride = 220 // 22 = 10 (< 24) -> разбор отклоняется, не падает
    assert packets.parse_player_damage(_buf(HEADER_SIZE + 22 * 10), 0) == {}
    # пустое тело -> {}
    assert packets.parse_player_damage(_buf(HEADER_SIZE), 0) == {}


@pytest.mark.parametrize("raw, expected", [(0, 0), (1, 1), (2, 2)])
def test_parse_player_lap_pit_status(raw, expected):
    buf = _buf(HEADER_SIZE + LAP_DATA_SIZE)
    base = HEADER_SIZE
    buf[base + 32] = 3          # position (non-empty packet)
    buf[base + 33] = 5          # current lap
    buf[base + 34] = raw        # m_pitStatus
    out = packets.parse_player_lap(buf, 0)
    assert out["pit_status"] == expected


def test_parse_player_damage_categories():
    stride = 42
    buf = _buf(HEADER_SIZE + 22 * stride)
    base = HEADER_SIZE  # player_idx=0

    struct.pack_into("<ffff", buf, base + 0, 20.0, 24.0, 28.0, 32.0)  # tyre_wear (уже покрыт)
    buf[base + 24] = 15   # front-left wing
    buf[base + 25] = 40   # front-right wing — максимум группы "крылья"
    buf[base + 26] = 10   # rear wing
    buf[base + 27] = 5    # floor
    buf[base + 28] = 60   # diffuser — максимум группы "аэро/пол"
    buf[base + 29] = 30   # sidepod
    buf[base + 32] = 22   # gearbox
    buf[base + 33] = 77   # engine

    out = packets.parse_player_damage(buf, 0)
    assert out["tyre_wear"] == 26.0        # среднее, поведение не изменилось
    assert out["wing_damage"] == 40
    assert out["floor_damage"] == 60
    assert out["gearbox_damage"] == 22
    assert out["engine_damage"] == 77


def test_parse_player_damage_categories_second_car():
    """Второй по счёту автомобиль (player_idx=1) — офсет-логика (stride) не ломается
    при переходе за одну машину."""
    stride = 42
    buf = _buf(HEADER_SIZE + 22 * stride)
    base = HEADER_SIZE + 1 * stride
    buf[base + 24] = 5
    buf[base + 25] = 5
    buf[base + 26] = 90   # rear wing — максимум
    buf[base + 32] = 12
    buf[base + 33] = 3

    out = packets.parse_player_damage(buf, 1)
    assert out["wing_damage"] == 90
    assert out["gearbox_damage"] == 12
    assert out["engine_damage"] == 3


def test_parse_event_collision():
    buf = _buf(HEADER_SIZE + 4 + 2)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"COLL"
    buf[HEADER_SIZE + 4] = 3       # vehicle1_idx
    buf[HEADER_SIZE + 5] = 7       # vehicle2_idx
    out = packets.parse_event(bytes(buf))
    assert out["event_code"] == "COLL"
    assert out["vehicle1_idx"] == 3
    assert out["vehicle2_idx"] == 7
    assert out["priority"] == "critical"


# --------------------------------------------------------------------------- #
# parse_car_status_all — тыре эйдж для всех 22 машин
# --------------------------------------------------------------------------- #

def test_parse_car_status_all_tyre_age_per_car():
    buf = _buf(HEADER_SIZE + 22 * CAR_STATUS_SIZE)
    base0 = HEADER_SIZE + 0 * CAR_STATUS_SIZE
    buf[base0 + 26] = 16          # visual compound = soft
    buf[base0 + 27] = 3           # tyre age
    base1 = HEADER_SIZE + 1 * CAR_STATUS_SIZE
    buf[base1 + 26] = 17          # medium
    buf[base1 + 27] = 12

    out = packets.parse_car_status_all(buf)
    assert out[0]["tyre_age"] == 3
    assert out[0]["tyre_compound"] == "S"
    assert out[1]["tyre_age"] == 12
    assert out[1]["tyre_compound"] == "M"


def test_parse_car_status_all_matches_parse_player_status():
    """parse_player_status делегирует в тот же хелпер — результат идентичен
    для того же car_idx."""
    buf = _buf(HEADER_SIZE + 22 * CAR_STATUS_SIZE)
    base1 = HEADER_SIZE + 1 * CAR_STATUS_SIZE
    buf[base1 + 26] = 18
    buf[base1 + 27] = 7
    struct.pack_into("<f", buf, base1 + 5, 42.5)

    all_out = packets.parse_car_status_all(buf)
    single_out = packets.parse_player_status(buf, 1)
    assert all_out[1] == single_out


# --------------------------------------------------------------------------- #
# parse_car_damage_all — повреждения для всех 22 машин
# --------------------------------------------------------------------------- #

def test_parse_car_damage_all_categories_per_car():
    stride = 42
    buf = _buf(HEADER_SIZE + 22 * stride)
    base1 = HEADER_SIZE + 1 * stride
    buf[base1 + 24] = 45          # wing
    buf[base1 + 27] = 10          # floor
    buf[base1 + 32] = 5           # gearbox
    buf[base1 + 33] = 0           # engine

    out = packets.parse_car_damage_all(buf)
    assert out[1]["wing_damage"] == 45
    assert out[1]["floor_damage"] == 10
    assert out[0]["wing_damage"] == 0     # car 0 untouched


def test_parse_car_damage_all_matches_parse_player_damage():
    stride = 42
    buf = _buf(HEADER_SIZE + 22 * stride)
    base1 = HEADER_SIZE + 1 * stride
    struct.pack_into("<ffff", buf, base1 + 0, 10.0, 10.0, 10.0, 10.0)
    buf[base1 + 24] = 20

    all_out = packets.parse_car_damage_all(buf)
    single_out = packets.parse_player_damage(buf, 1)
    assert all_out[1] == single_out


def test_parse_car_damage_all_bad_stride_guard():
    assert packets.parse_car_damage_all(_buf(HEADER_SIZE + 22 * 10)) == {}
    assert packets.parse_car_damage_all(_buf(HEADER_SIZE)) == {}


# --------------------------------------------------------------------------- #
# corner_cutting_warnings (LapData@40) + golden-master полной раскладки
# --------------------------------------------------------------------------- #

# Golden-master раскладка LapData F1 25 — СВЕРЕНА с независимым парсером
# github.com/MacManley/f1-25-udp (2026-07-11). Каждое поле -> офсет; сумма ==
# LAP_DATA_SIZE. Little-endian, packed, без паддинга (гарантия спеки). Тест
# кодирует ВСЮ структуру, чтобы будущий дрейф после патча игры поймался
# тестом, а не на слух в игре (тот же приём, что уже страховал CarStatusData).
_LAP_DATA_LAYOUT = [
    ("m_lastLapTimeInMS",              0,  "I"),
    ("m_currentLapTimeInMS",           4,  "I"),
    ("m_sector1TimeMSPart",            8,  "H"),
    ("m_sector1TimeMinutesPart",       10, "B"),
    ("m_sector2TimeMSPart",            11, "H"),
    ("m_sector2TimeMinutesPart",       13, "B"),
    ("m_deltaToCarInFrontMSPart",      14, "H"),
    ("m_deltaToCarInFrontMinutesPart", 16, "B"),
    ("m_deltaToRaceLeaderMSPart",      17, "H"),
    ("m_deltaToRaceLeaderMinutesPart", 19, "B"),
    ("m_lapDistance",                  20, "f"),
    ("m_totalDistance",                24, "f"),
    ("m_safetyCarDelta",               28, "f"),
    ("m_carPosition",                  32, "B"),
    ("m_currentLapNum",                33, "B"),
    ("m_pitStatus",                    34, "B"),
    ("m_numPitStops",                  35, "B"),
    ("m_sector",                       36, "B"),
    ("m_currentLapInvalid",            37, "B"),
    ("m_penalties",                    38, "B"),
    ("m_totalWarnings",                39, "B"),
    ("m_cornerCuttingWarnings",        40, "B"),
    ("m_numUnservedDriveThroughPens",  41, "B"),
    ("m_numUnservedStopGoPens",        42, "B"),
    ("m_gridPosition",                 43, "B"),
    ("m_driverStatus",                 44, "B"),
    ("m_resultStatus",                 45, "B"),
    ("m_pitLaneTimerActive",           46, "B"),
    ("m_pitLaneTimeInLaneInMS",        47, "H"),
    ("m_pitStopTimerInMS",             49, "H"),
    ("m_pitStopShouldServePen",        51, "B"),
    ("m_speedTrapFastestSpeed",        52, "f"),
    ("m_speedTrapFastestLap",          56, "B"),
]


def test_lap_data_layout_sums_to_lap_data_size():
    total = _LAP_DATA_LAYOUT[-1][1] + struct.calcsize(_LAP_DATA_LAYOUT[-1][2])
    assert total == LAP_DATA_SIZE == 57


def test_corner_cutting_warnings_read_from_40_not_adjacent_fields():
    """Прямая страховка от путаницы с соседними однобайтовыми полями
    m_totalWarnings@39 / m_numUnservedDriveThroughPens@41."""
    buf = _buf(HEADER_SIZE + LAP_DATA_SIZE)
    base = HEADER_SIZE
    buf[base + 32] = 3          # position (непустой пакет)
    buf[base + 33] = 5          # current lap
    buf[base + 39] = 9          # m_totalWarnings (соседнее слева)
    buf[base + 40] = 2          # m_cornerCuttingWarnings
    buf[base + 41] = 7          # m_numUnservedDriveThroughPens (соседнее справа)
    out = packets.parse_player_lap(buf, 0)
    assert out["corner_cutting_warnings"] == 2


def test_corner_cutting_warnings_none_when_packet_too_short():
    buf = _buf(HEADER_SIZE + 40)   # base+41 > len(data) -> поле недоступно
    buf[HEADER_SIZE + 32] = 1
    buf[HEADER_SIZE + 33] = 1
    out = packets.parse_player_lap(buf, 0)
    assert out.get("corner_cutting_warnings") is None


# --------------------------------------------------------------------------- #
# parse_event PENA — infringement_type capture + TRACK_LIMITS classification
# --------------------------------------------------------------------------- #

def test_parse_event_pena_includes_infringement_type():
    buf = _buf(HEADER_SIZE + 4 + 7)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"PENA"
    # ptype=1, infringement_type=25 (lap invalidated corner cutting),
    # vehicle_idx=4, other=0, time_seconds=5, lap_num=12, places_gained=0
    struct.pack_into("<BBBBBBB", buf, HEADER_SIZE + 4, 1, 25, 4, 0, 5, 12, 0)
    out = packets.parse_event(bytes(buf))
    assert out["event_code"] == "PENA"
    assert out["vehicle_idx"] == 4
    assert out["infringement_type"] == 25


def test_track_limits_infringement_types_confirmed_set():
    assert packets.TRACK_LIMITS_INFRINGEMENT_TYPES == frozenset(
        {7, 8, 9, 25, 26, 27, 28, 29})


# --------------------------------------------------------------------------- #
# parse_event SCAR/RDFL — Phase B (Safety Car/VSC/red flag), см. docs/
# superpowers/plans/2026-07-19-safety-car-vsc-red-flag.md
# --------------------------------------------------------------------------- #

def test_parse_event_scar_includes_type_and_reason():
    buf = _buf(HEADER_SIZE + 4 + 2)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"SCAR"
    struct.pack_into("<BB", buf, HEADER_SIZE + 4, 1, 0)   # Full SC, Deployed
    out = packets.parse_event(bytes(buf))
    assert out["event_code"] == "SCAR"
    assert out["priority"] == "critical"
    assert out["safety_car_type"] == 1
    assert out["event_reason"] == 0


def test_parse_event_rdfl_is_critical_no_payload():
    buf = _buf(HEADER_SIZE + 4)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"RDFL"
    out = packets.parse_event(bytes(buf))
    assert out["event_code"] == "RDFL"
    assert out["priority"] == "critical"


# ── Санити-гейт заряда ERS ────────────────────────────────────────────────────
# Тот же приём, что у lap_distance_m: значение вне физического диапазона значит,
# что офсет уехал после патча игры. Лучше промолчать про батарею, чем объявить
# «Батарея 4200%» — все потребители (сводка инженера, Voice Q&A) умеют None.

def _status_with_ers(joules: float) -> bytearray:
    buf = _buf(HEADER_SIZE + 22 * CAR_STATUS_SIZE)
    struct.pack_into("<f", buf, HEADER_SIZE + 37, joules)
    return buf


def test_ers_out_of_range_high_is_dropped_not_announced():
    out = packets.parse_player_status(_status_with_ers(170_000_000.0), 0)
    assert "ers_percent" not in out
    # Остальные поля пакета при этом остаются доступными.
    assert "ers_deploy_mode" in out


def test_ers_negative_is_dropped():
    out = packets.parse_player_status(_status_with_ers(-1_000_000.0), 0)
    assert "ers_percent" not in out


def test_ers_slightly_over_full_is_clamped_not_dropped():
    """Игра изредка присылает чуть больше 4 МДж — это полный заряд, не сбой."""
    out = packets.parse_player_status(_status_with_ers(4_020_000.0), 0)
    assert out["ers_percent"] == 100.0


def test_ers_empty_battery_is_zero_not_missing():
    """0% — валидные данные («батарея пустая»), а не отсутствие телеметрии."""
    out = packets.parse_player_status(_status_with_ers(0.0), 0)
    assert out["ers_percent"] == 0.0
