# Погода + прогноз дождя: парсинг — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `parse_session` читает текущую погоду (weather/track_temp/air_temp) и
самопроверяющийся прогноз дождя (`rain_forecast` = ближайший будущий дождь).
**Только парсинг, без advisory-логики.**

**Architecture:** Текущая погода — офсеты 0/1/2 (перед подтверждённым
`total_laps@3`, нулевой риск). Прогноз — массив на офсете 127, с runtime-
валидацией (неверный офсет/битый пакет → `None`, не мусор). Throttled DIAG.

**Tech Stack:** Python 3.12, pytest. Проект НЕ под git — без commit-шагов.

**Спека:** `docs/superpowers/specs/2026-07-10-weather-forecast-parsing-design.md`
— офсеты сверены со спекой F1 25 (три подтверждённых якоря) + runtime-
валидация как доп. страховка (EA-PDF отдавал 403, живой прогон опционален).

---

### Task 1: Погода + прогноз в `parse_session`

**Files:**
- Modify: `core/packets.py`
- Create: `tests/test_packets_weather.py`

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_packets_weather.py`:
```python
"""Погода + прогноз дождя из Session-пакета (parse_session).
См. docs/superpowers/specs/2026-07-10-weather-forecast-parsing-design.md.
"""
import struct

from core import packets
from core.packets import parse_session, HEADER_SIZE


# Полноразмерный Session-буфер: заголовок + payload минимум до конца массива
# прогноза (HEADER_SIZE + 127 + 64*8 = HEADER_SIZE + 639).
_PAYLOAD_LEN = 639


def _session_buf(weather=0, track_temp=30, air_temp=22,
                 total_laps=58, session_type=10, track_id=5,
                 num_forecast=0, samples=None):
    """samples: list of (time_offset, weather, rain_pct) на нужных позициях."""
    buf = bytearray(HEADER_SIZE + _PAYLOAD_LEN)
    b = HEADER_SIZE
    buf[b + 0] = weather
    struct.pack_into("<b", buf, b + 1, track_temp)
    struct.pack_into("<b", buf, b + 2, air_temp)
    buf[b + 3] = total_laps
    buf[b + 6] = session_type
    struct.pack_into("<b", buf, b + 7, track_id)
    buf[b + 126] = num_forecast
    arr = b + 127
    for i, (time_offset, w, rain_pct) in enumerate(samples or []):
        off = arr + i * 8
        buf[off + 1] = time_offset
        buf[off + 2] = w
        buf[off + 7] = rain_pct
    return bytes(buf)


def test_current_weather_parsed():
    out = parse_session(_session_buf(weather=4, track_temp=35, air_temp=28))
    assert out["weather"] == 4
    assert out["track_temp"] == 35
    assert out["air_temp"] == 28


def test_negative_temps_signed():
    out = parse_session(_session_buf(track_temp=-5, air_temp=-2))
    assert out["track_temp"] == -5
    assert out["air_temp"] == -2


def test_rain_forecast_nearest_future_rain():
    out = parse_session(_session_buf(
        num_forecast=3,
        samples=[(0, 0, 0), (15, 3, 60), (30, 4, 90)]))
    assert out["rain_forecast"] == {"minutes": 15, "rain_pct": 60, "weather": 3}


def test_rain_forecast_picks_closest_when_multiple():
    out = parse_session(_session_buf(
        num_forecast=3,
        samples=[(45, 4, 80), (20, 3, 50), (10, 5, 95)]))
    assert out["rain_forecast"]["minutes"] == 10


def test_dry_forecast_returns_none():
    out = parse_session(_session_buf(
        num_forecast=2, samples=[(15, 1, 0), (30, 2, 10)]))
    assert out["rain_forecast"] is None


def test_time_offset_zero_is_not_forecast():
    # weather>=3 но time_offset=0 (сейчас) — это текущая погода, не прогноз
    out = parse_session(_session_buf(num_forecast=1, samples=[(0, 4, 90)]))
    assert out["rain_forecast"] is None


# --- Самопроверка: неверный офсет/битый пакет → None, не мусор ---

def test_invalid_num_forecast_returns_none():
    out = parse_session(_session_buf(num_forecast=200))   # >64
    assert out["rain_forecast"] is None


def test_implausible_rain_pct_returns_none():
    buf = bytearray(_session_buf(num_forecast=1, samples=[(15, 3, 60)]))
    buf[HEADER_SIZE + 127 + 7] = 250                      # rain_pct вне 0..100
    out = parse_session(bytes(buf))
    assert out["rain_forecast"] is None


def test_implausible_weather_returns_none():
    buf = bytearray(_session_buf(num_forecast=1, samples=[(15, 3, 60)]))
    buf[HEADER_SIZE + 127 + 2] = 99                       # weather вне 0..7
    out = parse_session(bytes(buf))
    assert out["rain_forecast"] is None


def test_short_packet_forecast_none_no_crash():
    # payload только 8 байт (как старые тесты) — прогноза нет, но погода есть
    header = b"\x00" * HEADER_SIZE
    payload = struct.pack("<BBbBHBb", 3, 25, 20, 58, 5793, 10, 5)
    out = parse_session(header + payload)
    assert out["rain_forecast"] is None
    assert out["weather"] == 3
    assert out["total_laps"] == 58


def test_existing_fields_unbroken():
    out = parse_session(_session_buf(total_laps=44, session_type=10, track_id=7))
    assert out["total_laps"] == 44
    assert out["session_type"] == "race"
    assert out["track_id"] == 7
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `py -3.12 -u -m pytest tests/test_packets_weather.py -q`
Expected: FAIL — `KeyError: 'weather'` (поля ещё не парсятся).

- [ ] **Step 3: Реализовать в `core/packets.py`**

3a. Константы (рядом с `TYRE_VISUAL`/`ERS_MAX_JOULES`, после них):
```python
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
```

3b. Новая функция `_parse_rain_forecast` (перед `parse_session`):
```python
def _parse_rain_forecast(data: bytes) -> dict | None:
    """Ближайший будущий сэмпл с дождём (weather>=3, time_offset>0), либо None.
    Самопроверяется: неверный офсет/битый пакет → None, не мусор (у прогноза
    есть естественные диапазоны валидности — используем их)."""
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
        time_offset = data[off + 1]
        weather = data[off + 2]
        rain_pct = data[off + 7]
        if time_offset > 130 or weather > 7 or rain_pct > 100:
            return None                  # неправдоподобно → офсет неверен
        if weather >= _RAIN_WEATHER_MIN and time_offset > 0:
            if best is None or time_offset < best["minutes"]:
                best = {"minutes": time_offset, "rain_pct": rain_pct,
                        "weather": weather}
    return best
```

3c. Дополнить `parse_session` (после сборки существующего `out`-словаря,
ПЕРЕД `return`). Текущий код заканчивается:
```python
    return {
        "total_laps": data[HEADER_SIZE + 3],
        "track_id": int(track_id),
        "session_type_raw": session_type_raw,
        "session_type": SESSION_TYPE_MAP.get(session_type_raw, "unknown"),
    }
```
Заменить на:
```python
    out = {
        "total_laps": data[HEADER_SIZE + 3],
        "track_id": int(track_id),
        "session_type_raw": session_type_raw,
        "session_type": SESSION_TYPE_MAP.get(session_type_raw, "unknown"),
        # Текущая погода — офсеты 0/1/2, ПЕРЕД подтверждённым total_laps@3.
        "weather": data[HEADER_SIZE + 0],
        "track_temp": struct.unpack_from("<b", data, HEADER_SIZE + 1)[0],
        "air_temp": struct.unpack_from("<b", data, HEADER_SIZE + 2)[0],
        "rain_forecast": _parse_rain_forecast(data),
    }
    if _DIAG:
        global _last_weather_diag_t
        now = time.time()
        if now - _last_weather_diag_t >= 2.0:
            _last_weather_diag_t = now
            rf = out["rain_forecast"]
            _log.warning(
                "DIAG weather: now=%s(%d) track=%d°C air=%d°C rain_forecast=%s",
                WEATHER_LABEL.get(out["weather"], "?"), out["weather"],
                out["track_temp"], out["air_temp"], rf,
            )
    return out
```
(`time`/`_DIAG`/`_log` уже импортированы/определены в файле — добавлены при
ERS-парсинге.)

- [ ] **Step 4: Прогнать, зелёные**

Run: `py -3.12 -u -m pytest tests/test_packets_weather.py tests/test_session_type.py -q`
Expected: все зелёные (новые + существующие session-тесты не сломаны).

---

## Верификация (сквозная)

- `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q` — весь набор зелёный.
- Точечно: `pytest tests/test_packets_weather.py tests/test_session_type.py -q`.
- Офсеты подтверждены статически (3 якоря + спека F1 25) + runtime-валидация
  само-детектирует неверный офсет. `SPOTTER_DIAG=1` — доп. страховка на случай
  будущего патча игры, живой прогон опционален (не блокер для advisory-шага).
