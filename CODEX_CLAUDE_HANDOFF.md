# Codex ↔ Claude Code — рабочий контекст

Этот файл — короткий канал передачи работы между Codex и Claude Code. Он не заменяет
`CONTEXT.md`: здесь хранится только активная зона ответственности, изменённые контракты,
проверки и следующий шаг совместной работы.

## Правила совместной работы

- Проект не находится под Git: не редактировать один файл одновременно из двух сессий.
- Перед началом работы отметить владельца файлов в разделе «Активная работа».
- Codex владеет визуальным слоем `NewSpotterUI/components/spotter/` и дизайн-токенами
  `NewSpotterUI/app/globals.css`, пока активная задача ниже не закрыта.
- Claude Code может параллельно работать с Python/backend, но не менять перечисленные
  UI-файлы без записи в этот файл.
- Изменение JSON/API-контракта сначала фиксируется в разделе «Контракты», затем обе
  стороны обновляют свои слои последовательно.
- После передачи: перечислить файлы, команды проверки, известные ограничения и точный
  следующий шаг. Не копировать сюда длинную историю сессий.

## Активная работа

**Владелец:** нет (файлы разблокированы) — Broadcast Team Radio Overlay закрыт.
**Изменены:** `core/radio/{speakers.py (новый),session,message,policy}.py`,
`core/{ui_state,settings,overlay_window}.py`, `web_server.py`, `SpotterApp.spec`,
`assets/radio/README.md` (новый), `tests/test_radio_projection.py` (новый),
`tests/test_radio_{session,ptt_dialogue}.py` (расширен контракт секции),
`NewSpotterUI/lib/{api,radio-ui (новый)}.ts`,
`NewSpotterUI/components/spotter/overlay/{in-game-overlay,broadcast-radio-card (новый)}.tsx`,
`NewSpotterUI/components/spotter/views/team-radio.tsx`, `webui/` (73/73, SHA diff 0).

### Контракт после Broadcast Radio Overlay

- Секция `radio` выросла на `revision` и `speakers`; `active_message` и строки
  истории несут `speaker_id/name/role/accent` (+ `speaker_initials`,
  `portrait_url` у активного). Тесты, фиксирующие набор ключей секции, —
  `test_radio_session.py::test_projection_has_the_documented_shape` и
  `test_radio_ptt_dialogue.py::test_state_exposes_the_radio_section`.
- `GET /api/state?radio_since=<revision>` при совпадении отдаёт
  `radio.history: null` + `history_unchanged: true`. Без параметра — как раньше.
- `revision` двигать ТОЛЬКО при видимом изменении. `updated_at` в сравнении PTT
  не участвует, иначе счётчик растёт на каждом опросе.
- `policy` и `speakers` не импортируют друг друга. Совпадение `short_label` и
  `voice_persona` держит тест `test_profiles_agree_with_the_pipeline_contract`.
- Персона комментатора приходит провайдером из `web_server.create_app`. Инженер
  и споттер её игнорируют — есть тест на все четыре персоны.
- Отступ карточки 290 продублирован в `core/overlay_window.py::place_over` и в
  `DEFAULT_LAYOUT`/`fittedDefaultLayout()`. Менять только парой.
- В оверлей карточка идёт с `width: "100%"`: `vw` там считается от нативного
  окна, а не от экрана.
- Ключи `show_*`/`radio_card_*`/`subtitle_size`/`remember_overlay_position` —
  ТОЛЬКО показ. Ни один не отключает звук.
- `assets/radio/` пустая намеренно; имена файлов — в её README и в
  `speakers.py`. `SpotterApp.spec` уже включает папку в `datas`.

**Внимание следующей сессии:** полный `pytest` на момент передачи НЕ зелёный —
9 падений в `tests/test_{position_calls,track_limits}.py` от параллельной работы
по переносу фраз в банк (детекторы отдают семантический код, тесты ждут строку).
К этой задаче отношения не имеют; области, затронутые здесь, — 846 passed.

Предыдущая запись:

---

**ВТОРОЙ ВЛАДЕЛЕЦ (параллельно):** Claude Code — перенос оставшихся источников
фраз в банк. **Работа ЗАВЕРШЕНА 2026-07-31**, но владение СОХРАНЯЕТСЯ до конца
задачи выше (решение пользователя): пока Broadcast Overlay в работе, эти файлы
не должна брать третья сессия.
**Занятые файлы:** `core/radio/phrases.py`, `core/strategy_ai/{weather_advisory,
pit_window,track_limits,position_calls,leader_change,module}.py`,
`core/engine.py`, `tests/test_radio_phrases*.py`,
`tests/test_{weather_advisory,track_limits,position_calls,strategy_ai,
engine_planner,engine_position_calls,engine_pit_window_approach}.py`.
**Начато:** 2026-07-30. **Вторая волна (2026-07-31):** доперенос остатка —
`commentator/{radio,strategist,pre_race_pep_talk}.py` и композиция
`gap_digest`. Дополнительно заняты эти три файла + `core/radio/resolver.py`.
**Пересечения с задачей выше:** НЕТ. `core/radio/{speakers,session,message,
policy}.py`, `core/{ui_state,settings}.py`, `web_server.py`, UI и `webui/` не
трогаю. Если понадобится новая категория в `policy.py` — сначала запись здесь.
**Осторожно обеим сторонам:** обе сессии пишут в `core/radio/`, а проект не под
git. Полный `pytest` в этот период — ненадёжный сигнал (см. gotcha про
параллельные сессии в `CONTEXT.md`); падение сначала перепроверять изолированно.
Реальный случай 2026-07-31: тест упал на строке банка, которой уже не было ни в
одном варианте — прогон шёл против состояния файла, изменённого между чтением и
запуском. Тест оказался просто устаревшим, но зелёный результат в такие моменты
держится на удачном тайминге, а не на корректности.

### Контракт после переноса фраз (2026-07-31)

- Обратной связи «строка → код» не осталось нигде. Последним её местом был
  выбор `POSITION_CALL_OWN_PIT` по подстроке «пит-стопа» в тексте — заменён
  картой `core/engine.py::_POSITION_EVENT_CODE`. Не возвращать: любая правка
  формулировки молча меняла тип события.
- Трекеры `weather_advisory` / `track_limits` / `pit_window` / `position_calls`
  возвращают СЕМАНТИЧЕСКИЙ КОД. `weather_advisory._phrase()` удалён.
- Событие может нести `phrase_code` вместо `phrase` — движок рендерит его при
  публикации (`core/engine.py`, цикл по `strategy_result.events`). Так сделано
  для `core/strategy_ai/module.py`: он чистый и не знает `dedupe_key`, из
  которого берётся стабильный выбор варианта.
- `weather.rain_soon`: `minutes` — **volatile**, не required. Горизонт дождя
  обновляется перед озвучкой; при пропаже прогноза реплика отменяется целиком.
- Числовой токен раскрывается вместе с единицей (`resolver._format`). Шаблон
  единицу НЕ дописывает — иначе «через 5 минут минут».
- НЕ перенесены сознательно: `commentator/{radio,engineer,strategist,templates,
  pre_race_pep_talk}.py` (другой владелец и другая ось ключей) и
  `gap_digest` (сводка склеивается из частей, нужен механизм композиции).

---

ТЗ пользователя от 2026-07-30 заменяет UI-часть Task 5–7 прежнего плана и
добавляет поверх закрытого редизайна: speaker profiles (имя/роль/портрет/акцент),
`revision` в проекции, отдачу портретов, `answer_message_id`, Broadcast Radio Card
снизу по центру, компактный вариант споттера, preview-сценарии `?preview=radio-*`,
настройки представления. План: `C:\Users\Artem\.claude\plans\rippling-launching-snowglobe.md`.

**Предыдущая задача:** Team Radio redesign — все 8 задач закрыты 2026-07-30.
UI-файлы освобождены после Task 8, как и обещано при захвате.

Изменённый визуальный слой: `NewSpotterUI/components/spotter/views/team-radio.tsx`
(новый экран «Рация»), `overlay/in-game-overlay.tsx` (карточка рации),
`sidebar.tsx` (пункт навигации), `lib/{api,spotter-data}.ts`, `app/page.tsx`,
`webui/` (пересобран, 73/73, SHA-256 diff = 0). `globals.css` и `ui.tsx` НЕ
менялись — существующие токены уже соответствовали визуальному брифу.

**Предыдущая задача:** Team Radio redesign, Task 3 (Engineer Phrase Bank) +
Task 4 (позднее связывание, TTL, актуальность) + Task 5 (PTT-диалог, история).
Спека: `docs/superpowers/specs/2026-07-29-f1-manager-radio-redesign.md`.
План: `docs/superpowers/plans/2026-07-29-f1-manager-radio-redesign.md`.
**Статус:** Task 1–4 закрыты 2026-07-30, полный `pytest` зелёный
(3125 passed, 1 skipped). Живой проверки в F1 25 не было. Следующий шаг —
Task 5 (PTT-диалог и история радио), он снова тронет `core/engine.py`,
`core/radio/*`, `commentator/radio_answer.py` и UI-слой.

### Контракт после Task 3

- `core/radio/phrases.py` — единственный банк формулировок инженерского
  радио-канала. Реестр `PhraseSpec` по semantic code `<секция>.<ситуация>`.
- Детекторы (`strategy_ai/{spotter,drs_advisory,defense}.py`) возвращают
  СЕМАНТИЧЕСКИЙ КОД, не строку. Движок переводит код в `event_code` через
  `_SPOTTER_EVENT_CODE` / `_DRS_EVENT_CODE`. Обратно (строка → код) больше не
  сравнивать — так было и это молча ломалось при правке текста.
- Выбор варианта детерминирован: `phrases.select_variant` берёт индекс из crc32
  стабильного ключа (`dedupe_key` события). `random` в банке и детекторах
  запрещён, есть тест. Один `dedupe_key` = одна формулировка.
- Волатильные токены (`{gap}`, `{ers}`, `{position}`) НЕ разрешаются при
  рендере — они доживают до Task 4. Есть тест на то, что даже переданное
  значение не подставляется.
- `allow_llm=True` есть ровно у одной спеки (`ambient.calm`), есть тест.
- `damage_severity >= policy.CRITICAL_DAMAGE_SEVERITY` переключает спеку на
  `damage.*_critical` (только крыло и двигатель — им нужен немедленный бокс).
- Числовой токен раскрывается в УЖЕ СОГЛАСОВАННЫЙ фрагмент вместе с единицей
  («5 минут», «48 процентов»). Шаблон единицу не дописывает — иначе «через
  1 минут». Есть тест.

### Контракт после Task 4

- `core/radio/resolver.py::resolve_for_playback` — ЕДИНСТВЕННАЯ точка финального
  разрешения волатильных данных. Вызывается воркером `TTSQueue` через колбэк
  `prepare()`. Не переносить раньше: смысл именно в том, что позади остались и
  пауза `MIN_COMMENT_GAP`, и очередь воспроизведения.
- Политики полей — `FieldPolicy` в том же модуле. Новое волатильное поле
  добавляется в `_FIELD_POLICY` + `_MISSING_POLICY` + `_SANITY` + `_SNAPSHOT_KEY`,
  иначе оно молча не обновится.
- `_volatile_snapshot()` в движке — источник для резолвера. Новый guard требует
  новых ключей именно там.
- Отмена всегда несёт `RadioCancelReason`; `with_state(CANCELLED)` без причины
  бросает `ValueError`.
- `speaking` поднимает `Voice._notify_playback("playing")` из реального
  `stream.start()`. Не возвращать паттерн `set_speaking(True)/say()/
  set_speaking(False)` — `say()` возвращается мгновенно.
- `timeline_revision` входит ТОЛЬКО в `dedupe_key`, никогда в `situation_id`.
- Гэп в снимке — в МИЛЛИСЕКУНДАХ (санитарный диапазон 0..600000).

**Файлы разблокированы.** Изменены в Task 3–4: `core/radio/*.py` (новые
`phrases.py`, `resolver.py`), `core/strategy_ai/{spotter,drs_advisory,defense,
weather_advisory,box_call,module,gap_digest}.py`, `core/engine.py`,
`core/racefeed/models.py`, `new_tts/queue_handler.py`, `voice/tts.py`,
`tests/test_radio_*.py`, `tests/test_{spotter,drs_advisory,engine_damage}.py`.

Task 1–2 (аудит + доменная модель и очередь) — детали в `CONTEXT.md`, сессия
2026-07-29 «Team Radio в стиле F1 Manager».

Предыдущая задача (для истории):

**Владелец:** нет (файлы разблокированы)  
**Последняя задача:** RaceFeed — карьерные истории (3-й из 4 пунктов; comments-UI
и разнообразие постов уже были готовы к моменту исследования — см. историю
ниже). Спека: `docs/superpowers/specs/2026-07-22-racefeed-career-stories-design.md`.
План: `docs/superpowers/plans/2026-07-22-racefeed-career-stories.md`.  
**Статус:** code-complete, полный `pytest` зелёный (1863 теста, 0 ошибок/фейлов,
1 skip), 2026-07-23. Файлы разблокированы: `core/engine.py`,
`core/racefeed/engine.py`, `commentator/channel_router.py`,
`tests/test_engine_career_memory.py`, `tests/test_channel_router.py`,
`tests/racefeed/test_story_builder.py`,
`tests/racefeed/test_career_recap_integration.py` (новый). Живая проверка на
реальной гонке F1 25 (побить личный рекорд + финишировать) ещё не выполнена.

### RaceFeed-контракт после этой правки

- `CAREER_PB`/`CAREER_SECTOR_PB` (`core/engine.py::_update_career_memory`)
  теперь несут `vehicle_idx=self._player_car_index` + сырые числа (`gap_ms`,
  `player_best_ms`, `best_ever_ms`, `best_ever_date`, `sector`,
  `sector_gap_ms`, `sector_player_ms`). Это исправило реальный баг:
  `_event_involves()` не видел эти события как относящиеся к игроку без
  `vehicle_idx`. Побочный эффект (согласован с пользователем, принят как
  желаемый второй фикс, не регрессия): важность в голосовом комментаторе
  выросла (CAREER_PB 55→75, CAREER_SECTOR_PB 45→65) из-за
  `score_importance()`'s `+20 player-involved` бонуса.
- **Идентичный баг (`vehicle_idx` отсутствует) есть у `F1_BENCH`/
  `F1_SECTOR_BENCH` (`core/engine.py:~1844-1871`) — сознательно НЕ исправлен**,
  отдельный follow-up при желании.
- Новое: `self._career_pb_this_race: bool` — `True` если в текущей гонке уже
  был личный рекорд (круг/сектор), сбрасывается на `SSTA`.
- Новое: `core/engine.py::_publish_career_recap()` — публикует `CAREER_RECAP`
  один раз на финише гонки (вызывается из `_generate_story`), с важностью
  90 (подиум)/70 (личный рекорд ИЛИ лучше прошлого визита по времени/позиции)/
  40 (обычный финиш, ниже `PUBLISH_THRESHOLD=60`, гасится Editor'ом). Несёт
  `vs_last_visit`/`career_stats` целиком для контекста LLM.
  **`CAREER_RECAP` намеренно НЕ несёт `phrase`** и явно маршрутизируется в
  `CHANNEL_OVERLAY` (`commentator/channel_router.py::_ALWAYS_OVERLAY`) — без
  этого событие уходило в обычный голосовой конвейер и при подиуме (important=90
  = `PLAN_INTERRUPT_THRESHOLD`) могло прервать Post-Race Story приоритетом
  `critical`. Не убирать эту маршрутизацию и не добавлять `phrase` этому коду.
  Известное, принятое ограничение: ручной `generate_story_now()` может
  теоретически опубликовать `CAREER_RECAP` дважды с разной важностью, если
  `_final_classification` придёт поздно между вызовами — не исправлено,
  задокументировано в docstring `_publish_career_recap`.
- `core/racefeed/engine.py::StoryBuilder`: `_PLAYER_ONLY_CODES` теперь
  включает `CAREER_PB`/`CAREER_SECTOR_PB`/`CAREER_RECAP` → категория
  `player_progression` (была зарезервирована, но не использовалась). Для ЭТОЙ
  категории (и только для неё) `story_key` включает `event_code` в качестве
  суффикса — три эти кода для одного игрока иначе схлопывались бы в одну
  историю и Scheduler (`ignore_if_pending`) молча терял бы второе/третье
  событие. Другие категории (`safety_car` и т.д.) этот суффикс не получают —
  их поведение (одна эволюционирующая история через несколько стадий)
  сохранено намеренно, не трогать.

Предыдущая задача (для истории):

**Владелец:** нет (файлы разблокированы)  
**Последняя задача:** RaceFeed — прогрессивное появление комментариев
(comments уже были полностью реализованы Codex — панель, аватары, вложенные
ответы — параллельно с брейнштормом этой задачи; итоговый скоуп сузился до
одного: комментарии должны появляться постепенно по `created_at`, а не все
сразу). Спека (с пометкой о пересечении и сузившемся скоупе):
`docs/superpowers/specs/2026-07-22-racefeed-comments-ui-design.md`. План:
`docs/superpowers/plans/2026-07-22-racefeed-comments-progressive-reveal.md`.  
**Статус:** code-complete, `tsc --noEmit` и `pnpm build` зелёные, 2026-07-22.
Файлы разблокированы: `NewSpotterUI/lib/spotter-data.ts`,
`NewSpotterUI/lib/racefeed.ts`, `NewSpotterUI/components/spotter/views/race-feed.tsx`.
`race-feed-channel.tsx` не менялся. Живая проверка на реальной гонке F1 25 ещё
не выполнена — см. план, Task 3, шаг 2.

### RaceFeed-контракт после этой правки

- `RaceFeedComment.revealAt: number` (сырые epoch-секунды, = `created_at`) —
  новое поле рядом с уже существующим форматированным `time: string`.
- `race-feed.tsx` фильтрует `post.comments` по `revealAt <= Date.now()/1000`
  ДО передачи в `RaceFeedChannel` — сам `race-feed-channel.tsx` ничего не
  знает о таймингах, просто рендерит переданный (уже отфильтрованный) массив.
  Если `race-feed-channel.tsx` меняется в будущем, важно не сломать эту
  границу (не читать `comments` где-то ещё в обход `race-feed.tsx`).

Следующие три запланированные доработки (не начаты): разнообразие постов
(format_id/angle_id уже есть как поля, но реального разнообразия форматов
пока нет — Editor/Reporter всегда отдают дефолт), карьерные истории, скрины
гонок.

Предыдущая задача (для истории):

**Владелец:** Codex  
**Задача:** PTT — свободный выбор одиночной клавиши или комбинации.  
**Статус:** code-complete, проверено и передано, 2026-07-21. Файлы разблокированы.

План:

1. `RegisterHotKey` теперь принимает PTT с `mods=0`: одиночная клавиша допустима.
2. Каноническая таблица охватывает буквы/цифры, F1–F24, Space/Enter/Esc/Tab,
   navigation/editing, numpad, punctuation, browser и media keys.
3. UI захватывает физический `KeyboardEvent.code`, поэтому раскладка языка не меняет
   выбранную физическую клавишу.
4. Чистые Ctrl/Alt/Shift и неизвестные системные клавиши не сохраняются.
5. `Ctrl+Alt+C/P/T/X/S/O` по-прежнему защищены от коллизии.
6. Production export синхронизирован в `webui/`.

### PTT binding-контракты

- JSON shape не менялся: `ptt_hotkey = {ctrl, alt, shift, key}`; `key` теперь
  canonical name (`SPACE`, `ARROW_UP`, `NUM7`, `SEMICOLON`, `MEDIA_PLAY_PAUSE`, etc.).
- Бинд применяется после перезапуска приложения, как и раньше.
- Одиночная клавиша глобальная; UI предупреждает не выбирать управление болидом.
- Мышь/gamepad/DirectInput-кнопки этим контрактом не охвачены; это отдельный input stack.

### Проверки PTT binding

- Полный `py -3.12 -u -m pytest -q` — зелёный, 1 skip; прежние YandexSpeech warnings.
- `pnpm exec tsc --noEmit` и `pnpm build` — успешно.
- `NewSpotterUI/out` → `webui/`: 64 файла, SHA-256 diff = 0.

Изменены: `core/{hotkeys,settings}.py`, `tests/test_hotkeys.py`,
`NewSpotterUI/components/spotter/views/hotkeys.tsx`, production export `webui/`.

### Overlay-контракты

- Native lifecycle: `app.pyw` создаёт `Spotter Overlay`; закрытие основного окна уничтожает
  overlay, чтобы pywebview event loop не зависал.
- `core/overlay_window.py` — единственный владелец Win32 стилей click-through/edit mode.
- `Ctrl+Alt+O` зарезервирован; PTT UI считает его занятой фиксированной комбинацией.
- Overlay не показывает telemetry HUD без `state.connected`, кроме явного edit mode;
  серверный offline-индикатор остаётся видимым.
- `?preview=1` — локальный визуальный fixture, сеть/API не мутирует.

### Проверки overlay

- `py -3.12 -u -m pytest -q` — зелёный, 1 skip; только известные YandexSpeech warnings.
- `pnpm exec tsc --noEmit` и `pnpm build` — успешно; static route `/overlay` создан.
- `NewSpotterUI/out` → `webui/`: 64 файла, SHA-256 diff = 0.
- Визуально проверено на 1920×1080 и 1280×720.

Изменены: `app.pyw`, `core/{overlay_window,hotkeys,runtime}.py`,
`NewSpotterUI/app/{globals.css,overlay/page.tsx}`,
`NewSpotterUI/components/spotter/overlay/in-game-overlay.tsx`,
`NewSpotterUI/components/spotter/views/hotkeys.tsx`, `NewSpotterUI/lib/spotter-data.ts`,
`tests/test_{app_overlay_entrypoint,overlay_window}.py`, production export `webui/`.

Ограничение живой проверки: обычное desktop-overlay окно рассчитано на borderless/windowed
режим игры; exclusive fullscreen может перекрыть его на уровне DirectX compositor.

### RaceFeed-контракты после передачи

- `RaceFeedEngine.start()` пассивен до первого race-сигнала; `reset()` открывает новую
  сессию и отбрасывает старые queue/scheduler/memory/editor данные.
- `RaceFeedEngine.stop()` возвращает `bool`: `False` означает, что worker ещё жив и
  владелец не должен терять ссылку.
- `Candidate` несёт snapshots фактов/history и editorial metadata
  (`format_id`, `angle_id`, `claim_fingerprint`).
- `Post` и SQLite row несут `session_id`, `story_stage` и те же editorial metadata.
- `storage.save_publication()` — единая транзакционная граница Story+Post.
- `/api/racefeed` объединяет persisted rows с временными in-memory posts без дублей.
- Golden race должен оставаться в диапазоне 15–25; не заменять его тестом на уникальный
  `story_id`, потому что один Story законно публикуется в нескольких stages.

### Проверки RaceFeed

- Focused RaceFeed/engine suite — зелёный.
- Полный `py -3.12 -u -m pytest -q` — зелёный, 1 skip; известные YandexSpeech warnings.
- `pnpm exec tsc --noEmit` — успешно.
- `pnpm build` — успешно.
- `NewSpotterUI/out` → `webui/`: 52 файла с одинаковыми SHA-256.

Следующий безопасный шаг Claude Code: только живая гонка F1 25 с включённым RaceFeed.
Проверить фактическое количество/ритм постов, YandexGPT-тексты, смену форматов и отсутствие
публикаций после SEND. Не переделывать deterministic Editor в LLM-решение.

## Контракты

- Отображаемые имена и исходные данные не меняются: фонетические формы существуют только
  внутри TTS-препроцессоров.
- Yandex получает `С+ерхио П+ерес`, `Л+андо Н+оррис`, `Макс Ферст+аппен`; правило фамилий
  сохраняется в падежах (`П+ереса`, `Н+орриса`, `Ферст+аппена`).
- Piper получает `Серхйо` и `Ландъо`; фамилии остаются без respell, поскольку espeak уже
  ставит в них правильное ударение.
- Латинские имена всех известных пилотов 2025/2026 нормализуются на общей границе обоих
  TTS; диакритика Jolpica учитывается (`Sergio Pérez` → `Серхио Перес`).
- Версия дискового TTS-кэша — `yandex-v6`; возвращать старую нельзя, иначе снова заиграют
  WAV с побуквенным чтением латиницы.

Предыдущие UI-контракты:

- Backend API не меняется.
- Используются существующие `GET /api/state` и `POST /api/settings`.
- `saveSettings()` возвращает `{ ok: boolean }`; UI обязан считать `ok !== true` ошибкой.
- Источник истины для live-состояния: `state.connected` (UDP F1), для доступности локального
  сервера: `online` из `useSpotterState()`.
- Значения `strategy_ai`/`track_ai`/`coach_ai` не считаются актуальными при
  `state.connected === false`, даже если объект содержит backend-дефолты.

## Передача Claude Code

UI-файлы разблокированы: Codex завершил запись. Перед новым изменением Claude Code должен
назначить себя владельцем здесь, чтобы следующая сессия Codex не начала параллельную запись.

Следующий безопасный шаг для Claude Code: не менять фонетические формы без проверки
`piper.phonemize_espeak`. При следующем живом запуске попросить пользователя прослушать
фразу «Серхио Перес атакует Ландо Норриса, Макс Ферстаппен впереди». Если останется
акустический дефект, приложить конкретный аудиофрагмент и имя реально выбранного движка.

## Последний итог

Codex завершил TTS-проход:

- `core/pronunciation.py`: добавлены явные ударения Yandex для трёх полных имён и падежей.
- `new_tts/ru_textnorm.py`: только Серхио и Ландо получили проверенные Piper-respell с
  сохранением регистра; Перес, Норрис и Ферстаппен оставлены без лишних искажений.
- `core/transliterate.py` + `core/f1_metadata.py`: полные имена, фамилии, регистр и
  диакритика Jolpica нормализуются единообразно; имя больше не сокращается до фамилии.
- `voice/tts.py`: кэш поднят до `yandex-v6`.
- Регрессионный тест на фактическое `Sergio Pérez` сначала воспроизвёл утечку латиницы,
  после фикса прошёл. Расширенный прогон — 122/122; полный `pytest -q` — зелёный (1 skip).

Предыдущий UI-итог:

Codex завершил дизайн-проход:

- `sidebar.tsx`: 11 плоских англоязычных пунктов сгруппированы в четыре русских раздела.
- `dashboard.tsx`: оставлены только быстрые race-time действия; без UDP показывается единый
  empty-state вместо фиктивных значений стратегии/коуча/телеметрии.
- `settings.tsx`: все подробные режимы перенесены в один блок; добавлены optimistic update,
  статус сохранения и откат значения при ошибке API.
- `topbar.tsx` + `statusbar.tsx`: одна health-панель с понятными названиями; нижняя строка
  больше не дублирует ONLINE/OFFLINE и LLM.
- `globals.css` + `ui.tsx`: разделены brand/destructive цвета, уменьшен letter-spacing,
  переключатели поддерживают disabled-состояние.
- `page.tsx`: CPU/RAM без данных показывают `—`, а не ложные `0%`.
- `NewSpotterUI/out` синхронизирован в `webui/`; обе папки содержат 52 одинаковых файла
  (SHA-256 diff = 0). Старые build-id/chunk-файлы в `webui/` удалены зеркальной синхронизацией
  и восстанавливаются обычной `pnpm build` + sync.

Проверки:

- `pnpm exec tsc --noEmit` — успешно.
- `pnpm build` — успешно, static export создан.
- Production UI проверен визуально на 1280×720: Dashboard и Settings.
- `pnpm lint` не запускался: существующий script вызывает `eslint .`, но `eslint` отсутствует
  в `devDependencies`/локальном PATH. Это инфраструктурный пробел, не ошибка текущего кода.

Ограничение: live-состояние с настоящей F1 25 телеметрией не проверялось; нужен следующий
живой запуск пользователя или Claude Code через основной `web_server.py`.
