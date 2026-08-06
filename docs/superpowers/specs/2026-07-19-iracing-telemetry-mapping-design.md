# iRacing telemetry mapping — справочник полей (Phase 1 done, Phase 2/3 TODO)

Дата: 2026-07-19
Статус: Phase 1 реализован (`core/iracing_telemetry.py`, `core/iracing_packets.py`,
`settings.telemetry_source`), Phase 2/3 — заглушки. План:
`C:\Users\Artem\.claude\plans\peaceful-humming-teacup.md`.

## Контекст

`core/iracing_packets.py` — шим/переводчик: переводит переменные iRacing SDK
(`pyirsdk`, опрос shared memory) в словари ТОЙ ЖЕ ФОРМЫ, что `core/packets.py`
отдаёт для F1 UDP. Функции совпадают 1:1 по имени/сигнатуре с F1-версией —
`core/engine.py` и все трекеры (`TrackLimitsTracker`, `DriverCoach`,
`RivalTracker` и т.д.) работают без изменений независимо от источника.

Этот документ — единая таблица "что от iRacing куда мапится", чтобы не
приходилось восстанавливать неявные допущения по коду при реализации Phase 2/3.

## Mapping: реализовано (Phase 1)

| Внутреннее поле (F1-форма) | Источник iRacing (`pyirsdk`) | Нюанс |
|---|---|---|
| `positions[idx]` | `CarIdxPosition[idx]` | `0` = ещё не классифицирован — отфильтровано (`pos > 0`) |
| `laps[idx]` | `CarIdxLap[idx]` | прямое совпадение семантики |
| `pit_status[idx]` | `CarIdxOnPitRoad[idx]` (bool) | F1 различает "заезжает"(1)/"в пит-лейн"(2); iRacing даёт только bool → мапим `True → 2`, нет аналога для "заезжает"(1) |
| `leader_idx` | вычисляется из `positions` (`position == 1`) | как и в F1-парсере — не отдельная переменная SDK |
| `name`/`team`/`number` (participants) | `DriverInfo.Drivers[].{UserName,TeamName,CarNumber}` | YAML session info, НЕ polled var — не тикает каждый кадр, читается через `_session_drivers()` |
| `team` fallback | `CarClassShortName` | iRacing — классовые заезды (multiclass), нет команд реального мира; `team` = лига/класс/livery, никогда не сопоставляется с `f1_metadata.TEAM_INFO` |
| `color` (participants) | — | нет офиц. цвета команды у iRacing → нейтральный `#9CA3AF` заглушка; Phase 4 — цвет по классу |
| `speed` | `Speed` (м/с) | конвертация `* 3.6` → км/ч, та же sanity-проверка `0 <= speed_kmh <= 400`, что и у F1 |
| `gear` | `Gear` | `-1`=R, `0`=N, иначе строка — идентичная F1-конвенции |

**Фундаментальное ограничение SDK**, не недосмотр: iRacing транслирует
подробную per-tick телеметрию (`Speed`/`Gear`) только для машины ИГРОКА — в
отличие от F1, где `CarTelemetry` приходит для всех 22 машин. `player_idx` в
`parse_player_telemetry` принимается только для совпадения сигнатуры с F1 и не
используется.

## Mapping: пока НЕ переведено (Phase 1 → безопасный placeholder)

| Внутреннее поле | Почему не переведено сейчас | Кто нужен для Phase 2/3 |
|---|---|---|
| `gaps_front` | нет прямого отрыва в мс; расчёт требует `CarIdxEstTime` (оценка времени круга по позиции на трассе) | Phase 2/3 |
| `lap_distances` (метры) | `CarIdxLapDistPct` — ДОЛЯ круга (0..1), не метры; нужна длина трассы (`WeekendInfo.TrackLength` из session YAML) для конвертации | Phase 2/3 |
| `last_lap_ms`/`s1_ms`/`s2_ms`/`s3_ms` | не переведены; `0` — сознательный "не переведено", НЕ "круг был нулевым" (engine.py's `if lms > 0` уже пропускает такие круги) | `LapLastLapTime` (сек) `* 1000`; секторы — Phase 2/3 |
| `corner_cutting_warnings` | нет аналога дискретного счётчика; track-limits для iRacing пойдёт через `synthesize_events` (инциденты), не через это поле | Phase 3 |

## Mapping: полные заглушки (Phase 2/3, функции возвращают `{}`/`None`/`[]`)

| Функция | Что нужно реализовать | Известная лоссовость |
|---|---|---|
| `parse_session` | `session_type`, `total_laps`, `track_id`, weather | нет прямого 0-5 weather-кода, как у F1; iRacing weather — отдельная модель (`WeatherType`, `Skies`, влажность трека), большинство контента — статическая погода без прогноза → `rain_forecast` скорее всего всегда `None` |
| `parse_player_status`/`parse_car_status_all` | `fuel`, `tyre_compound`, `tyre_age`, ERS-аналог | iRacing НЕ имеет ERS — поле должно ОТСУТСТВОВАТЬ в словаре (не `0`), чтобы трекеры, проверяющие `"ers_percent" in result`, корректно деградировали; компаунд шин — нет единой FIA-схемы `S/M/H/I/W`, мапинг будет per-car-class и заведомо приблизительным |
| `parse_player_damage`/`parse_car_damage_all` | `tyre_wear`, категории повреждений кузова | iRacing даёт менее гранулярные данные по повреждениям — реализация заведомо lossy, не пытаться выдумать категории, которых нет |
| `parse_event` | — (остаётся заглушкой навсегда) | iRacing не имеет push-событий; вся событийная логика — в `synthesize_events`, не здесь. Не путать одно с другим |
| `synthesize_events` | детекция дельт между тиками: флаг-транзишены (`SessionFlags`), инциденты (`PlayerCarMyIncidentCount` delta → приближение PENA/track-limits), обгоны (diff `CarIdxPosition` между тиками → `OVTK`), пит/буксировка (`CarIdxOnPitRoad`/`CarIdxTrackSurface` transitions → `RTMT`-аналог) | Самая рискованная часть — инференс, не перевод. Приоритет: пропущенное событие (false negative) безопаснее спонтанной болтовни (false positive) |

## Что НЕ входит в объём (см. план, "What NOT to build")

- Не строить универсальную таблицу компаундов шин "на все случаи" заранее —
  per-car-class уточнение отложено до Phase 4.
- Не пытаться сопоставить iRacing track ID с F1 `TRACK_ID_TO_GP`/track-benchmark
  подсистемой — разные неродственные пространства ID, эти F1-специфичные
  подсистемы (`f1_benchmark`, career memory) должны просто не активироваться
  для iRacing-сессий.
- Не расширять `f1_metadata.py`'s ростер/сезонные таблицы под iRacing.

## Тестирование

- Чистые функции (`parse_lap_data`, `parse_participants`, `parse_player_telemetry`
  и т.д.) — `tests/test_iracing_packets.py`, `dict -> dict`, без живого iRacing.
- `IRacingTelemetry`/`.poll()`/`.listen()` — интеграционный тест с моком
  модуля `irsdk` (см. `tests/test_iracing_telemetry_integration.py`), проверяет
  connected/disconnected переходы и форму возвращаемых данных без реального
  запуска iRacing.
- Живая верификация (реальная сессия iRacing) остаётся ручной/лог-based на
  каждой фазе — как и зафиксировано в разделе "Verification" плана.
