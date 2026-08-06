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
                 num_forecast=0, samples=None, safety_car_status=0):
    """samples: list of (time_offset, weather, rain_pct) на нужных позициях."""
    buf = bytearray(HEADER_SIZE + _PAYLOAD_LEN)
    b = HEADER_SIZE
    buf[b + 0] = weather
    struct.pack_into("<b", buf, b + 1, track_temp)
    struct.pack_into("<b", buf, b + 2, air_temp)
    buf[b + 3] = total_laps
    buf[b + 6] = session_type
    struct.pack_into("<b", buf, b + 7, track_id)
    buf[b + 124] = safety_car_status
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


# --- m_safetyCarStatus@124 (см. docs/superpowers/specs/
# 2026-07-10-weather-forecast-parsing-design.md — тот же якорь-выверенный
# офсет, что уже используют total_laps@3/session_type@6/track_id@7) ---

def test_safety_car_status_parsed():
    out = parse_session(_session_buf(safety_car_status=2))
    assert out["safety_car_status"] == 2


def test_safety_car_status_defaults_zero():
    out = parse_session(_session_buf())
    assert out["safety_car_status"] == 0


def test_existing_fields_unbroken():
    # session_type=15 -> "race" (F1 25: 10-14 сдвинуты под Sprint Shootout,
    # см. SESSION_TYPE_MAP в core/packets.py, найдено живой проверкой 2026-07-18).
    out = parse_session(_session_buf(total_laps=44, session_type=15, track_id=7))
    assert out["total_laps"] == 44
    assert out["session_type"] == "race"
    assert out["track_id"] == 7


# --- Кросс-сверка m_sessionType сэмпла (найдено ревью — сужает промежуточные
# 1-7-байтовые сдвиги; целый-сэмпл сдвиг (8 байт) принципиально не ловится
# самосогласованностью одного поля, см. докстринг _parse_rain_forecast) ---

def test_sample_session_type_mismatch_returns_none():
    buf = bytearray(_session_buf(
        session_type=10, num_forecast=1, samples=[(15, 3, 60)]))
    buf[HEADER_SIZE + 127 + 0] = 5                    # сэмпл "про" qualifying, не race(10)
    out = parse_session(bytes(buf))
    assert out["rain_forecast"] is None


def test_sample_session_type_zero_is_wildcard():
    buf = bytearray(_session_buf(
        session_type=10, num_forecast=1, samples=[(15, 3, 60)]))
    buf[HEADER_SIZE + 127 + 0] = 0                    # 0 = не привязан к конкретной сессии
    out = parse_session(bytes(buf))
    assert out["rain_forecast"] == {"minutes": 15, "rain_pct": 60, "weather": 3}


def test_sample_session_type_matching_passes():
    buf = bytearray(_session_buf(
        session_type=10, num_forecast=1, samples=[(15, 3, 60)]))
    buf[HEADER_SIZE + 127 + 0] = 10                   # совпадает с session_type пакета
    out = parse_session(bytes(buf))
    assert out["rain_forecast"] == {"minutes": 15, "rain_pct": 60, "weather": 3}


# --- Точные границы валидации (не только заведомо невалидные значения) ---

def test_num_forecast_exactly_at_max_is_valid():
    out = parse_session(_session_buf(num_forecast=64, samples=[(15, 3, 60)]))
    assert out["rain_forecast"] == {"minutes": 15, "rain_pct": 60, "weather": 3}


def test_num_forecast_one_past_max_is_invalid():
    out = parse_session(_session_buf(num_forecast=65))
    assert out["rain_forecast"] is None


def test_weather_exactly_at_upper_bound_is_valid():
    out = parse_session(_session_buf(num_forecast=1, samples=[(15, 5, 60)]))
    assert out["rain_forecast"] == {"minutes": 15, "rain_pct": 60, "weather": 5}


def test_weather_one_past_upper_bound_is_invalid():
    out = parse_session(_session_buf(num_forecast=1, samples=[(15, 6, 60)]))
    assert out["rain_forecast"] is None


def test_rain_pct_exactly_100_is_valid():
    out = parse_session(_session_buf(num_forecast=1, samples=[(15, 3, 100)]))
    assert out["rain_forecast"]["rain_pct"] == 100


def test_rain_pct_101_is_invalid():
    out = parse_session(_session_buf(num_forecast=1, samples=[(15, 3, 101)]))
    assert out["rain_forecast"] is None


def test_mid_array_truncation_stops_gracefully():
    """num заявляет больше сэмплов, чем реально влезает в буфер — цикл должен
    остановиться (break), а не упасть/читать за границей."""
    buf = bytearray(_session_buf(num_forecast=5, samples=[(15, 3, 60)]))
    short = bytes(buf[:HEADER_SIZE + 127 + 8])   # ровно 1 сэмпл влезает, не 5
    out = parse_session(short)
    assert out["rain_forecast"] == {"minutes": 15, "rain_pct": 60, "weather": 3}


# --- DIAG-троттлинг (по образцу ERS, см. tests/test_packets_gaps_tyre.py) ---

def test_weather_diag_throttle_skips_second_call_within_window(monkeypatch):
    import time as time_mod

    monkeypatch.setattr(packets, "_DIAG", True)
    monkeypatch.setattr(packets, "_last_weather_diag_t", 0.0)
    calls = []
    monkeypatch.setattr(packets._log, "warning", lambda *a, **kw: calls.append(a))

    buf = _session_buf(num_forecast=1, samples=[(15, 3, 60)])

    parse_session(buf)                              # первый вызов — логирует
    assert len(calls) == 1

    parse_session(buf)                               # сразу второй — троттлинг молчит
    assert len(calls) == 1

    monkeypatch.setattr(packets, "_last_weather_diag_t", time_mod.time() - 3.0)
    parse_session(buf)
    assert len(calls) == 2
