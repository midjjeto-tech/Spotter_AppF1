"""
core/packets.py
================
Разбор UDP-пакетов телеметрии F1 25: заголовок, список пилотов (Participants)
и игровые события (Event). Вся "битовая магия" живёт здесь — остальной код
работает с уже готовыми словарями.
"""

from __future__ import annotations

import logging
import os
import struct
import time

_log = logging.getLogger(__name__)

# Temporary field diagnostics. Enable with SPOTTER_DIAG=1 to dump raw participant
# bytes / packet format when driver names or tyre data look wrong in-game.
_DIAG = os.environ.get("SPOTTER_DIAG") == "1"

HEADER_FORMAT = "<HBBBBBQfIIBB"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

PACKET_SESSION = 1
PACKET_LAP_DATA = 2
PACKET_EVENT = 3
PACKET_PARTICIPANTS = 4
PACKET_CAR_TELEMETRY = 6
PACKET_CAR_STATUS = 7
PACKET_CAR_DAMAGE = 10
PACKET_MOTION = 0
PACKET_FINAL_CLASSIFICATION = 8
PACKET_TYRE_SETS = 12
PACKET_SESSION_HISTORY = 11
MOTION_SIZE = 60   # CarMotionData — см. golden-master в tests/test_packets_motion.py

PACKET_MOTION_EX = 13
PACKET_CAR_SETUPS = 5

# CarSetupData (packet 5) — офсеты ВНУТРИ одного элемента m_carSetups[22].
# Шаг между машинами выводится из длины пакета, а не хардкодится: захардкоженный
# PARTICIPANT_SIZE уже один раз ломал парсер после патча игры (см. «Известные
# gotchas» в CONTEXT.md). Раскладка реконструирована по публичному формату F1
# UDP и требует живой сверки SPOTTER_DIAG=1 — тот же класс риска, что MotionEx.
_SETUP_FRONT_WING_OFF = 0
_SETUP_REAR_WING_OFF = 1
_SETUP_ON_THROTTLE_OFF = 2      # дифференциал на разгоне
_SETUP_OFF_THROTTLE_OFF = 3
_SETUP_BRAKE_PRESSURE_OFF = 26
_SETUP_BRAKE_BIAS_OFF = 27
# m_engineBraking появился в F1 24 (байт 28) и сдвинул давления на байт вперёд.
# Офсет ниже — для структуры С ним; для более короткой структуры вычитается 1.
_SETUP_TYRE_PRESSURE_OFF = 29
_SETUP_STRIDE_WITH_ENGINE_BRAKING = 50

# Порядок колёс во ВСЕХ поколёсных массивах пакетов F1: заднее левое, заднее
# правое, переднее левое, переднее правое. Не менять и не «исправлять» на
# привычный FL/FR/RL/RR — перепутанный порядок заставит коуча уверенно называть
# не то колесо, и пилот начнёт чинить то, что не сломано.
WHEEL_ORDER: tuple[str, str, str, str] = ("rl", "rr", "fl", "fr")

# PacketMotionExData (packet 13) — офсеты ОТ КОНЦА ЗАГОЛОВКА. Пакет всегда про
# машину ИГРОКА, массива по 22 машинам в нём нет. Раскладка реконструирована по
# публичному формату F1 UDP; живая сверка — SPOTTER_DIAG=1 (см. Task 13 плана
# docs/superpowers/plans/2026-08-06-driving-coach-phase1.md). Массивы идут
# подряд по 4 float: suspensionPosition(0) / Velocity(16) / Acceleration(32),
# wheelSpeed(48), slipRatio(64), slipAngle(80).
_MOTION_EX_SLIP_RATIO_OFF = 64
_MOTION_EX_SLIP_ANGLE_OFF = 80
_MOTION_EX_ANG_VEL_Y_OFF = 148     # m_angularVelocityY — скорость рыскания
_MOTION_EX_FRONT_ANGLE_OFF = 168   # m_frontWheelsAngle
MOTION_EX_MIN_SIZE = _MOTION_EX_FRONT_ANGLE_OFF + 4

LAP_DATA_SIZE = 57
CAR_TELEMETRY_SIZE = 60
CAR_STATUS_SIZE = 55
CAR_TELEMETRY_FORMAT = "<HfffBbHBBBBHHHHbbbbHffffBBBB"

# Хвост CarTelemetryData читается по ЯВНЫМ офсетам, а НЕ по
# CAR_TELEMETRY_FORMAT: формат разъехался с реальной структурой начиная с
# внутренних температур (там 4 байта uint8, а формат читает один H), поэтому
# всё, что в строке дальше — давления и surfaceType — смещено на 4 байта.
# Поля 0-8, которыми пользуется parse_player_telemetry, лежат ДО этого места и
# верны; формат не трогаем, чтобы не переписывать рабочий код, но и не
# расширяем по индексам. Реальная раскладка (60 байт): brakesTemperature[4] @22,
# tyresSurfaceTemperature[4] @30, tyresInnerTemperature[4] @34,
# engineTemperature @38, tyresPressure[4] @40, surfaceType[4] @56.
_CAR_TELEMETRY_TYRE_SURF_TEMP_OFF = 30    # uint8[4]
_CAR_TELEMETRY_TYRE_INNER_TEMP_OFF = 34   # uint8[4]
_CAR_TELEMETRY_SURFACE_OFF = 56           # uint8[4]

# m_surfaceType: покрытие под колесом.
SURFACE_TYPE = {
    0: "tarmac", 1: "rumble_strip", 2: "concrete", 3: "rock", 4: "gravel",
    5: "mud", 6: "sand", 7: "grass", 8: "water", 9: "cobblestone",
    10: "metal", 11: "ridged",
}
# Поребрик — часть трассы, а не выезд: пилот кладёт на него колесо намеренно.
SURFACE_ON_TRACK = frozenset({"tarmac", "rumble_strip", "concrete"})

# TyreSetData (Tyre Sets, packet 12) — офсеты внутри одного элемента
# m_tyreSetData[20], сверены EA F1 25 UDP spec + MacManley/f1-25-udp.
TYRE_SET_SIZE = 10
# FinalClassificationData (Final Classification, packet 8) — один элемент
# m_classificationData[22]. См. docs/superpowers/plans/2026-07-19-tyre-sets-final-classification.md.
FINAL_CLASSIFICATION_ENTRY_SIZE = 46

# Session History (packet 11) — ПОЦИКЛОВОЙ, один car_idx за раз (та же схема,
# что у Tyre Sets). LapHistoryData/TyreStintHistoryData — офсеты сверены EA
# F1 25 UDP spec + MacManley/f1-25-udp. См. docs/superpowers/plans/
# 2026-07-20-session-history-sector-comparison.md.
LAP_HISTORY_SIZE = 14
TYRE_STINT_HISTORY_SIZE = 3
_SESSION_HISTORY_LAP_ARRAY_OFF = 7          # от HEADER_SIZE
_SESSION_HISTORY_NUM_LAP_SLOTS = 100
_SESSION_HISTORY_TYRE_STINTS_OFF = (
    _SESSION_HISTORY_LAP_ARRAY_OFF + _SESSION_HISTORY_NUM_LAP_SLOTS * LAP_HISTORY_SIZE
)
_SESSION_HISTORY_BODY_SIZE = _SESSION_HISTORY_TYRE_STINTS_OFF + 8 * TYRE_STINT_HISTORY_SIZE
RESULT_STATUS_LABEL = {
    0: "неизвестно", 1: "не стартовал", 2: "в гонке", 3: "финишировал",
    4: "не финишировал", 5: "дисквалифицирован", 6: "не классифицирован",
    7: "сошёл с дистанции",
}
RESULT_REASON_LABEL = {
    0: "неизвестно", 1: "сход", 2: "финиш", 3: "критическое повреждение",
    4: "неактивен", 5: "недостаточно кругов", 6: "чёрный флаг",
    7: "красный флаг", 8: "механическая неисправность",
    9: "сессия пропущена", 10: "сессия симулирована",
}

# m_visualTyreCompound (Car Status) -> короткая метка для комментатора/UI.
TYRE_VISUAL = {16: "S", 17: "M", 18: "H", 7: "I", 8: "W",
               19: "S", 20: "M", 21: "H"}  # 19-21 — классические шины F1

# Ёмкость Energy Store в играх F1 — 4 МДж (регламент FIA, ES хранит максимум
# 4 МДж). Стандартный делитель для % заряда в F1-телеметрии
# (m_ersStoreEnergy / 4e6 * 100). Технический параметр реального спорта, НЕ
# игровой — не меняется между версиями игры (в отличие от размеров структур).
ERS_MAX_JOULES = 4_000_000.0

# Для читаемости DIAG-лога при живой сверке офсетов с HUD игры.
_ERS_MODE_LABEL = {0: "none", 1: "medium", 2: "overtake", 3: "hotlap"}

_last_ers_diag_t = 0.0

# Session packet: погода + прогноз дождя. Офсеты сверены со спекой F1 25
# (три подтверждённых якоря total_laps@3/session_type@6/track_id@7), плюс
# runtime-валидация в _parse_rain_forecast. См. spec
# 2026-07-10-weather-forecast-parsing-design.md.
WEATHER_LABEL = {0: "ясно", 1: "облачно", 2: "пасмурно",
                 3: "слабый дождь", 4: "сильный дождь", 5: "гроза"}
_WFS_NUM_OFF = 126          # m_numWeatherForecastSamples (от HEADER_SIZE)
_WFS_ARRAY_OFF = 127        # начало m_weatherForecastSamples
_WFS_SAMPLE_SIZE = 8
_WFS_MAX_SAMPLES = 64
_RAIN_WEATHER_MIN = 3       # weather >= 3 = дождь (слабый/сильный/гроза)

_last_weather_diag_t = 0.0

# --- Команды F1 25: имя + официальный цвет (для UI) ---
TEAM_INFO = {
    0: ("Mercedes", "#27F4D2"),
    1: ("Ferrari", "#E8002D"),
    2: ("Red Bull Racing", "#3671C6"),
    3: ("Williams", "#64C4FF"),
    4: ("Aston Martin", "#229971"),
    5: ("Alpine", "#FF87BC"),
    6: ("RB", "#6692FF"),
    7: ("Haas", "#B6BABD"),
    8: ("McLaren", "#FF8000"),
    9: ("Sauber", "#52E252"),
    41: ("F1 Academy", "#E6B800"),
    255: ("Своя команда", "#9CA3AF"),
}

# Сезон 2026: те же numeric teamId, но два ребренда (Sauber->Audi, RB->Racing
# Bulls) — реальный мир переименовал команды, движок игры номера не меняет.
# The 2026 Season Pack uses a revised participant layout with uint16 team IDs;
# known low IDs remain useful, while roster enrichment still resolves a future
# or mode-specific Cadillac ID from the race number/name.

# Live F1 25 Season Pack v1.24 identifiers (observed in PacketParticipants) —
# confirmed via live capture, unlike the id=10 Cadillac guess below (which is
# only ever consulted when the packet is confidently flagged as 2026-era).
# Kept as its own dict so the fallback lookup in parse_participants() can
# consult ONLY these confirmed entries, without also exposing the unconfirmed
# id=10 guess to packets that weren't confidently detected as 2026-era.
_SEASON_PACK_V124_TEAM_IDS: dict[int, tuple[str, str]] = {
    220: ("Mercedes", "#27F4D2"),
    221: ("Ferrari", "#E8002D"),
    222: ("Red Bull Racing", "#3671C6"),
    223: ("Williams", "#64C4FF"),
    224: ("Aston Martin", "#229971"),
    225: ("Alpine", "#FF87BC"),
    226: ("Racing Bulls", "#6692FF"),
    227: ("Haas", "#B6BABD"),
    228: ("McLaren", "#FF8000"),
    229: ("Audi", "#52E252"),
    230: ("Cadillac", "#A8A9AD"),
}

TEAM_INFO_2026 = {
    **TEAM_INFO,
    9: ("Audi", "#52E252"),
    6: ("Racing Bulls", "#6692FF"),
    10: ("Cadillac", "#A8A9AD"),  # unconfirmed guess — see CONTEXT.md, needs
                                   # a live SPOTTER_DIAG=1 capture once DLC ships
    **_SEASON_PACK_V124_TEAM_IDS,
}


def team_info_for_year(game_year: int) -> dict[int, tuple[str, str]]:
    """Выбор TEAM_INFO по году игровой сессии (см. roster_by_number — тот же принцип:
    game_year=0/неизвестно → дефолт на текущий TEAM_INFO, без Season Pack эффекта)."""
    return TEAM_INFO_2026 if game_year >= 2026 else TEAM_INFO

EVENT_DESCRIPTIONS = {
    "SSTA": "Старт сессии",
    "SEND": "Сессия завершена",
    "FTLP": "Новый быстрейший круг",
    "RTMT": "Машина ушла в гараж (ретайр)",
    "DRSE": "DRS включён",
    "DRSD": "DRS выключен",
    "TMPT": "Шина перегрелась",
    "CHQF": "Финишный флаг",
    "RCWN": "Победитель гонки определён",
    "PENA": "Назначен штраф",
    "SPTP": "Спид-трэп",
    "STLG": "Старт-сигналы",
    "FLBK": "Flashback",
    "OVTK": "Обгон",
    "COLL": "Столкновение",
    # Phase B (Safety Car/VSC/красный флаг) — см. docs/superpowers/plans/
    # 2026-07-19-safety-car-vsc-red-flag.md. Описание здесь временное:
    # core/engine.py::_handle_event_packet переписывает event_code/description
    # на синтетический (SAFETY_CAR_DEPLOYED/ENDING/CLEAR) через
    # core/strategy_ai/safety_car.py::derive_safety_car_event() ДО того, как
    # событие уходит в остальной пайплайн.
    "SCAR": "Событие Safety Car",
    "RDFL": "Красный флаг — сессия остановлена",
}

# Какие события вообще интересны комментатору (остальное — шум: BUTN и т.п.)
RELEVANT_EVENTS = set(EVENT_DESCRIPTIONS.keys())

# Критичные события — реагируем максимально оперативно, без очереди
CRITICAL_EVENTS = {"PENA", "RTMT", "CHQF", "RCWN", "COLL", "SCAR", "RDFL"}

# InfringementType-коды "трек-лимитной" семьи (corner cutting / running wide),
# подтверждено 2026-07-11 двумя независимыми источниками (EA-спека F1 25 +
# github.com/MacManley/f1-25-udp) — см. spec
# 2026-07-11-track-limits-engineer-toggle-design.md.
TRACK_LIMITS_INFRINGEMENT_TYPES = frozenset({7, 8, 9, 25, 26, 27, 28, 29})

# F1 25 Session packet: m_sessionType (uint8) at HEADER_SIZE+6.
# НАЙДЕНО ЖИВОЙ ПРОВЕРКОЙ 2026-07-18: старая раскладка (10-12=Race, 13=Time
# Trial) — это F1 23/24 enum. F1 25 вставил 5 новых кодов Sprint Shootout
# ПОСЕРЕДИНЕ (10-14), сдвинув всё, что после: реальная гонка игрока пришла с
# session_type_raw=15, что старая карта маппила в "unknown" — из-за этого
# ВСЕ race-only фичи (гэп-дайджест, position-calls, leader-change,
# pit-window-approach, pre-race-pep-talk) молчали в каждой живой гонке с
# самого своего появления, не только в Фазе A. Подтверждено независимо двумя
# источниками (форум EA + сторонние F1 25 UDP парсеры):
#   0=Unknown, 1-4=Practice(P1/P2/P3/ShortP), 5-9=Qualifying(Q1/Q2/Q3/ShortQ/OSQ),
#   10-14=Sprint Shootout(SQ1/SQ2/SQ3/ShortSQ/OSSQ), 15-17=Race/Race2/Race3,
#   18=Time Trial.
# Values: 1-4=Practice, 5-9=Qualifying, 10-14=Sprint Shootout, 15-17=Race, 18=Time Trial
SESSION_TYPE_MAP: dict[int, str] = {
    0: "unknown",
    1: "practice", 2: "practice", 3: "practice", 4: "practice",
    5: "qualifying", 6: "qualifying", 7: "qualifying",
    8: "qualifying", 9: "qualifying",
    # Sprint Shootout — квалификационный формат (single-lap, определяет
    # стартовую решётку спринта), той же природы, что и обычная Qualifying —
    # не Practice и не Race.
    10: "qualifying", 11: "qualifying", 12: "qualifying",
    13: "qualifying", 14: "qualifying",
    15: "race", 16: "race", 17: "race",
    18: "practice",   # Time Trial treated as practice (low-frequency commentary)
}

# ParticipantData — IDENTITY fields are stable across F1 2020–26:
#   aiControlled@0 driverId@1 networkId@2 teamId@3 myTeam@4 raceNumber@5
#   nationality@6 name@7 (char[], \x00-terminated) ...then version-specific tail.
# The TOTAL struct size has CHANGED between game versions (F1 25 appended livery
# colour data), so a hardcoded stride drifts the read for every car after the
# first → garbage teamId/raceNumber → "гонщик". We therefore DERIVE the stride
# from the packet length (the array is always 22 fixed slots), mirroring
# parse_player_damage. 60 is only the F1 23/24 fallback when derivation is implausible.
# Known F1 25 behavior: AI driver name bytes are all-zero in some game modes
# (offline, certain session types). Resolution falls back to race number lookup.
PARTICIPANT_SIZE = 60                 # F1 23/24 size; fallback only
PARTICIPANT_FORMAT = "<BBBBBBB48sBBHB"  # F1 23/24 layout (kept for reference/tests)
PARTICIPANT_TEAM_OFF = 3              # teamId offset within ParticipantData
PARTICIPANT_NUM_OFF = 5              # raceNumber offset
PARTICIPANT_NAME_OFF = 7            # name (char[], \x00-terminated) offset
PARTICIPANTS_ARRAY_LEN = 22         # m_participants is always a fixed [22] array
PARTICIPANTS_ARRAY_LEN_2026 = 24    # official 2026 Season Pack UDP v10


def parse_header(data: bytes) -> dict:
    fields = struct.unpack_from(HEADER_FORMAT, data, 0)
    keys = [
        "packet_format", "game_year", "game_major_version",
        "game_minor_version", "packet_version", "packet_id",
        "session_uid", "session_time", "frame_identifier",
        "overall_frame_identifier", "player_car_index",
        "secondary_player_car_index",
    ]
    return dict(zip(keys, fields))


def _looks_like_name(s: str) -> bool:
    """Reject garbled/empty participant names so resolution falls back to the
    race-number lookup instead of feeding Yandex TTS random characters.

    A real driver name is letters (Latin or Cyrillic) plus a few separators.
    """
    s = s.strip()
    if len(s) < 2:
        return False
    if any(ord(c) < 32 or c == "�" for c in s):
        return False
    letters = sum(c.isalpha() for c in s)
    # at least 2 letters AND at least half the string is letters
    return letters >= 2 and letters >= (len(s) - letters)


def _decode_name(raw_bytes: bytes) -> str:
    raw = raw_bytes.split(b"\x00", 1)[0].strip()
    decoded = ""
    for codec in ("utf-8", "cp1251", "latin-1"):
        try:
            decoded = raw.decode(codec)
            break
        except UnicodeDecodeError:
            continue
    else:
        decoded = raw.decode("utf-8", errors="ignore")
    return decoded if _looks_like_name(decoded) else ""


def _participant_stride(data: bytes, array_start: int, array_len: int = PARTICIPANTS_ARRAY_LEN) -> int:
    """Derive ParticipantData size from packet length (array is a fixed [22]).

    Survives version-to-version struct growth (F1 25 livery colours). Falls back
    to the known F1 23/24 size when the derived value is implausible.
    """
    body = len(data) - array_start
    if body <= 0:
        return PARTICIPANT_SIZE
    stride = body // array_len
    # Plausible struct size: ≥ identity+name(48), ≤ generous upper bound for tails.
    if 56 <= stride <= 200:
        return stride
    return PARTICIPANT_SIZE


def parse_participants(data: bytes, game_year: int = 0) -> dict:
    """Возвращает {vehicle_idx: {"name":..., "team":..., "color":..., "number":...}}.

    Шаг между машинами выводится из длины пакета (см. _participant_stride), а не
    хардкодится — иначе при смене размера структуры между версиями игры машины
    «уезжают» по смещению и читаются мусором (teamId/raceNumber → 'гонщик').
    Поля идентичности (teamId@3, raceNumber@5, name@7) стабильны для F1 2020–26.

    game_year (из заголовка того же пакета, Engine._game_year) выбирает
    TEAM_INFO vs TEAM_INFO_2026 — teamId один и тот же, но название/цвет
    команды зависят от ребрендинга (Sauber->Audi и т.п.), см. team_info_for_year.
    """
    result: dict = {}
    if len(data) <= HEADER_SIZE:
        return result
    num_active = data[HEADER_SIZE]
    array = HEADER_SIZE + 1
    packet_format = struct.unpack_from("<H", data, 0)[0] if len(data) >= 2 else 0
    is_2026_udp = packet_format >= 2026
    # F1 25 Season Pack keeps m_gameYear=25 but advertises packetFormat=2026.
    team_info = TEAM_INFO_2026 if is_2026_udp else team_info_for_year(game_year)
    array_len = PARTICIPANTS_ARRAY_LEN_2026 if is_2026_udp else PARTICIPANTS_ARRAY_LEN
    stride = _participant_stride(data, array, array_len)
    team_off = 5 if is_2026_udp else PARTICIPANT_TEAM_OFF
    number_off = 8 if is_2026_udp else PARTICIPANT_NUM_OFF
    name_off = 10 if is_2026_udp else PARTICIPANT_NAME_OFF

    for idx in range(min(num_active, array_len)):
        base = array + idx * stride
        if base + name_off > len(data):
            break
        team_id = (
            struct.unpack_from("<H", data, base + team_off)[0]
            if is_2026_udp else data[base + team_off]
        )
        race_no = data[base + number_off]
        # Read the name from its offset to the struct end and stop at the first
        # \x00 — robust to whatever the buffer length is in this game version.
        name = _decode_name(data[base + name_off: base + stride]).strip()
        # team_info (picked above by packet_format/game_year) may miss a team_id
        # that only exists in the OTHER table — observed live: F1 25 Season Pack
        # v1.24 emits teamId in the 220-230 range on packets that don't reliably
        # advertise packetFormat>=2026. Falling back to the confirmed Season
        # Pack v1.24 ids before giving up to a numeric placeholder fixes this
        # without risking the Sauber/Audi or RB/Racing Bulls rebrand distinction:
        # a classic low team_id (0-9/41/255) is always found in whichever table
        # team_info_for_year() correctly picked, so this fallback path is only
        # ever reached for IDs neither the 2020-25 nor the "is_2026_udp" branch
        # recognized on their own.
        team_name, team_color = team_info.get(
            team_id, _SEASON_PACK_V124_TEAM_IDS.get(
                team_id, (f"Команда #{team_id}", "#9CA3AF")))
        result[idx] = {
            "name": name or None,
            "team": team_name,
            "team_id": team_id,
            "color": team_color,
            "number": race_no,
        }

        if _DIAG:
            _log.warning(
                "DIAG participant idx=%d raceNumber=%d teamId=%d name=%r stride=%d",
                idx, race_no, team_id, name or "", stride,
            )

    if _DIAG:
        _log.warning("DIAG participants: num_active=%d parsed=%d stride=%d",
                     num_active, len(result), stride)

    return result


def parse_event(data: bytes) -> dict | None:
    """Возвращает событие с деталями, либо None для нерелевантных кодов (BUTN и т.п.)."""
    offset = HEADER_SIZE
    code = data[offset:offset + 4].decode("ascii", errors="ignore")

    if code not in RELEVANT_EVENTS:
        return None

    payload = data[offset + 4:]
    details: dict = {}

    if code == "FTLP" and len(payload) >= 5:
        vehicle_idx, lap_time = struct.unpack_from("<Bf", payload, 0)
        details = {"vehicle_idx": vehicle_idx, "lap_time": round(lap_time, 3)}

    elif code == "RTMT" and len(payload) >= 1:
        details = {"vehicle_idx": struct.unpack_from("<B", payload, 0)[0]}

    elif code == "PENA" and len(payload) >= 7:
        _ptype, infr, vehicle_idx, _other, time_s, lap_num, places = \
            struct.unpack_from("<BBBBBBB", payload, 0)
        details = {
            "vehicle_idx": vehicle_idx,
            "infringement_type": infr,
            "time_seconds": time_s,
            "lap_num": lap_num,
            "places_gained": places,
        }

    elif code == "OVTK" and len(payload) >= 2:
        overtaking, overtaken = struct.unpack_from("<BB", payload, 0)
        details = {"overtaking_idx": overtaking, "being_overtaken_idx": overtaken}

    elif code == "COLL" and len(payload) >= 2:
        v1, v2 = struct.unpack_from("<BB", payload, 0)
        details = {"vehicle1_idx": v1, "vehicle2_idx": v2}

    elif code == "SCAR" and len(payload) >= 2:
        # SafetyCarEventData: uint8 safetyCarType (0=none 1=full SC 2=VSC
        # 3=formation lap), uint8 eventType (0=Deployed 1=Returning
        # 2=Returned 3=Resume Race). Confirmed via EA's F1 25 UDP spec +
        # independent MacManley/f1-25-udp parser — see plan doc referenced
        # above EVENT_DESCRIPTIONS["SCAR"].
        safety_car_type, event_reason = struct.unpack_from("<BB", payload, 0)
        details = {"safety_car_type": safety_car_type, "event_reason": event_reason}

    return {
        "event_code": code,
        "description": EVENT_DESCRIPTIONS[code],
        "priority": "critical" if code in CRITICAL_EVENTS else "normal",
        **details,
    }


def _parse_rain_forecast(data: bytes, session_type_raw: int | None = None) -> dict | None:
    """Ближайший будущий сэмпл с дождём (weather>=3, time_offset>0), либо None.
    Самопроверяется: неверный офсет/битый пакет → None, не мусор (у прогноза
    есть естественные диапазоны валидности — используем их).

    ВАЖНО (найдено ревью): самопроверка НЕ закрывает сдвиг ровно на один целый
    сэмпл (8 байт) — в этом случае каждое читаемое поле берётся из СОСЕДНЕГО,
    но полностью валидного сэмпла, и пройдёт любую проверку диапазона. Кросс-
    сверка `m_sessionType` (offset+0) каждого сэмпла с уже известным
    `session_type_raw` пакета сужает промежуточные (1-7 байт) сдвиги, но
    целый-сэмпл сдвиг принципиально не ловится самосогласованностью одного
    поля — см. docs/superpowers/specs/2026-07-10-weather-forecast-parsing-design.md."""
    num_pos = HEADER_SIZE + _WFS_NUM_OFF
    if num_pos + 1 > len(data):
        return None
    num = data[num_pos]
    if not (1 <= num <= _WFS_MAX_SAMPLES):
        return None
    best: dict | None = None
    arr = HEADER_SIZE + _WFS_ARRAY_OFF
    for i in range(num):
        off = arr + i * _WFS_SAMPLE_SIZE
        if off + _WFS_SAMPLE_SIZE > len(data):
            break
        sample_session_type = data[off]
        time_offset = data[off + 1]
        weather = data[off + 2]
        rain_pct = data[off + 7]
        if time_offset > 130 or weather > 5 or rain_pct > 100:
            return None                  # неправдоподобно → офсет неверен
        if (session_type_raw is not None
                and sample_session_type not in (0, session_type_raw)):
            return None                  # сэмпл "не про эту сессию" → офсет неверен
        if weather >= _RAIN_WEATHER_MIN and time_offset > 0:
            if best is None or time_offset < best["minutes"]:
                best = {"minutes": time_offset, "rain_pct": rain_pct,
                        "weather": weather}
    return best


def parse_session(data: bytes) -> dict:
    """Session type, total laps, track ID from Session Data (packet 1).

    F1 25 Session payload offsets (relative to HEADER_SIZE):
      +3: m_totalLaps (uint8)
      +6: m_sessionType (uint8)
      +7: m_trackId (int8, signed; -1 = unknown)
      +124: m_safetyCarStatus (uint8; 0=none 1=full SC 2=VSC 3=formation lap)
    """
    if len(data) < HEADER_SIZE + 8:
        return {}
    track_id = struct.unpack_from("<b", data, HEADER_SIZE + 7)[0]
    session_type_raw = data[HEADER_SIZE + 6]
    out = {
        "total_laps": data[HEADER_SIZE + 3],
        "track_id": int(track_id),
        "session_type_raw": session_type_raw,
        "session_type": SESSION_TYPE_MAP.get(session_type_raw, "unknown"),
        # Текущая погода — офсеты 0/1/2, ПЕРЕД подтверждённым total_laps@3.
        "weather": data[HEADER_SIZE + 0],
        "track_temp": struct.unpack_from("<b", data, HEADER_SIZE + 1)[0],
        "air_temp": struct.unpack_from("<b", data, HEADER_SIZE + 2)[0],
        "safety_car_status": data[HEADER_SIZE + 124] if len(data) > HEADER_SIZE + 124 else 0,
        "rain_forecast": _parse_rain_forecast(data, session_type_raw),
    }
    if _DIAG:
        global _last_weather_diag_t
        now = time.time()
        if now - _last_weather_diag_t >= 2.0:
            _last_weather_diag_t = now
            rf = out["rain_forecast"]
            # Сырые тики первых сэмплов (БЕЗ валидации _parse_rain_forecast) —
            # сильный сигнал для живой сверки: полоса прогноза в HUD игры
            # обычно фиксированные минутные метки (5/10/15/30/45/60...).
            # Одного "похоже на процент" недостаточно (см. ревью, тот же
            # класс ловушки, что и с соседним ERS-полем) — нужно сверять
            # ВСЮ полосу, не только уже отфильтрованный ближайший дождь.
            num_pos = HEADER_SIZE + _WFS_NUM_OFF
            raw_samples = "n/a"
            if num_pos + 1 <= len(data):
                num = data[num_pos]
                arr = HEADER_SIZE + _WFS_ARRAY_OFF
                ticks = []
                for i in range(min(num, 6)):
                    off = arr + i * _WFS_SAMPLE_SIZE
                    if off + _WFS_SAMPLE_SIZE > len(data):
                        break
                    ticks.append((data[off + 1], data[off + 2], data[off + 7]))
                raw_samples = f"num={num} first6(min,weather,rain%)={ticks}"
            _log.warning(
                "DIAG weather: now=%s(%d) track=%d°C air=%d°C rain_forecast=%s | %s",
                WEATHER_LABEL.get(out["weather"], "?"), out["weather"],
                out["track_temp"], out["air_temp"], rf, raw_samples,
            )
    return out


def _lap_delta_ms(data: bytes, base: int, ms_off: int, min_off: int) -> int:
    """Дельта F1 25 формата «минуты + мс» -> суммарные мс (как у секторов)."""
    ms_part = struct.unpack_from("<H", data, base + ms_off)[0]
    minutes = data[base + min_off]
    return minutes * 60000 + ms_part


def parse_lap_data(data: bytes) -> dict:
    """Позиции всех машин + лидер (P1) + отрыв к машине впереди (для расчёта соседей)
    + реальный pit_status (для RivalTracker — отличать настоящий пит от ошибки/спина)
    + lap_distance_m всех машин (для дешёвого продольного фильтра споттера —
    см. core/strategy_ai/spotter.py, spec 2026-07-18-real-spotter-motion-design.md).
    F1 25 LapData: m_carPosition на offset 32, m_currentLapNum на 33, m_pitStatus на 34,
    m_lapDistance (float32) на offset 20 (уже подтверждён для игрока в parse_player_lap).
    deltaToCarInFront: msPart@14 + minutesPart@16 (формат как у секторов).
    PacketLapData не имеет numActiveCars — данные 22 машин начинаются сразу после header."""
    positions: dict[int, int] = {}
    laps: dict[int, int] = {}
    gaps_front: dict[int, int] = {}   # idx -> мс отрыва до машины впереди
    pit_status: dict[int, int] = {}
    lap_distances: dict[int, float | None] = {}
    for idx in range(22):
        base = HEADER_SIZE + idx * LAP_DATA_SIZE
        if base + 35 > len(data):
            break
        positions[idx] = data[base + 32]  # m_carPosition
        laps[idx] = data[base + 33]       # m_currentLapNum
        pit_status[idx] = data[base + 34]  # m_pitStatus: 0=нет, 1=заезжает, 2=в пит-лейн
        gaps_front[idx] = _lap_delta_ms(data, base, 14, 16)
        val = struct.unpack_from("<f", data, base + 20)[0]
        lap_distances[idx] = val if 0.0 <= val <= 10000.0 else None
    leader_idx = next((i for i, p in positions.items() if p == 1), None)
    return {"positions": positions, "laps": laps, "pit_status": pit_status,
            "leader_idx": leader_idx, "gaps_front": gaps_front,
            "lap_distances": lap_distances}


def parse_player_lap(data: bytes, player_idx: int) -> dict:
    base = HEADER_SIZE + player_idx * LAP_DATA_SIZE
    if base + 34 > len(data):
        return {}

    last_lap_ms = struct.unpack_from("<I", data, base + 0)[0]

    # Sector times: F1 25 format (verify offsets with diag_lap_offsets.py)
    # S1 = minutes*60000 + ms_part; S3 derived from total - S1 - S2
    s1_ms_part = struct.unpack_from("<H", data, base + 8)[0]
    s1_minutes  = data[base + 10]
    s2_ms_part = struct.unpack_from("<H", data, base + 11)[0]
    s2_minutes  = data[base + 13]
    s1_ms = s1_minutes * 60000 + s1_ms_part
    s2_ms = s2_minutes * 60000 + s2_ms_part
    s3_ms = (last_lap_ms - s1_ms - s2_ms
             if last_lap_ms > 0 and s1_ms > 0 and s2_ms > 0 else 0)

    # m_lapDistance (float32) at offset +20 — F1 25 LapData spec confirmed by:
    # m_carPosition@+32 and m_currentLapNum@+33 matching existing fields above.
    lap_distance_m: float | None = None
    if base + 24 <= len(data):
        val = struct.unpack_from("<f", data, base + 20)[0]
        if 0.0 <= val <= 10000.0:   # sanity: no real F1 track > 10 km
            lap_distance_m = val

    # m_currentLapTimeInMS @+4 (uint32) — время ТЕКУЩЕГО круга. Нужно коучу для
    # времени прохождения поворота (core/coach_ai/reference.py). Санитарный
    # предел по духу тот же, что у скорости и передачи: час на круге означает
    # смещённый пакет, а не медленный круг.
    current_lap_time_ms: int | None = None
    if base + 8 <= len(data):
        val_ms = struct.unpack_from("<I", data, base + 4)[0]
        if 0 <= val_ms <= 3_600_000:
            current_lap_time_ms = val_ms

    corner_cutting_warnings: int | None = None
    if base + 41 <= len(data):
        # m_cornerCuttingWarnings @40 (uint8) — сверено с независимым парсером
        # github.com/MacManley/f1-25-udp (2026-07-11), совпадает с уже
        # подтверждёнными m_carPosition@32/m_currentLapNum@33/m_pitStatus@34.
        corner_cutting_warnings = data[base + 40]

    return {
        "position": data[base + 32],
        "current_lap": data[base + 33],
        # m_pitStatus @34: 0=нет, 1=заезжает в пит-лейн, 2=в зоне пит-лейн
        # (сразу после m_carPosition@32/m_currentLapNum@33 — F1 25 LapData спека).
        "pit_status": data[base + 34],
        "last_lap_ms": last_lap_ms,
        "current_lap_time_ms": current_lap_time_ms,
        "s1_ms": s1_ms,
        "s2_ms": s2_ms,
        "s3_ms": s3_ms,
        # отрывы (мс): к машине впереди (@14/16) и к лидеру гонки (@17/19)
        "gap_front_ms": _lap_delta_ms(data, base, 14, 16),
        "gap_leader_ms": _lap_delta_ms(data, base, 17, 19),
        "lap_distance_m": lap_distance_m,
        "corner_cutting_warnings": corner_cutting_warnings,
    }


def parse_player_telemetry(data: bytes, player_idx: int) -> dict:
    """Speed (km/h) and gear from CarTelemetry (packet 6).

    Sanity-checked: speed > 400 km/h or gear outside [-1, 8] are silently
    dropped (logged at WARNING level). This prevents absurd UI values when
    the packet format has changed or endian/sign confusion exists.
    """
    # PacketCarTelemetryData = header + CarTelemetryData[22], NO numActiveCars
    # prefix (only PacketParticipantsData has one). Same framing as parse_lap_data.
    base = HEADER_SIZE + player_idx * CAR_TELEMETRY_SIZE
    chunk = data[base:base + CAR_TELEMETRY_SIZE]
    if len(chunk) < CAR_TELEMETRY_SIZE:
        return {}
    try:
        fields = struct.unpack_from(CAR_TELEMETRY_FORMAT, chunk, 0)
    except struct.error:
        return {}

    result: dict = {}
    speed: int = fields[0]          # uint16 km/h
    gear: int = fields[5]           # int8

    if 0 <= speed <= 400:
        result["speed"] = speed
    else:
        _log.warning(
            "suspicious speed %d km/h for car_idx=%d — dropped", speed, player_idx
        )

    if -1 <= gear <= 8:
        result["gear"] = "N" if gear == 0 else ("R" if gear == -1 else str(gear))
    else:
        _log.warning(
            "suspicious gear %d for car_idx=%d — dropped", gear, player_idx
        )

    # Driver inputs + engine, for the in-game HUD (pedal traces, rev lights,
    # gear dial arcs). Same packet, already unpacked — these fields were simply
    # discarded before. Percentages here, so the UI never has to know the game
    # sends 0.0-1.0 floats.
    throttle: float = fields[1]     # 0.0-1.0
    steer: float = fields[2]        # -1.0 (full left) .. 1.0 (full right)
    brake: float = fields[3]        # 0.0-1.0
    rpm: int = fields[6]            # uint16
    drs: int = fields[7]            # uint8, 1 = flap currently open
    rev_lights: int = fields[8]     # uint8, already a percentage

    if 0.0 <= throttle <= 1.0:
        result["throttle_pct"] = round(throttle * 100, 1)
    if 0.0 <= brake <= 1.0:
        result["brake_pct"] = round(brake * 100, 1)
    if -1.0 <= steer <= 1.0:
        result["steer"] = round(steer, 3)
    if 0 <= rpm <= 20000:
        result["rpm"] = rpm
    if 0 <= rev_lights <= 100:
        result["rev_lights_pct"] = rev_lights
    result["drs_active"] = bool(drs)

    # Хвост структуры: покрытие и температуры резины по колёсам — то, чего не
    # даёт CAR_TELEMETRY_FORMAT (см. комментарий у _CAR_TELEMETRY_SURFACE_OFF).
    # Читаем от base, а не от начала пакета: у второй машины тот же офсет
    # внутри её собственного элемента.
    if base + CAR_TELEMETRY_SIZE <= len(data):
        surf_base = base + _CAR_TELEMETRY_SURFACE_OFF
        result["surface"] = {
            wheel: SURFACE_TYPE.get(data[surf_base + i], "unknown")
            for i, wheel in enumerate(WHEEL_ORDER)
        }
        temp_base = base + _CAR_TELEMETRY_TYRE_SURF_TEMP_OFF
        result["tyre_surface_temp"] = {
            wheel: data[temp_base + i] for i, wheel in enumerate(WHEEL_ORDER)
        }
        # Внутренняя температура — про то, как резина работает под нагрузкой;
        # поверхностная скачет от одного торможения. Коучу нужны обе.
        inner_base = base + _CAR_TELEMETRY_TYRE_INNER_TEMP_OFF
        result["tyre_inner_temp"] = {
            wheel: data[inner_base + i] for i, wheel in enumerate(WHEEL_ORDER)
        }

    return result


def _car_status_fields(data: bytes, base: int) -> dict:
    """Топливо + шины (компаунд/возраст) + ERS для ОДНОЙ машины на офсете
    `base`. Общий хелпер для parse_player_status (один car_idx) и
    parse_car_status_all (все 22) — офсеты не дублируются в двух местах."""
    fuel = struct.unpack_from("<f", data, base + 5)[0]
    out = {"fuel": round(fuel, 1)}
    if base + 17 <= len(data):
        # m_fuelRemainingLaps @13 (float) — laps of fuel left RELATIVE to the
        # race distance, so negative means "short of the finish".
        out["fuel_remaining_laps"] = round(
            struct.unpack_from("<f", data, base + 13)[0], 2)
    if base + 23 <= len(data):
        # m_drsAllowed @22 (uint8) — офсет уже в golden-master _CAR_STATUS_LAYOUT
        # (сверен на ERS 2026-07-10), новой сверки не требуется.
        out["drs_allowed"] = bool(data[base + 22])
    if base + 25 <= len(data):
        # m_drsActivationDistance @23 (uint16) — metres to the next DRS zone,
        # 0 = not approaching one. Drives the HUD's DRS proximity bar.
        out["drs_distance_m"] = struct.unpack_from("<H", data, base + 23)[0]
    if base + 28 <= len(data):
        visual = data[base + 26]
        out["tyre_compound"] = TYRE_VISUAL.get(visual, "?")
        out["tyre_age"] = data[base + 27]
    if base + 37 <= len(data):
        # Power unit split, in kW (the game sends watts). m_enginePowerMGUK@33
        # sits immediately before m_ersStoreEnergy@37 — see
        # tests/test_packets_gaps_tyre.py::test_ers_read_from_37_... for why
        # that adjacency is dangerous and is pinned by a test.
        out["power_ice_kw"] = round(
            struct.unpack_from("<f", data, base + 29)[0] / 1000, 1)
        out["power_mguk_kw"] = round(
            struct.unpack_from("<f", data, base + 33)[0] / 1000, 1)
    if base + 42 <= len(data):
        ers_energy = struct.unpack_from("<f", data, base + 37)[0]
        percent = round(ers_energy / ERS_MAX_JOULES * 100, 1)
        # Sanity drop, как у lap_distance/speed выше: заряд вне 0-100% означает,
        # что офсет уехал после патча игры. Пропустить поле правильнее, чем
        # объявить «Батарея 4200%» — потребители (сводка инженера, Voice Q&A)
        # уже умеют молчать при None. Небольшой запас сверху: игра изредка
        # присылает 4 МДж с плавающей погрешностью.
        if -0.5 <= percent <= 101.0:
            out["ers_percent"] = min(max(percent, 0.0), 100.0)
        out["ers_deploy_mode"] = data[base + 41]
    if base + 54 <= len(data):
        # Harvest/deploy THIS LAP, as % of the 4 MJ store, for the HUD's ERS
        # ring arcs. MGU-K and MGU-H are summed: the ring shows one harvest arc.
        harvested = (struct.unpack_from("<f", data, base + 42)[0]
                     + struct.unpack_from("<f", data, base + 46)[0])
        deployed = struct.unpack_from("<f", data, base + 50)[0]
        out["ers_harvested_pct"] = round(harvested / ERS_MAX_JOULES * 100, 1)
        out["ers_deployed_pct"] = round(deployed / ERS_MAX_JOULES * 100, 1)
    return out


def parse_player_status(data: bytes, player_idx: int) -> dict:
    """Топливо + шины (компаунд/возраст) + ERS из Car Status (packet 7) для
    игрока. F1 25: m_fuelInTank@5, m_visualTyreCompound@26, m_tyresAgeLaps@27,
    m_ersStoreEnergy@37, m_ersDeployMode@41 — все офсеты СВЕРЕНЫ с официальной
    спецификацией EA (Data Output from F1 25 v3.pdf) и независимым парсером
    github.com/MacManley/f1-25-udp; полная golden-раскладка зафиксирована в
    tests/test_packets_gaps_tyre.py::_CAR_STATUS_LAYOUT. SPOTTER_DIAG=1
    оставлен как доп. страховка на случай будущего патча игры.

    PacketCarStatusData = header + CarStatusData[22], NO numActiveCars prefix
    (only PacketParticipantsData has one). Same framing as parse_lap_data."""
    base = HEADER_SIZE + player_idx * CAR_STATUS_SIZE
    if base + 9 > len(data):
        return {}
    result = _car_status_fields(data, base)
    if _DIAG and "ers_percent" in result:
        global _last_ers_diag_t
        now = time.time()
        if now - _last_ers_diag_t >= 2.0:
            _last_ers_diag_t = now
            mode = result["ers_deploy_mode"]
            _log.warning(
                "DIAG ers: ers_percent=%.1f%% deploy_mode=%d (%s)",
                result["ers_percent"], mode,
                _ERS_MODE_LABEL.get(mode, "?"),
            )
    return result


def parse_car_status_all(data: bytes) -> dict[int, dict]:
    """Как parse_player_status, но для всех 22 машин — нужно RivalTracker для
    свежести резины соперника (design spec 2026-07-07-rival-mistake-tyre-freshness)."""
    out: dict[int, dict] = {}
    for idx in range(22):
        base = HEADER_SIZE + idx * CAR_STATUS_SIZE
        if base + 9 > len(data):
            break
        out[idx] = _car_status_fields(data, base)
    return out


def _car_damage_fields(data: bytes, base: int) -> dict:
    """Износ шин + категории повреждений кузова для ОДНОЙ машины на офсете
    `base`. Общий хелпер для parse_player_damage (один car_idx) и
    parse_car_damage_all (все 22) — офсеты не дублируются в двух местах."""
    wear = struct.unpack_from("<ffff", data, base + 0)   # RL, RR, FL, FR
    avg = sum(wear) / 4.0
    # Поколёсный износ раньше распаковывался и тут же выбрасывался. Среднее
    # нужно стратегии («пора в боксы»), поколёсное — коучу: перекос между
    # колёсами одной оси показывает, ЧЕМ пилот убивает резину.
    per_wheel = {wheel: round(wear[i], 1) for i, wheel in enumerate(WHEEL_ORDER)}
    wing = max(data[base + 24], data[base + 25], data[base + 26])
    floor = max(data[base + 27], data[base + 28], data[base + 29])
    gearbox = data[base + 32]
    engine = data[base + 33]
    return {
        "tyre_wear": round(avg, 1),
        "tyre_wear_per_wheel": per_wheel,
        "wing_damage": wing,
        "floor_damage": floor,
        "gearbox_damage": gearbox,
        "engine_damage": engine,
    }


def parse_player_damage(data: bytes, player_idx: int) -> dict:
    """Износ шин + категории повреждений кузова из Car Damage (packet 10) для
    игрока. Офсеты 24-33 подтверждены косвенно: уже существующий тест этого
    файла использует stride=42 как "правдоподобный размер структуры", что
    совпадает с полной раскладкой полей F1 25 CarDamageData (42 байта на
    машину) — тем не менее сверить с реальной телеметрией через
    diag_lap_offsets.py перед тем, как полностью полагаться (см. design spec
    docs/superpowers/specs/2026-07-05-damage-and-collisions-design.md §2).
    Шаг машины выводим из длины пакета (numCars нет, как и в LapData) — без
    хардкода размера."""
    body = len(data) - HEADER_SIZE
    if body <= 0:
        return {}
    stride = body // 22
    if not (24 <= stride <= 80):
        return {}
    base = HEADER_SIZE + player_idx * stride
    if base + 34 > len(data):
        return {}
    return _car_damage_fields(data, base)


def parse_car_damage_all(data: bytes) -> dict[int, dict]:
    """Как parse_player_damage, но для всех 22 машин — нужно RivalTracker для
    детекта "соперник только что ошибся" (design spec
    2026-07-07-rival-mistake-tyre-freshness)."""
    body = len(data) - HEADER_SIZE
    if body <= 0:
        return {}
    stride = body // 22
    if not (24 <= stride <= 80):
        return {}
    out: dict[int, dict] = {}
    for idx in range(22):
        base = HEADER_SIZE + idx * stride
        if base + 34 > len(data):
            break
        out[idx] = _car_damage_fields(data, base)
    return out


_last_motion_diag_t = 0.0


def _motion_fields(data: bytes, base: int) -> dict:
    """Мировые X/Z (высота Y не нужна для лево/право) + единичный вектор
    "право" машины (int16 нормализованный -32767..32767 -> -1.0..1.0, игра
    уже даёт готовое направление — своя геометрия не нужна). Общий хелпер,
    как _car_status_fields/_car_damage_fields — единая точка чтения для
    любого числа машин."""
    x, _y, z = struct.unpack_from("<fff", data, base + 0)
    rx, _ry, rz = struct.unpack_from("<hhh", data, base + 30)
    return {
        "world_x": x, "world_z": z,
        "right_x": rx / 32767.0, "right_z": rz / 32767.0,
    }


def parse_player_setup(data: bytes, player_idx: int) -> dict:
    """Настройки машины ИГРОКА из Car Setups (packet 5).

    Отдаём только то, на чём коуч реально делает выводы (баланс тормозов,
    дифференциал на разгоне), плюс крылья и давления как факт для экрана.
    Остальные поля структуры сознательно не разбираем: советовать по ним мы
    всё равно не будем (см. spec 2026-08-07-driving-coach-phase3-garage.md §2.2).

    Шаг между машинами выводится из длины пакета — версия игры меняет размер
    структуры, и хардкод здесь уже однажды стоил мусорных данных."""
    body = len(data) - HEADER_SIZE
    if body <= 0 or not (0 <= player_idx < 22):
        return {}
    stride = body // 22
    if not (40 <= stride <= 80):
        return {}
    base = HEADER_SIZE + player_idx * stride
    if base + stride > len(data):
        return {}
    # Структура без m_engineBraking короче на байт, и всё после него смещено.
    pressure_off = _SETUP_TYRE_PRESSURE_OFF
    if stride < _SETUP_STRIDE_WITH_ENGINE_BRAKING:
        pressure_off -= 1
    return {
        "front_wing": data[base + _SETUP_FRONT_WING_OFF],
        "rear_wing": data[base + _SETUP_REAR_WING_OFF],
        "diff_on_throttle": data[base + _SETUP_ON_THROTTLE_OFF],
        "diff_off_throttle": data[base + _SETUP_OFF_THROTTLE_OFF],
        "brake_pressure": data[base + _SETUP_BRAKE_PRESSURE_OFF],
        "brake_bias": data[base + _SETUP_BRAKE_BIAS_OFF],
        # Округляем: давление показывается пилоту в PSI, одного знака хватает,
        # а сырой float даёт 23.200000762939453 на экране и в тестах.
        "tyre_pressure": {
            wheel: round(value, 1)
            for wheel, value in _wheel_floats(data, base + pressure_off).items()
        },
    }


_last_motion_ex_diag_t = 0.0


def _wheel_floats(data: bytes, base: int) -> dict[str, float]:
    """Четыре float подряд -> словарь по WHEEL_ORDER. Единая точка чтения
    любого поколёсного массива — порядок колёс не дублируется по функциям."""
    values = struct.unpack_from("<ffff", data, base)
    return dict(zip(WHEEL_ORDER, values))


def parse_motion_ex(data: bytes) -> dict:
    """MotionEx (packet 13) — проскальзывание колёс машины ИГРОКА.

    В отличие от PACKET_MOTION (тот про взаимное расположение всех машин, для
    споттера) этот пакет всегда про одну машину и нужен для другого — понять,
    ПОЧЕМУ пилот теряет время. Возвращает пустой словарь на коротком буфере;
    вызывающий обязан это проверять."""
    if len(data) < HEADER_SIZE + MOTION_EX_MIN_SIZE:
        return {}
    out = {
        "slip_ratio": _wheel_floats(data, HEADER_SIZE + _MOTION_EX_SLIP_RATIO_OFF),
        "slip_angle": _wheel_floats(data, HEADER_SIZE + _MOTION_EX_SLIP_ANGLE_OFF),
        "yaw_rate": struct.unpack_from(
            "<f", data, HEADER_SIZE + _MOTION_EX_ANG_VEL_Y_OFF)[0],
        "front_wheels_angle": struct.unpack_from(
            "<f", data, HEADER_SIZE + _MOTION_EX_FRONT_ANGLE_OFF)[0],
    }
    if _DIAG:
        global _last_motion_ex_diag_t
        now = time.time()
        # Пакет идёт с той же частотой, что Motion (20-60 Гц) — без троттлинга
        # DIAG-строка захлестнула бы лог. Тот же приём, что у parse_motion_all.
        if now - _last_motion_ex_diag_t >= 1.0:
            _last_motion_ex_diag_t = now
            _log.warning(
                "DIAG motion_ex slip_ratio rl=%.3f rr=%.3f fl=%.3f fr=%.3f | "
                "slip_angle rl=%.3f rr=%.3f fl=%.3f fr=%.3f | yaw=%.3f front=%.3f",
                *(out["slip_ratio"][w] for w in WHEEL_ORDER),
                *(out["slip_angle"][w] for w in WHEEL_ORDER),
                out["yaw_rate"], out["front_wheels_angle"],
            )
    return out


def parse_tyre_sets(data: bytes) -> dict:
    """Tyre Sets (packet 12) — ПОЦИКЛОВОЙ пакет, одна машина за раз
    (`m_carIdx`), не все 22 разом (в отличие от большинства пакетов этого
    файла). Возвращает данные ДЛЯ ТОЙ машины, что в пакете — вызывающий
    (core/engine.py) решает, игрок ли это. Считает только `m_available==1`
    комплекты (ещё не использованные по регламенту FIA на этот уикенд),
    сгруппированные по `TYRE_VISUAL`-метке компаунда. См. docs/superpowers/
    plans/2026-07-19-tyre-sets-final-classification.md."""
    body_needed = HEADER_SIZE + 1 + 20 * TYRE_SET_SIZE + 1
    if len(data) < body_needed:
        return {}
    car_idx = data[HEADER_SIZE]
    array_start = HEADER_SIZE + 1
    available_by_compound: dict[str, int] = {}
    for i in range(20):
        base = array_start + i * TYRE_SET_SIZE
        available = data[base + 3]
        if available:
            visual = data[base + 1]
            label = TYRE_VISUAL.get(visual, "?")
            available_by_compound[label] = available_by_compound.get(label, 0) + 1
    fitted_idx = data[array_start + 20 * TYRE_SET_SIZE]
    fitted_base = array_start + fitted_idx * TYRE_SET_SIZE
    fitted_visual = data[fitted_base + 1]
    fitted_wear = data[fitted_base + 2]
    return {
        "car_idx": car_idx,
        "available_by_compound": available_by_compound,
        "fitted_compound": TYRE_VISUAL.get(fitted_visual, "?"),
        "fitted_wear": fitted_wear,
    }


def _parse_final_classification_entry(data: bytes, vehicle_idx: int) -> dict:
    """Decode one entry from PacketFinalClassificationData."""
    base = HEADER_SIZE + 1 + vehicle_idx * FINAL_CLASSIFICATION_ENTRY_SIZE
    if base + FINAL_CLASSIFICATION_ENTRY_SIZE > len(data):
        return {}
    result_status = data[base + 5]
    result_reason = data[base + 6]
    return {
        "vehicle_idx": vehicle_idx,
        "position": data[base + 0],
        "num_laps": data[base + 1],
        "grid_position": data[base + 2],
        "points": data[base + 3],
        "num_pit_stops": data[base + 4],
        "result_status": result_status,
        "result_status_label": RESULT_STATUS_LABEL.get(result_status, "неизвестно"),
        "result_reason": result_reason,
        "result_reason_label": RESULT_REASON_LABEL.get(result_reason, "неизвестно"),
        "best_lap_time_ms": struct.unpack_from("<I", data, base + 7)[0],
        "total_race_time_s": struct.unpack_from("<d", data, base + 11)[0],
        "penalties_time_s": data[base + 19],
        "num_penalties": data[base + 20],
    }


def parse_final_classification_grid(data: bytes) -> list[dict]:
    """Return the official finishing order for every active car.

    The player-only parser remains public for the existing UI.  Season
    automation needs both cars from every team, so it consumes this complete
    view of the same packet instead of inferring results from the last live
    lap snapshot.
    """
    if len(data) <= HEADER_SIZE:
        return []
    num_cars = min(data[HEADER_SIZE], 22)
    entries = [_parse_final_classification_entry(data, idx) for idx in range(num_cars)]
    return [entry for entry in entries if entry]


def parse_final_classification(data: bytes, player_idx: int) -> dict:
    """Final Classification (packet 8) — все 22 машины в одном пакете, срез
    по `player_idx` (та же схема, что parse_player_damage). Официальный
    подтверждённый результат — точнее live-снимка позиции на CHQF (см.
    core/engine.py::_generate_story). См. docs/superpowers/plans/
    2026-07-19-tyre-sets-final-classification.md."""
    result = _parse_final_classification_entry(data, player_idx)
    # Keep the established player-facing payload stable.
    result.pop("vehicle_idx", None)
    return result


def parse_session_history(data: bytes) -> dict:
    """Session History (packet 11) — ПОЦИКЛОВОЙ пакет, одна машина за раз
    (`m_carIdx`), не все 22 разом. Возвращает данные ДЛЯ ТОЙ машины, что в
    пакете — вызывающий (core/engine.py) кэширует по car_idx, включая игрока
    (пакет цикличен по всем машинам, не различает игрока от соперников).

    `m_bestSectorNLapNum`/`m_bestLapTimeLapNum` — лап-номер (судя по всему
    1-индексированный, как m_currentLapNum в остальной спеке этого проекта,
    но НЕ подтверждено официальной документацией для именно этих полей) —
    каждый lookup защищён диапазоном `1 <= lapNum <= num_laps <= 100`,
    иначе соответствующее best-значение отсутствует, а не читает мусор/
    выходит за границы. НЕ хранит сырой массив из 100 кругов целиком —
    ничего в проекте пока не итерируется по кругам, лишние 1.4 КБ на
    машину не нужны (см. план)."""
    num_laps_off = HEADER_SIZE + 1
    if num_laps_off + 1 > len(data):
        return {}
    num_laps = data[num_laps_off]

    def _lap_entry_base(lap_num: int) -> int | None:
        """Байтовый офсет m_lapHistoryData[lap_num - 1], либо None, если
        lap_num вне диапазона `1..num_laps` (0 — "ещё не установлено")."""
        if not (1 <= lap_num <= num_laps <= _SESSION_HISTORY_NUM_LAP_SLOTS):
            return None
        base = (HEADER_SIZE + _SESSION_HISTORY_LAP_ARRAY_OFF
                + (lap_num - 1) * LAP_HISTORY_SIZE)
        return base if base + LAP_HISTORY_SIZE <= len(data) else None

    def _best_lap_ms(lap_num: int) -> int | None:
        base = _lap_entry_base(lap_num)
        return struct.unpack_from("<I", data, base)[0] if base is not None else None

    def _best_sector_ms(lap_num: int, ms_off: int, min_off: int) -> int | None:
        base = _lap_entry_base(lap_num)
        return _lap_delta_ms(data, base, ms_off, min_off) if base is not None else None

    if HEADER_SIZE + _SESSION_HISTORY_BODY_SIZE > len(data):
        return {}

    num_tyre_stints = data[HEADER_SIZE + 2]
    best_lap_ms = _best_lap_ms(data[HEADER_SIZE + 3])
    best_sector_ms: dict[int, int] = {}
    for sector, (ms_off, min_off) in {1: (4, 6), 2: (7, 9), 3: (10, 12)}.items():
        lap_num = data[HEADER_SIZE + 3 + sector]
        value = _best_sector_ms(lap_num, ms_off, min_off)
        if value is not None:
            best_sector_ms[sector] = value

    tyre_stints = []
    for i in range(min(num_tyre_stints, 8)):
        base = HEADER_SIZE + _SESSION_HISTORY_TYRE_STINTS_OFF + i * TYRE_STINT_HISTORY_SIZE
        tyre_stints.append({
            "end_lap": data[base + 0],
            "actual_compound": data[base + 1],
            "visual_compound": data[base + 2],
        })

    return {
        "car_idx": data[HEADER_SIZE + 0],
        "num_laps": num_laps,
        "best_lap_ms": best_lap_ms,
        "best_sector_ms": best_sector_ms,
        "tyre_stints": tyre_stints,
    }


def parse_motion_all(data: bytes) -> dict[int, dict]:
    """Мировые координаты + вектор "право" для всех 22 машин (PACKET_MOTION,
    id 0). Используется дешёвым продольным фильтром + геометрией споттера
    (core/strategy_ai/spotter.py). CarMotionData — фиксированный размер
    (НЕ версионируется между играми, в отличие от ParticipantData), страйд
    не выводится из длины пакета, как у parse_participants."""
    out: dict[int, dict] = {}
    for idx in range(22):
        base = HEADER_SIZE + idx * MOTION_SIZE
        if base + MOTION_SIZE > len(data):
            break
        out[idx] = _motion_fields(data, base)

        if _DIAG:
            _log.warning(
                "DIAG motion idx=%d world_x=%.1f world_z=%.1f right_x=%.3f right_z=%.3f",
                idx, out[idx]["world_x"], out[idx]["world_z"],
                out[idx]["right_x"], out[idx]["right_z"],
            )

    if _DIAG:
        global _last_motion_diag_t
        now = time.time()
        if now - _last_motion_diag_t >= 2.0:
            _last_motion_diag_t = now
            _log.warning("DIAG motion: parsed=%d/22 cars", len(out))

    return out
