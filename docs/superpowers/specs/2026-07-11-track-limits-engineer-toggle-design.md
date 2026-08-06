# Трек-лимиты инженера + тумблер «болтовни» — дизайн (Фаза 4b + открытый пункт «замены инженера»)

Дата: 2026-07-11
Статус: утверждён пользователем (диалог 2026-07-11), реализация — по плану в
`docs/superpowers/plans/`.

## Контекст

Продолжение «замены внутриигрового инженера F1 25» (см.
`docs/superpowers/specs/2026-07-09-precise-box-call-design.md` и последующие
фазы в CONTEXT.md). На момент этой сессии закрыты: Фаза 1 (точный box-call),
Фаза 2 (гэп-дайджест), Фаза 3 (топливо/ERS — телеметрия + 3 совета), Фаза 4
шаг 1/2 (парсинг погоды/дождя) и — обнаружено при разборе кода, не было
зафиксировано в CONTEXT.md — Фаза 4 шаг 2/2 (`RainAdvisoryTracker`,
`ENGINEER_RAIN_ADVISORY`) тоже уже реализован.

Остаются два пункта, оба выбраны пользователем в этой сессии:

1. **Фаза 4b — трек-лимиты.** Единственное явное ограничение из памяти проекта:
   повторные срезания в F1 25 эскалируют в `PENA`, который уже озвучивается
   (все 4 персоны, критический приоритет) — новое уведомление не должно с ним
   конкурировать/дублироваться.
2. **Тумблер на периодическую «болтовню» инженера** — дважды помеченный
   открытый non-blocker (гэп-дайджест и ERS-советы сейчас можно приглушить
   только всей `commentary_enabled` или громкостью голоса `calm`).

Пользователь выбрал полное покрытие для (1): живые предупреждения ДО штрафа
(как это делает настоящий инженер — «осторожно, трек-лимиты»), плюс уточнение
причины уже случившегося `PENA`. И единый тумблер для (2), не трогающий
box-call/PENA (это критические/решающие события, не «болтовня»).

## Решение

### Часть 1 — живые предупреждения по счётчику трек-лимитов

`LapData.m_cornerCuttingWarnings` (offset 40, uint8) — счётчик, растущий при
срезании поворотов, статически подтверждён двумя независимыми источниками
(GitHub `MacManley/f1-25-udp` + перекрёстный веб-поиск по офиц. EA-спеке F1 25),
раскладка сходится байт-в-байт с уже подтверждёнными `m_carPosition@32`/
`m_currentLapNum@33`/`m_pitStatus@34` — тот же уровень уверенности, что был у
ERS/погоды. Живой проверки через `SPOTTER_DIAG=1` не было (недоступна игра в
этой сессии) — тот же класс допущения, что уже принимался для ERS до его
статического подтверждения.

Новый чистый трекер `core/strategy_ai/track_limits.py::TrackLimitsTracker`
(без I/O, стиль как `box_call.py`): edge-triggered на РОСТ счётчика относительно
предыдущего тика → готовая фраза. Не гейтуется по `session_type` (трек-лимиты
важны и в квалификации, в отличие от гэп-дайджеста).

### Часть 2 — причина уже случившегося PENA

`core/packets.py::parse_event()` уже парсит `_infr` (infringement type) для
PENA, но отбрасывает его. Начинаем прокидывать как `infringement_type` в
`details`. Восемь кодов "трек-лимитной" семьи подтверждены тем же способом
(два независимых источника): `{7, 8, 9, 25, 26, 27, 28, 29}` — corner cutting
gained time / overtake single/multiple / lap invalidated corner
cutting/running wide / corner cutting ran wide gained time (minor/significant/
extreme).

Когда `PENA` — про игрока (`vehicle_idx == player_car_index`) И
`infringement_type` из этого набора: рядом с уже существующей (не изменяемой!)
драматической репликой комментатора о штрафе ставится КОРОТКАЯ реплика голосом
инженера — тот же паттерн-компаньон, что уже применён для `PIT_CALL_NOTICE`
рядом с box-call tier 1 (готовая фраза напрямую через `event["phrase"]`,
`bypass_speak_threshold: True`, в обход LLM и `commentator/templates.py`
целиком — 4 персональных пула фраз для `PENA` НЕ трогаются, ноль риска для уже
настроенной драматургии комментатора).

### Часть 3 — подавление дублирования (ключевое ограничение из памяти проекта)

`TrackLimitsTracker` получает `note_penalty(now)` — вызывается инженерным
компаньоном из Части 2 при срабатывании трек-лимитного `PENA`. `check_warning()`
не отдаёт фразу, если `now - last_penalty_t < SUPPRESSION_WINDOW_S` (5с) — даже
если счётчик предупреждений только что вырос. Так «живое предупреждение» и
«штраф уже случился» никогда не звучат почти одновременно про один и тот же
эпизод, как и требовала заметка в CONTEXT.md. `note_penalty()` вызывается
БЕЗУСЛОВНО (независимо от тумблера болтовни из части 4) — подавление должно
работать, даже если тумблер переключили посреди гонки.

### Часть 4 — тумблер `engineer_chatter_enabled`

Новый ключ в `core/settings.py::DEFAULTS` (`True` по умолчанию — ничего не
меняется для тех, кто не трогал настройки). Гейтует ТОЛЬКО периодическую
«болтовню» инженера:
- гэп-дайджест (`ENGINEER_GAP_DIGEST`),
- ERS-советы (`STRAT_ERS_SAVE`/`STRAT_ERS_OVERTAKE`),
- rain-advisory (`ENGINEER_RAIN_ADVISORY`),
- новые: живое предупреждение трек-лимитов + компаньон-причина у PENA.

НЕ гейтует: box-call (`STRAT_BOX_CALL_*`/`PIT_CALL_NOTICE`) и саму озвучку
`PENA` — это критические/решающие события, остаются на `critical_events_enabled`/
`commentary_enabled`, как сейчас.

## Не входит в объём

- Изменение существующих 4 персональных пулов фраз `PENA` в
  `commentator/templates.py` — реплика-причина идёт отдельным компаньон-событием,
  не трогает уже настроенную драматургию комментатора.
- LLM-путь для новых реплик — обе используют готовую фразу через
  `event["phrase"]`, как `ENGINEER_RAIN_ADVISORY`/`ENGINEER_GAP_DIGEST`, в обход
  `commentator/brain.py::create()` целиком.
- Отдельные тумблеры на каждую под-фичу инженера — один общий переключатель
  (осознанный выбор пользователя, см. «Контекст»).
- Живая проверка офсета `m_cornerCuttingWarnings` в игре — только статическая
  сверка в этой фазе (см. «Граничные случаи»).
- Персистентность `TrackLimitsTracker` между перезапусками — ephemeral, как
  остальные трекеры движка.

## Архитектура

### Новый модуль `core/strategy_ai/track_limits.py`

```python
SUPPRESSION_WINDOW_S = 5.0

class TrackLimitsTracker:
    def __init__(self) -> None:
        self._last_count: int | None = None
        self._last_penalty_t: float = 0.0

    def check_warning(self, count: int, now: float) -> str | None:
        prev, self._last_count = self._last_count, count
        if prev is None or count <= prev:
            return None
        if now - self._last_penalty_t < SUPPRESSION_WINDOW_S:
            return None
        return "Осторожно с лимитами трассы!"

    def note_penalty(self, now: float) -> None:
        self._last_penalty_t = now

    def reset(self) -> None:
        self._last_count = None
        self._last_penalty_t = 0.0
```

`prev is None` на первом наблюдаемом тике сессии — не считаем это «ростом»
(иначе первый же пакет с ненулевым счётчиком из прошлой сессии/после
рестарта ложно объявит предупреждение).

### `core/packets.py`

- `parse_event()`, ветка `PENA` (~строка 274): добавить `_infr` в `details` как
  `infringement_type`.
- Новая константа `TRACK_LIMITS_INFRINGEMENT_TYPES = frozenset({7, 8, 9, 25, 26,
  27, 28, 29})`, рядом с `CRITICAL_EVENTS`.
- `parse_player_lap()` (~строка 425): добавить `"corner_cutting_warnings":
  data[base + 40]` в возвращаемый словарь (по образцу `pit_status@34`).
- Golden-master тест на полную 57-байтную раскладку `LapData` (аналог
  `_CAR_STATUS_LAYOUT` для ERS) + тест, что чтение идёт именно с 40, а не с
  соседних `m_totalWarnings@39`/`m_numUnservedDriveThroughPens@41` (тот же
  приём, что уже страховал ERS от `m_enginePowerMGUK`).

### `core/engine.py`

**Инициализация** (рядом с остальными per-race трекерами):
```python
self._track_limits = TrackLimitsTracker()
```

**LapData-ветка `_update_telemetry`** (рядом с чтением `pl = parse_player_lap(...)`,
~строка 910):
```python
cc = pl.get("corner_cutting_warnings")
if cc is not None:
    tl_phrase = self._track_limits.check_warning(cc, time.time())
    if tl_phrase and self._get_setting("engineer_chatter_enabled", True):
        self._enqueue_event({
            "event_code": "ENGINEER_TRACK_LIMITS_WARNING", "priority": "normal",
            "phrase": tl_phrase, "speaker": SPEAKER_ENGINEER,
            "driver": "", "color": "#38BDF8",
            "bypass_speak_threshold": True,
        })
```
`check_warning()` вызывается ВСЕГДА (счётчик должен оставаться синхронным),
тумблер гейтует только сам `_enqueue_event`.

**PACKET_EVENT-ветка** (сразу после `enriched = self.race_state.enrich(event)`,
~строка 1594, рядом с уже существующей особой обработкой `OVTK`):
```python
if code == "PENA" and enriched.get("vehicle_idx") == self._player_car_index:
    if enriched.get("infringement_type") in TRACK_LIMITS_INFRINGEMENT_TYPES:
        self._track_limits.note_penalty(time.time())
        if self._get_setting("engineer_chatter_enabled", True):
            self._enqueue_event({
                "event_code": "ENGINEER_PENA_TRACK_LIMITS", "priority": "normal",
                "phrase": "Это за трек-лимиты — аккуратнее на выходе из поворота.",
                "speaker": SPEAKER_ENGINEER, "driver": "", "color": "#38BDF8",
                "bypass_speak_threshold": True,
            })
```
Обычный `enriched` PENA-объект продолжает идти в `_enqueue_event(enriched)`
(~строка 1688) без изменений — драматическая реплика комментатора не трогается,
компаньон-реплика инженера ставится в очередь ДОПОЛНИТЕЛЬНО.

**Сброс состояния** — `self._track_limits.reset()` добавляется в три уже
существующие точки сброса per-race трекеров:
- `SSTA` (~строка 1626, рядом с `self._box_call_tracker.reset()`),
- `CHQF`/`SEND` (~строка 1648),
- `_handle_flashback()` (~строка 1243).

**Тумблер, гейт №3** — гэп-дайджест, `_maybe_emit_gap_digest` (~строка 1891):
```python
if (self._is_paused() or self._session_type != "race"
        or self._in_event_cooldown(now)
        or not self._get_setting("engineer_chatter_enabled", True)):
    return False
```

**Тумблер, гейт №4** — rain-advisory (~строка 836):
```python
if _rain_phrase is not None and self._get_setting("engineer_chatter_enabled", True):
    self._enqueue_event({...})  # без изменений внутри
```

**Тумблер, гейт №5** — ERS-советы внутри общего `_st_code_map`-блока
(~строка 1151-1177, который также обслуживает `STRAT_PIT`/`STRAT_FUEL`/... —
ИХ тумблер не касается):
```python
_ENGINEER_CHATTER_TYPES = {"ers_save", "ers_overtake"}
...
if strategy_event is not None and not _bc_decisive:
    if now - self._last_strategy_ai_event_t >= 20.0:
        _type = strategy_event.type
        if (_type not in _ENGINEER_CHATTER_TYPES
                or self._get_setting("engineer_chatter_enabled", True)):
            self._last_strategy_ai_event_t = now
            ...  # существующая сборка события без изменений
```

### `core/settings.py`

```python
DEFAULTS: dict = {
    ...
    "engineer_chatter_enabled": True,
}
```

### `NewSpotterUI`

- `lib/api.ts`: `Settings.engineer_chatter_enabled: boolean`.
- `components/spotter/views/dashboard.tsx`: новая строка `local.engineerChatter`
  (синхронизация в том же `useEffect`, что и `ambient`), новый `ControlRow`
  рядом с ambient-переключателем — заголовок «Болтовня инженера», подпись
  «Гэп-дайджест, ERS-советы, дождь, трек-лимиты».

## Граничные случаи

- **`m_cornerCuttingWarnings` — счётчик за круг или за сессию?** Не подтверждено
  ни одним источником явно. Дизайн не полагается на это различие: фраза не
  называет номер предупреждения («предупреждение 2 из 3»), только сам факт
  роста — корректно в обоих случаях. Если впоследствии выяснится, что счётчик
  сбрасывается на каждом круге, `prev is None or count <= prev` уже отфильтрует
  ложные «предупреждения» от сброса к 0 (не считается ростом).
- **Трек-лимиты у AI-соперников** — не обрабатываются, только игрок (как
  ERS/box-call/гэп-дайджест) — инженер разговаривает с игроком, не с полем.
- **PENA не про трек-лимиты (например, столкновение, превышение в pit lane)** —
  `infringement_type` не в наборе → компаньон-реплика не создаётся, обычная
  драматическая PENA-фраза комментатора звучит как сейчас, без изменений.
- **Тумблер выключен, но штраф всё равно случился** — `note_penalty()`
  вызывается безусловно, только озвучка компаньон-реплики гейтуется. Штраф
  (обычный PENA) всё равно объявляется, как и раньше — тумблер не относится к
  критическим событиям.
- **Рестарт приложения посреди гонки** — трекер не персистится, начинает с
  `_last_count = None`, первый тик не считается ростом (см. код выше).
- **Флешбек** — `TrackLimitsTracker.reset()` в `_handle_flashback()`, иначе
  устаревший `_last_penalty_t`/`_last_count` может неверно подавить или
  наоборот ложно объявить предупреждение после перемотки.

## Тестирование

`tests/test_track_limits.py` (новый, без моков):
- первый тик с любым `count > 0` → `None` (нет предыдущего значения)
- рост со второго тика → фраза
- повтор того же значения → `None`
- `note_penalty()` только что вызван → рост счётчика в пределах
  `SUPPRESSION_WINDOW_S` не даёт фразу
- после окна подавления — рост снова даёт фразу
- `reset()` возвращает в исходное состояние

`tests/test_packets.py` (расширение):
- golden-master полной 57-байтной раскладки `LapData` с новым полем на 40
- чтение `corner_cutting_warnings` именно с 40, не с 39/41 (соседние поля)
- `parse_event()` PENA прокидывает `infringement_type`
- `TRACK_LIMITS_INFRINGEMENT_TYPES` содержит ровно подтверждённые 8 кодов

`tests/test_engine.py` (расширение, по образцу существующих тестов box-call/
гэп-дайджеста):
- трек-лимитный PENA игрока → компаньон-событие в очереди, обычная PENA не
  тронута
- PENA другого гонщика или не трек-лимитной причины → компаньон-событие не
  создаётся
- живое предупреждение подавляется в течение 5с после трек-лимитного PENA
- `engineer_chatter_enabled=False` → гэп-дайджест/ERS-советы/rain-advisory/
  трек-лимиты не ставятся в очередь; box-call и обычный PENA — ставятся
  (тумблер их не должен трогать)
- сброс трекера на SSTA/CHQF/flashback

Полный прогон `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q` в конце —
как во всех предыдущих сессиях. Живая проверка в игре (звучат ли
предупреждения в нужный момент, не спамят ли) — отдельно пользователем после
сборки EXE, недоступна в среде разработки.
