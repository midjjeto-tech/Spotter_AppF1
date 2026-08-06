# Погода + прогноз дождя: парсинг (Фаза 4, шаг 1/2) — дизайн

Дата: 2026-07-10
Статус: утверждён по объёму пользователем (диалог 2026-07-10: погода первой,
трек-лимиты потом). Офсеты подтверждены статически (см. ниже).

## Контекст

Фаза 4 «замены инженера» = погода/дождь + трек-лимиты. Пользователь выбрал
погоду первой (чистые данные, самая ценная реплика — «дождь через N минут»);
трек-лимиты — отдельным будущим шагом (грязнее данные, игра и так показывает).

Как и ERS (Фаза 3), сначала ТОЛЬКО парсинг (этот документ), потом advisory-
логика (шаг 2). Погодные данные лежат в Session-пакете (packet 1), который уже
принимается и частично парсится (`parse_session` читает `total_laps@3`,
`session_type@6`, `track_id@7`).

## Проблема

`parse_session` не читает ни текущую погоду, ни массив прогноза. Нужны:
- **Текущая погода** (тривиально безопасно): `m_weather@0`, `m_trackTemperature@1`,
  `m_airTemperature@2` — ПЕРЕД уже подтверждённым `m_totalLaps@3`, нулевой риск.
- **Прогноз дождя** (главная фича, офсет рискованнее): массив
  `m_weatherForecastSamples[64]`, каждый сэмпл 8 байт, начинается на офсете 127.

## Верификация офсетов (статическая, без запуска игры)

Раскладка `PacketSessionData` (от `base = HEADER_SIZE`), сверена с
[независимым парсером MacManley f1-25-udp](https://github.com/MacManley/f1-25-udp)
и общедоступной спекой F1 24/25 (структура сессии до массива прогноза стабильна
с F1 23):
```
@0   m_weather              uint8   (0=ясно 1=облачно 2=пасмурно
                                     3=слаб.дождь 4=сильн.дождь 5=гроза)
@1   m_trackTemperature     int8    °C
@2   m_airTemperature       int8    °C
@3   m_totalLaps            uint8   ← уже парсится (ЯКОРЬ)
@4   m_trackLength          uint16
@6   m_sessionType          uint8   ← уже парсится (ЯКОРЬ)
@7   m_trackId              int8    ← уже парсится (ЯКОРЬ)
@8   m_formula              uint8
@9   m_sessionTimeLeft      uint16
@11  m_sessionDuration      uint16
@13  m_pitSpeedLimit        uint8
@14  m_gamePaused           uint8
@15  m_isSpectating         uint8
@16  m_spectatorCarIndex    uint8
@17  m_sliProNativeSupport  uint8
@18  m_numMarshalZones      uint8
@19  m_marshalZones[21]     21×5=105 байт  → @19..123
@124 m_safetyCarStatus      uint8
@125 m_networkGame          uint8
@126 m_numWeatherForecastSamples  uint8   ← число валидных сэмплов
@127 m_weatherForecastSamples[64] 64×8=512 байт
```
Каждый `WeatherForecastSample` (8 байт):
```
+0 m_sessionType          uint8
+1 m_timeOffset           uint8   минуты в будущее (0,5,10,15,30,45,60...)
+2 m_weather              uint8   0..5 (как выше)
+3 m_trackTemperature     int8
+4 m_trackTemperatureChange int8  (0=up 1=down 2=no change)
+5 m_airTemperature       int8
+6 m_airTemperatureChange int8
+7 m_rainPercentage       uint8   0..100
```

**Три якоря сходятся** (`total_laps@3`, `session_type@6`, `track_id@7` уже
работают в проде), и от них field-by-field вычисление даёт `@126`/`@127`.
Замечание: summary MacManley-README называл офсет «140», но это противоречит
его же списку полей (который суммируется в 126) — артефакт пересказа,
отклонён. EA-PDF отдаёт 403 (не пробить без auth), поэтому доп. страховка —
runtime-валидация (ниже).

## Решение (одним абзацем)

`parse_session` дополняется текущей погодой (`weather`/`track_temp`/`air_temp`,
офсеты 0/1/2 — безопасны) и **самопроверяющимся** разбором массива прогноза:
находим ближайший будущий сэмпл с дождём и отдаём `rain_forecast` = {минут до
дождя, % дождя, тип погоды}. Разбор ВАЛИДИРУЕТСЯ (см. ниже) — при неверном
офсете (напр. будущий патч игры сдвинул структуру) возвращаем `None`, а не
мусор. Плюс throttled DIAG-лог (как у ERS) для живого подтверждения.

## Самопроверка (ключевое отличие от ERS) — и её реальные границы

У прогноза есть естественные ограничения валидности — используем их, чтобы
неверный офсет само-детектировался:
- `m_numWeatherForecastSamples` должно быть 1..64 (иначе офсет неверен → `None`).
- Каждый разбираемый сэмпл: `m_timeOffset` ∈ 0..130 (минуты), `m_weather` ∈ 0..5
  (сужено ревью с исходных 0..7 — `WEATHER_LABEL` определяет только 0-5),
  `m_rainPercentage` ∈ 0..100.
- **Кросс-сверка** (добавлена по находке ревью): `m_sessionType` каждого сэмпла
  должен совпадать с уже известным `session_type_raw` пакета (или быть 0 —
  трактуется как «не привязан к конкретной сессии», раз неизвестно, бывает ли
  такое легитимно). Сужает промежуточные (1-7 байт) сдвиги офсета.

**ИСПРАВЛЕНО (было заявлено сильнее, чем есть на самом деле — нашло финальное
ревью):** самопроверка НЕ закрывает сдвиг ровно на ОДИН ЦЕЛЫЙ сэмпл (8 байт).
В этом случае каждое поле читается из СОСЕДНЕГО, но полностью валидного (и с
тем же `m_sessionType`) сэмпла — пройдёт любую проверку диапазона И кросс-
сверку. Это принципиально не ловится самосогласованностью одного поля, при
том что 8-байтовый сдвиг — как раз самый правдоподобный класс ошибки, если
`m_numMarshalZones`/длина массива перед прогнозом когда-нибудь окажутся
неверны. Единственная реальная защита от ЭТОГО конкретного класса ошибки —
внешняя сверка (живой `SPOTTER_DIAG=1` против HUD игры), не код. DIAG-лог
поэтому усилен: показывает СЫРЫЕ тики первых 6 сэмплов (`num`,
`(minutes,weather,rain%)` без валидации), не только уже отфильтрованный
ближайший дождь — сильный сигнал сверки: совпадает ли ВСЯ полоса минутных
меток с HUD, а не «похоже ли на процент» (та же ловушка, что была с ERS и
соседним `m_enginePowerMGUK`).

Итог: самопроверка строже, чем у ERS, но НЕ «пуленепробиваемая», как
формулировка спеки утверждала изначально — один конкретный класс ошибки
(целый-сэмпл сдвиг) остаётся закрыт только живой проверкой, не кодом.

## Не входит в объём

- Advisory-логика («дождь через N минут, готовь интермедиейты») — шаг 2.
- Трек-лимиты — отдельная подфича Фазы 4, позже.
- `m_trackTemperatureChange`/`m_airTemperatureChange` в сэмплах — не нужны
  для «дождь идёт», не парсим (YAGNI).
- Погода соперников — не существует (погода общая на сессию).

## Архитектура

### `core/packets.py`

```python
WEATHER_LABEL = {0: "ясно", 1: "облачно", 2: "пасмурно",
                 3: "слабый дождь", 4: "сильный дождь", 5: "гроза"}

# Session packet weather forecast layout (см. дизайн-спеку, сверено со спекой F1 25).
_WFS_ARRAY_OFF = 127      # начало m_weatherForecastSamples (от HEADER_SIZE)
_WFS_NUM_OFF = 126        # m_numWeatherForecastSamples
_WFS_SAMPLE_SIZE = 8
_WFS_MAX_SAMPLES = 64
_RAIN_WEATHER_MIN = 3     # weather >= 3 = дождь (слабый/сильный/гроза)

_last_weather_diag_t = 0.0
```

`parse_session` дополняется (после существующего разбора, НЕ ломая его):
```python
    out = {
        "total_laps": data[HEADER_SIZE + 3],
        "track_id": int(track_id),
        "session_type_raw": session_type_raw,
        "session_type": SESSION_TYPE_MAP.get(session_type_raw, "unknown"),
    }
    # Текущая погода — офсеты 0/1/2, перед подтверждённым total_laps@3 (безопасно).
    out["weather"] = data[HEADER_SIZE + 0]
    out["track_temp"] = struct.unpack_from("<b", data, HEADER_SIZE + 1)[0]
    out["air_temp"] = struct.unpack_from("<b", data, HEADER_SIZE + 2)[0]
    # Прогноз дождя — самопроверяющийся разбор массива.
    out["rain_forecast"] = _parse_rain_forecast(data)
    ... (DIAG-лог, throttled) ...
    return out
```

Новая чистая функция `_parse_rain_forecast(data) -> dict | None`:
```python
def _parse_rain_forecast(data: bytes) -> dict | None:
    """Ближайший будущий сэмпл с дождём (weather>=3), либо None.
    Самопроверяется: неверный офсет/битый пакет → None, не мусор."""
    base = HEADER_SIZE + _WFS_NUM_OFF
    if base + 1 > len(data):
        return None
    num = data[base]
    if not (1 <= num <= _WFS_MAX_SAMPLES):
        return None                      # офсет неверен или пакет без прогноза
    best: dict | None = None
    arr = HEADER_SIZE + _WFS_ARRAY_OFF
    for i in range(num):
        off = arr + i * _WFS_SAMPLE_SIZE
        if off + _WFS_SAMPLE_SIZE > len(data):
            break
        time_offset = data[off + 1]
        weather = data[off + 2]
        rain_pct = data[off + 7]
        # Валидация: неправдоподобные значения → офсет неверен, прекращаем.
        if time_offset > 130 or weather > 7 or rain_pct > 100:
            return None
        if weather >= _RAIN_WEATHER_MIN and time_offset > 0:
            if best is None or time_offset < best["minutes"]:
                best = {"minutes": time_offset, "rain_pct": rain_pct,
                        "weather": weather}
    return best
```
(Ищем БЛИЖАЙШИЙ будущий дождь — минимальный `time_offset > 0` среди сэмплов с
`weather >= 3`. `time_offset == 0` = текущий момент, не «прогноз».)

### DIAG (throttled, как у ERS)

При `SPOTTER_DIAG=1`, раз в 2с в лог: текущая погода + ближайший дождь, чтобы
пользователь при желании сверил с погодным HUD игры (доп. страховка, не блокер).

## Граничные случаи

- **Сухая сессия** (нет дождя в прогнозе) — `rain_forecast = None`, штатно.
- **Неверный офсет** (будущий патч) — валидация ловит (num вне 1..64 ИЛИ
  первый же сэмпл с неправдоподобными значениями) → `None`, не мусор.
- **Дождь уже идёт** (`weather >= 3` сейчас, `m_weather@0`) — это ТЕКУЩАЯ
  погода (`out["weather"]`), не прогноз; advisory-шаг решит, как разделять
  «идёт сейчас» и «будет через N минут».
- **Пакет короче** — все чтения за границей → `None`/пропуск.

## Тестирование

- `tests/test_packets_weather.py` (новый) — синтетический Session-буфер:
  - текущая погода (weather/track_temp/air_temp) читается с офсетов 0/1/2;
  - прогноз: сэмпл с дождём на `time_offset=15` → `rain_forecast` =
    {minutes:15, ...}; ближайший из нескольких дождевых выбирается;
  - сухой прогноз (все weather<3) → `None`;
  - **валидация**: `num=200` (>64) → `None`; сэмпл с `rain_pct=250` → `None`;
    `weather=99` → `None` (само-детект неверного офсета);
  - короткий пакет → `None`, `parse_session` не падает;
  - существующие поля (`total_laps`/`session_type`/`track_id`) не сломаны.
- DIAG-троттлинг — юнит по образцу ERS.
- Живая сверка — доп. страховка (не блокер): офсеты подтверждены статически +
  runtime-валидация.
