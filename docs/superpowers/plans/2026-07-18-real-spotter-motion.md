# Настоящий споттер (car left/right) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Настоящая споттер-функция («Держи слева!»/«Держи справа!»/«Чисто.») —
через парсинг `PACKET_MOTION` (мировые координаты машин), которого сейчас
вообще нет в проекте.

**Architecture:** Дешёвый фильтр по `lap_distance_m` (расширение уже
существующего `parse_lap_data()` на все 22 машины) отсеивает, кто физически
близко на трассе прямо сейчас; для прошедших фильтр — точная сторона через
проекцию на вектор "право" игрока из нового `PACKET_MOTION`. Новый чистый
трекер `core/strategy_ai/spotter.py::SpotterTracker` (стиль
`DRSAdvisoryTracker` — edge-triggered, без I/O) + проводка в
`core/engine.py` как отдельная ветка `_telemetry_loop` (по образцу
`PACKET_PARTICIPANTS`/`PACKET_EVENT` — Motion не участвует в
`state["telemetry"]`, отдельный путь без `_update_telemetry`).

**Tech Stack:** Python 3.12, pytest.

**Спека:** `docs/superpowers/specs/2026-07-18-real-spotter-motion-design.md`.

**Проект НЕ под git** — шаги "Commit" опущены, как в предыдущих планах этого
проекта.

---

### Task 1: `core/packets.py` — `lap_distance_m` для всех 22 машин

**Files:**
- Modify: `core/packets.py:409-429` (`parse_lap_data`)
- Test: `tests/test_packets_gaps_tyre.py`

Офсет `+20` уже подтверждён для игрока в `parse_player_lap` (F1 25 LapData
спека, см. докстринг файла) — расширение на все 22 машины не добавляет
нового риска по офсетам, тот же приём, что уже применён для `pit_status`
(`test_parse_lap_data_pit_status_for_all_cars`).

- [ ] **Step 1: Написать падающий тест**

Добавить в `tests/test_packets_gaps_tyre.py` сразу после
`test_parse_lap_data_pit_status_for_all_cars` (строка 77):

```python
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
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `py -3.12 -u -m pytest tests/test_packets_gaps_tyre.py -k lap_distance_for_all_cars -v`
Expected: FAIL — `KeyError: 'lap_distances'`

- [ ] **Step 3: Реализация**

В `core/packets.py`, `parse_lap_data()` — полный текст функции с добавлением
(проверено чтением реального кода, единственные новые строки помечены):

```python
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
    lap_distances: dict[int, float | None] = {}   # НОВОЕ
    for idx in range(22):
        base = HEADER_SIZE + idx * LAP_DATA_SIZE
        if base + 35 > len(data):
            break
        positions[idx] = data[base + 32]  # m_carPosition
        laps[idx] = data[base + 33]       # m_currentLapNum
        pit_status[idx] = data[base + 34]  # m_pitStatus: 0=нет, 1=заезжает, 2=в пит-лейн
        gaps_front[idx] = _lap_delta_ms(data, base, 14, 16)
        val = struct.unpack_from("<f", data, base + 20)[0]   # НОВОЕ
        lap_distances[idx] = val if 0.0 <= val <= 10000.0 else None   # НОВОЕ
    leader_idx = next((i for i, p in positions.items() if p == 1), None)
    return {"positions": positions, "laps": laps, "pit_status": pit_status,
            "leader_idx": leader_idx, "gaps_front": gaps_front,
            "lap_distances": lap_distances}
```

- [ ] **Step 4: Запустить тесты снова**

Run: `py -3.12 -u -m pytest tests/test_packets_gaps_tyre.py -v`
Expected: PASS, все тесты файла зелёные

---

### Task 2: `core/packets.py` — парсинг `PACKET_MOTION`

**Files:**
- Modify: `core/packets.py` (новые константы + `_motion_fields`/`parse_motion_all`, DIAG-лог)
- Test: `tests/test_packets_motion.py` (новый)

Офсеты `CarMotionData` — реконструкция по публичному формату F1 UDP
(стабилен с F1 2020, структура НЕ версионируется, в отличие от
`ParticipantData`). Требуют той же живой сверки, что ERS/погода/трек-лимиты
(EA-PDF + независимый парсер + `SPOTTER_DIAG` — см. спеку, раздел
«Тестирование»); код безопасен и без подтверждения (диапазон X/Z разумно
ограничен, мусор не проходит в вычисления Задачи 5 без валидации).

- [ ] **Step 1: Написать падающие тесты**

```python
# tests/test_packets_motion.py
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
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `py -3.12 -u -m pytest tests/test_packets_motion.py -v`
Expected: FAIL — `ImportError: cannot import name 'MOTION_SIZE'`

- [ ] **Step 3: Реализация**

В `core/packets.py` — добавить константы рядом с остальными `PACKET_*`
(после `PACKET_CAR_DAMAGE = 10`, строка 31):

```python
PACKET_MOTION = 0
MOTION_SIZE = 60   # CarMotionData — см. golden-master в tests/test_packets_motion.py
```

Новые функции — добавить после `parse_car_damage_all` (конец файла):

```python
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
```

**Важно про DIAG:** лог по КАЖДОЙ машине (`idx=%d ...`) не троттлится — при
`SPOTTER_DIAG=1` это будет шумно (22 строки на каждый Motion-пакет,
~20-60 Гц). Это осознанно (нужна ПОЛНАЯ картина для живой сверки с мини-картой
игры — троттлинг скрыл бы момент, который сверяется), но верификация
офсетов должна проводиться короткими сессиями (несколько секунд), не
весь заезд — как и с трек-лимитами/погодой раньше.

- [ ] **Step 4: Запустить тесты снова**

Run: `py -3.12 -u -m pytest tests/test_packets_motion.py -v`
Expected: PASS, 5 passed

---

### Task 3: `core/strategy_ai/spotter.py::SpotterTracker`

**Files:**
- Create: `core/strategy_ai/spotter.py`
- Test: `tests/test_spotter.py`

- [ ] **Step 1: Написать падающие тесты**

```python
# tests/test_spotter.py
"""SpotterTracker — edge-triggered состояние (clear/left/right/both) из уже
готовых (lateral_abs_m, side) кандидатов. Анти-дребезг гасит только
ВОЗВРАТ фразы (не состояние) — та же конвенция, что у DRSAdvisoryTracker.
См. docs/superpowers/specs/2026-07-18-real-spotter-motion-design.md.
"""
from core.strategy_ai.spotter import (
    LATERAL_ENTER_M, LATERAL_EXIT_M, MIN_REPEAT_S, SpotterTracker,
    _LEFT_ENTER, _RIGHT_ENTER, _BOTH, _CLEAR,
)


def test_no_candidates_stays_clear_no_phrase():
    t = SpotterTracker()
    assert t.update([], now=100.0) is None


def test_enters_left():
    t = SpotterTracker()
    phrase = t.update([(2.0, "left")], now=100.0)
    assert phrase in _LEFT_ENTER


def test_enters_right():
    t = SpotterTracker()
    phrase = t.update([(2.0, "right")], now=100.0)
    assert phrase in _RIGHT_ENTER


def test_enters_both_sides_simultaneously():
    t = SpotterTracker()
    phrase = t.update([(2.0, "left"), (2.0, "right")], now=100.0)
    assert phrase in _BOTH


def test_stays_in_hysteresis_band_no_change():
    t = SpotterTracker()
    t.update([(2.0, "left")], now=100.0)                    # вошёл (<= ENTER)
    phrase = t.update([(3.0, "left")], now=101.0)            # между ENTER и EXIT
    assert phrase is None


def test_exits_to_clear_beyond_exit_threshold():
    t = SpotterTracker()
    t.update([(2.0, "left")], now=100.0)
    phrase = t.update([], now=110.0)   # далеко за MIN_REPEAT_S, чтобы не попасть под анти-дребезг
    assert phrase in _CLEAR


def test_direct_transition_left_to_right_without_intermediate_clear():
    t = SpotterTracker()
    t.update([(2.0, "left")], now=100.0)
    phrase = t.update([(2.0, "right")], now=110.0)
    assert phrase in _RIGHT_ENTER


def test_repeat_of_same_state_returns_none():
    t = SpotterTracker()
    t.update([(2.0, "left")], now=100.0)
    phrase = t.update([(2.1, "left")], now=110.0)   # всё ещё left, hysteresis не даёт выйти
    assert phrase is None


def test_anti_repeat_suppresses_second_transition_within_window():
    t = SpotterTracker()
    t.update([(2.0, "left")], now=100.0)              # вошёл слева
    phrase = t.update([], now=100.0 + MIN_REPEAT_S - 0.5)  # быстрый выход, внутри окна
    assert phrase is None


def test_anti_repeat_allows_transition_after_window():
    t = SpotterTracker()
    t.update([(2.0, "left")], now=100.0)
    t.update([], now=100.0 + MIN_REPEAT_S - 0.5)      # подавлено, но состояние истинно clear
    phrase = t.update([(2.0, "right")], now=100.0 + MIN_REPEAT_S + 0.5)
    assert phrase in _RIGHT_ENTER


def test_closest_candidate_on_each_side_decides_hysteresis():
    """Несколько кандидатов на одной стороне -> учитывается ближайший."""
    t = SpotterTracker()
    phrase = t.update([(5.0, "left"), (2.0, "left")], now=100.0)  # ближайший 2.0 <= ENTER
    assert phrase in _LEFT_ENTER


def test_reset_clears_state():
    t = SpotterTracker()
    t.update([(2.0, "left")], now=100.0)
    t.reset()
    phrase = t.update([], now=100.5)   # сразу после reset — не "выход", а исходное состояние
    assert phrase is None
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `py -3.12 -u -m pytest tests/test_spotter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.strategy_ai.spotter'`

- [ ] **Step 3: Реализация**

```python
"""
core/strategy_ai/spotter.py
=============================
Настоящий споттер: "Держи слева!"/"Держи справа!"/"Чисто." — из готовых
(lateral_abs_m, side) кандидатов, уже прошедших дешёвый продольный фильтр
по lap_distance в core/engine.py::_spotter_tick. Не парсит пакеты и не
занимается геометрией — pure edge-triggered состояние, тот же паттерн, что
DRSAdvisoryTracker.

Анти-дребезг (MIN_REPEAT_S) гасит только ВОЗВРАТ фразы, а не внутреннее
состояние (self._left/self._right) — состояние всегда остаётся правдивым
снимком текущей геометрии, устаревшим не бывает. _last_change_t
обновляется ТОЛЬКО когда переход реально объявлен (не на каждую
подавленную попытку) — иначе непрерывный дребезг быстрее MIN_REPEAT_S мог
бы бесконечно откладывать таймер и никогда ничего не объявить. Подавленный
переход НЕ откладывается, теряется навсегда, если состояние с тех пор не
изменилось снова — та же семантика, что у DRSAdvisoryTracker.

См. docs/superpowers/specs/2026-07-18-real-spotter-motion-design.md.
"""
from __future__ import annotations

import random

LONGITUDINAL_WINDOW_M = 6.0     # длина машины F1 + запас — НЕ откалибровано
LATERAL_ENTER_M = 2.5           # НЕ откалибровано, нужна живая проверка
LATERAL_EXIT_M = 4.0            # гистерезис, как ENTER/EXIT_GAP_MS у DRS
MIN_REPEAT_S = 3.0              # анти-дребезг на границе порога

_LEFT_ENTER = ["Держи слева!", "Машина слева, не закрывайся!", "Слева атакует."]
_RIGHT_ENTER = ["Держи справа!", "Машина справа, не закрывайся!", "Справа атакует."]
_BOTH = ["Машины с обеих сторон! Держи руль ровно."]
_CLEAR = ["Чисто.", "Свободно сзади и по бокам."]


class SpotterTracker:
    def __init__(self) -> None:
        self._left = False
        self._right = False
        self._last_change_t = 0.0

    def update(self, candidates: list[tuple[float, str]], now: float) -> str | None:
        """candidates: [(lateral_abs_m, side), ...] — только те, что уже
        прошли продольный фильтр (LONGITUDINAL_WINDOW_M) в engine.py.
        side: "left" | "right"."""
        left_dists = [d for d, s in candidates if s == "left"]
        right_dists = [d for d, s in candidates if s == "right"]
        prev_left, prev_right = self._left, self._right

        if left_dists and min(left_dists) <= LATERAL_ENTER_M:
            self._left = True
        elif not left_dists or min(left_dists) > LATERAL_EXIT_M:
            self._left = False

        if right_dists and min(right_dists) <= LATERAL_ENTER_M:
            self._right = True
        elif not right_dists or min(right_dists) > LATERAL_EXIT_M:
            self._right = False

        changed = (self._left, self._right) != (prev_left, prev_right)
        if not changed:
            return None
        if now - self._last_change_t < MIN_REPEAT_S:
            return None                     # подавлено — _last_change_t НЕ трогаем
        self._last_change_t = now

        if self._left and self._right:
            return random.choice(_BOTH)
        if self._left:
            return random.choice(_LEFT_ENTER)
        if self._right:
            return random.choice(_RIGHT_ENTER)
        return random.choice(_CLEAR)

    def reset(self) -> None:
        self._left = False
        self._right = False
        self._last_change_t = 0.0
```

- [ ] **Step 4: Запустить тесты снова**

Run: `py -3.12 -u -m pytest tests/test_spotter.py -v`
Expected: PASS, 12 passed

- [ ] **Step 5 (ДОБАВЛЕНО код-ревью): исправить общий анти-дребезг на раздельный по сторонам**

**Найден реальный баг в Step 3, не только стиль.** Общий `_last_change_t` на
КОМБИНИРОВАННОЕ состояние `(left, right)` может проглотить объявление о
НОВОЙ опасности с одной стороны только из-за недавнего перехода на ДРУГОЙ
стороне: t=0 машина слева → «Держи слева!» (`_last_change_t=0`); t=1 она
уходит, справа появляется другая машина → `changed=True`, но
`1-0=1 < MIN_REPEAT_S` → подавлено ОБЩИМ таймером, хотя причина подавления
не имеет отношения к новой опасности справа. Водитель слышит УСТАРЕВШУЮ и
уже НЕВЕРНУЮ команду («слева», хотя опасность теперь справа) — для
safety-функции хуже отсутствия объявления. Полное обоснование — см.
обновлённую спеку, раздел 3 «Ревизия после code-quality-ревью».

Написать падающий тест (добавить в `tests/test_spotter.py`):

```python
def test_cross_side_flip_within_window_still_announces_new_side():
    """Регрессия на найденный ревью баг: общий анти-дребезг на (left, right)
    не должен глушить НОВУЮ опасность с другой стороны только из-за
    недавнего перехода на ПЕРВОЙ. t=0 left входит и объявляется; t=1 (внутри
    MIN_REPEAT_S=3.0 от t=0) left выходит И right входит одновременно —
    right ДОЛЖЕН быть объявлен (его собственный анти-дребезг таймер свежий),
    несмотря на то что left только что менялся."""
    t = SpotterTracker()
    t.update([(2.0, "left")], now=100.0)                       # left входит, объявлено
    phrase = t.update([(2.0, "right")], now=100.5)             # left уходит, right входит
    assert phrase in _RIGHT_ENTER
```

Запустить: `py -3.12 -u -m pytest tests/test_spotter.py -k cross_side_flip -v`
Expected: FAIL — с исходной реализацией Step 3 вернёт `None` (подавлено
общим таймером), а не фразу из `_RIGHT_ENTER`.

Заменить класс `SpotterTracker` целиком на исправленную версию (раздельные
таймеры `_last_left_change_t`/`_last_right_change_t`, анти-дребезг
проверяется НЕЗАВИСИМО по стороне, фраза объявляется если хотя бы ОДНА
сторона прошла свою проверку — но всегда отражает ТЕКУЩЕЕ правдивое
комбинированное состояние, не то, что именно изменилось):

```python
class SpotterTracker:
    """Анти-дребезг (MIN_REPEAT_S) — НЕЗАВИСИМО по каждой стороне (см.
    docs/superpowers/specs/2026-07-18-real-spotter-motion-design.md, раздел
    3 «Ревизия после code-quality-ревью» — общий таймер на комбинированное
    состояние глушил новую опасность с другой стороны). Гасит только
    ВОЗВРАТ фразы, не внутреннее состояние — self._left/self._right всегда
    остаются правдивым снимком текущей геометрии. _last_left_change_t/
    _last_right_change_t обновляются ТОЛЬКО когда переход по ЭТОЙ стороне
    реально учтён в объявлении."""

    def __init__(self) -> None:
        self._left = False
        self._right = False
        self._last_left_change_t = 0.0
        self._last_right_change_t = 0.0

    def update(self, candidates: list[tuple[float, str]], now: float) -> str | None:
        """candidates: [(lateral_abs_m, side), ...] — только те, что уже
        прошли продольный фильтр (LONGITUDINAL_WINDOW_M) в engine.py.
        side: "left" | "right". Возвращает готовую фразу, если хотя бы одна
        сторона прошла свой анти-дребезг, либо None."""
        left_dists = [d for d, s in candidates if s == "left"]
        right_dists = [d for d, s in candidates if s == "right"]
        prev_left, prev_right = self._left, self._right

        if left_dists and min(left_dists) <= LATERAL_ENTER_M:
            self._left = True
        elif not left_dists or min(left_dists) > LATERAL_EXIT_M:
            self._left = False

        if right_dists and min(right_dists) <= LATERAL_ENTER_M:
            self._right = True
        elif not right_dists or min(right_dists) > LATERAL_EXIT_M:
            self._right = False

        left_changed = self._left != prev_left
        right_changed = self._right != prev_right

        left_announceable = left_changed and (now - self._last_left_change_t >= MIN_REPEAT_S)
        right_announceable = right_changed and (now - self._last_right_change_t >= MIN_REPEAT_S)

        if left_announceable:
            self._last_left_change_t = now
        if right_announceable:
            self._last_right_change_t = now

        if not (left_announceable or right_announceable):
            return None

        if self._left and self._right:
            return random.choice(_BOTH)
        if self._left:
            return random.choice(_LEFT_ENTER)
        if self._right:
            return random.choice(_RIGHT_ENTER)
        return random.choice(_CLEAR)

    def reset(self) -> None:
        self._left = False
        self._right = False
        self._last_left_change_t = 0.0
        self._last_right_change_t = 0.0
```

**Важно:** старые тесты, ссылавшиеся на поведение `_last_change_t` косвенно
(через сценарии подавления), должны остолись зелёными без изменений —
переименования атрибута НЕ затрагивает их (тесты не обращаются к приватным
полям напрямую, только к возвращаемому значению `update()`). Дополнительно
проверить вручную: `test_anti_repeat_suppresses_second_transition_within_window`
и `test_anti_repeat_allows_transition_after_window` — оба сценария меняют
ТОЛЬКО left (right остаётся пустым весь тест), поэтому раздельные таймеры
дают тот же результат, что и общий, для этих двух тестов; ничего чинить в
них не нужно.

Запустить: `py -3.12 -u -m pytest tests/test_spotter.py -v`
Expected: PASS, 13 passed (12 исходных + 1 новый регрессионный)

---

### Task 4: `commentator/planner.py` — таблица важности

**Files:**
- Modify: `commentator/planner.py:45-65` (`_BASE_IMPORTANCE`)

Не TDD-задача (константы, не поведение) — изменить таблицу и прогнать
существующие тесты планировщика на регрессию.

- [ ] **Step 1: Зафиксировать baseline**

Run: `py -3.12 -u -m pytest tests/test_planner.py -v`
Expected: все тесты проходят — записать точное число для сравнения.

- [ ] **Step 2: Добавить записи в `_BASE_IMPORTANCE`**

```python
_BASE_IMPORTANCE: dict[str, int] = {
    "COLL": 90, "RTMT": 90,
    "PENA": 88, "RCWN": 88, "CHQF": 88,
    "OVTK": 60,
    "FTLP": 55,
    "DAMAGE_WING": 65, "DAMAGE_FLOOR": 65, "DAMAGE_GEARBOX": 65, "DAMAGE_ENGINE": 65,
    "F1_BENCH": 55, "CAREER_PB": 55,
    "F1_SECTOR_BENCH": 45, "CAREER_SECTOR_PB": 45,
    "SSTA": 70, "STLG": 70,
    "SEND": 40,
    "TMPT": 30, "SPTP": 30, "DRSE": 30, "DRSD": 30,
    "FLBK": 25,
    "AMBIENT": 20,
    "PIT_EXIT": 65,
    "DRS_PROXIMITY_ENTER": 30, "DRS_PROXIMITY_EXIT": 30,
    "DRS_ALLOWED_ON": 30, "DRS_ALLOWED_OFF": 30,
    "DRS_PROXIMITY_ENTER_AND_ALLOWED": 30,
    "POSITION_CALL": 55, "POSITION_CALL_OWN_PIT": 55,
    "LEADER_CHANGE": 55,
    "PIT_WINDOW_APPROACH": 55,
    "SPOTTER_CAR_LEFT": 70, "SPOTTER_CAR_RIGHT": 70,
    "SPOTTER_CAR_BOTH": 70, "SPOTTER_CLEAR": 70,
}
```
(Единственные новые строки — 4 записи `SPOTTER_*`; ничего существующего не
меняется в этой задаче.)

- [ ] **Step 3: Запустить тесты планировщика снова**

Run: `py -3.12 -u -m pytest tests/test_planner.py -v`
Expected: PASS, тот же набор тестов, что в baseline (0 regressions).

---

### Task 5: `core/engine.py` — проводка споттера

**Files:**
- Modify: `core/engine.py` (импорты, `__init__`, `_telemetry_loop`, новый метод `_spotter_tick`, `PACKET_LAP_DATA`-ветка, сброс x3)
- Test: `tests/test_engine_spotter.py` (новый)

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_engine_spotter.py
"""Проводка SpotterTracker в F1Engine: PACKET_MOTION -> _spotter_tick,
дешёвый фильтр по lap_distance (self._lap_distances, из PACKET_LAP_DATA)
отсекает дальние машины ДО геометрии, событие НЕ гейтуется
engineer_chatter_enabled (решение пользователя — безопасность, не болтовня).
См. docs/superpowers/specs/2026-07-18-real-spotter-motion-design.md.
"""
import struct

import pytest

import core.engine as eng_mod
from core.engine import F1Engine, SPEAKER_ENGINEER
from core.packets import HEADER_SIZE, MOTION_SIZE, LAP_DATA_SIZE, PACKET_LAP_DATA


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _drain(engine):
    drained = []
    while not engine.event_queue.empty():
        drained.append(engine.event_queue.get_nowait())
    return drained


def _lap_buf_with_distance(distances: dict[int, float]) -> bytes:
    buf = bytearray(HEADER_SIZE + 22 * LAP_DATA_SIZE)
    for idx, dist in distances.items():
        base = HEADER_SIZE + idx * LAP_DATA_SIZE
        struct.pack_into("<f", buf, base + 20, dist)
    return bytes(buf)


def _motion_buf(cars: dict[int, tuple[float, float, float, float]]) -> bytes:
    """cars: {idx: (world_x, world_z, right_x, right_z)} — right_* в диапазоне
    -1..1, конвертируется в int16 как в реальном пакете."""
    n = max(cars.keys()) + 1 if cars else 1
    buf = bytearray(HEADER_SIZE + n * MOTION_SIZE)
    for idx, (wx, wz, rx, rz) in cars.items():
        base = HEADER_SIZE + idx * MOTION_SIZE
        struct.pack_into("<f", buf, base + 0, wx)
        struct.pack_into("<f", buf, base + 8, wz)
        struct.pack_into("<h", buf, base + 30, int(rx * 32767))
        struct.pack_into("<h", buf, base + 34, int(rz * 32767))
    return bytes(buf)


def test_close_car_on_right_produces_spotter_event(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    engine._spotter.reset()
    _drain(engine)

    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf_with_distance({0: 100.0, 1: 101.0}))
    _drain(engine)

    # Игрок смотрит вдоль +Z (right = +X), соперник на +2м по X -> справа.
    from core.packets import parse_motion_all
    motion = _motion_buf({0: (0.0, 0.0, 1.0, 0.0), 1: (2.0, 0.0, 0.0, 0.0)})
    engine._spotter_tick(parse_motion_all(motion))

    drained = _drain(engine)
    found = [e for e in drained if e["event_code"] == "SPOTTER_CAR_RIGHT"]
    assert len(found) == 1
    assert found[0]["speaker"] == SPEAKER_ENGINEER
    assert found[0]["bypass_speak_threshold"] is True
    engine._spotter.reset()


def test_far_car_by_lap_distance_is_filtered_out_before_geometry(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    engine._spotter.reset()
    _drain(engine)

    # 50м по lap_distance — далеко за LONGITUDINAL_WINDOW_M, даже если по
    # мировым координатам эта машина оказалась бы геометрически "рядом".
    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf_with_distance({0: 100.0, 1: 150.0}))
    _drain(engine)

    motion = _motion_buf({0: (0.0, 0.0, 1.0, 0.0), 1: (2.0, 0.0, 0.0, 0.0)})
    from core.packets import parse_motion_all
    engine._spotter_tick(parse_motion_all(motion))

    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"].startswith("SPOTTER_")]
    engine._spotter.reset()


def test_chatter_disabled_does_not_suppress_spotter_event(engine):
    """Решение пользователя 2026-07-18: споттер — безопасность, не болтовня,
    как PENA/box-call. engineer_chatter_enabled=False НЕ должен гасить его."""
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = False
    engine._spotter.reset()
    _drain(engine)

    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf_with_distance({0: 100.0, 1: 101.0}))
    _drain(engine)

    from core.packets import parse_motion_all
    motion = _motion_buf({0: (0.0, 0.0, 1.0, 0.0), 1: (2.0, 0.0, 0.0, 0.0)})
    engine._spotter_tick(parse_motion_all(motion))

    drained = _drain(engine)
    assert [e for e in drained if e["event_code"] == "SPOTTER_CAR_RIGHT"]
    engine.settings["engineer_chatter_enabled"] = True
    engine._spotter.reset()


def test_no_player_in_motion_packet_is_noop(engine):
    engine._player_car_index = 5
    engine._spotter.reset()
    _drain(engine)

    from core.packets import parse_motion_all
    motion = _motion_buf({0: (0.0, 0.0, 1.0, 0.0)})   # индекс 5 отсутствует
    engine._spotter_tick(parse_motion_all(motion))

    assert _drain(engine) == []
    engine._player_car_index = 0


def test_flashback_resets_spotter(engine, monkeypatch):
    calls = []
    monkeypatch.setattr(engine._spotter, "reset", lambda: calls.append(True))
    engine._handle_flashback()
    assert calls == [True]
```

- [ ] **Step 2: Запустить тест, убедиться что падает**

Run: `py -3.12 -u -m pytest tests/test_engine_spotter.py -v`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute '_spotter'`

- [ ] **Step 3: Проводка в `core/engine.py`**

Импорт (рядом с `from core.strategy_ai.pit_window import detect_pit_window, PitWindowApproachTracker`,
строка 64) — сразу финальная версия (трекер + пороги/пулы фраз, нужные
`_spotter_tick` для классификации `event_code`):

```python
from core.strategy_ai.spotter import (
    SpotterTracker, LONGITUDINAL_WINDOW_M, _LEFT_ENTER, _RIGHT_ENTER, _BOTH, _CLEAR,
)
```

И расширить существующий импорт из `core.packets` (строки 26-34) —
добавить `parse_motion_all`, `PACKET_MOTION`:

```python
from core.packets import (
    parse_header, parse_participants, parse_event,
    parse_session, parse_lap_data, parse_player_lap,
    parse_player_telemetry, parse_player_status, parse_player_damage,
    parse_car_status_all, parse_car_damage_all, parse_motion_all,
    PACKET_PARTICIPANTS, PACKET_EVENT, PACKET_SESSION,
    PACKET_LAP_DATA, PACKET_CAR_TELEMETRY, PACKET_CAR_STATUS, PACKET_CAR_DAMAGE,
    PACKET_MOTION,
    HEADER_SIZE, TRACK_LIMITS_INFRINGEMENT_TYPES,
)
```

Инициализация в `__init__` (сразу после `self._pit_window_approach =
PitWindowApproachTracker()`, строка 242):

```python
        self._spotter = SpotterTracker()
        self._lap_distances: dict[int, float] = {}
```

Новая ветка в `_telemetry_loop` (сразу после блока `if packet_id in
(PACKET_SESSION, PACKET_LAP_DATA, PACKET_CAR_TELEMETRY, PACKET_CAR_STATUS,
PACKET_CAR_DAMAGE): self._update_telemetry(header, packet_id, data)`,
ПЕРЕД веткой `if packet_id == PACKET_PARTICIPANTS:` — проверено чтением
реального кода, тот же стиль отдельной ветки, что уже используют
Participants/Event, а не `_update_telemetry`, потому что Motion не
участвует в сборке `telem`/`state["telemetry"]`):

```python
            if packet_id == PACKET_MOTION:
                self._spotter_tick(parse_motion_all(data))
                continue
```

Новый приватный метод класса `F1Engine` (рядом с другими `_maybe_*`/`_*_tick`
методами, например после `_drs_advisory_tick`):

```python
    def _spotter_tick(self, motion_all: dict[int, dict]) -> None:
        """Вызывается на каждом PACKET_MOTION. self._lap_distances (из
        последнего PACKET_LAP_DATA) даёт дешёвый продольный фильтр ДО
        геометрии — считаем проекцию на player["right_x"]/["right_z"] только
        для машин, чей lap_distance близок к игроку. НЕ гейтуется
        engineer_chatter_enabled — решение пользователя 2026-07-18, споттер
        это безопасность (как PENA/box-call), не периодическая болтовня.
        См. spec 2026-07-18-real-spotter-motion-design.md."""
        player = motion_all.get(self._player_car_index)
        if player is None:
            return
        player_dist = self._lap_distances.get(self._player_car_index)
        if player_dist is None:
            return

        candidates: list[tuple[float, str]] = []
        for idx, m in motion_all.items():
            if idx == self._player_car_index:
                continue
            rival_dist = self._lap_distances.get(idx)
            if rival_dist is None:
                continue
            if abs(rival_dist - player_dist) > LONGITUDINAL_WINDOW_M:
                continue
            rel_x = m["world_x"] - player["world_x"]
            rel_z = m["world_z"] - player["world_z"]
            lateral = rel_x * player["right_x"] + rel_z * player["right_z"]
            side = "right" if lateral > 0 else "left"
            candidates.append((abs(lateral), side))

        phrase = self._spotter.update(candidates, time.time())
        if not phrase:
            return
        if phrase in _CLEAR:
            code = "SPOTTER_CLEAR"
        elif phrase in _BOTH:
            code = "SPOTTER_CAR_BOTH"
        elif phrase in _LEFT_ENTER:
            code = "SPOTTER_CAR_LEFT"
        else:
            code = "SPOTTER_CAR_RIGHT"
        self._enqueue_event({
            "event_code": code, "priority": "normal",
            "phrase": phrase, "speaker": SPEAKER_ENGINEER,
            "driver": "", "color": "#38BDF8",
            "bypass_speak_threshold": True,
        })
```

В `_update_telemetry`, ветка `PACKET_LAP_DATA` — добавить сразу после
существующей строки `self._positions = lap_info.get("positions", {})`
(строка 997, проверено чтением реального кода):

```python
            self._positions = lap_info.get("positions", {})
            self._lap_distances = lap_info.get("lap_distances", {})
```

Сброс на SSTA/CHQF/flashback (три существующие точки — строки 1441,
1893, 1919 после Task-правок предыдущих фич; вставить рядом с
`self._pit_window_approach.reset()` в каждой из трёх):

```python
self._spotter.reset()
```

- [ ] **Step 4: Запустить тест снова**

Run: `py -3.12 -u -m pytest tests/test_engine_spotter.py -v`
Expected: PASS, 5 passed

Затем полный прогон: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: 0 failed

---

## После реализации (не входит в эти задачи, уже отражено в task-очереди сессии)

- Живая проверка в игре: звучание фраз, калибровка
  `LATERAL_ENTER_M`/`LATERAL_EXIT_M`/`LONGITUDINAL_WINDOW_M`, сверка
  офсетов Motion через `SPOTTER_DIAG=1` с мини-картой HUD игры.
- Обновить `CONTEXT.md` (архитектурная схема + голосовой движок раздел не
  трогать, но добавить запись в «На чём остановились» и, при желании,
  строку в `core/strategy_ai/` список внутри схемы архитектуры) — правило 2
  CLAUDE.md, после закрытия этой фичи.
