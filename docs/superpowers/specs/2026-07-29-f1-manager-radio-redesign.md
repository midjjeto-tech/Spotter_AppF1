# Team Radio в стиле F1 Manager — аудит существующей архитектуры

**Дата:** 2026-07-29
**Статус:** Task 1 (аудит), код НЕ менялся
**Плана:** `docs/superpowers/plans/2026-07-29-f1-manager-radio-redesign.md`

Документ фиксирует *что есть сейчас*. Проектные решения — в плане. Всё, что ниже,
получено чтением кода (файл:строка), а не по памяти.

---

## 1. Текущий путь инженерской реплики

Один сквозной путь от пакета до звука. Потоки помечены явно.

```
[поток telemetry]
  UDP-пакет F1 25
    → core/telemetry_adapters.py            транспорт + декод + dispatch
    → core/packets.py                       парсинг бинарной раскладки
    → F1Engine._update_telemetry (engine.py:~1400+)
        ├── обновляет self._player_* (gap/ers/fuel/tyre/pos/damage…)
        └── дёргает детерминированные «тики»:
              _spotter_tick        (engine.py:1239, на каждом PACKET_MOTION)
              _drs_advisory_tick   (engine.py:1207)
              _leader_change_tick  (engine.py:1307)
              _defense_tick        (engine.py:1330)
              _update_damage       (engine.py:906)
              …и т.д.
    → core/race_engineer.py                 фасад над трекерами
    → core/strategy_ai/<tracker>.py         edge-triggered состояние → ГОТОВАЯ строка
    → CommentaryEvents.publish(draft)       core/commentary_events.py:73

[внутри publish]
    ├── context_provider(values)            → PlanContext (player_involved/battle/laps)
    ├── score_importance(values, ctx)       commentator/planner.py:85 → importance 0..100
    ├── values["enqueued_at"] = time()      ← ЕДИНСТВЕННАЯ временна́я метка события
    ├── media_hook (скриншоты)
    ├── ImportanceQueue.put(event)          core/event_queue.py:31 (PriorityQueue, -importance)
    └── race_feed.ingest(...)               fanout в core/racefeed/

[поток commentary — ОДИН потребитель]
  F1Engine._commentary_loop (engine.py:2665)
    ├── 1. _is_paused()                                    → continue
    ├── 2. not _telemetry_connected                        → continue
    ├── 3. muted_by_threshold()   commentary_runtime.py:32 → в ленту muted, continue
    ├── 4. is_stale_backlog_event() commentary_runtime.py:44 → continue (тихо)
    ├── 5. entity resolution (driver/target: "#N" → имя)
    ├── 6. SessionGuard.should_emit()  session_guard.py:94  → continue
    ├── 7. flashback silence (engine.py:2723)               → continue
    ├── 8. SituationDedup.should_emit() situation_dedup.py:83 → continue
    ├── 9. route_event()          channel_router.py:60      → overlay ⇒ в ленту, continue
    ├── 10. ПОЛУЧЕНИЕ ТЕКСТА:
    │       event["phrase"] (готовый)  →  _resolve_volatile_phrase()  ← engine.py:2758
    │       ↓ иначе  get_radio_line(code)            commentator/radio.py
    │       ↓ иначе  strategist.get_message(...)     commentator/strategist.py
    │       ↓ иначе  commentator.create_broadcast()  (broadcast_mode)
    │       ↓ иначе  build_plan() + commentator.create()  ← LLM (brain.py)
    ├── 11. _should_voice(event)      engine.py:887
    ├── 12. БЛОКИРУЮЩАЯ ПАУЗА MIN_COMMENT_GAP (до 9 с), engine.py:2792
    ├── 13. ui_state.set_speaking(phrase, True)     ← и сразу set_speaking("", False) на 2823
    ├── 14. ui_state.set_radio_message(phrase, voiced)
    ├── 15. ui_state.append_feed({...})
    └── 16. voice.say(phrase, priority, persona)     voice/tts.py:386 — ВОЗВРАЩАЕТ МГНОВЕННО

[поток tts-queue]
  TTSQueue._worker           new_tts/queue_handler.py:77
    ├── critical при enqueue: clear() всей очереди + stop_fn() = _interrupt_playback()
    ├── PriorityQueue(maxsize=8) — при переполнении put_nowait молча ДРОПАЕТ (:47)
    └── Voice._play_blocking (tts.py:462)
          ├── cache hit  → _play_wav(path)              tts.py:642
          └── cache miss → _synthesize()  Yandex → Piper → pyttsx3
                         → _save_wav (сухой, без FX)
                         → _play_wav → radio_fx → sd.OutputStream (под _stream_lock)
```

**Каналов «в железе» три и они не те, что просит ТЗ:** `commentary` / `radio` /
`overlay` (`commentator/channel_router.py:23-25`) — это *способ доставки*
(озвучить длинно / озвучить коротко / только в ленту), а не *кто говорит*.
Голос выбирается отдельно, по полю `event["speaker"]` → `_SPEAKER_VOICE`
(engine.py:2820), и `SPEAKER_ENGINEER` уже маппится в персону `calm`.

---

## 2. Источники инженерских сообщений

Полный список мест, откуда сегодня приходит текст, который игрок слышит как
«инженер». 16 источников, все проверены по коду.

| # | Источник | Event codes | priority | Готовая фраза? |
|---|----------|-------------|----------|----------------|
| 1 | `strategy_ai/spotter.py` | `SPOTTER_CAR_LEFT/RIGHT/BOTH`, `SPOTTER_CLEAR` | **critical** | да, из 4 списков |
| 2 | `strategy_ai/module.py:154` | `STRAT_BOX_CALL_1..3` | **critical** | да |
| 3 | `strategy_ai/module.py:162` | `PIT_CALL_NOTICE` | normal + bypass | да |
| 4 | `strategy_ai/module.py:122` | `PIT_WINDOW_APPROACH` | normal + bypass | да |
| 5 | `strategy_ai/module.py:181` | `STRAT_PIT/UNDERCUT/OVERCUT/SAVE/PUSH/FUEL` | из события | нет → `strategist.py` |
| 6 | `strategy_ai/gap_digest.py` ← `_maybe_emit_gap_digest` (engine.py:2871) | `ENGINEER_GAP_DIGEST` | normal + bypass | да, **с токеном `{ers_clause}`** |
| 7 | `strategy_ai/drs_advisory.py` | `DRS_PROXIMITY_ENTER/EXIT`, `DRS_ALLOWED_ON/OFF`, `..._ENTER_AND_ALLOWED` | normal + bypass | да |
| 8 | `strategy_ai/position_calls.py` | `POSITION_CALL`, `POSITION_CALL_OWN_PIT` | normal | да |
| 9 | `strategy_ai/leader_change.py` | `LEADER_CHANGE` | normal + bypass | да |
| 10 | `strategy_ai/defense.py` | `DEFENSE` | normal + bypass | да |
| 11 | `strategy_ai/weather_advisory.py` | `ENGINEER_RAIN_ADVISORY` | normal | да |
| 12 | `strategy_ai/track_limits.py` | `ENGINEER_TRACK_LIMITS_WARNING`, `ENGINEER_PENA_TRACK_LIMITS` | normal | да |
| 13 | `engine.py::_update_damage` | `DAMAGE_WING/FLOOR/GEARBOX/ENGINE` | normal | нет → LLM/шаблон |
| 14 | `commentator/radio.py::get_radio_line` | всё, что ушло в `CHANNEL_RADIO` без `phrase` | — | да |
| 15 | `commentator/radio_answer.py` | `USER_Q` (PTT) | normal | да, 13 тем + 2 команды |
| 16 | `commentator/brain.py` (LLM) | всё остальное без `phrase` | — | нет, генерация |

Плюс комментаторские источники, которые делят ту же очередь и тот же голос-путь:
`AMBIENT`, `OVTK`, `FTLP`, `COLL`, `RTMT`, `PENA`, `SSTA/CHQF/RCWN`,
`SAFETY_CAR_*`, `RDFL`, `MILESTONE`, `CAREER_*`, `F1_BENCH*`, `STORY`,
`PRE_RACE_PEP_TALK`, `POST_RACE_INTERVIEW`.

**Вывод:** 12 из 16 источников уже отдают готовую короткую детерминированную
строку. Phrase bank де-факто существует, но размазан по `core/strategy_ai/*.py` —
единого места, где можно проверить длину/стиль/варианты, нет.

---

## 3. Текущая система приоритетов

Две независимые оси, которые часто путают.

### 3.1 `priority` — строка в драфте события

Значения ровно два: `"critical"` и `"normal"` (дефолт ставится в
`CommentaryEvent.from_mapping`, commentary_events.py:34).

**Найдено при аудите (не заявлено в ТЗ):** `priority="critical"` присваивается
сырым событиям не по срочности, а по набору
`core/packets.py:190::CRITICAL_EVENTS = {PENA, RTMT, CHQF, RCWN, COLL, SCAR,
RDFL}`. В нём лежат **финиш (CHQF) и определение победителя (RCWN)** — крупные
новости, которым нечего требовать от пилота прямо сейчас. То есть существующий
`priority` — это двухуровневое «важно / обычно», а не «требует реакции сейчас /
потом». Это подтверждает предпосылку ТЗ §6 о четырёх уровнях и означает, что
новый `urgency` не может просто наследовать `priority`: для перечисленных кодов
авторитетом должна быть таблица, иначе право прерывать звучащую фразу получает
половина событий гонки, и спотер тонет в общем потоке.

`priority == "critical"` даёт **четыре** гарантии:
1. `score_importance` флорит importance до `_CRITICAL_FLOOR = 90` (planner.py:101);
2. `SessionGuard.should_emit` возвращает True без cooldown (session_guard.py:100);
3. пропуск `situation_dedup` и flashback-тишины (engine.py:2723, 2728);
4. через importance ≥ 90 → `PLAN_GAP_SKIP_THRESHOLD` (пропуск паузы) и
   `PLAN_INTERRUPT_THRESHOLD` (`voice.say(priority="critical")` → прерывание).

### 3.2 `importance` — число 0..100

`commentator/planner.py:45` — базовая таблица по коду + модификаторы
(+20 игрок, +15 борьба, +10 последние круги, −10 вне гонки), клип [0,100].

Пороги (`config.py`):

| Константа | Значение | Смысл |
|---|---|---|
| `PLAN_BASE_THRESHOLD` | 35 | порог «говорить» в затишье |
| `PLAN_SPIKE_THRESHOLD` | 65 | порог сразу после озвученной фразы |
| `PLAN_THRESHOLD_DECAY_S` | 45 | за сколько спайк спадает к базе |
| `PLAN_STALE_S` | 20 | старше этого + importance < 70 → дроп |
| `PLAN_STALE_IMPORTANCE` | 70 | ниже — работает вытеснение по возрасту |
| `PLAN_GAP_HALF_THRESHOLD` | 80 | пауза режется вдвое |
| `PLAN_GAP_SKIP_THRESHOLD` | 90 | пауза игнорируется целиком |
| `PLAN_INTERRUPT_THRESHOLD` | 90 | `voice.say(priority="critical")` |
| `MIN_COMMENT_GAP` | 9.0 | блокирующая пауза между некритичными |
| `COMMENTARY_MODE_THRESHOLD_OFFSET` | live 0 / calm +20 / story +20 | сдвиг порогов по режиму |

### 3.3 `bypass_speak_threshold` — НЕ приоритет

Освобождает ровно от двух гейтов: `muted_by_threshold` и
`is_stale_backlog_event`. Не освобождает от cooldown, паузы, дедупа и не даёт
прерывания. Это задокументированная ловушка (`CONTEXT.md`, «Известные gotchas»),
и в редизайне её нельзя считать заменой critical.

### 3.4 Приоритет очереди воспроизведения

`TTSQueue` — своя, вторая приоритетная очередь, всего 2 уровня
(`prio = 0 if critical else 1`, queue_handler.py:41). `critical` при постановке
**очищает все ожидающие** и прерывает текущее (`clear()` + `stop_fn()`, :34-40).
Прерванная фраза в очередь не возвращается — это уже соответствует ТЗ §20.4.

---

## 4. Существующие cooldown и дедупликация

Пять независимых механизмов, каждый решает свою задачу:

| Механизм | Файл | Ключ | Окно |
|---|---|---|---|
| Порог важности | `commentary_runtime.py:32` | importance vs динамический порог | спайк 65 → база 35 за 45 с |
| Вытеснение по возрасту | `commentary_runtime.py:44` | `enqueued_at` | 20 с при importance < 70 |
| Per-code cooldown | `session_guard.py:94` | `event_code` | 4–300 с по типу сессии |
| Ситуационный дедуп | `situation_dedup.py:83` | `(сторона, сосед, band гэпа)` | 20 с, **только 4 proximity-кода** |
| Анти-дребезг трекера | напр. `spotter.py:19` | внутреннее состояние трекера | `MIN_REPEAT_S = 3.0` на сторону |

Плюс `MIN_COMMENT_GAP` (не дедуп, а кадансовая пауза) и flashback-тишина.

**Ключевой пробел:** `SituationDedup` покрывает только `OVTK/ATTACK/BATTLE/
ATTACK_ZONE` (`PROXIMITY_CODES`, situation_dedup.py:25). У повреждения,
pit-окна, погодного фронта, фазы Safety Car, штрафного эпизода и запроса пилота
понятия «ситуация» нет вообще — их повторы душатся только per-code cooldown'ом,
то есть по времени, а не по смыслу. Ровно то, что ТЗ §9 требует изменить.

---

## 5. Где фраза может устареть

Полный список задержек между «событие случилось» и «звук пошёл»:

| Этап | Задержка | Ограничена? |
|---|---|---|
| Ожидание в `ImportanceQueue` | не ограничена | только `PLAN_STALE_S`=20 с и только при importance < 70 |
| `MIN_COMMENT_GAP` | **до 9 с блокирующего сна** | пропускается при importance ≥ 90 |
| Ожидание в `TTSQueue` | не ограничена (maxsize 8) | нет |
| Синтез Yandex (сеть) | сотни мс — секунды | нет |
| Последовательное воспроизведение | длительность предыдущих фраз | нет |

**Найдено при аудите (не заявлено в ТЗ):** `_resolve_volatile_phrase` вызывается
на строке **engine.py:2758** — то есть *до* блокирующей паузы `MIN_COMMENT_GAP`
(строка 2792), *до* постановки в `TTSQueue` и *до* синтеза. Механизм позднего
связывания реализован, но подставляет значение не «максимально близко к началу
озвучки» (ТЗ §8), а за 9+ секунд до неё в худшем случае. Само правило
(`CONTEXT.md`, сессия 2026-07-29) верное — недотянута точка применения.

Второе: `enqueued_at` — единственная временна́я метка. Нет ни `created_at`
момента самого события, ни `expires_at`. TTL как понятие отсутствует; его
единственное приближение — `PLAN_STALE_S`, общий для всех кодов и отключаемый
флагом `bypass_speak_threshold`.

---

## 6. Какие состояния уже выводятся в UI

Через `GET /api/state` (`core/ui_state.py`):

| Поле | Форма | Проблема |
|---|---|---|
| `speaking: bool`, `now_speaking: str` | флаг + текст | **фактически ненаблюдаемы** — см. ниже |
| `radio_message: {text, voiced, ts}` | последняя реплика | нет id, канала, срочности, состояния |
| `voice_query: {status, question, answer, error}` | PTT-сеанс | 6 статусов: listening/recognizing/thinking/done/error (+ `null` = idle) |
| `feed: [{time, event_code, phrase, color, driver, muted, channel}]` | общая лента | одна на три экрана, обрезается по `max_feed_items` |

**Найдено при аудите (не заявлено в ТЗ):** `set_speaking(phrase, True)`
(engine.py:2800) и `set_speaking("", False)` (engine.py:2823) разделены только
вызовом `voice.say()`, который **возвращается мгновенно** (кладёт в очередь,
tts.py:406). Флаг `speaking` живёт микросекунды. Оверлей опрашивает состояние
раз в 250 мс (`in-game-overlay.tsx:979`) и делает
`if (nextState.speaking) setRadioUntil(...)` (:966) — почти всегда промахивается.

Следствия, которые видит пользователь:
- карточка рации в игре для **озвученной** реплики чаще всего не показывается
  вообще (показ держится только на ветке `radio_message.voiced === false`,
  in-game-overlay.tsx:857-859, и на PTT-ветке);
- «Комментатор говорит» на «Обзоре» (dashboard.tsx:131) практически не
  загорается.

Это не косметика — это ровно критерий готовности ТЗ №8 («UI ясно показывает,
кто говорит и почему»), и он сегодня не выполняется по причине в бэкенде, а не
во фронте.

**Чего в UI-состоянии нет совсем:** идентификатора сообщения, канала
spotter/engineer/commentator, срочности, времени жизни, состояния
(ожидает/синтезируется/звучит/завершено/отменено/прервано), длины очереди,
факта прерывания, истории радио отдельно от общей ленты событий.

---

## 7. Какие API можно расширить без нарушения совместимости

- **`GET /api/state`** — плоский dict, фронт читает поля по имени и игнорирует
  незнакомые. Новый верхнеуровневый ключ `radio` безопасен. Существующие
  `speaking` / `now_speaking` / `radio_message` / `voice_query` **оставляем на
  месте** (их читают `dashboard.tsx`, `in-game-overlay.tsx`, типы в `lib/api.ts`).
- **Элементы `feed[]`** — новые поля добавляемы: UI уже пережил добавление
  `muted`/`channel` (были в бэкенде раньше, чем в типах — см. `CONTEXT.md`,
  сессия 2026-07-29, п. 2).
- **Новые роуты** — свободно (`web_server.py`, `bottle`). Прецедент:
  `/api/hotkeys/status`, `/api/racefeed/*`.
- **`POST /api/settings`** — новые ключи должны появиться в
  `core/settings.py::DEFAULTS`, иначе `load()`/`save()` их отфильтруют
  (settings.py:81, 93). Это единственная жёсткая точка.
- **Провайдер-паттерн** — `set_hotkey_status_provider` (engine не владеет
  хоткеями, но даёт вход HTTP-слою). Тот же приём применим, если состояние
  радио захочется отдавать из `Voice`/`TTSQueue`, а не из движка.

Ломать нельзя: форму `ptt_hotkey` (`{ctrl, alt, shift, key}`), контракт
`saveSettings() → {ok: boolean}`, `state.connected` как источник истины по UDP.

---

## 8. Какие компоненты UI будут изменены

| Файл | Изменение |
|---|---|
| `NewSpotterUI/lib/api.ts` | типы `radio`, `RadioMessage`, `RadioHistoryItem` |
| `NewSpotterUI/lib/spotter-data.ts` | новый `ViewId` для экрана Team Radio |
| `NewSpotterUI/components/spotter/sidebar.tsx` | пункт навигации |
| `NewSpotterUI/components/spotter/views/team-radio.tsx` | **новый** экран |
| `NewSpotterUI/components/spotter/overlay/in-game-overlay.tsx` | `RadioPanel` (:851-909) + логика показа (:959-1001) |
| `NewSpotterUI/components/spotter/views/settings.tsx` | группа настроек радио |
| `NewSpotterUI/app/globals.css` | токены акцента/срочности, если текущих не хватит |

**Внимание к владению файлами:** `CODEX_CLAUDE_HANDOFF.md` объявляет
`NewSpotterUI/components/spotter/` и `globals.css` зоной Codex, сейчас
разблокированной. Перед правкой UI нужно записать себя владельцем в этом файле.

**Пересборка обязательна:** приложение отдаёт `webui/`, а не `NewSpotterUI/`.
Без `pnpm build` + синхронизации `out → webui` фича физически не доедет до
пользователя (уже случалось — `CONTEXT.md`, сессия 2026-07-29 ночная).

---

## 9. Какие существующие функции нельзя дублировать

Список того, что нужно **расширять**, а не строить рядом:

1. `core/situation_dedup.py` — расширять `signature()` на новые категории, не
   заводить второй дедуп.
2. `core/session_guard.py` — per-code cooldown уже есть; не добавлять третий
   слой поверх.
3. `F1Engine._resolve_volatile_phrase` + `resolve_volatile` — единственный
   механизм позднего связывания; переносить точку вызова, не писать второй.
4. `TTSQueue` critical-прерывание — уже чистит очередь, прерывает поток и не
   возвращает прерванную фразу. Не переписывать.
5. `voice/tts.py` `_stream_lock` + выделенный `sd.OutputStream` — защита от
   двух подтверждённых access violation. Модульные `sd.play/stop/wait` не
   возвращать (`CONTEXT.md`, gotcha).
6. `voice/radio_fx.py` — эффект накладывается при воспроизведении, в кэше
   «сухой» WAV. Не записывать FX в кэш.
7. `TTSCache.version` — любая правка текста, уходящего в TTS, требует бампа
   версии, иначе старые WAV играют вечно (`CONTEXT.md`, «Ферстаппен»).
8. `PENA` ↔ трек-лимиты — отдельного параллельного уведомления не заводить
   (решение пользователя 2026-07-10).
9. `ui_state.set_radio_message` — «System Message»: реплика показывается, даже
   когда не озвучена. Сохранить.
10. `CommentaryEvents.publish` fanout в RaceFeed — любая новая доменная модель
    обязана продолжать кормить `core/racefeed/`.
11. `commentator/channel_router.py::_ALWAYS_OVERLAY` — `CAREER_RECAP` намеренно
    без `phrase` и намеренно молчит. Не «чинить».
12. `core/strategy_ai/spotter.py` — узкое окно 6 м для голоса и широкое 25 м
    для радара это не дублирование, оба нужны.

---

## 10. Сводка находок, которых не было в ТЗ

Три вещи, найденные при аудите; все три влияют на объём работ.

1. **`state.speaking` ненаблюдаем** (см. §6). Без фикса бэкенда любой редизайн
   UI будет рисовать состояние, которое никогда не приходит.
2. **Позднее связывание применяется слишком рано** (см. §5) — до паузы до 9 с и
   до очереди синтеза. Механизм есть, точка вызова не та.
3. **`TTSQueue` молча дропает при переполнении** (`put_nowait` в `except
   queue.Full: pass`, queue_handler.py:47). При `maxsize=8` и всплеске событий
   реплика исчезает без следа в логе и без отметки в UI.

---

## 11. Что НЕ входит в объём

По ТЗ §22: новый TTS-движок, voice cloning, мышь/gamepad для PTT, переработка
RaceFeed, редизайн всех экранов, реорганизация `CONTEXT.md`, git-миграция,
новые внешние telemetry API.

Дополнительно по итогам аудита **не** трогаем: `core/packets.py` (парсинг),
`core/racefeed/*` (кроме сохранения fanout), `commentator/timeline.py`,
`commentator/rag.py`, аналитику и архив.

---

## 13. Хронология пути реплики (Task 4)

Повторная трассировка перед переносом позднего связывания. Столбец «может
измениться» — данные, которые к этой точке уже могли устареть.

| # | Точка | Файл | Может измениться к этому моменту |
|---|---|---|---|
| 1 | Событие опубликовано | `commentary_events.publish` | ничего, это t₀ (`created_at`/`created_mono`) |
| 2 | Событие извлечено из `ImportanceQueue` | `_commentary_loop` | всё volatile: очередь не ограничена по времени |
| 3 | Гейты (threshold, stale, cooldown, dedup) | `_commentary_loop` | — |
| 4 | Текст получен (банк / шаблон / LLM) | `_commentary_loop` | LLM добавляет сетевую задержку |
| 5 | **`_resolve_volatile_phrase` — СЕЙЧАС ЗДЕСЬ** | `engine.py` | ← дефект: ниже ещё четыре ожидания |
| 6 | `RadioMessage` собран | `_build_radio_message` | — |
| 7 | Блокирующая пауза `MIN_COMMENT_GAP` | `_commentary_loop` | **до 9 с** (importance < 90) |
| 8 | `Voice.say` → `TTSQueue.enqueue` | `voice/tts.py` | — |
| 9 | Ожидание в `TTSQueue` (до 8 элементов) | `queue_handler.py` | **секунды-десятки**: воспроизведение последовательное |
| 10 | Воркер взял элемент | `TTSQueue._worker` | — |
| 11 | `normalize(text)` | `_play_blocking` | — |
| 12 | **Вычисление cache key** | `_play_blocking` | ← финальный текст обязан быть готов ДО этой точки |
| 13 | Cache hit → playback | `_play_wav` | — |
| 14 | Cache miss → сетевой синтез Yandex | `_synthesize` | **сотни мс — секунды**, при отвале + retry больше |
| 15 | Запись WAV, playback | `_play_wav` | ← вторая проверка актуальности нужна здесь |

**Целевая точка резолва — между 10 и 11.** Это после обеих очередей и после
паузы, но до cache key и до сети. Вторая проверка — между 14 и 15: Yandex может
вернуть звук, когда сообщение уже неактуально.

Суммарный разрыв между точками 5 и 15 в загруженной гонке — десятки секунд.
Именно поэтому «батарея вечно называет не те цифры»: заряд ERS — единственное
число, успевающее пройти полный цикл разряд-заряд за это время.

---

## 12. Инвентарь источников инженерских реплик (Task 3)

Столбец «Перенесён» — состояние после **завершения переноса (2026-07-31)**.
`core/radio/phrases.py` — банк, трекер отдаёт семантический код, движок
переводит его в `event_code`. Обратной связи «строка → код» не осталось
нигде: последним её местом был выбор `POSITION_CALL_OWN_PIT` по подстроке
«пит-стопа» в тексте, заменён картой `_POSITION_EVENT_CODE`.

### Spotter

| Event code | Источник | Пример | Urgency | Volatile | Ген. | Лимит | Варианты | Перенесён |
|---|---|---|---|---|---|---|---|---|
| `SPOTTER_CAR_LEFT` | `strategy_ai/spotter.py` | «Держи слева!» | critical | нет | детерм. | 5 сл. | по стороне | ✅ `spotter.left` |
| `SPOTTER_CAR_RIGHT` | `strategy_ai/spotter.py` | «Держи справа!» | critical | нет | детерм. | 5 сл. | по стороне | ✅ `spotter.right` |
| `SPOTTER_CAR_BOTH` | `strategy_ai/spotter.py` | «Машины с обеих сторон!» | critical | нет | детерм. | 5 сл. | 2 | ✅ `spotter.both` |
| `SPOTTER_CLEAR` | `strategy_ai/spotter.py` | «Чисто.» | critical | нет | детерм. | 5 сл. | 3 | ✅ `spotter.clear` |

**Ключевой дефект, устранённый переносом:** сторона лежала в общем пуле с
остальными вариантами. Любой выбор из общего списка (случайный или по колоде)
рано или поздно выдал бы «справа» на машину слева. ТЗ §11 запрещает отдавать
сторону генерации — теперь это отдельные спеки, и тест сторожит, что в
`spotter.left` не встречается корень «справ».

### Critical Engineer

| Event code | Источник | Пример | Volatile | Ген. | Лимит | Перенесён |
|---|---|---|---|---|---|---|
| `STRAT_BOX_CALL_1/2/3` | `commentator/templates.py` через `brain._TEMPLATE_ONLY_CODES` | «Бокс, бокс.» | нет | детерм. | 9 сл. | ✅ `box.call_1/2/3` |
| `RDFL` | `commentator/templates.py` | «Красный флаг.» | нет | детерм. | 9 сл. | ✅ `flag.red` |
| `PENA` | `commentator/templates.py` | «Штраф.» | нет | детерм. | 9 сл. | ✅ `penalty.received` |
| `DAMAGE_*` (severity ≥ 70) | `core/engine.py` | «Крыло разбито. Нужен бокс.» | нет | детерм. | 9 сл. | ✅ `damage.*_critical` |

### High Engineer

| Event code | Источник | Пример | Volatile | Ген. | Лимит | Перенесён |
|---|---|---|---|---|---|---|
| `DAMAGE_WING/FLOOR/GEARBOX/ENGINE` | `core/engine.py::_DAMAGE_PHRASE_POOLS` | «Повреждено крыло!» | нет | детерм. | 14 сл. | ✅ `damage.*` |
| `ENGINEER_RAIN_ADVISORY` | `strategy_ai/weather_advisory.py` | «Дождь через 5 минут…» | minutes | детерм. | 14 сл. | ✅ `weather.rain_soon`; `_phrase()` удалён, `minutes` переведён в **volatile** — горизонт обновляется перед озвучкой |
| `PIT_WINDOW_APPROACH` | `strategy_ai/pit_window.py` | «Приближаемся к окну пит-стопа.» | нет | детерм. | 14 сл. | ✅ `box.window_approach` через поле `phrase_code` события |
| `SAFETY_CAR_DEPLOYED/ENDING/CLEAR` | `commentator/templates.py` | «Safety Car на трассе» | нет | детерм. | 14 сл. | ✅ спеки `flag.safety_car_*` |
| `ENGINEER_TRACK_LIMITS_WARNING` | `strategy_ai/track_limits.py` | «Осторожно с лимитами трассы.» | нет | детерм. | 14 сл. | ✅ `track_limits.warning`, 4 варианта вместо одной строки |
| `TYRE_WARN` | `commentator/radio.py` | «Шины на пределе.» | нет | детерм. | 14 сл. | ⏳ спека есть (`tyres.cliff`), пул остался в `radio.py` |

**`ENGINEER_PENA_TRACK_LIMITS` намеренно НЕ получил своей спеки.** Штраф за
трек-лимиты уже объявляет `penalty.received`; вторая реплика про тот же инцидент
спорила бы с первой (предупреждение пользователя 2026-07-10, `CONTEXT.md`). В
банке есть только ЖИВОЕ предупреждение до штрафа — `track_limits.warning`.

### Normal Engineer

| Event code | Источник | Пример | Volatile | Ген. | Лимит | Перенесён |
|---|---|---|---|---|---|---|
| `ENGINEER_GAP_DIGEST` | `strategy_ai/gap_digest.py` | «Отрыв впереди: 1.3. {ers_clause}» | gap, ers | детерм. | 18 сл. | ⏳ спеки есть (`gap.digest`, `ers.level`), сборка осталась в трекере. Причина не в лени: сводка **склеивается из частей** (гэп впереди + гэп сзади + тренд + ERS + сравнение секторов), и её нельзя выразить одним вариантом банка. Перенос требует композиции фрагментов — отдельная задача |
| `DRS_PROXIMITY_ENTER/EXIT`, `DRS_ALLOWED_ON/OFF`, `..._ENTER_AND_ALLOWED` | `strategy_ai/drs_advisory.py` (5 массивов) | «Ты в зоне DRS.» | нет | детерм. | 18 сл. | ✅ `drs.*` |
| `DEFENSE` | `strategy_ai/defense.py::_DEFENSE_PHRASES` | «Удержал позицию.» | нет | детерм. | 18 сл. | ✅ `battle.held` |
| `POSITION_CALL`, `POSITION_CALL_OWN_PIT` | `strategy_ai/position_calls.py` | «Ты пятый.» | position | детерм. | 18 сл. | ✅ `position.current` / `position.after_pit`; `event_code` берётся из карты `_POSITION_EVENT_CODE`, а не из подстроки текста |
| `LEADER_CHANGE` | `core/engine.py` (f-строка) | «Новый лидер гонки — Норрис.» | rival | детерм. | 18 сл. | ✅ `position.leader_change`|
| `PIT_EXIT` | `commentator/templates.py` | «Вышел из боксов…» | нет | детерм. | 18 сл. | ✅ `box.exit`|
| `STRAT_*` (PIT/SAVE/PUSH/FUEL/UNDERCUT/OVERCUT) | `commentator/{radio,strategist}.py` | «Береги шины.» | нет | детерм. | 18 сл. | ⏳ спеки частично (`fuel.*`, `tyres.*`), пулы остались в commentator |
| `ATTACK`, `BATTLE` | `commentator/engineer.py` | «{driver} атакует…» | rival, gap | детерм. | 18 сл. | ⏳ спека `battle.defend`; `engineer.py` — другая ось ключей, см. ниже |
| `PRE_RACE_PEP_TALK` | `commentator/pre_race_pep_talk.py` | «Работаем по плану.» | нет | детерм. | 18 сл. | ⏳ спека есть (`session.pep_talk`) |

### PTT answers — граница, не переработка (Task 5)

`commentator/radio_answer.py`: 13 тем + 2 голосовые команды, ответы собираются из
снимка телеметрии функциями `_gap_answer`/`_tyres_answer`/… Это **вычисление
ответа**, а не формулировка: перенос в банк требует сначала развести «что
ответить» и «как сказать», иначе в банк уедет бизнес-логика. Task 3 добавляет
только `ACKNOWLEDGEMENTS` и `NO_DATA_ANSWERS` — короткие подтверждения и честный
отказ по ТЗ §12. Полная переработка — Task 5.

### Companion / commentator — сознательно НЕ переносим

`commentator/radio.py` (пулы по `event_code`), `commentator/engineer.py`
(тактические реплики race_ai с подстановкой поворота/гэпа/износа),
`commentator/strategist.py`, `commentator/templates.py` (общий шаблонный фолбэк,
62 КБ).

Причина: у них другая ось ключей и другой владелец. `engineer.py` ключуется по
типу события race_ai × фазе поворота × `defense_advice`; загонять это в
`[код].[ситуация]` значило бы исказить обе структуры. Это подсистема
комментатора, а не радио-канала инженера, и ТЗ §22 запрещает переработку всего
пайплайна комментария в этой задаче.

Критерий «детекторы больше не владеют массивами формулировок» при этом
выполнен: массивы были в `strategy_ai/{spotter,drs_advisory,defense}.py` и
`core/engine.py::_DAMAGE_PHRASE_POOLS` — все четыре перенесены. Остальное —
одиночные строки и f-строки в трекерах либо пулы в подсистеме комментатора.
