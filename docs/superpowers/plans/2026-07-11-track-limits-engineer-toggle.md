# Трек-лимиты инженера + тумблер «болтовни» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Живые предупреждения «осторожно, трек-лимиты» до штрафа + причина уже
случившегося `PENA`, без дублирования; общий тумблер на периодическую
«болтовню» инженера (гэп-дайджест/ERS-советы/дождь/трек-лимиты), не
затрагивающий box-call и сам `PENA`.

**Architecture:** Новый чистый трекер `core/strategy_ai/track_limits.py`
(без I/O, стиль `box_call.py`). Два новых поля в `core/packets.py`
(`corner_cutting_warnings` из LapData, `infringement_type` из PENA-события) —
оба статически подтверждены двумя независимыми источниками. Проводка в
`core/engine.py`: обе новые реплики идут готовой строкой через
`event["phrase"]` в обход LLM/`commentator/templates.py` целиком (как уже
`ENGINEER_RAIN_ADVISORY`/`ENGINEER_GAP_DIGEST`). Новый ключ настроек
`engineer_chatter_enabled` гейтует 5 точек эмиссии.

**Tech Stack:** Python 3.12, pytest, TypeScript/React (NewSpotterUI).

**Спека:** `docs/superpowers/specs/2026-07-11-track-limits-engineer-toggle-design.md`.

**Важно — проект НЕ под git** (см. CONTEXT.md, решение 2026-07-09): шаги
"Commit" из шаблона плана опущены. После каждого таска просто переходим к
следующему.

---

### Task 1: `TrackLimitsTracker` — чистый трекер предупреждений

**Files:**
- Create: `core/strategy_ai/track_limits.py`
- Test: `tests/test_track_limits.py`

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_track_limits.py
"""TrackLimitsTracker — edge-triggered предупреждение по росту счётчика
m_cornerCuttingWarnings + подавление рядом с трек-лимитным PENA.
См. docs/superpowers/specs/2026-07-11-track-limits-engineer-toggle-design.md.
"""
from core.strategy_ai.track_limits import SUPPRESSION_WINDOW_S, TrackLimitsTracker


def test_first_tick_never_warns():
    t = TrackLimitsTracker()
    assert t.check_warning(count=1, now=100.0) is None


def test_warns_on_increase():
    t = TrackLimitsTracker()
    t.check_warning(count=1, now=100.0)
    phrase = t.check_warning(count=2, now=101.0)
    assert phrase == "Осторожно с лимитами трассы!"


def test_no_warning_on_same_count():
    t = TrackLimitsTracker()
    t.check_warning(count=1, now=100.0)
    assert t.check_warning(count=1, now=101.0) is None


def test_no_warning_on_decrease():
    t = TrackLimitsTracker()
    t.check_warning(count=3, now=100.0)
    assert t.check_warning(count=0, now=101.0) is None


def test_penalty_suppresses_warning_within_window():
    t = TrackLimitsTracker()
    t.check_warning(count=1, now=100.0)
    t.note_penalty(now=101.0)
    result = t.check_warning(count=2, now=101.0 + SUPPRESSION_WINDOW_S - 0.1)
    assert result is None


def test_warning_resumes_after_suppression_window():
    t = TrackLimitsTracker()
    t.check_warning(count=1, now=100.0)
    t.note_penalty(now=101.0)
    phrase = t.check_warning(count=2, now=101.0 + SUPPRESSION_WINDOW_S + 0.1)
    assert phrase == "Осторожно с лимитами трассы!"


def test_reset_clears_state():
    t = TrackLimitsTracker()
    t.check_warning(count=5, now=100.0)
    t.note_penalty(now=100.0)
    t.reset()
    assert t.check_warning(count=1, now=100.5) is None   # снова "первый тик"
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `py -3.12 -u -m pytest tests/test_track_limits.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'core.strategy_ai.track_limits'`

- [ ] **Step 3: Реализация**

```python
"""
core/strategy_ai/track_limits.py
==================================
Живое предупреждение "осторожно, трек-лимиты" по росту счётчика
m_cornerCuttingWarnings (LapData) — edge-triggered, без эскалации (в отличие
от box_call.py). Подавляется на SUPPRESSION_WINDOW_S после трек-лимитного
PENA — тот же инцидент не объявляется дважды (живое предупреждение + штраф).
См. docs/superpowers/specs/2026-07-11-track-limits-engineer-toggle-design.md.
"""
from __future__ import annotations

SUPPRESSION_WINDOW_S = 5.0

_WARNING_PHRASE = "Осторожно с лимитами трассы!"


class TrackLimitsTracker:
    """Отслеживает рост m_cornerCuttingWarnings игрока за сессию."""

    def __init__(self) -> None:
        self._last_count: int | None = None
        self._last_penalty_t: float = 0.0

    def check_warning(self, count: int, now: float) -> str | None:
        """Один тик LapData. count — текущее значение
        m_cornerCuttingWarnings. Возвращает готовую фразу при росте
        относительно предыдущего тика, иначе None."""
        prev, self._last_count = self._last_count, count
        if prev is None or count <= prev:
            return None
        if now - self._last_penalty_t < SUPPRESSION_WINDOW_S:
            return None
        return _WARNING_PHRASE

    def note_penalty(self, now: float) -> None:
        """Вызывается при трек-лимитном PENA игрока — открывает окно
        подавления живых предупреждений про тот же инцидент."""
        self._last_penalty_t = now

    def reset(self) -> None:
        self._last_count = None
        self._last_penalty_t = 0.0
```

- [ ] **Step 4: Запустить тест снова**

Run: `py -3.12 -u -m pytest tests/test_track_limits.py -v`
Expected: PASS, 7 passed

---

### Task 2: `core/packets.py` — поле `corner_cutting_warnings`

**Files:**
- Modify: `core/packets.py:425-465` (`parse_player_lap`)
- Test: `tests/test_packets_gaps_tyre.py`

Офсет 40 (uint8) в `LapData` статически подтверждён 2026-07-11 независимым
источником (github.com/MacManley/f1-25-udp), совпадает байт-в-байт с уже
подтверждёнными `m_carPosition@32`/`m_currentLapNum@33`/`m_pitStatus@34`.

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/test_packets_gaps_tyre.py`:

```python
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
```

- [ ] **Step 2: Запустить тесты, убедиться, что падают**

Run: `py -3.12 -u -m pytest tests/test_packets_gaps_tyre.py -k corner_cutting -v`
Expected: FAIL — `KeyError: 'corner_cutting_warnings'` (поле ещё не добавлено)

- [ ] **Step 3: Добавить поле в `parse_player_lap`**

В `core/packets.py`, внутри `parse_player_lap` (после блока `lap_distance_m`,
перед `return {...}`, ~строка 449):

```python
    corner_cutting_warnings: int | None = None
    if base + 41 <= len(data):
        # m_cornerCuttingWarnings @40 (uint8) — сверено с независимым парсером
        # github.com/MacManley/f1-25-udp (2026-07-11), совпадает с уже
        # подтверждёнными m_carPosition@32/m_currentLapNum@33/m_pitStatus@34.
        corner_cutting_warnings = data[base + 40]
```

И добавить ключ в возвращаемый словарь (рядом с `"lap_distance_m"`):

```python
        "lap_distance_m": lap_distance_m,
        "corner_cutting_warnings": corner_cutting_warnings,
```

- [ ] **Step 4: Запустить тесты снова**

Run: `py -3.12 -u -m pytest tests/test_packets_gaps_tyre.py -v`
Expected: PASS, все тесты файла зелёные

---

### Task 3: `core/packets.py` — `infringement_type` в PENA + классификация

**Files:**
- Modify: `core/packets.py:117` (константа), `core/packets.py:274-282` (`parse_event`)
- Test: `tests/test_packets_gaps_tyre.py`

Восемь кодов трек-лимитной семьи `{7, 8, 9, 25, 26, 27, 28, 29}` подтверждены
2026-07-11 двумя независимыми источниками (EA-спека F1 25 через веб-поиск +
github.com/MacManley/f1-25-udp).

- [ ] **Step 1: Написать падающие тесты**

Добавить в `tests/test_packets_gaps_tyre.py`:

```python
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
```

- [ ] **Step 2: Запустить тесты, убедиться, что падают**

Run: `py -3.12 -u -m pytest tests/test_packets_gaps_tyre.py -k "infringement" -v`
Expected: FAIL — `KeyError: 'infringement_type'` и `AttributeError:
module 'core.packets' has no attribute 'TRACK_LIMITS_INFRINGEMENT_TYPES'`

- [ ] **Step 3: Реализация**

В `core/packets.py`, сразу после `CRITICAL_EVENTS = {"PENA", "RTMT", "CHQF",
"RCWN", "COLL"}` (~строка 117):

```python
# InfringementType-коды "трек-лимитной" семьи (corner cutting / running wide),
# подтверждено 2026-07-11 двумя независимыми источниками (EA-спека F1 25 +
# github.com/MacManley/f1-25-udp) — см. spec
# 2026-07-11-track-limits-engineer-toggle-design.md.
TRACK_LIMITS_INFRINGEMENT_TYPES = frozenset({7, 8, 9, 25, 26, 27, 28, 29})
```

В `parse_event`, ветка `PENA` (заменить существующий блок ~строка 274-282):

```python
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
```

- [ ] **Step 4: Запустить тесты снова**

Run: `py -3.12 -u -m pytest tests/test_packets_gaps_tyre.py -v`
Expected: PASS, все тесты файла зелёные

---

### Task 4: `core/engine.py` — живое предупреждение (LapData-ветка)

**Files:**
- Modify: `core/engine.py` (импорты ~строка 55, `__init__` ~строка 213, `_update_telemetry` ~строка 909-924)
- Test: `tests/test_engine_track_limits.py` (новый)

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_engine_track_limits.py
"""Проводка TrackLimitsTracker в F1Engine: живое предупреждение по LapData +
компаньон-реплика к трек-лимитному PENA + тумблер engineer_chatter_enabled.
См. docs/superpowers/specs/2026-07-11-track-limits-engineer-toggle-design.md.
"""
import struct

import pytest

import core.engine as eng_mod
from core.engine import F1Engine, SPEAKER_ENGINEER
from core.packets import HEADER_SIZE, LAP_DATA_SIZE, PACKET_LAP_DATA


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


def _lap_buf(*, current_lap=5, pit_status=0, corner_cutting_warnings=0):
    buf = bytearray(HEADER_SIZE + LAP_DATA_SIZE)
    base = HEADER_SIZE
    buf[base + 33] = current_lap
    buf[base + 34] = pit_status
    buf[base + 40] = corner_cutting_warnings
    return bytes(buf)


def _reset_track_limits_state(engine):
    engine._track_limits.reset()
    engine._prev_lap = 0
    engine._current_lap_pit = False


def test_corner_cutting_increase_enqueues_engineer_warning(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    _reset_track_limits_state(engine)
    _drain(engine)

    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(corner_cutting_warnings=0))
    _drain(engine)
    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(corner_cutting_warnings=1))

    drained = _drain(engine)
    found = [e for e in drained if e["event_code"] == "ENGINEER_TRACK_LIMITS_WARNING"]
    assert len(found) == 1
    assert found[0]["speaker"] == SPEAKER_ENGINEER
    assert found[0]["bypass_speak_threshold"] is True
    assert found[0]["phrase"]
    _reset_track_limits_state(engine)


def test_corner_cutting_same_value_no_warning(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    _reset_track_limits_state(engine)
    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(corner_cutting_warnings=1))
    _drain(engine)
    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(corner_cutting_warnings=1))
    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"] == "ENGINEER_TRACK_LIMITS_WARNING"]
    _reset_track_limits_state(engine)


def test_chatter_disabled_suppresses_track_limits_warning(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = False
    _reset_track_limits_state(engine)
    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(corner_cutting_warnings=0))
    _drain(engine)
    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(corner_cutting_warnings=1))
    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"] == "ENGINEER_TRACK_LIMITS_WARNING"]
    engine.settings["engineer_chatter_enabled"] = True
    _reset_track_limits_state(engine)
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `py -3.12 -u -m pytest tests/test_engine_track_limits.py -v`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute '_track_limits'`

- [ ] **Step 3: Проводка в `core/engine.py`**

Импорт (после строки 55, `from core.strategy_ai.weather_advisory import
RainAdvisoryTracker`):

```python
from core.strategy_ai.track_limits import TrackLimitsTracker
```

Инициализация в `__init__` (сразу после `self._box_call_tracker =
BoxCallTracker()`, ~строка 213):

```python
        self._track_limits = TrackLimitsTracker()
```

В `_update_telemetry`, LapData-ветка (сразу после `self._maybe_announce_pit_exit(
_prev_pit_status, self._player_pit_status)`, ~строка 924, ДО блока
`if pl.get("pit_status"): self._current_lap_pit = True`):

```python
                cc = pl.get("corner_cutting_warnings")
                if cc is not None:
                    tl_phrase = self._track_limits.check_warning(cc, time.time())
                    if tl_phrase and self._get_setting("engineer_chatter_enabled", True):
                        self._enqueue_event({
                            "event_code": "ENGINEER_TRACK_LIMITS_WARNING",
                            "priority": "normal",
                            "phrase": tl_phrase, "speaker": SPEAKER_ENGINEER,
                            "driver": "", "color": "#38BDF8",
                            "bypass_speak_threshold": True,
                        })
```

`check_warning()` вызывается ВСЕГДА (счётчик должен оставаться синхронным
независимо от тумблера) — гейт применяется только к самому `_enqueue_event`.

- [ ] **Step 4: Запустить тест снова**

Run: `py -3.12 -u -m pytest tests/test_engine_track_limits.py -v`
Expected: PASS, 3 passed

---

### Task 5: `core/engine.py` — сброс трекера на SSTA/CHQF/flashback

**Files:**
- Modify: `core/engine.py:1243, 1626, 1648`
- Test: `tests/test_engine_track_limits.py` (расширение)

- [ ] **Step 1: Написать падающий тест**

Добавить в `tests/test_engine_track_limits.py`. Проверяем сам факт вызова
`reset()` (не косвенные признаки через `check_warning` — расчёт "росло/не
росло" после сброса слишком легко проходит случайно даже без фикса):

```python
def test_flashback_resets_track_limits_tracker(engine, monkeypatch):
    calls = []
    monkeypatch.setattr(engine._track_limits, "reset", lambda: calls.append(True))
    engine._handle_flashback()
    assert calls == [True]
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `py -3.12 -u -m pytest tests/test_engine_track_limits.py -k flashback -v`
Expected: FAIL — `calls == []` (сброс ещё не подключен)

- [ ] **Step 3: Добавить сброс в трёх точках**

`_handle_flashback()` (~строка 1243, рядом с `self._box_call_tracker.reset()`):

```python
        self._box_call_tracker.reset()
        self._track_limits.reset()
```

Блок `SSTA` (~строка 1626-1628, рядом с существующими сбросами):

```python
                self._box_call_tracker.reset()
                self._gap_digest.reset()
                self._rain_advisory.reset()
                self._track_limits.reset()
```

Блок `CHQF`/`SEND` (~строка 1648):

```python
                self._session_events.append(code)
                self._box_call_tracker.reset()
                self._track_limits.reset()
```

- [ ] **Step 4: Запустить тест снова**

Run: `py -3.12 -u -m pytest tests/test_engine_track_limits.py -v`
Expected: PASS, все тесты файла зелёные

---

### Task 6: `core/engine.py` — извлечь `_handle_event_packet` (рефакторинг для тестируемости)

**Files:**
- Modify: `core/engine.py:1529-1689` (`_telemetry_loop`)

Чисто механическое извлечение, поведение не меняется — весь код внутри
`if packet_id != PACKET_EVENT: continue` ... до конца обработки события
переезжает в новый метод `_handle_event_packet(self, data: bytes) -> None`.
Каждый `continue` внутри извлекаемого блока становится `return`. Это нужно,
чтобы Task 7 (компаньон-реплика к PENA) можно было протестировать напрямую,
как уже тестируется `_update_telemetry` (см. `tests/test_engine_pit_tracking.py`).

Проверка отсутствия регрессии — полный прогон тестов ДО и ПОСЛЕ, без новых
юнит-тестов на сам рефакторинг (чистое перемещение кода, поведение исходного
блока уже покрыто существующими тестами `_should_commentate`/`_enqueue_event`/
`FLBK` и т.п., которые продолжат идти через `_telemetry_loop` в проде так же,
как раньше — просто через один уровень вызова метода).

- [ ] **Step 1: Зафиксировать baseline**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: все тесты проходят (0 failed) — записать, что видно в выводе, для
сравнения после рефакторинга.

- [ ] **Step 2: Извлечь метод**

В `core/engine.py`, найти в `_telemetry_loop`:

```python
            if packet_id != PACKET_EVENT:
                continue

            event = parse_event(data)
            if event is None:
                continue
```

Заменить на:

```python
            if packet_id != PACKET_EVENT:
                continue

            self._handle_event_packet(data)
```

Дальше добавить новый метод `_handle_event_packet` сразу ПОСЛЕ конца
`_telemetry_loop` (перед следующим методом класса). Тело — код, который был
удалён из `_telemetry_loop` выше, ЦЕЛИКОМ от `event = parse_event(data)` до
финального `self._enqueue_event(enriched)`, с заменой ВСЕХ `continue` внутри
этого блока на `return`:

```python
    def _handle_event_packet(self, data: bytes) -> None:
        """Обработка одного PACKET_EVENT: разбор, flashback, аналитика
        жизненного цикла сессии, компаньон-реплики, постановка в очередь.
        Извлечено из _telemetry_loop для тестируемости (см. spec
        2026-07-11-track-limits-engineer-toggle-design.md, Task 6)."""
        event = parse_event(data)
        if event is None:
            return

        # Track DRS state for race_ai threat detection
        _ec = event.get("event_code")
        if _ec == "DRSE":
            self._player_drs_active = True
        elif _ec == "DRSD":
            self._player_drs_active = False

        # Flashback: игрок перемотал момент — гасим очередь до-флэшбековых событий
        # и сбрасываем состояние, иначе комментатор спамит уже неактуальным.
        if _ec == "FLBK":
            self._handle_flashback()
            with self.state_lock:
                self.state["feed"].insert(0, {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "event_code": "FLBK",
                    "phrase": "Перемотка — переигрываем эпизод.",
                    "color": "#9CA3AF",
                    "driver": "",
                    "muted": True,
                    "channel": "overlay",
                })
                self.state["feed"] = self.state["feed"][:config.MAX_FEED_ITEMS]
            return

        enriched = self.race_state.enrich(event)
        # COLL тоже двухмашинное событие (vehicle1_idx/vehicle2_idx), но стиль
        # соперника сознательно ограничен OVTK (design spec 2026-07-05-race-memory)
        # — не забыто, не техническое ограничение get_style().
        if enriched.get("event_code") == "OVTK":
            overtaking_idx = enriched.get("overtaking_idx")
            being_overtaken_idx = enriched.get("being_overtaken_idx")
            now = time.time()
            enriched["driver_style"] = self.rival_tracker.get_style(overtaking_idx)
            enriched["target_style"] = self.rival_tracker.get_style(being_overtaken_idx)
            enriched["driver_recent_mistake"] = self.rival_tracker.get_recent_mistake(overtaking_idx, now)
            enriched["target_recent_mistake"] = self.rival_tracker.get_recent_mistake(being_overtaken_idx, now)
            enriched["driver_tyre_age"] = self.rival_tracker.get_tyre_age(overtaking_idx)
            enriched["target_tyre_age"] = self.rival_tracker.get_tyre_age(being_overtaken_idx)
        self.race_state.record_event(event)
        self._note_story_event(event, enriched)
        with self.state_lock:
            self.timeline.record_event(enriched)

        # Analytics: session lifecycle hooks
        code = event.get("event_code")
        if code == "SSTA":
            self.recorder.reset()
            with self.state_lock:
                self.timeline.reset()
            self._session_events = []
            self._prev_lap = 0
            self._current_lap_pit = False
            self._last_completed_lap_was_pit = False
            self._damage_announced = {
                "wing": False, "floor": False, "gearbox": False, "engine": False,
            }
            self._box_call_tracker.reset()
            self._gap_digest.reset()
            self._rain_advisory.reset()
            self._track_limits.reset()
            self.story_collector.reset()
            self._story_fired = False
            self._f1_best_ms = None
            self._f1_best_sector_ms = {}
            self._f1_context_line = None
            self._career_best_ms = None
            self._career_best_sector_ms = {}
            self._career_context_line = None
            # В отличие от _career_context_line (трековый), _career_stats_context_line
            # — кросс-трековый агрегат: сбрасывается только тут, на новой гонке, а не
            # при смене трассы (см. комментарий в блоке смены трассы выше по файлу).
            self._career_stats_context_line = None
            self._refresh_analytics_context()
            with self.state_lock:
                self.state["race_story"] = None
                self.state["f1_benchmark"] = None
                self.state["career_memory"] = None
        elif code in ("CHQF", "SEND"):
            self._session_events.append(code)
            self._box_call_tracker.reset()
            self._track_limits.reset()
            track_name = TRACK_ID_TO_GP.get(self._track_id, ("Unknown", "Unknown"))[0]
            with self.state_lock:
                grid = self.state.get("race", {}).get("grid", [])
                pidx = self._player_car_index
                pos = next((e.get("position") for e in grid
                            if e.get("vehicle_idx") == pidx), None)
            saved_path = self.recorder.finalize(
                track_id=self._track_id, track_name=track_name,
                session_type=self._session_type, final_position=pos,
                events=list(self._session_events),
                game_year=self._game_year,
            )
            if (code == "CHQF"
                    and self._session_type in ("race", "qualifying", "practice")
                    and not self._story_fired):
                self._story_fired = True
                threading.Thread(
                    target=self._generate_story, args=(saved_path,),
                    daemon=True, name="race-story").start()
        else:
            self._session_events.append(code)

        if code == "PENA" and enriched.get("vehicle_idx") == self._player_car_index:
            if enriched.get("infringement_type") in TRACK_LIMITS_INFRINGEMENT_TYPES:
                self._track_limits.note_penalty(time.time())
                if self._get_setting("engineer_chatter_enabled", True):
                    self._enqueue_event({
                        "event_code": "ENGINEER_PENA_TRACK_LIMITS",
                        "priority": "normal",
                        "phrase": "Это за трек-лимиты — аккуратнее на выходе из поворота.",
                        "speaker": SPEAKER_ENGINEER, "driver": "", "color": "#38BDF8",
                        "bypass_speak_threshold": True,
                    })

        if self._is_paused() or not self._should_commentate(enriched):
            with self.state_lock:
                self.state["feed"].insert(0, {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "event_code": event["event_code"],
                    "phrase": enriched.get("description", event["event_code"]),
                    "color": enriched.get("color", "#9CA3AF"),
                    "driver": enriched.get("driver", ""),
                    "muted": True,
                    "channel": "commentary",
                })
                self.state["feed"] = self.state["feed"][:config.MAX_FEED_ITEMS]
            return

        # Адаптивность/cooldown ambient: значимое событие двигает оба механизма.
        if self._is_significant_event(enriched):
            self._note_event_activity(time.time())
        self._enqueue_event(enriched)
```

Обратите внимание: компаньон-реплика (Task 7 по смыслу, добавлена здесь сразу
вместе с рефакторингом, чтобы не создавать промежуточный некорректный
диф) вставлена ПОСЛЕ блока `SSTA`/`CHQF`/`SEND`/`else`, ДО гейта
`_is_paused()/_should_commentate` — компаньон-реплика ставится в очередь
напрямую через `_enqueue_event`, минуя этот гейт, тем же способом, что уже
делает `PIT_CALL_NOTICE` рядом с box-call.

Также нужен импорт `TRACK_LIMITS_INFRINGEMENT_TYPES` — добавить в существующий
`from core.packets import (...)` блок (~строка 26-34):

```python
from core.packets import (
    parse_header, parse_participants, parse_event,
    parse_session, parse_lap_data, parse_player_lap,
    parse_player_telemetry, parse_player_status, parse_player_damage,
    parse_car_status_all, parse_car_damage_all,
    PACKET_PARTICIPANTS, PACKET_EVENT, PACKET_SESSION,
    PACKET_LAP_DATA, PACKET_CAR_TELEMETRY, PACKET_CAR_STATUS, PACKET_CAR_DAMAGE,
    HEADER_SIZE, TRACK_LIMITS_INFRINGEMENT_TYPES,
)
```

- [ ] **Step 3: Запустить полный прогон, сверить с baseline**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: тот же результат, что в Step 1 (0 failed) — рефакторинг не сломал
ничего существующего.

---

### Task 7: `core/engine.py` — тесты компаньон-реплики PENA + подавления

**Files:**
- Test: `tests/test_engine_track_limits.py` (расширение)

Логика уже вписана в Task 6 (вместе с рефакторингом). Этот таск — тесты,
которые её фиксируют.

- [ ] **Step 1: Написать тесты**

Добавить в `tests/test_engine_track_limits.py`:

```python
def test_player_track_limits_pena_enqueues_companion_line(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    engine._track_limits.reset()
    _drain(engine)

    buf = bytearray(HEADER_SIZE + 4 + 7)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"PENA"
    # infringement_type=25 (lap invalidated corner cutting), vehicle_idx=0 (игрок)
    struct.pack_into("<BBBBBBB", buf, HEADER_SIZE + 4, 1, 25, 0, 0, 5, 12, 0)
    engine._handle_event_packet(bytes(buf))

    drained = _drain(engine)
    codes = [e["event_code"] for e in drained]
    assert "ENGINEER_PENA_TRACK_LIMITS" in codes
    companion = next(e for e in drained if e["event_code"] == "ENGINEER_PENA_TRACK_LIMITS")
    assert companion["speaker"] == SPEAKER_ENGINEER
    assert companion["bypass_speak_threshold"] is True
    assert "PENA" in codes                    # обычная драматическая реплика не тронута
    engine._track_limits.reset()


def test_pena_not_track_limits_no_companion_line(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    engine._track_limits.reset()
    _drain(engine)

    buf = bytearray(HEADER_SIZE + 4 + 7)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"PENA"
    # infringement_type=3 (Big Collision) — не трек-лимиты
    struct.pack_into("<BBBBBBB", buf, HEADER_SIZE + 4, 1, 3, 0, 0, 5, 12, 0)
    engine._handle_event_packet(bytes(buf))

    drained = _drain(engine)
    codes = [e["event_code"] for e in drained]
    assert "ENGINEER_PENA_TRACK_LIMITS" not in codes
    assert "PENA" in codes
    engine._track_limits.reset()


def test_opponent_track_limits_pena_no_companion_line(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    engine._track_limits.reset()
    _drain(engine)

    buf = bytearray(HEADER_SIZE + 4 + 7)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"PENA"
    # vehicle_idx=7 (не игрок, у которого _player_car_index=0)
    struct.pack_into("<BBBBBBB", buf, HEADER_SIZE + 4, 1, 25, 7, 0, 5, 12, 0)
    engine._handle_event_packet(bytes(buf))

    drained = _drain(engine)
    codes = [e["event_code"] for e in drained]
    assert "ENGINEER_PENA_TRACK_LIMITS" not in codes
    engine._track_limits.reset()


def test_track_limits_pena_suppresses_live_warning_same_window(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = True
    _reset_track_limits_state(engine)
    _drain(engine)

    # Живой рост счётчика на 1
    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(corner_cutting_warnings=0))
    _drain(engine)

    # Трек-лимитный PENA игрока — открывает окно подавления
    buf = bytearray(HEADER_SIZE + 4 + 7)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"PENA"
    struct.pack_into("<BBBBBBB", buf, HEADER_SIZE + 4, 1, 25, 0, 0, 5, 12, 0)
    engine._handle_event_packet(bytes(buf))
    _drain(engine)

    # Следующий тик счётчика в ту же секунду — живое предупреждение подавлено
    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(corner_cutting_warnings=1))
    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"] == "ENGINEER_TRACK_LIMITS_WARNING"]
    _reset_track_limits_state(engine)


def test_chatter_disabled_suppresses_pena_companion_but_not_pena(engine):
    engine._player_car_index = 0
    engine.settings["engineer_chatter_enabled"] = False
    engine._track_limits.reset()
    _drain(engine)

    buf = bytearray(HEADER_SIZE + 4 + 7)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"PENA"
    struct.pack_into("<BBBBBBB", buf, HEADER_SIZE + 4, 1, 25, 0, 0, 5, 12, 0)
    engine._handle_event_packet(bytes(buf))

    drained = _drain(engine)
    codes = [e["event_code"] for e in drained]
    assert "ENGINEER_PENA_TRACK_LIMITS" not in codes
    assert "PENA" in codes                    # штраф всё равно объявляется
    engine.settings["engineer_chatter_enabled"] = True
    engine._track_limits.reset()
```

- [ ] **Step 2: Запустить тесты**

Run: `py -3.12 -u -m pytest tests/test_engine_track_limits.py -v`
Expected: PASS, все тесты файла зелёные (логика уже реализована в Task 6)

---

### Task 8: Тумблер `engineer_chatter_enabled` — settings + оставшиеся 3 гейта

**Files:**
- Modify: `core/settings.py:19-42` (`DEFAULTS`)
- Modify: `core/engine.py` (гэп-дайджест ~строка 1891, rain-advisory ~строка 836-843, ERS-советы ~строка 1151-1177)
- Test: `tests/test_engine_settings.py`, `tests/test_engine_planner.py`

Живое предупреждение трек-лимитов и PENA-компаньон уже гейтованы (Task 4/6).
Здесь — три оставшиеся точки эмиссии + новый ключ настроек по умолчанию.

- [ ] **Step 1: Написать падающий тест на дефолт**

Добавить в `tests/test_engine_settings.py`:

```python
from core.settings import DEFAULTS


def test_engineer_chatter_enabled_defaults_to_true():
    assert DEFAULTS["engineer_chatter_enabled"] is True
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `py -3.12 -u -m pytest tests/test_engine_settings.py -v`
Expected: FAIL — `KeyError: 'engineer_chatter_enabled'`

- [ ] **Step 3: Добавить ключ в `core/settings.py`**

В `DEFAULTS` (~строка 41, после `"commentary_mode": "live",`):

```python
    "commentary_mode":         "live",
    "engineer_chatter_enabled": True,
}
```

- [ ] **Step 4: Запустить тест снова**

Run: `py -3.12 -u -m pytest tests/test_engine_settings.py -v`
Expected: PASS

- [ ] **Step 5: Написать падающие тесты на гейтинг гэп-дайджеста/rain-advisory/ERS**

Добавить в начало `tests/test_engine_planner.py`, к существующему блоку
импортов (~строка 8-10):

```python
from core.packets import HEADER_SIZE, PACKET_SESSION
```

Добавить в конец `tests/test_engine_planner.py`:

```python
# --------------------------------------------------------------------------- #
# engineer_chatter_enabled — гейтинг периодической "болтовни" инженера
# --------------------------------------------------------------------------- #

def test_chatter_disabled_suppresses_gap_digest(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = False
    engine._session_type = "race"
    engine._last_significant_event_t = 0.0
    monkeypatch.setattr(engine, "_is_paused", lambda: False)
    with engine.state_lock:
        engine.state["connected"] = True
    monkeypatch.setattr(engine._gap_digest, "build", lambda *a, **kw: "Отрыв впереди: 1.2")

    emitted = engine._maybe_emit_gap_digest(time.time())
    assert emitted is False

    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "unknown"


def test_chatter_enabled_allows_gap_digest(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "race"
    engine._last_significant_event_t = 0.0
    monkeypatch.setattr(engine, "_is_paused", lambda: False)
    with engine.state_lock:
        engine.state["connected"] = True
    monkeypatch.setattr(engine._gap_digest, "build", lambda *a, **kw: "Отрыв впереди: 1.2")
    _drain(engine)

    emitted = engine._maybe_emit_gap_digest(time.time())
    assert emitted is True
    drained = _drain(engine)
    assert any(e["event_code"] == "ENGINEER_GAP_DIGEST" for e in drained)

    engine._session_type = "unknown"


def test_chatter_disabled_suppresses_rain_advisory(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = False
    monkeypatch.setattr(engine._rain_advisory, "check", lambda forecast: "Дождь через 5 минут")
    _drain(engine)

    buf = bytearray(HEADER_SIZE + 200)   # с запасом под Session-пакет, нулевой буфер безопасен
    engine._update_telemetry({"player_car_index": 0}, PACKET_SESSION, bytes(buf))

    drained = _drain(engine)
    assert not [e for e in drained if e["event_code"] == "ENGINEER_RAIN_ADVISORY"]
    engine.settings["engineer_chatter_enabled"] = True


def test_chatter_disabled_suppresses_ers_advisory_but_not_fuel(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = False
    _drain(engine)
    engine._player_lap = 20
    engine._player_pit_status = 0
    engine._last_snap_t = 0.0
    engine._last_strategy_ai_event_t = 0.0

    class _FakeDecision:
        action = "hold"
        reason = "ers_save_recommended"

    class _FakeEvent:
        type = "ers_save"
        priority = "normal"
        decision = _FakeDecision()
        confidence = 0.3
        data = {}

    monkeypatch.setattr(engine.strategy_analyzer, "update", lambda snap: _FakeEvent())
    engine._maybe_snapshot()

    drained = _drain(engine)
    codes = [e["event_code"] for e in drained]
    assert "STRAT_ERS_SAVE" not in codes

    engine.settings["engineer_chatter_enabled"] = True
    engine._player_lap = None
    engine._player_pit_status = None
    engine._last_snap_t = 0.0
    engine._last_strategy_ai_event_t = 0.0
```

(`_drain` уже определён выше в файле — переиспользуется.)

- [ ] **Step 6: Запустить, убедиться что падают**

Run: `py -3.12 -u -m pytest tests/test_engine_planner.py -k chatter -v`
Expected: FAIL — `_maybe_emit_gap_digest`/rain/ERS ещё не проверяют
`engineer_chatter_enabled` (события ставятся в очередь несмотря на
`False`).

- [ ] **Step 7: Гейт №1 — гэп-дайджест**

В `core/engine.py`, `_maybe_emit_gap_digest` (~строка 1891):

```python
    def _maybe_emit_gap_digest(self, now: float) -> bool:
        if (self._is_paused() or self._session_type != "race"
                or self._in_event_cooldown(now)
                or not self._get_setting("engineer_chatter_enabled", True)):
            return False
```

- [ ] **Step 8: Гейт №2 — rain-advisory**

В `_update_telemetry`, ветка `PACKET_SESSION` (~строка 836-843):

```python
            _rain_phrase = self._rain_advisory.check(self._rain_forecast)
            if _rain_phrase is not None and self._get_setting("engineer_chatter_enabled", True):
                self._enqueue_event({
                    "event_code": "ENGINEER_RAIN_ADVISORY", "priority": "normal",
                    "phrase": _rain_phrase, "speaker": SPEAKER_ENGINEER,
                    "driver": "", "color": "#38BDF8",
                    "bypass_speak_threshold": True,
                })
```

- [ ] **Step 9: Гейт №3 — ERS-советы (без затрагивания STRAT_PIT/STRAT_FUEL/... и без затрагивания race_event ниже)**

**Важно:** после этого блока в `_maybe_snapshot` идёт НЕЗАВИСИМАЯ обработка
`race_event` (attack/battle/tyre_warning/final_lap, ~строка 1179-1199) — нельзя
использовать `return` внутри блока `_st_code_map`, иначе гейтинг ERS-совета
случайно глушил бы и её. Гейтуем только сам `_enqueue_event`, throttle
(`_last_strategy_ai_event_t`) продолжает обновляться как раньше.

В `_maybe_snapshot`, блок `_st_code_map` (~строка 1151-1177), заменить:

```python
        if strategy_event is not None and not _bc_decisive:
            if now - self._last_strategy_ai_event_t >= 20.0:
                self._last_strategy_ai_event_t = now
                _st_code_map = {
                    "undercut":    "STRAT_UNDERCUT",
                    "overcut":     "STRAT_OVERCUT",
                    "pit_window":  "STRAT_PIT",
                    "tyre_save":   "STRAT_SAVE",
                    "push_pace":   "STRAT_PUSH",
                    "fuel_save":   "STRAT_FUEL",
                    "ers_save":     "STRAT_ERS_SAVE",
                    "ers_overtake": "STRAT_ERS_OVERTAKE",
                }
                self._enqueue_event({
                    "event_code": _st_code_map.get(strategy_event.type, "STRAT_PIT"),
                    "priority": strategy_event.priority,
                    "driver": "player",
                    "speaker": SPEAKER_ENGINEER,
                    "color": "#38BDF8",
                    "strategy_ai_type": strategy_event.type,
                    "strategy_ai_data": {
                        **strategy_event.data,
                        "confidence": strategy_event.confidence,
                        "action": strategy_event.decision.action,
                        "reason": strategy_event.decision.reason,
                    },
                })
```

на:

```python
        if strategy_event is not None and not _bc_decisive:
            if now - self._last_strategy_ai_event_t >= 20.0:
                self._last_strategy_ai_event_t = now
                _st_code_map = {
                    "undercut":    "STRAT_UNDERCUT",
                    "overcut":     "STRAT_OVERCUT",
                    "pit_window":  "STRAT_PIT",
                    "tyre_save":   "STRAT_SAVE",
                    "push_pace":   "STRAT_PUSH",
                    "fuel_save":   "STRAT_FUEL",
                    "ers_save":     "STRAT_ERS_SAVE",
                    "ers_overtake": "STRAT_ERS_OVERTAKE",
                }
                _engineer_chatter_types = {"ers_save", "ers_overtake"}
                _chatter_gated = (
                    strategy_event.type in _engineer_chatter_types
                    and not self._get_setting("engineer_chatter_enabled", True)
                )
                if not _chatter_gated:
                    self._enqueue_event({
                        "event_code": _st_code_map.get(strategy_event.type, "STRAT_PIT"),
                        "priority": strategy_event.priority,
                        "driver": "player",
                        "speaker": SPEAKER_ENGINEER,
                        "color": "#38BDF8",
                        "strategy_ai_type": strategy_event.type,
                        "strategy_ai_data": {
                            **strategy_event.data,
                            "confidence": strategy_event.confidence,
                            "action": strategy_event.decision.action,
                            "reason": strategy_event.decision.reason,
                        },
                    })
```

- [ ] **Step 10: Запустить тесты снова**

Run: `py -3.12 -u -m pytest tests/test_engine_planner.py tests/test_engine_settings.py -v`
Expected: PASS, все тесты файлов зелёные

---

### Task 9: NewSpotterUI — тумблер «Болтовня инженера»

**Files:**
- Modify: `NewSpotterUI/lib/api.ts:36-49` (`SettingsState`)
- Modify: `NewSpotterUI/components/spotter/views/dashboard.tsx`

Ручного теста через pytest нет (TS/React) — проверка через сборку +
визуально в браузере (см. Step 4).

- [ ] **Step 1: Добавить поле в тип**

В `NewSpotterUI/lib/api.ts`, `SettingsState` (после `ambient_enabled:
boolean,`):

```typescript
export type SettingsState = {
  persona: string
  commentary_enabled: boolean
  autovoice_enabled: boolean
  critical_events_enabled: boolean
  ambient_enabled: boolean
  engineer_chatter_enabled: boolean
  radio_fx: boolean
  ...
```

- [ ] **Step 2: Добавить переключатель в `dashboard.tsx`**

Локальное состояние (~строка 65):

```typescript
  const [local, setLocal] = useState({ commentary: true, voice: true, critical: true, ambient: true, engineerChatter: true, broadcast: false, position: "auto" })
```

Синхронизация (~строка 68-77):

```typescript
    if (s) {
      setLocal({
        commentary: s.commentary_enabled,
        voice: s.autovoice_enabled,
        critical: s.critical_events_enabled,
        ambient: s.ambient_enabled ?? true,
        engineerChatter: s.engineer_chatter_enabled ?? true,
        broadcast: s.broadcast_mode_enabled ?? false,
        position: s.commentator_position,
      })
    }
  }, [s?.commentary_enabled, s?.autovoice_enabled, s?.critical_events_enabled, s?.ambient_enabled, s?.engineer_chatter_enabled, s?.broadcast_mode_enabled, s?.commentator_position])
```

Новый `ControlRow` (после блока `ambient`, ~строка 177, до блока `broadcast`):

```tsx
            <ControlRow
              icon={Mic}
              title="Болтовня инженера"
              subtitle="Гэп-дайджест, ERS-советы, дождь, трек-лимиты"
              checked={local.engineerChatter}
              onChange={apply("engineerChatter", "engineer_chatter_enabled")}
            />
```

(`Mic` уже импортирован из `lucide-react` в шапке файла — новый импорт не
нужен.)

- [ ] **Step 3: Проверить типы**

Run (из `NewSpotterUI/`): `npm run build` или `npx tsc --noEmit`
Expected: без ошибок типов на изменённых файлах

- [ ] **Step 4: Визуальная проверка**

Запустить dev-сервер NewSpotterUI, открыть Dashboard, убедиться что
переключатель «Болтовня инженера» отображается в блоке «Управление» под
«Авто-анализ», кликабелен, состояние сохраняется через `saveSettings`.

---

### Task 10: CONTEXT.md — задокументировать пробел и эту сессию

**Files:**
- Modify: `CONTEXT.md`

- [ ] **Step 1: Полный прогон тестов**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: 0 failed (все тесты, включая новые из Task 1-8, зелёные)

- [ ] **Step 2: Обновить CONTEXT.md**

В раздел «На чём остановились» добавить ДВЕ записи (в начало, самое свежее
первым):

1. Запись о том, что **Фаза 4 шаг 2/2 (rain-advisory) была реализована
   2026-07-10, но не попала в CONTEXT.md** — задокументировать задним числом
   (файл, событие, спека `docs/superpowers/specs/2026-07-10-rain-advisory-design.md`).
2. Запись об этой сессии (2026-07-11) — трек-лимиты (живые предупреждения +
   причина PENA + подавление дублирования) и тумблер
   `engineer_chatter_enabled`, со ссылкой на спеку/план этого документа,
   результат прогона тестов, и явно — **не проверено вживую** (нужна игра).

Обновить сводную заметку про открытые пункты «замены инженера»: Фаза 4b
закрыта (код), тумблер закрыт; остаются только пункты, требующие живой игры
(калибровка ERS-порогов, живая проверка всех фаз на слух) — это НЕ входило в
объём этой сессии (см. диалог в начале — пользователь выбрал закрыть C и D,
не A/E).

Следовать конвенции файла (см. `[[project_context_reorg]]` в памяти) — не
разрастать сверх ~100 пунктов, при необходимости свернуть старые записи в
`docs/CONTEXT_ARCHIVE.md`.
