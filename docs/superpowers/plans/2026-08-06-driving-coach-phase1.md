# Коуч пилотажа, фаза 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Научить приложение называть причину ошибки пилотажа, колесо и поворот («блокируешь переднее левое на входе в третий») — из пакета MotionEx, без эталонного круга.

**Architecture:** Новый пакет 13 парсится в `core/packets.py` и едет отдельным `TelemetryDelta("motion_ex")`. Детекторы-автоматы в `core/coach_ai/slip.py` работают на тике и отдают завершённое событие с пиком проскальзывания; `core/coach_ai/corner_log.py` копит их по кругам, привязывает к повороту через уже существующий `track_ai` и решает, была ли ошибка повторяющейся. Живьём озвучивается только повтор, каналом инженера; полная карта уезжает в дебриф.

**Tech Stack:** Python 3, `struct`, pytest; фронт — Next.js static export в `NewSpotterUI/`, собирается в `webui/`.

**Спека:** `docs/superpowers/specs/2026-08-06-driving-coach-motion-ex-design.md`

---

## Важно до начала

**Проект НЕ под git.** Шага «commit» в этом плане нет намеренно — вместо него в конце каждой задачи стоит прогон целевых тестов. Если задача выполняется в параллельной сессии, перед прогоном полного набора сверить `mtime` затронутых файлов: «весь набор зелёный» на этом проекте — сигнал, верный только когда никто другой не пишет в те же файлы.

**Порядок колёс во всех пакетах F1: `RL, RR, FL, FR`** — заднее левое первым. Это единственная ошибка, которая делает коуча вредным, поэтому порядок зафиксирован константой и проверяется тестом отдельно от всего остального.

**Пороги детекторов в Task 5–6 — предварительные.** Они помечены в коде как некалиброванные и калибруются в Task 13 по живому прогону. Фича до этого выключена по умолчанию.

---

## Task 1: `parse_motion_ex` — пакет 13

**Files:**
- Modify: `core/packets.py` (константы рядом с `MOTION_SIZE`, :36; функция — рядом с `parse_motion_all`, :999)
- Test: `tests/test_packets_motion_ex.py` (создать)

Офсеты `PacketMotionExData` реконструированы по публичному формату F1 UDP — тот же класс риска, что был у пакета 0. Golden-master ниже фиксирует **парсер относительно документированной раскладки**; саму раскладку подтверждает живой прогон в Task 13.

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_packets_motion_ex.py`:

```python
"""PACKET_MOTION_EX (id 13) — проскальзывание по колёсам.

Golden-master раскладка PacketMotionExData: офсеты реконструированы по
публичному формату F1 UDP, требуют живой сверки через SPOTTER_DIAG=1
(Task 13 плана 2026-08-06-driving-coach-phase1.md).

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


def test_truncated_buffer_returns_empty_dict_without_error():
    assert packets.parse_motion_ex(bytes(_buf(HEADER_SIZE + 8))) == {}


def test_empty_data_returns_empty_dict():
    assert packets.parse_motion_ex(b"") == {}
```

- [ ] **Step 2: Прогнать тест, убедиться что падает**

Run: `python -m pytest tests/test_packets_motion_ex.py -v`
Expected: FAIL — `AttributeError: module 'core.packets' has no attribute 'WHEEL_ORDER'`

- [ ] **Step 3: Реализовать парсер**

В `core/packets.py` после строки `MOTION_SIZE = 60` (:36) добавить:

```python
PACKET_MOTION_EX = 13

# Порядок колёс во ВСЕХ массивах пакетов F1: заднее левое, заднее правое,
# переднее левое, переднее правое. Не менять и не «исправлять» на привычный
# FL/FR/RL/RR — перепутанный порядок заставит коуча называть не то колесо.
WHEEL_ORDER: tuple[str, str, str, str] = ("rl", "rr", "fl", "fr")

# PacketMotionExData — офсеты ОТ КОНЦА ЗАГОЛОВКА. Реконструированы по
# публичному формату F1 UDP, живая сверка — SPOTTER_DIAG=1 (см. план
# 2026-08-06-driving-coach-phase1.md, Task 13). Массивы идут подряд, каждый
# 4 float: suspensionPosition/Velocity/Acceleration, wheelSpeed, slipRatio,
# slipAngle, latForce, longForce.
_MOTION_EX_SLIP_RATIO_OFF = 64
_MOTION_EX_SLIP_ANGLE_OFF = 80
_MOTION_EX_ANG_VEL_Y_OFF = 148     # m_angularVelocityY — скорость рыскания
_MOTION_EX_FRONT_ANGLE_OFF = 168   # m_frontWheelsAngle
MOTION_EX_MIN_SIZE = _MOTION_EX_FRONT_ANGLE_OFF + 4
```

Рядом с `parse_motion_all` (:999) добавить:

```python
_last_motion_ex_diag_t = 0.0


def _wheel_floats(data: bytes, base: int) -> dict[str, float]:
    """Четыре float подряд -> словарь по WHEEL_ORDER. Единая точка чтения
    любого поколёсного массива — офсеты порядка не дублируются."""
    values = struct.unpack_from("<ffff", data, base)
    return dict(zip(WHEEL_ORDER, values))


def parse_motion_ex(data: bytes) -> dict:
    """MotionEx (packet 13) — проскальзывание колёс машины ИГРОКА.

    В отличие от PACKET_MOTION этот пакет всегда про одну машину (игрока),
    массива по 22 машинам в нём нет. Возвращает пустой словарь на коротком
    буфере — вызывающий обязан это проверять."""
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
```

- [ ] **Step 4: Прогнать тест, убедиться что проходит**

Run: `python -m pytest tests/test_packets_motion_ex.py -v`
Expected: PASS, 6 passed

---

## Task 2: Хвост пакета 6 — тип покрытия и температуры резины

**Files:**
- Modify: `core/packets.py` (`parse_player_telemetry`, :614)
- Test: `tests/test_packets_surface.py` (создать)

**Читать только по явным офсетам.** `CAR_TELEMETRY_FORMAT` (:41) разъехался с реальной структурой начиная с внутренних температур: они занимают 4 байта (uint8×4), а формат читает там один `H`, из-за чего давления и `surfaceType` в конце строки смещены на 4 байта. Поля 0–8, которые используются сегодня, лежат до этого места и корректны — существующего бага нет, но расширять формат по индексам нельзя.

Реальная раскладка `CarTelemetryData` (60 байт): `brakesTemperature[4]` @22, `tyresSurfaceTemperature[4]` @30, `tyresInnerTemperature[4]` @34, `engineTemperature` @38, `tyresPressure[4]` @40, `surfaceType[4]` @56.

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_packets_surface.py`:

```python
"""Хвост CarTelemetryData (packet 6): тип покрытия под колёсами и
температуры резины. Читаются по ЯВНЫМ офсетам, не по CAR_TELEMETRY_FORMAT —
хвост формата разъехался со структурой (см. Task 2 плана
2026-08-06-driving-coach-phase1.md)."""
import struct

from core import packets
from core.packets import CAR_TELEMETRY_SIZE, HEADER_SIZE


def _telemetry_buf(cars: int = 22) -> bytearray:
    return bytearray(HEADER_SIZE + cars * CAR_TELEMETRY_SIZE)


def test_surface_type_read_per_wheel_in_rl_rr_fl_fr_order():
    buf = _telemetry_buf()
    base = HEADER_SIZE + packets._CAR_TELEMETRY_SURFACE_OFF
    buf[base:base + 4] = bytes([0, 0, 7, 4])   # rl/rr асфальт, fl трава, fr гравий

    out = packets.parse_player_telemetry(bytes(buf), 0)

    assert out["surface"] == {"rl": "tarmac", "rr": "tarmac",
                              "fl": "grass", "fr": "gravel"}


def test_unknown_surface_code_falls_back_to_unknown():
    buf = _telemetry_buf()
    base = HEADER_SIZE + packets._CAR_TELEMETRY_SURFACE_OFF
    buf[base:base + 4] = bytes([200, 0, 0, 0])

    out = packets.parse_player_telemetry(bytes(buf), 0)

    assert out["surface"]["rl"] == "unknown"


def test_tyre_surface_temperature_read_per_wheel():
    buf = _telemetry_buf()
    base = HEADER_SIZE + packets._CAR_TELEMETRY_TYRE_SURF_TEMP_OFF
    buf[base:base + 4] = bytes([90, 95, 105, 110])

    out = packets.parse_player_telemetry(bytes(buf), 0)

    assert out["tyre_surface_temp"] == {"rl": 90, "rr": 95, "fl": 105, "fr": 110}


def test_surface_read_at_correct_stride_for_second_car():
    buf = _telemetry_buf()
    base = HEADER_SIZE + CAR_TELEMETRY_SIZE + packets._CAR_TELEMETRY_SURFACE_OFF
    buf[base:base + 4] = bytes([7, 7, 0, 0])

    out = packets.parse_player_telemetry(bytes(buf), 1)

    assert out["surface"]["rl"] == "grass"
    assert out["surface"]["fl"] == "tarmac"


def test_existing_speed_and_gear_still_parsed():
    """Регрессия: правка хвоста не должна тронуть поля 0-8."""
    buf = _telemetry_buf()
    struct.pack_into("<H", buf, HEADER_SIZE + 0, 250)
    struct.pack_into("<b", buf, HEADER_SIZE + 15, 6)

    out = packets.parse_player_telemetry(bytes(buf), 0)

    assert out["speed"] == 250
    assert out["gear"] == "6"
```

- [ ] **Step 2: Прогнать тест, убедиться что падает**

Run: `python -m pytest tests/test_packets_surface.py -v`
Expected: FAIL — `AttributeError: module 'core.packets' has no attribute '_CAR_TELEMETRY_SURFACE_OFF'`

- [ ] **Step 3: Реализовать**

В `core/packets.py` рядом с `CAR_TELEMETRY_FORMAT` (:41) добавить:

```python
# Хвост CarTelemetryData читается по ЯВНЫМ офсетам, а НЕ по
# CAR_TELEMETRY_FORMAT: формат разъехался со структурой начиная с внутренних
# температур (там 4 байта uint8, а формат читает один H), поэтому всё, что в
# нём после — давления и surfaceType — смещено. Поля 0-8, которыми пользуется
# parse_player_telemetry, лежат ДО этого места и верны; формат не трогаем,
# чтобы не переписывать рабочий код, но и не расширяем.
_CAR_TELEMETRY_TYRE_SURF_TEMP_OFF = 30    # uint8[4]
_CAR_TELEMETRY_TYRE_INNER_TEMP_OFF = 34   # uint8[4]
_CAR_TELEMETRY_SURFACE_OFF = 56           # uint8[4]

# m_surfaceType: коды покрытия под колесом. Всё, что не асфальт и не поребрик,
# для коуча означает «пилот вне трассы».
SURFACE_TYPE = {
    0: "tarmac", 1: "rumble_strip", 2: "concrete", 3: "rock", 4: "gravel",
    5: "mud", 6: "sand", 7: "grass", 8: "water", 9: "cobblestone",
    10: "metal", 11: "ridged",
}
SURFACE_ON_TRACK = frozenset({"tarmac", "rumble_strip", "concrete"})
```

В конце `parse_player_telemetry`, перед `return result` (:673), добавить:

```python
    # Хвост структуры: покрытие и температуры резины по колёсам. Читаем по
    # явным офсетам от base (см. комментарий у _CAR_TELEMETRY_SURFACE_OFF).
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
```

- [ ] **Step 4: Прогнать тесты**

Run: `python -m pytest tests/test_packets_surface.py tests/test_packets_gaps_tyre.py -v`
Expected: PASS — 5 новых плюс существующие телеметрийные тесты без регрессий

---

## Task 3: Довезти пакет 13 до движка

**Files:**
- Modify: `core/telemetry_adapters.py` (`_decode`, :152-208)
- Test: `tests/test_telemetry_adapters.py` (дописать)

- [ ] **Step 1: Написать падающий тест**

Файл использует поддельный `_Decoder` со своей нумерацией пакетов (`tests/test_telemetry_adapters.py:10-34`) — расширяем именно его, настоящий `core.packets` сюда не тянем.

Сначала дописать в класс `_Decoder`, после `PACKET_EVENT = 11`:

```python
    PACKET_MOTION_EX = 12

    @staticmethod
    def parse_motion_ex(_data):
        return {"slip_ratio": {"rl": 0.0, "rr": 0.0, "fl": -0.4, "fr": 0.0}}
```

Затем добавить тест:

```python
def test_motion_ex_packet_yields_motion_ex_delta():
    """Пакет 13 доезжает ОТДЕЛЬНЫМ kind: PACKET_MOTION — про соседние машины
    (споттер), MotionEx — про собственное сцепление (коуч). Смешивать их в
    один kind нельзя, у потребителей нет ничего общего."""
    adapter = F1TelemetryAdapter(
        "127.0.0.1", 20777, transport_factory=_Transport, decoder=_Decoder)

    messages = list(adapter._decode(bytes([_Decoder.PACKET_MOTION_EX])))

    assert messages == [TelemetryDelta(
        "motion_ex",
        {"slip_ratio": {"rl": 0.0, "rr": 0.0, "fl": -0.4, "fr": 0.0}},
        player_car_index=3,
        game_year=25,
    )]
```

- [ ] **Step 2: Прогнать тест, убедиться что падает**

Run: `python -m pytest tests/test_telemetry_adapters.py -k motion_ex -v`
Expected: FAIL — `assert [] == ['motion_ex']`

- [ ] **Step 3: Реализовать**

В `core/telemetry_adapters.py::_decode`, сразу после ветки `PACKET_MOTION` (:184-185), добавить:

```python
        elif packet_id == self._decoder.PACKET_MOTION_EX:
            yield TelemetryDelta(
                "motion_ex", self._decoder.parse_motion_ex(data), player, telemetry_year)
```

- [ ] **Step 4: Прогнать тесты**

Run: `python -m pytest tests/test_telemetry_adapters.py -v`
Expected: PASS

---

## Task 4: Модель ошибки

**Files:**
- Modify: `core/coach_ai/models.py`
- Test: покрывается тестами Task 5

- [ ] **Step 1: Добавить датакласс**

В конец `core/coach_ai/models.py`:

```python
@dataclass
class CornerMistake:
    """Одна завершённая ошибка пилотажа, привязанная к месту на трассе.

    Создаётся детектором только ПОСЛЕ окончания срыва: нужен пик, а не факт.
    `peak` — модуль максимального проскальзывания за событие, он же степень
    ошибки; `duration_s` отсекает шум подвески от настоящей потери сцепления.
    """
    kind: str            # "lockup" | "wheelspin" | "understeer" | "oversteer" | "offtrack"
    wheel: str | None    # "rl" | "rr" | "fl" | "fr"; None для ошибок всей машины
    corner_id: int | None
    corner_name: str | None
    phase: str           # "braking" | "entry" | "apex" | "exit" | "straight"
    lap: int
    peak: float
    duration_s: float
    speed_kmh: int | None

    def signature(self) -> tuple[str, int | None, str]:
        """Ключ повторяемости: та же ошибка, тот же поворот, та же фаза.
        Колесо в ключ НЕ входит — «блокирую передние в третьем» остаётся одной
        и той же проблемой, каким бы колесом ни поймалось в этот раз."""
        return (self.kind, self.corner_id, self.phase)
```

- [ ] **Step 2: Проверить импорт**

Run: `python -c "from core.coach_ai.models import CornerMistake; print(CornerMistake('lockup','fl',3,'Turn 3','braking',5,0.6,0.3,180).signature())"`
Expected: `('lockup', 3, 'braking')`

---

## Task 5: Детекторы срывов сцепления

**Files:**
- Create: `core/coach_ai/slip.py`
- Test: `tests/test_coach_slip.py` (создать)

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_coach_slip.py`:

```python
"""Детекторы срывов сцепления. Кадры синтетические: детектор обязан быть
чистой функцией от потока телеметрии, без обращений к движку."""
import pytest

from core.coach_ai.slip import SlipDetector


def _frame(**kw):
    """Один кадр MotionEx + вводов. Всё нейтрально, если не переопределено."""
    base = {
        "slip_ratio": {"rl": 0.0, "rr": 0.0, "fl": 0.0, "fr": 0.0},
        "slip_angle": {"rl": 0.0, "rr": 0.0, "fl": 0.0, "fr": 0.0},
        "yaw_rate": 0.0,
        "front_wheels_angle": 0.0,
        "throttle_pct": 0.0,
        "brake_pct": 0.0,
        "steer": 0.0,
        "speed_kmh": 200,
        "surface": {"rl": "tarmac", "rr": "tarmac", "fl": "tarmac", "fr": "tarmac"},
    }
    base.update(kw)
    return base


def _feed(detector, frame, seconds, step=0.05, lap=1, corner=(3, "Turn 3"), phase="braking"):
    """Прогнать один и тот же кадр `seconds` секунд. Возвращает все события."""
    out = []
    t = 0.0
    while t < seconds:
        ev = detector.tick(frame, now=t, lap=lap,
                           corner_id=corner[0], corner_name=corner[1], phase=phase)
        if ev is not None:
            out.append(ev)
        t += step
    return out


def test_sustained_front_lockup_under_braking_is_reported_on_release():
    d = SlipDetector()
    braking = _frame(brake_pct=100.0,
                     slip_ratio={"rl": 0.0, "rr": 0.0, "fl": -0.5, "fr": -0.05})

    during = _feed(d, braking, seconds=0.4)
    assert during == [], "событие не должно публиковаться, пока срыв идёт"

    after = _feed(d, _frame(), seconds=0.1)
    assert len(after) == 1
    ev = after[0]
    assert ev.kind == "lockup"
    assert ev.wheel == "fl"
    assert ev.corner_id == 3
    assert ev.phase == "braking"
    assert ev.peak == pytest.approx(0.5)
    assert ev.duration_s >= 0.3


def test_brief_slip_below_duration_threshold_is_ignored():
    d = SlipDetector()
    _feed(d, _frame(brake_pct=100.0,
                    slip_ratio={"rl": 0.0, "rr": 0.0, "fl": -0.5, "fr": 0.0}),
          seconds=0.05)
    assert _feed(d, _frame(), seconds=0.1) == []


def test_lockup_requires_brake_pressed():
    d = SlipDetector()
    _feed(d, _frame(brake_pct=0.0,
                    slip_ratio={"rl": 0.0, "rr": 0.0, "fl": -0.5, "fr": 0.0}),
          seconds=0.4)
    assert _feed(d, _frame(), seconds=0.1) == []


def test_rear_wheelspin_on_throttle_is_reported():
    d = SlipDetector()
    _feed(d, _frame(throttle_pct=90.0,
                    slip_ratio={"rl": 0.35, "rr": 0.30, "fl": 0.0, "fr": 0.0}),
          seconds=0.4, phase="exit")
    events = _feed(d, _frame(), seconds=0.1)
    assert len(events) == 1
    assert events[0].kind == "wheelspin"
    assert events[0].wheel == "rl"
    assert events[0].phase == "exit"


def test_understeer_needs_steering_and_missing_yaw():
    d = SlipDetector()
    frame = _frame(steer=0.6, yaw_rate=0.02,
                   slip_angle={"rl": 0.02, "rr": 0.02, "fl": 0.18, "fr": 0.17})
    _feed(d, frame, seconds=0.5, phase="entry")
    events = _feed(d, _frame(), seconds=0.1)
    assert len(events) == 1
    assert events[0].kind == "understeer"
    assert events[0].wheel is None


def test_high_front_slip_without_steering_is_not_understeer():
    d = SlipDetector()
    frame = _frame(steer=0.0, yaw_rate=0.0,
                   slip_angle={"rl": 0.02, "rr": 0.02, "fl": 0.18, "fr": 0.17})
    _feed(d, frame, seconds=0.5)
    assert _feed(d, _frame(), seconds=0.1) == []


def test_oversteer_reported_on_counter_steer():
    d = SlipDetector()
    # Руль вправо, кузов разворачивает влево — контр-руление.
    frame = _frame(steer=0.5, yaw_rate=-0.6,
                   slip_angle={"rl": 0.22, "rr": 0.21, "fl": 0.03, "fr": 0.03})
    _feed(d, frame, seconds=0.4, phase="exit")
    events = _feed(d, _frame(), seconds=0.1)
    assert len(events) == 1
    assert events[0].kind == "oversteer"


def test_reset_drops_event_in_progress():
    d = SlipDetector()
    _feed(d, _frame(brake_pct=100.0,
                    slip_ratio={"rl": 0.0, "rr": 0.0, "fl": -0.5, "fr": 0.0}),
          seconds=0.4)
    d.reset()
    assert _feed(d, _frame(), seconds=0.1) == []
```

- [ ] **Step 2: Прогнать тест, убедиться что падает**

Run: `python -m pytest tests/test_coach_slip.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.coach_ai.slip'`

- [ ] **Step 3: Реализовать**

Создать `core/coach_ai/slip.py`:

```python
"""
core/coach_ai/slip.py
======================
Детекторы срывов сцепления по MotionEx. Чистые конечные автоматы: на вход —
кадр телеметрии, на выходе — завершённая `CornerMistake` или None.

Событие публикуется ТОЛЬКО по окончании срыва: до этого неизвестен пик, а пик
и есть степень ошибки. Один автомат на вид ошибки — они могут идти
одновременно (блокировка передних на входе и снос там же — разные проблемы).

Пороги ниже НЕ откалиброваны на живых данных (см. Task 13 плана
2026-08-06-driving-coach-phase1.md). До калибровки фича выключена по
умолчанию: `driving_coach_enabled=False`.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.coach_ai.models import CornerMistake

# ── Пороги (НЕ откалиброваны, см. Task 13) ───────────────────────────────────
LOCKUP_SLIP = -0.25        # slip_ratio ниже этого при нажатом тормозе
LOCKUP_MIN_BRAKE_PCT = 20.0
WHEELSPIN_SLIP = 0.20      # slip_ratio выше этого при открытом газе
WHEELSPIN_MIN_THROTTLE_PCT = 40.0
UNDERSTEER_SLIP_ANGLE = 0.12       # передние, рад
UNDERSTEER_MIN_STEER = 0.25        # |steer|, доля хода руля
UNDERSTEER_MAX_YAW_RATE = 0.10     # кузов не доворачивает, рад/с
OVERSTEER_SLIP_ANGLE = 0.15        # задние, рад
MIN_EVENT_DURATION_S = 0.20        # короче — шум подвески, не потеря сцепления

_REAR = ("rl", "rr")
_FRONT = ("fl", "fr")


@dataclass
class _Ongoing:
    kind: str
    wheel: str | None
    started_at: float
    peak: float
    corner_id: int | None
    corner_name: str | None
    phase: str
    lap: int
    speed_kmh: int | None


class SlipDetector:
    """Один экземпляр на сессию. `tick()` зовётся на каждом MotionEx."""

    def __init__(self) -> None:
        self._ongoing: dict[str, _Ongoing] = {}

    def reset(self) -> None:
        """Смена сессии/флэшбек — незакрытые события выбрасываются, а не
        дозакрываются: их место на трассе уже неактуально."""
        self._ongoing.clear()

    def tick(
        self,
        frame: dict,
        now: float,
        lap: int,
        corner_id: int | None,
        corner_name: str | None,
        phase: str,
    ) -> CornerMistake | None:
        """Один кадр. Возвращает завершённую ошибку или None.

        За тик закрывается не более одной ошибки — этого достаточно: кадры
        идут с частотой пакета, и второе событие закроется на следующем.
        """
        finished: CornerMistake | None = None
        for kind, wheel, magnitude in self._candidates(frame):
            if magnitude is None:
                done = self._close(kind, now)
                if done is not None and finished is None:
                    finished = done
                continue
            cur = self._ongoing.get(kind)
            if cur is None:
                self._ongoing[kind] = _Ongoing(
                    kind=kind, wheel=wheel, started_at=now, peak=magnitude,
                    corner_id=corner_id, corner_name=corner_name, phase=phase,
                    lap=lap, speed_kmh=frame.get("speed_kmh"),
                )
            elif magnitude > cur.peak:
                cur.peak = magnitude
                cur.wheel = wheel
        return finished

    def _close(self, kind: str, now: float) -> CornerMistake | None:
        cur = self._ongoing.pop(kind, None)
        if cur is None:
            return None
        duration = now - cur.started_at
        if duration < MIN_EVENT_DURATION_S:
            return None
        return CornerMistake(
            kind=cur.kind, wheel=cur.wheel, corner_id=cur.corner_id,
            corner_name=cur.corner_name, phase=cur.phase, lap=cur.lap,
            peak=round(cur.peak, 3), duration_s=round(duration, 2),
            speed_kmh=cur.speed_kmh,
        )

    def _candidates(self, frame: dict):
        """(вид, колесо, величина) по каждому виду ошибки; величина None —
        сейчас не срывает."""
        ratio = frame.get("slip_ratio") or {}
        angle = frame.get("slip_angle") or {}
        brake = frame.get("brake_pct") or 0.0
        throttle = frame.get("throttle_pct") or 0.0
        steer = frame.get("steer") or 0.0
        yaw = frame.get("yaw_rate") or 0.0

        yield ("lockup", *_worst(
            ratio, lambda v: v <= LOCKUP_SLIP and brake >= LOCKUP_MIN_BRAKE_PCT,
            key=lambda v: -v))
        yield ("wheelspin", *_worst(
            {w: ratio.get(w, 0.0) for w in _REAR},
            lambda v: v >= WHEELSPIN_SLIP and throttle >= WHEELSPIN_MIN_THROTTLE_PCT,
            key=lambda v: v))

        front = max((abs(angle.get(w, 0.0)) for w in _FRONT), default=0.0)
        rear = max((abs(angle.get(w, 0.0)) for w in _REAR), default=0.0)

        understeer = (
            front >= UNDERSTEER_SLIP_ANGLE
            and front > rear
            and abs(steer) >= UNDERSTEER_MIN_STEER
            and abs(yaw) <= UNDERSTEER_MAX_YAW_RATE
        )
        yield ("understeer", None, front if understeer else None)

        counter_steering = steer * yaw < 0
        oversteer = (
            rear >= OVERSTEER_SLIP_ANGLE and rear > front and counter_steering
        )
        yield ("oversteer", None, rear if oversteer else None)


def _worst(values: dict, predicate, key):
    """Худшее колесо среди сработавших: (колесо, величина) или (None, None)."""
    hits = [(w, v) for w, v in values.items() if predicate(v)]
    if not hits:
        return None, None
    wheel, value = max(hits, key=lambda wv: key(wv[1]))
    return wheel, abs(value)
```

- [ ] **Step 4: Прогнать тесты**

Run: `python -m pytest tests/test_coach_slip.py -v`
Expected: PASS, 8 passed

---

## Task 6: Детектор выезда за пределы

**Files:**
- Modify: `core/coach_ai/slip.py`
- Test: `tests/test_coach_slip.py` (дописать)

Выезд принципиально отличается от срывов: он определяется не проскальзыванием, а покрытием, и у него другое условие «сколько колёс». Логика — в том же автомате, чтобы правило «событие закрывается по окончании» было одно на все виды.

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_coach_slip.py`:

```python
def test_two_wheels_off_track_is_reported():
    d = SlipDetector()
    off = _frame(surface={"rl": "grass", "rr": "tarmac",
                          "fl": "grass", "fr": "tarmac"})
    _feed(d, off, seconds=0.4, phase="exit")
    events = _feed(d, _frame(), seconds=0.1)
    assert len(events) == 1
    assert events[0].kind == "offtrack"
    assert events[0].wheel is None


def test_one_wheel_off_track_is_not_reported():
    d = SlipDetector()
    off = _frame(surface={"rl": "tarmac", "rr": "tarmac",
                          "fl": "grass", "fr": "tarmac"})
    _feed(d, off, seconds=0.4)
    assert _feed(d, _frame(), seconds=0.1) == []


def test_rumble_strip_is_not_off_track():
    d = SlipDetector()
    kerb = _frame(surface={"rl": "rumble_strip", "rr": "rumble_strip",
                           "fl": "rumble_strip", "fr": "rumble_strip"})
    _feed(d, kerb, seconds=0.5)
    assert _feed(d, _frame(), seconds=0.1) == []
```

- [ ] **Step 2: Прогнать тест, убедиться что падает**

Run: `python -m pytest tests/test_coach_slip.py -k off_track -v`
Expected: FAIL — событий нет

- [ ] **Step 3: Реализовать**

В `core/coach_ai/slip.py` добавить импорт и порог:

```python
from core.packets import SURFACE_ON_TRACK

OFFTRACK_MIN_WHEELS = 2    # поребрик за выезд не считается
```

В конец `_candidates`, после ветки `oversteer`, добавить:

```python
        surface = frame.get("surface") or {}
        off_wheels = sum(
            1 for s in surface.values() if s not in SURFACE_ON_TRACK and s != "unknown"
        )
        yield ("offtrack", None,
               float(off_wheels) if off_wheels >= OFFTRACK_MIN_WHEELS else None)
```

- [ ] **Step 4: Прогнать тесты**

Run: `python -m pytest tests/test_coach_slip.py -v`
Expected: PASS, 11 passed

---

## Task 7: Буфер круга и правило «три из пяти»

**Files:**
- Create: `core/coach_ai/corner_log.py`
- Test: `tests/test_coach_corner_log.py` (создать)

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_coach_corner_log.py`:

```python
"""Буфер ошибок по кругам: что уезжает в дебриф и что имеет право
прозвучать вживую."""
from core.coach_ai.corner_log import CornerLog
from core.coach_ai.models import CornerMistake


def _m(lap, kind="lockup", corner_id=3, phase="braking", wheel="fl", peak=0.5):
    return CornerMistake(kind=kind, wheel=wheel, corner_id=corner_id,
                         corner_name=f"Turn {corner_id}", phase=phase, lap=lap,
                         peak=peak, duration_s=0.3, speed_kmh=180)


def test_single_mistake_never_triggers_live_advice():
    log = CornerLog()
    assert log.add(_m(1)) is None


def test_three_of_last_five_laps_triggers_advice():
    log = CornerLog()
    assert log.add(_m(1)) is None
    assert log.add(_m(2)) is None
    advice = log.add(_m(3))
    assert advice is not None
    assert advice.kind == "lockup"
    assert advice.corner_id == 3
    assert advice.wheel == "fl"


def test_same_lap_repeats_do_not_count_as_separate_laps():
    """Три блокировки на одном круге — это один круг, а не три."""
    log = CornerLog()
    log.add(_m(1))
    log.add(_m(1))
    assert log.add(_m(1)) is None


def test_mistakes_spread_beyond_five_laps_do_not_trigger():
    log = CornerLog()
    log.add(_m(1))
    log.add(_m(4))
    assert log.add(_m(9)) is None


def test_different_corners_are_tracked_separately():
    log = CornerLog()
    log.add(_m(1, corner_id=3))
    log.add(_m(2, corner_id=7))
    assert log.add(_m(3, corner_id=3)) is None


def test_advice_is_not_repeated_for_the_same_signature_too_soon():
    log = CornerLog()
    log.add(_m(1)); log.add(_m(2))
    assert log.add(_m(3)) is not None
    assert log.add(_m(4)) is None, "подряд второй раз о том же — молчим"


def test_all_mistakes_are_kept_for_the_debrief_map():
    log = CornerLog()
    log.add(_m(1)); log.add(_m(1)); log.add(_m(2, corner_id=7))
    rows = log.map_rows()
    assert len(rows) == 3
    assert {r["corner_id"] for r in rows} == {3, 7}


def test_top_corners_ranked_by_count():
    log = CornerLog()
    for lap in (1, 2, 3):
        log.add(_m(lap, corner_id=3))
    log.add(_m(1, corner_id=7))
    top = log.top_corners(limit=2)
    assert top[0]["corner_id"] == 3
    assert top[0]["count"] == 3
    assert top[1]["corner_id"] == 7


def test_reset_clears_everything():
    log = CornerLog()
    log.add(_m(1))
    log.reset()
    assert log.map_rows() == []
```

- [ ] **Step 2: Прогнать тест, убедиться что падает**

Run: `python -m pytest tests/test_coach_corner_log.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.coach_ai.corner_log'`

- [ ] **Step 3: Реализовать**

Создать `core/coach_ai/corner_log.py`:

```python
"""
core/coach_ai/corner_log.py
============================
Копилка ошибок пилотажа за сессию. Два разных потребителя с намеренно
разными правилами:

  дебриф   — ВСЁ, включая одиночные срывы: экран после сессии никого не
             перебивает;
  эфир     — только повтор (REPEAT_LAPS из последних WINDOW_LAPS кругов):
             разовый срыв пилот почувствовал сам, а комментировать каждый —
             это ровно та жалоба «говорит без остановки», которую в этом
             проекте чинили дважды с разных сторон.

Модуль решает, ЧТО повторяется. Каким словом это сказать — банк
`core/radio/phrases.py`; когда это можно озвучить — радио-конвейер.
"""
from __future__ import annotations

from core.coach_ai.models import CornerMistake

WINDOW_LAPS = 5
REPEAT_LAPS = 3
#: Сколько кругов молчать об уже озвученной проблеме. Пилот не успеет
#: исправить привычку за один круг, а повтор совета раздражает быстрее, чем
#: помогает.
ADVICE_COOLDOWN_LAPS = 5


class CornerLog:
    def __init__(self) -> None:
        self._all: list[CornerMistake] = []
        self._laps_by_signature: dict[tuple, list[int]] = {}
        self._advised_on_lap: dict[tuple, int] = {}

    def reset(self) -> None:
        self._all.clear()
        self._laps_by_signature.clear()
        self._advised_on_lap.clear()

    def add(self, mistake: CornerMistake) -> CornerMistake | None:
        """Записать ошибку. Вернуть её же, если пора сказать вживую."""
        self._all.append(mistake)
        sig = mistake.signature()
        laps = self._laps_by_signature.setdefault(sig, [])
        if mistake.lap not in laps:
            laps.append(mistake.lap)

        recent = [l for l in laps if mistake.lap - l < WINDOW_LAPS]
        if len(recent) < REPEAT_LAPS:
            return None

        last_advised = self._advised_on_lap.get(sig)
        if last_advised is not None and mistake.lap - last_advised < ADVICE_COOLDOWN_LAPS:
            return None

        self._advised_on_lap[sig] = mistake.lap
        return mistake

    def map_rows(self) -> list[dict]:
        """Плоская карта для дебрифа и архива — ВСЕ ошибки без фильтра."""
        return [
            {
                "lap": m.lap, "corner_id": m.corner_id, "corner_name": m.corner_name,
                "kind": m.kind, "wheel": m.wheel, "phase": m.phase,
                "peak": m.peak, "duration_s": m.duration_s, "speed_kmh": m.speed_kmh,
            }
            for m in self._all
        ]

    def top_corners(self, limit: int = 3) -> list[dict]:
        """Самые проблемные повороты по числу ошибок."""
        counts: dict[int | None, dict] = {}
        for m in self._all:
            row = counts.setdefault(m.corner_id, {
                "corner_id": m.corner_id, "corner_name": m.corner_name,
                "count": 0, "kinds": {},
            })
            row["count"] += 1
            row["kinds"][m.kind] = row["kinds"].get(m.kind, 0) + 1
        ranked = sorted(counts.values(), key=lambda r: -r["count"])
        return ranked[:limit]
```

- [ ] **Step 4: Прогнать тесты**

Run: `python -m pytest tests/test_coach_corner_log.py -v`
Expected: PASS, 9 passed

---

## Task 8: Настройка `driving_coach_enabled`

**Files:**
- Modify: `core/settings.py` (`DEFAULTS`)
- Test: `tests/test_settings.py` (дописать)

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_settings.py`:

```python
def test_driving_coach_disabled_by_default():
    """Пороги детекторов до живой калибровки не проверены, а коуч, который
    может назвать не то колесо, хуже выключенного."""
    assert s.DEFAULTS["driving_coach_enabled"] is False


def test_driving_coach_flag_survives_save_and_load(isolate):
    s.save({**s.DEFAULTS, "driving_coach_enabled": True})
    assert s.load()["driving_coach_enabled"] is True
```

`isolate` — существующая фикстура этого файла (`tests/test_settings.py:9`), подменяющая `s._PATH` на `tmp_path`; второй способ изоляции не заводить. Модуль импортирован там как `s`.

- [ ] **Step 2: Прогнать тест, убедиться что падает**

Run: `python -m pytest tests/test_settings.py -k driving_coach -v`
Expected: FAIL — `KeyError: 'driving_coach_enabled'`

- [ ] **Step 3: Реализовать**

В `core/settings.py::DEFAULTS`, рядом с `engineer_chatter_enabled`, добавить:

```python
    # Подсказки по ПИЛОТАЖУ (блокировка, пробуксовка, снос, занос, выезд).
    # Отдельный тумблер, а не часть engineer_chatter_enabled: держать инженера
    # тихим, а подсказки по вождению включёнными — осмысленное сочетание, это
    # разные потребности. Выключено по умолчанию, пока пороги детекторов не
    # откалиброваны на живой сессии (см. план 2026-08-06-driving-coach-phase1).
    "driving_coach_enabled":    False,
```

- [ ] **Step 4: Прогнать тесты**

Run: `python -m pytest tests/test_settings.py -v`
Expected: PASS

---

## Task 9: Фразы `coach.*`

**Files:**
- Modify: `core/radio/phrases.py` (реестр, после блока `track_limits.warning` :258)
- Test: `tests/test_radio_phrases.py` (дописать — именно он держит инварианты этого банка; `tests/test_phrases.py` относится к пулам `commentator/`, не сюда)

Инварианты банка, которые тест уже проверяет для остальных спек и обязан проверить для этих: не меньше шести вариантов у небоевой спеки, у всех вариантов одной спеки одно `action`, длина в пределах `MAX_WORDS_NORMAL`.

Сторона колеса — **отдельная спека**, а не переменная в пуле: «переднее левое» и «переднее правое» требуют разных действий пилота, и выбор не должен делать колода.

- [ ] **Step 1: Написать падающий тест**

Дописать в тест-файл банка:

```python
COACH_CODES = [
    "coach.lockup_front_left", "coach.lockup_front_right",
    "coach.wheelspin", "coach.understeer", "coach.oversteer", "coach.offtrack",
]


def test_coach_specs_exist():
    for code in COACH_CODES:
        assert code in phrases.codes(), code


def test_coach_specs_have_enough_variants():
    for code in COACH_CODES:
        assert len(phrases.spec_for(code).variants) >= 6, code


def test_coach_specs_are_never_critical():
    """Подсказка по пилотажу не имеет права перебивать споттера или box-call."""
    for code in COACH_CODES:
        assert phrases.spec_for(code).urgency != policy.URGENCY_CRITICAL, code


def test_lockup_sides_are_separate_specs_not_one_pool():
    left = phrases.spec_for("coach.lockup_front_left")
    right = phrases.spec_for("coach.lockup_front_right")
    assert left.action != right.action
```

Доступ к спеке — `phrases.spec_for(code)` (`core/radio/phrases.py:1465`), перечень кодов — `phrases.codes()` (:1625).

- [ ] **Step 2: Прогнать тест, убедиться что падает**

Run: `python -m pytest tests/test_radio_phrases.py -k coach -v`
Expected: FAIL — `KeyError: 'coach.lockup_front_left'` из `spec_for`

- [ ] **Step 3: Реализовать**

В `core/radio/phrases.py`, после спеки `track_limits.warning` (:258), добавить:

```python
    # ── Подсказки по пилотажу (коуч, фаза 1) ─────────────────────────────────
    # Звучат ТОЛЬКО на повторяющейся ошибке (core/coach_ai/corner_log.py) и
    # никогда не критические: перебивать споттера подсказкой по вождению
    # нельзя. Сторона колеса — отдельная спека, а не переменная в пуле: «левое»
    # и «правое» требуют разных действий, выбор не должен делать колода.
    _spec("coach.lockup_front_left", _N, (
        "Блокируешь переднее левое, тормози мягче.",
        "Переднее левое встаёт под тормозом.",
        "Левое переднее блокируется, сними давление.",
        "Опять переднее левое в блокировке.",
        "Переднее левое теряет сцепление на торможении.",
        "Плавнее на педаль — переднее левое встаёт.",
    ), action="coach_lockup_fl"),
    _spec("coach.lockup_front_right", _N, (
        "Блокируешь переднее правое, тормози мягче.",
        "Переднее правое встаёт под тормозом.",
        "Правое переднее блокируется, сними давление.",
        "Опять переднее правое в блокировке.",
        "Переднее правое теряет сцепление на торможении.",
        "Плавнее на педаль — переднее правое встаёт.",
    ), action="coach_lockup_fr"),
    _spec("coach.wheelspin", _N, (
        "Пробуксовка на выходе, газ плавнее.",
        "Задние срываются, добавляй газ позже.",
        "Теряешь тягу на выходе, аккуратнее с педалью.",
        "Буксуешь на выходе из поворота.",
        "Задняя ось скользит под газом.",
        "Раньше времени открываешь газ — буксует.",
    ), action="coach_wheelspin"),
    _spec("coach.understeer", _N, (
        "Сносит наружу, входи медленнее.",
        "Передок не идёт в поворот, сбрось на входе.",
        "Недостаточная поворачиваемость, сбавь на входе.",
        "Машина не доворачивает, тормози чуть раньше.",
        "Сносит передней осью в этом повороте.",
        "Слишком быстро на входе — сносит наружу.",
    ), action="coach_understeer"),
    _spec("coach.oversteer", _N, (
        "Задняя ось гуляет, аккуратнее.",
        "Ловишь занос, мягче на выходе.",
        "Избыточная поворачиваемость в этом повороте.",
        "Зад срывается, плавнее руль и газ.",
        "Машину разворачивает на выходе.",
        "Занос на выходе, дай ей встать.",
    ), action="coach_oversteer"),
    _spec("coach.offtrack", _N, (
        "Выезжаешь за трассу, теряешь время.",
        "Опять двумя колёсами по траве.",
        "Уходишь с трассы на выходе.",
        "Держи машину в границах, так медленнее.",
        "Съезжаешь с полотна, это потеря времени.",
        "Не хватает места на выходе — сдержи машину.",
    ), action="coach_offtrack"),
```

- [ ] **Step 4: Прогнать тесты**

Run: `python -m pytest tests/test_radio_phrases.py -v`
Expected: PASS — включая существующие тесты СВОЙСТВ, которые обходят реестр целиком и автоматически применят к новым спекам ограничения длины и запрет LLM

---

## Task 10: Проводка в движок

**Files:**
- Modify: `core/engine.py` (импорты; `__init__` :334; `_consume_telemetry_delta` :3099; новый метод рядом с `_spotter_tick` :1505)
- Test: `tests/test_coach_wiring.py` (создать)

Это та задача, где живут самые дорогие баги проекта: корректное ядро есть, а наружу не уезжает. Тест проверяет весь путь — пакет → событие → спека.

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_coach_wiring.py`:

```python
"""Проводка коуча целиком: MotionEx -> детектор -> буфер -> реплика.

Зелёный юнит-тест детектора ничего не говорит о том, доехало ли до эфира,
поэтому здесь проверяется именно путь наружу.
"""
import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.coach_ai.models import CornerMistake


@pytest.fixture
def engine():
    """Тот же приём, что в tests/test_engine_damage.py: подменяем загрузку
    креденшелов, чтобы конструктор не лез в сеть. Здесь фикстура функциональная,
    а не модульная — тесты ниже мутируют settings и буфер коуча."""
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _mistake(lap, kind="lockup", wheel="fl", corner_id=3, phase="braking"):
    return CornerMistake(kind=kind, wheel=wheel, corner_id=corner_id,
                         corner_name=f"Turn {corner_id}", phase=phase, lap=lap,
                         peak=0.5, duration_s=0.3, speed_kmh=180)


def test_motion_ex_delta_reaches_the_coach_tick(engine, monkeypatch):
    seen = []
    monkeypatch.setattr(engine, "_coach_tick", lambda payload: seen.append(payload))
    from core.telemetry_adapters import TelemetryDelta

    engine._consume_telemetry_delta(
        TelemetryDelta("motion_ex", {"slip_ratio": {}}, 0, 25))

    assert seen == [{"slip_ratio": {}}]


def test_disabled_coach_publishes_nothing(engine, monkeypatch):
    engine.settings["driving_coach_enabled"] = False
    published = []
    monkeypatch.setattr(engine, "_publish_coach_advice", lambda m: published.append(m))
    monkeypatch.setattr(engine.coach_log, "add", lambda m: m)

    engine._emit_coach_advice(_mistake(3))

    assert published == []


def _capture(engine, monkeypatch):
    """Перехватить и публикацию, и рендер фразы.

    Черновик события НЕ несёт `phrase_code` — движок сразу превращает код в
    готовый текст через `_render_engineer_phrase` (см. хвост `_spotter_tick`),
    поэтому проверять надо именно с каким кодом позвали рендер."""
    drafts, codes = [], []
    monkeypatch.setattr(engine._commentary_events, "publish", drafts.append)
    monkeypatch.setattr(
        engine, "_render_engineer_phrase",
        lambda draft, code: codes.append(code) or "фраза")
    return drafts, codes


def test_repeated_mistake_publishes_expected_phrase_code(engine, monkeypatch):
    engine.settings["driving_coach_enabled"] = True
    drafts, codes = _capture(engine, monkeypatch)

    for lap in (1, 2, 3):
        engine._emit_coach_advice(_mistake(lap))

    assert codes == ["coach.lockup_front_left"]
    assert len(drafts) == 1
    assert drafts[0]["speaker"] == eng_mod.SPEAKER_ENGINEER
    assert drafts[0].get("priority") != "critical"
    assert drafts[0].get("bypass_speak_threshold") is not True


def test_offtrack_counted_as_track_limits_is_left_to_the_existing_tracker(
        engine, monkeypatch):
    """Засчитанная игрой срезка принадлежит TrackLimitsTracker. Коуч про неё
    молчит — иначе два объявления об одном инциденте, ровно то, что уже
    один раз чинили односторонней проверкой."""
    engine.settings["driving_coach_enabled"] = True
    drafts, _ = _capture(engine, monkeypatch)
    engine._note_track_limits_announcement(now=100.0)

    for lap in (1, 2, 3):
        engine._emit_coach_advice(_mistake(lap, kind="offtrack", wheel=None), now=100.5)

    assert drafts == []


def test_slip_mistakes_are_not_suppressed_by_track_limits(engine, monkeypatch):
    """Глушение относится ТОЛЬКО к выезду. Блокировка рядом с трек-лимитом —
    другая проблема и должна прозвучать."""
    engine.settings["driving_coach_enabled"] = True
    drafts, _ = _capture(engine, monkeypatch)
    engine._note_track_limits_announcement(now=100.0)

    for lap in (1, 2, 3):
        engine._emit_coach_advice(_mistake(lap), now=100.5)

    assert len(drafts) == 1
```

- [ ] **Step 2: Прогнать тест, убедиться что падает**

Run: `python -m pytest tests/test_coach_wiring.py -v`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute '_coach_tick'`

- [ ] **Step 3: Реализовать**

В `core/engine.py` добавить импорты рядом с существующим импортом `TrackManager` (:124):

```python
from core.coach_ai.corner_log import CornerLog
from core.coach_ai.slip import SlipDetector
```

Карта видов ошибок в коды банка — рядом с `_SPOTTER_EVENT_CODE`:

```python
# Вид ошибки коуча -> семантический код банка. Сторона колеса разводится
# здесь, а не внутри спеки: у левого и правого разные действия пилота.
_COACH_PHRASE_CODE = {
    ("lockup", "fl"): "coach.lockup_front_left",
    ("lockup", "fr"): "coach.lockup_front_right",
    ("wheelspin", None): "coach.wheelspin",
    ("understeer", None): "coach.understeer",
    ("oversteer", None): "coach.oversteer",
    ("offtrack", None): "coach.offtrack",
}
#: Выезд, засчитанный игрой как срезка, принадлежит TrackLimitsTracker.
#: Окно то же, что у симметричного глушения PENA в track_limits.py.
COACH_TRACK_LIMITS_SUPPRESSION_S = 5.0
```

В `F1Engine.__init__`, рядом с `self._track_manager = None` (:334):

```python
        self.coach_slip = SlipDetector()
        self.coach_log = CornerLog()
        self._last_track_limits_announcement_t = 0.0
```

В `_consume_telemetry_delta`, после ветки `motion` (:3099-3100):

```python
        elif delta.kind == "motion_ex":
            self._coach_tick(delta.payload)
```

Новые методы рядом с `_spotter_tick` (:1505):

```python
    def _coach_tick(self, motion_ex: dict) -> None:
        """Вызывается на каждом PACKET_MOTION_EX. Собирает кадр из MotionEx и
        уже разобранных вводов пилота (self._player_hud), привязывает его к
        повороту через track_ai и отдаёт детекторам.

        Гейтуется driving_coach_enabled ВНУТРИ _emit_coach_advice, а не здесь:
        карта ошибок для дебрифа собирается независимо от того, разрешена ли
        живая подсказка — экран после сессии никого не перебивает."""
        if not motion_ex:
            return
        track_ctx = None
        if self._track_manager and self._lap_distance_m is not None:
            track_ctx = self._track_manager.resolve(self._lap_distance_m)

        frame = {
            **motion_ex,
            "throttle_pct": self._player_hud.get("throttle_pct", 0.0),
            "brake_pct": self._player_hud.get("brake_pct", 0.0),
            "steer": self._player_hud.get("steer", 0.0),
            "speed_kmh": self._player_speed,
            "surface": self._player_surface,
        }
        mistake = self.coach_slip.tick(
            frame,
            now=time.time(),
            lap=self._player_lap or 0,
            corner_id=track_ctx.corner.id if track_ctx and track_ctx.corner else None,
            corner_name=track_ctx.corner.name if track_ctx and track_ctx.corner else None,
            phase=track_ctx.phase if track_ctx else "straight",
        )
        if mistake is not None:
            self._emit_coach_advice(mistake)

    def _note_track_limits_announcement(self, now: float) -> None:
        """Отметка, что о трек-лимитах только что объявили. Зовётся из той же
        точки, что и объявление TrackLimitsTracker."""
        self._last_track_limits_announcement_t = now

    def _emit_coach_advice(self, mistake, now: float | None = None) -> None:
        """Записать ошибку в карту сессии и, если она повторяется, озвучить."""
        now = time.time() if now is None else now
        repeat = self.coach_log.add(mistake)
        if repeat is None:
            return
        if not self._get_setting("driving_coach_enabled", False):
            return
        if (
            repeat.kind == "offtrack"
            and now - self._last_track_limits_announcement_t
            < COACH_TRACK_LIMITS_SUPPRESSION_S
        ):
            # Тот же инцидент уже объявлен как трек-лимит — второй раз молчим.
            return
        self._publish_coach_advice(repeat)

    def _publish_coach_advice(self, mistake) -> None:
        """Черновик события тем же путём, что у споттера (:1563): код банка
        превращается в текст ЗДЕСЬ, наружу уезжает готовая `phrase`.

        Ни `priority: critical`, ни `bypass_speak_threshold` — подсказка по
        пилотажу обязана уступать споттеру и box-call. Это два разных флага с
        разным смыслом, и коучу не положен ни один из них."""
        code = _COACH_PHRASE_CODE.get((mistake.kind, mistake.wheel))
        if code is None:
            # Неизвестное сочетание (например блокировка заднего) банку не
            # знакомо — промолчать безопаснее, чем сказать не то.
            return
        draft = {
            "event_code": "COACH_ADVICE",
            "speaker": SPEAKER_ENGINEER,
            "driver": "", "color": "#38BDF8",
            "corner": mistake.corner_name,
            "corner_id": mistake.corner_id,
        }
        draft["phrase"] = self._render_engineer_phrase(draft, code)
        self._commentary_events.publish(draft)
```

Атрибутов `self._player_speed` и `self._player_surface` в движке сейчас нет — завести их в `_apply_telemetry_delta` рядом с блоком `_hud_key` (:2179), по тому же принципу «сохраняем только непустое»:

```python
        if telem.get("speed") is not None:
            self._player_speed = telem["speed"]
        if telem.get("surface") is not None:
            self._player_surface = telem["surface"]
```

и инициализировать их в `__init__` (`self._player_speed: int | None = None`, `self._player_surface: dict = {}`) рядом с остальными полями игрока.

В точке, где движок объявляет предупреждение `TrackLimitsTracker`, добавить вызов `self._note_track_limits_announcement(time.time())`.

- [ ] **Step 4: Прогнать тесты**

Run: `python -m pytest tests/test_coach_wiring.py tests/test_engine_voice.py -v`
Expected: PASS

---

## Task 11: Карта ошибок в архив сессии

**Files:**
- Modify: `core/session_recorder.py`, `core/engine.py` (вызов `finalize`)
- Test: `tests/test_session_recorder_laps.py` (дописать — это существующий тест-файл рекордера; файла `test_session_recorder.py` в проекте нет)

`analytics/archive.py` править НЕ нужно: `save_game_session(data)` пишет переданный словарь как есть, без белого списка ключей.

- [ ] **Step 1: Написать падающий тест**

Дописать в `tests/test_session_recorder_laps.py`. Проверки finalize в этом файле пока нет, поэтому хелпер заводится здесь же — он перехватывает запись в архив вместо того, чтобы трогать реальный каталог `game_sessions/`:

```python
from core import session_recorder as rec_mod
from core.session_recorder import SessionRecorder


def _finalize_captured(rec, monkeypatch) -> dict:
    """Вызвать finalize, перехватив то, что ушло бы в архив.

    Живой каталог game_sessions/ тесты трогать не должны: один раз тест уже
    писал в боевые данные пользователя."""
    captured = {}

    def _fake_save(data: dict):
        captured.update(data)
        return None

    monkeypatch.setattr(rec_mod.archive, "save_game_session", _fake_save)
    rec.finalize(track_id=1, track_name="Bahrain", session_type="practice",
                 final_position=5, events=[])
    return captured


def test_finalize_stores_coach_map_and_top_corners(monkeypatch):
    rec = SessionRecorder()
    rec.on_lap_complete(lap_num=1, last_lap_ms=91000,
                        s1_ms=30000, s2_ms=31000, s3_ms=30000)
    rec.set_coach_map(
        rows=[{"lap": 1, "corner_id": 3, "corner_name": "Turn 3",
               "kind": "lockup", "wheel": "fl", "phase": "braking",
               "peak": 0.5, "duration_s": 0.3, "speed_kmh": 180}],
        top_corners=[{"corner_id": 3, "corner_name": "Turn 3",
                      "count": 1, "kinds": {"lockup": 1}}],
    )

    saved = _finalize_captured(rec, monkeypatch)

    assert saved["coach_map"][0]["corner_id"] == 3
    assert saved["coach_top_corners"][0]["count"] == 1


def test_finalize_without_coach_data_keeps_empty_lists(monkeypatch):
    """Сессия без коуча обязана сохраняться и читаться как раньше."""
    rec = SessionRecorder()
    rec.on_lap_complete(lap_num=1, last_lap_ms=91000,
                        s1_ms=30000, s2_ms=31000, s3_ms=30000)

    saved = _finalize_captured(rec, monkeypatch)

    assert saved["coach_map"] == []
    assert saved["coach_top_corners"] == []
```

- [ ] **Step 2: Прогнать тест, убедиться что падает**

Run: `python -m pytest tests/test_session_recorder_laps.py -k coach -v`
Expected: FAIL — `AttributeError: 'SessionRecorder' object has no attribute 'set_coach_map'`

- [ ] **Step 3: Реализовать**

В `core/session_recorder.py`:

```python
    def __init__(self):
        self._laps: list[dict] = []
        self._coach_map: list[dict] = []
        self._coach_top: list[dict] = []
        self._done = False

    def reset(self) -> None:
        self._laps = []
        self._coach_map = []
        self._coach_top = []
        self._done = False

    def set_coach_map(self, rows: list[dict], top_corners: list[dict]) -> None:
        """Карта ошибок пилотажа за сессию. Пишется целиком одним вызовом
        перед finalize — копилка живёт в core/coach_ai/corner_log.py, а не
        здесь: рекордер только сохраняет."""
        self._coach_map = list(rows)
        self._coach_top = list(top_corners)
```

В теле `finalize`, в словарь сохраняемых данных, добавить:

```python
            "coach_map": self._coach_map,
            "coach_top_corners": self._coach_top,
```

В `core/engine.py`, непосредственно перед вызовом `self.recorder.finalize(...)`, добавить:

```python
        self.recorder.set_coach_map(
            rows=self.coach_log.map_rows(),
            top_corners=self.coach_log.top_corners(),
        )
```

Там же, где движок сбрасывает состояние сессии (рядом с `self.recorder.reset()`), добавить `self.coach_log.reset()` и `self.coach_slip.reset()`.

- [ ] **Step 4: Прогнать тесты**

Run: `python -m pytest tests/test_session_recorder_laps.py -v`
Expected: PASS

---

## Task 12: UI — тумблер и блок дебрифа

**Files:**
- Modify: `NewSpotterUI/components/spotter/views/voice.tsx`
- Modify: `NewSpotterUI/components/spotter/views/debrief.tsx`
- Modify: `NewSpotterUI/lib/api.ts` (тип настроек)

- [ ] **Step 1: Добавить флаг в типы API**

В `NewSpotterUI/lib/api.ts`, в тип настроек, рядом с `engineer_chatter_enabled`:

```ts
  driving_coach_enabled: boolean
```

- [ ] **Step 2: Тумблер на экране «Голос»**

В `voice.tsx`, в панель микрофона (там же, где описана двусторонняя рация), добавить переключатель, подписанный честно — без обещаний того, чего система не делает:

```tsx
<Toggle
  checked={settings.driving_coach_enabled}
  onChange={(v) => update({ driving_coach_enabled: v })}
  label="Подсказки по пилотажу"
  hint="Инженер скажет о блокировке, пробуксовке, сносе, заносе или выезде — только если ошибка повторяется в одном и том же повороте. Разовый срыв не комментируется. Полный разбор всегда доступен в дебрифе."
/>
```

Компонент переключателя взять тот же, что используют соседние настройки этого экрана.

- [ ] **Step 3: Блок карты ошибок в дебрифе**

В `debrief.tsx` добавить секцию, читающую `coach_top_corners` и `coach_map` из данных сессии:

```tsx
{coachTopCorners.length > 0 && (
  <section>
    <h3>Где теряется время</h3>
    <ul>
      {coachTopCorners.map((c) => (
        <li key={c.corner_id ?? "none"}>
          <strong>{c.corner_name ?? "Вне поворота"}</strong>
          <span>{c.count} ошибк(и)</span>
          <span>{Object.entries(c.kinds).map(([k, n]) => `${KIND_RU[k] ?? k}: ${n}`).join(", ")}</span>
        </li>
      ))}
    </ul>
  </section>
)}
```

Со словарём рядом:

```tsx
const KIND_RU: Record<string, string> = {
  lockup: "блокировка",
  wheelspin: "пробуксовка",
  understeer: "снос",
  oversteer: "занос",
  offtrack: "выезд",
}
```

Пустой массив не должен рисовать заголовок: сессия без ошибок не повод показывать пустую таблицу. Разметку и классы взять из соседних секций этого файла, новый визуальный язык не изобретать.

- [ ] **Step 4: Проверить типы и собрать**

Run: `cd NewSpotterUI; pnpm exec tsc --noEmit`
Expected: чисто, без ошибок

Run: `cd NewSpotterUI; pnpm build`
Expected: сборка проходит

- [ ] **Step 5: Синхронизировать `webui/`**

Приложение отдаёт статику из `webui/`, а не из `NewSpotterUI/` — без этого шага готовая фича просто не доедет до пользователя.

Run: `robocopy NewSpotterUI\out webui /MIR`
Expected: exit code 1 или 3 (скопировано / скопировано + удалены лишние файлы прошлой сборки) — это успех, не ошибка

- [ ] **Step 6: Проверить, что новый текст доехал**

Run: `grep -r "Подсказки по пилотажу" webui | head -3`
Expected: непустой вывод

---

## Task 13: Живая калибровка порогов

**Files:**
- Modify: `core/coach_ai/slip.py` (пороги)
- Modify: `CONTEXT.md` (раздел «На чём остановились»)

Это единственная задача, которую нельзя выполнить без игры. До неё фича остаётся выключенной.

- [ ] **Step 1: Снять живой лог**

Run: `$env:SPOTTER_DIAG=1; python app.pyw`
Проехать 3–5 кругов практики с намеренными ошибками: заблокировать переднее в тяжёлом торможении, пробуксовать на выходе, снести машину на входе, поймать занос, выехать двумя колёсами.

- [ ] **Step 2: Сверить правдоподобие**

В `spotter.log` найти строки `DIAG motion_ex`. Проверить:
- на прямой с ровным газом все `slip_ratio` близки к нулю;
- при блокировке уходит в минус то колесо, которое реально дымило (сторона видна на повторе в игре);
- при пробуксовке в плюс уходят задние (`rl`/`rr`), а не передние;
- `yaw_rate` меняет знак при смене направления поворота.

Если знаки или колёса не совпадают — **раскладка неверна**, а не пороги: вернуться к Task 1 и сверить офсеты по спецификации EA F1 25 UDP, не подгоняя пороги под неправильные данные.

- [ ] **Step 3: Выставить пороги**

Подобрать `LOCKUP_SLIP`, `WHEELSPIN_SLIP`, `UNDERSTEER_SLIP_ANGLE`, `OVERSTEER_SLIP_ANGLE`, `MIN_EVENT_DURATION_S` по снятым значениям так, чтобы намеренные ошибки ловились, а чистые круги не давали ни одного события. В комментарии над блоком порогов заменить «НЕ откалиброваны» на дату и трассу калибровки.

- [ ] **Step 4: Включить по умолчанию**

Только после того, как чистый круг даёт ноль событий: в `core/settings.py` поменять `"driving_coach_enabled": False` на `True` и поправить тест `test_driving_coach_disabled_by_default` вместе с его обоснованием.

- [ ] **Step 5: Прогнать полный набор**

Run: `python -m pytest -q`
Expected: без падений; при расхождении сначала проверить `mtime` затронутых файлов — не пишет ли в них параллельная сессия

- [ ] **Step 6: Записать в CONTEXT.md**

Добавить запись сессии в «На чём остановились»: что сделано по файлам, на какой трассе калибровались пороги, что осталось (фазы 2 и 3), и обновить счётчик задач.
