# Post-Race Story Mode — Design Spec

**Дата:** 2026-06-29
**Статус:** утверждён (дизайн), готов к плану реализации
**Источник:** killer-фича из конкурентного анализа (никто из Crew Chief / DRE / Trophi / SimHub этого не делает).

## 1. Обзор

После финиша гонки приложение генерирует короткий голосовой **итог-репортаж** в духе
гоночного журналиста: как сложилась гонка игрока (старт → ключевые моменты → финиш),
озвучивает его через TTS и показывает текстом в панели Debrief. Цель — emotional hook и
replayability: захотеть переиграть, чтобы услышать другую историю.

Опирается на УЖЕ собираемые данные (SessionRecorder, DriverCoach, RaceTimeline, grid,
analytics_context). Никаких новых источников телеметрии.

## 2. Цели и не-цели

**Цели**
- Авто-генерация на финише гонки (CHQF, только session_type == "race").
- 3–5 предложений (~25–40 с TTS), тон — ретроспектива в стиле текущей персоны.
- Только реальные факты гонки (анти-галлюцинация): старт/финиш-позиции, лучший круг,
  ключевые обгоны игрока с именами, штрафы/сходы, слабый сектор/консистентность.
- Офлайн-фолбэк: при недоступном LLM — шаблонный итог из тех же фактов.
- Показ в Debrief + кнопка «Переозвучить»; ручной триггер «Сгенерировать итог».
- Персист истории в архив сессии.

**Не-цели (YAGNI для v1)**
- История для практики/квалификации (только гонка).
- Мульти-сегментный/«главами» рассказ — один цельный блок.
- Отдельный кастомный голос для итога — используем активную персону/голос.
- Графики/таймлайн-визуализация истории — только текст + озвучка.
- Сравнение «по углам» с реальным пилотом (есть отдельная фича load_f1; здесь —
  только опциональная строка-сверка, если контекст уже посчитан).

## 3. Архитектура (юниты и границы)

Чёткое разделение: **core собирает факты → commentator превращает в прозу → engine
оркестрирует → web/UI показывают.**

### 3.1 `core/race_story.py` (новый) — `RaceStoryCollector`
Накопитель фактов за ВСЮ гонку (RaceTimeline windowed — не годится для полного рассказа).
- Состояние: `start_position`, `notable_events: list[dict]`, плюс производное.
- Методы:
  - `reset()` — на SSTA.
  - `note_start_position(pos)` — фиксируется один раз (первая известная позиция игрока).
  - `note_event(code, lap, driver=None, target=None)` — фильтрует и копит значимые:
    OVTK с участием игрока, PENA(игрок), RTMT(игрок), FTLP(игрок). Кап ~12 записей
    (берём первые + последние, чтобы не раздувать промпт).
  - `facts(*, final_position, laps, coach_state, leader_name, total_laps) -> dict` —
    собирает финальный факт-блок: старт/финиш, дельта позиций, лучший круг (из laps:
    min last_lap_ms > 0 + его номер), число обгонов, инциденты, слабый сектор/консистентность.
- Чистый, без I/O и сети. Тестируется изолированно.

### 3.2 `commentator/story.py` (новый) — `StoryGenerator`
Превращает факт-блок в текст.
- `build_prompt(facts, persona, gp_context=None) -> str` — структурный fact-only промпт
  (по образцу `core/broadcast/prompts.py`): «используй ТОЛЬКО эти факты», тон персоны
  (из `commentator/personas.py` стиль), формат «3–5 предложений, ретроспектива, русский,
  числа словами, имена в правильном падеже (даём шпаргалку через `core.ru_names.glossary`)».
- `generate(facts, ai, persona, gp_context=None) -> str` — зовёт `AIProvider.generate`;
  при `None`/пусто → `render_fallback(facts, persona)`.
- `render_fallback(facts, persona) -> str` — детерминированный шаблонный итог из фактов
  (работает офлайн). Пример: «Финиш P{final} со старта P{start}. Лучший круг {time} на
  {lap}-м. Обгонов: {n}. Слабый сектор — S{weak}.»
- Имена склоняются через `core.ru_names` (фикс прошлой сессии — переиспользуем glossary).

### 3.3 `core/engine.py` — оркестрация
- `__init__`: `self.story_collector = RaceStoryCollector()`, `self._story_fired = False`.
- На `SSTA` (в `_telemetry_loop`, рядом с `recorder.reset()`): `story_collector.reset()`,
  `self._story_fired = False`.
- Кормление коллектора:
  - старт-позиция: при первом известном `_player_pos`.
  - события: в event-петле — `story_collector.note_event(code, lap, driver, target)` для
    релевантных кодов (после enrich, имена уже разрешены).
- На `CHQF` (только `session_type == "race"`), после `recorder.finalize(...)`, если не
  `_story_fired`: `self._story_fired = True` и запуск **фонового потока** `_generate_story()`:
  - собрать `facts` (collector + recorder._laps + coach.get_state + leader + total_laps),
  - `text = StoryGenerator.generate(facts, ai, persona, analytics_context)`,
  - `voice.say(text)`, `state["race_story"] = {...}`, запись в `feed`, дописать в архив сессии.
- Фоновый поток: LLM медленный (2–6 с) — нельзя блокировать поток телеметрии.
- Метод `generate_story_now()` для ручного триггера (API) — тот же путь, без `_story_fired`-гейта.

### 3.4 `web_server.py` — API
- `race_story` уезжает в UI автоматически через `/api/state` (поле в `state`).
- `POST /api/story/generate` → `engine.generate_story_now()` → `{ok, story?}`.
- `POST /api/story/replay` → `engine.replay_story()` (переозвучить текущий `state["race_story"]`).
- Пустые/нет-данных случаи → `{ok: false, reason}`.

### 3.5 UI — `NewSpotterUI`
- `lib/api.ts`: тип `RaceStory = {text, track, final_position, ts}`; поле `race_story?: RaceStory`
  в `SpotterState`; функции `generateStory()`, `replayStory()`.
- `components/spotter/views/debrief.tsx`: панель «История гонки»:
  - есть `race_story` → текст + кнопка «Переозвучить».
  - нет → кнопка «Сгенерировать итог» (доступна после гонки) + подсказка.

## 4. Модель данных

### Факт-блок (`RaceStoryCollector.facts()`)
```python
{
  "track": str | None,
  "start_position": int | None,
  "final_position": int | None,
  "positions_gained": int | None,      # start - final (>0 = отыграл)
  "total_laps": int | None,
  "best_lap_ms": int | None,
  "best_lap_number": int | None,
  "overtakes": [ {"lap": int, "target": str}, ... ],   # игрок (overtaking_idx==player) обогнал target
  "incidents": [ {"lap": int, "code": str, "driver": str}, ... ],  # PENA/RTMT игрока
  "fastest_lap_flag": bool,            # был ли FTLP игрока
  "weak_sector": int | None,
  "consistency": float | None,
}
```

### `state["race_story"]` (в `/api/state`)
```python
{"text": str, "track": str | None, "final_position": int | None, "ts": float}
```
Изначально `None` (нет истории). Сбрасывается в `None` на SSTA.

### Архив
В JSON сессии (`analytics/archive.save_game_session`) дописываем ключ `story: str`.
Конкретно: `SessionRecorder.finalize()` уже пишет файл сессии и возвращает `Path`; после
генерации истории `engine._generate_story()` дописывает `story` в ТОТ ЖЕ файл через новый
маленький хелпер `analytics/archive.attach_story(path, text)` (read-modify-write JSON).
Новых форматов файлов не вводим.

## 5. Дизайн промпта (LLM)
- Системная часть: тон персоны (из `personas.py`) + «ты подводишь ИТОГ уже завершённой
  гонки игрока как спортивный журналист; ретроспектива, прошедшее время».
- Пользовательская часть: факт-блок построчно + (опц.) `gp_context` + шпаргалка склонений.
- Контракт: «3–5 предложений, один абзац, русский, без markdown/эмодзи; числа словами;
  опирайся ТОЛЬКО на факты; если фактов почти нет — короткий нейтральный итог».
- Анти-галлюцинация: модель не выдумывает позиции/имена/события вне факт-блока (как в
  `broadcast/prompts.py` + `validator` по образцу, если уместно).

## 6. Обработка ошибок / граничные случаи
- LLM недоступен/таймаут → `render_fallback` (офлайн-шаблон). Фича всегда что-то выдаёт.
- Мало данных (сход на 1-м круге, нет кругов) → короткий честный итог («Гонка завершилась
  рано: сход на круге N»). Если совсем пусто — история не генерится (`{ok:false}`).
- Двойной CHQF / CHQF+SEND → `_story_fired`-гейт (1 раз на сессию).
- Не-гонка (практика/квалификация) → история не фаерит.
- Фоновый поток: исключения логируются, не валят engine.
- TTS длинной фразы — очередь TTS уже режет по предложениям (см. voice/tts.py).

## 7. Тестирование
- `tests/test_story_collector.py`: старт-позиция фиксируется один раз; фильтр событий
  (только игрок-релевантные); кап; `facts()` считает лучший круг/дельту позиций; reset.
- `tests/test_story_generator.py`: `build_prompt` содержит факты+склонения; `generate` с
  фейковым AIProvider возвращает текст; фолбэк при `None`; фолбэк офлайн детерминирован.
- `tests/test_engine_story.py` (фикстура engine как в test_engine_ambient): история фаерит
  1 раз на CHQF(race), не в практике; анти-дабл-файр; `generate_story_now` работает.
- Полный прогон `pytest` зелёный.

## 8. Вне рамок (будущее)
- Story для квалификации/практики (другой нарратив — «лучший круг», прогресс по программе).
- Сравнение «по углам» с реальным пилотом внутри истории (связка с load_f1/FastF1).
- Кастомный «голос журналиста», отличный от живого комментатора.
- История «карьеры»/межгоночная память (Идея 10 из конкурентного анализа).
