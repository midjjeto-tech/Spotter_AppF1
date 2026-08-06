# Real-F1 Benchmark (live) — Design Spec

**Дата:** 2026-06-29
**Статус:** утверждён (дизайн), готов к плану реализации
**Источник:** killer-фича #2 из конкурентного анализа (Идея 9). Уникально для F1-аудитории.

## 1. Обзор

Во время гонки сравниваем темп игрока с РЕАЛЬНЫМ F1: при определении трассы фоном
тянем эталон (быстрейший круг настоящего Гран-при) из Jolpica, кэшируем. На каждом
завершённом круге считаем гэп лучшего круга игрока к эталону → обновляем HUD и
подмешиваем строку-сверку в контекст комментатора (готовый `set_analytics_context`).
На личном рекорде круга — отдельная озвученная реплика.

**Семантическая поправка 2026-07-21:** игровое и реальное время не нормализованы
по физике, настройкам, погоде, топливу, шинам и состоянию трассы. Поэтому результат
является только справочной разницей записанных времён, а не рейтингом мастерства.
UI, голос и LLM-контекст не должны формулировать отрицательный `gap_ms` как
«ты быстрее реального пилота»; корректная формулировка — «игровое время меньше
реального ориентира» с явной пометкой о несопоставимости условий.

**Решения (из брейншторма):** источник — **Jolpica** (лёгкий, без FastF1/pandas);
сравнение — **по времени круга** (Ergast не даёт сектора); сюрфейс — **комментатор + HUD**;
озвучка — **только на личном рекорде** (HUD обновляется каждый круг).

## 2. Цели и не-цели

**Цели**
- Авто-загрузка эталона при смене трассы (фоновый поток, кэш Jolpica на диске).
- Эталон = **быстрейший круг гонки** реального GP (год из `F1_SEASON`, иначе год−1). Это основной
  и единственный смысловой эталон для сравнения ТЕМПА в гонке. **Поул — только фолбэк-источник**,
  если fastest lap по трассе недоступен; тогда формулировки меняются на «поул».
- Live-гэп лучшего круга игрока к эталону на каждом завершённом круге → HUD + контекст LLM.
- Гэп показывается как нейтральная разница времён; знак не интерпретируется как
  превосходство или отставание игрока по мастерству относительно пилота F1.
- Озвученная реплика ТОЛЬКО на новом личном лучшем круге.
- Полная graceful-деградация: нет сети/данных/трассы → фича молча выключена.
- Без новых тяжёлых зависимостей (только существующий `JolpicaClient`).

**Не-цели (YAGNI v1)**
- Сектора / по-угловое сравнение (Ergast не отдаёт сектора).
- Поул как ОСНОВНОЙ эталон (поул — лишь фолбэк при отсутствии fastest lap).
- Сравнение по конкретному кругу гонки (твой круг 12 vs его круг 12).
- Озвучка каждый круг.

## 3. Архитектура (юниты и границы)

### 3.1 `core/ergast_client.py` (+метод + helper)
- `_laptime_to_ms(t: str|None) -> int|None` (модульный helper): `"1:21.046"→81046`, `"58.4"→58400`.
- `JolpicaClient.get_circuit_fastest_lap(year, circuit_id) -> dict | None`:
  - `data = self.get_json(f"{year}/circuits/{circuit_id}/results.json")`.
  - В `MRData.RaceTable.Races[0].Results[]` берём результат с `FastestLap.rank == "1"`
    (фолбэк — минимальное `FastestLap.Time.time`); вернуть `{"driver": familyName, "time_ms": ms}`.
  - Нет данных/гонки/времени → `None`. Кэш/rate-limit/offline — уже в `get_json`.
- `JolpicaClient.get_circuit_pole(year, circuit_id) -> dict | None` (**фолбэк**):
  - `self.get_json(f"{year}/circuits/{circuit_id}/qualifying.json")` → `QualifyingResults[]`,
    берём `position=="1"`, лучшее доступное из `Q3→Q2→Q1` (через `_laptime_to_ms`).
  - Вернуть `{"driver": familyName, "time_ms": ms}` или `None`. Зовётся, только если fastest lap пуст.

### 3.2 `core/f1_benchmark.py` (новый) — `F1Benchmark`
Чистый юнит: данные эталона + расчёт гэпа. Без потоков (engine зовёт `load` в фоне).
- `TRACK_ID_TO_CIRCUIT: dict[int, str]` — карта 24 трасс → ergast circuitId
  (напр. `0→"albert_park"`, `7→"monaco"`, `11→"silverstone"`, `15→"monza"`, `12→"spa"`…).
- `__init__(self, client=None)` — лениво создаёт `JolpicaClient()`, если не передан (инъекция для тестов).
- `load(self, track_id, year) -> bool` — резолвит circuit; пробует **fastest lap** (`year`, затем
  `year-1` если `year>2024`); если пусто — **фолбэк на поул** (`year`, `year-1`); хранит
  `self.reference = {"driver","time_ms","year","event","source"}`, где `source ∈ {"fastest_lap","pole"}`;
  `event` — из `TRACK_ID_TO_GP[track_id][1]`. Возвращает готовность.
- `ready -> bool` — `self.reference is not None`.
- `compare(self, player_laps) -> dict | None` — инлайн (без `comparator`): из `player_laps`
  берём лучший `last_lap_ms>0`; `gap_ms = best - reference.time_ms`. Возврат:
  `{"gap_ms","player_best_ms","player_best_lap","f1_time_ms","f1_driver","event","year"}` или `None`.
- `context_line(self, cmp) -> str` — строка-сверка для LLM:
  «Эталон трассы — {ref} {driver_gen} {f1_time} ({event}). Твой лучший {pt}, отставание {gap}с.»,
  где `{ref}` = «быстрейший круг» или «поул» по `reference["source"]`. Имя в родительном через
  `core.ru_names.decline`. Время — словами уже на TTS-нормализации.
- `pb_line(self, cmp) -> str` — детерминированная реплика на рекорд:
  «Личный рекорд круга — {pt}. {lag} {gap}с от {ref} {driver_gen}.» (тот же `{ref}` по source).
- `reset(self)` — `reference=None` (на смене трассы перед загрузкой).

### 3.3 `core/engine.py` — оркестрация
- `__init__`: `self.f1_benchmark = F1Benchmark()`; `self._f1_best_ms: int|None = None` (для детекта PB);
  в `state` — `"f1_benchmark": None`.
- **Смена трассы** (в `_update_telemetry`, ветка SESSION, где `new_tid != self._track_id`):
  `self.f1_benchmark.reset()`, `self._f1_best_ms=None`, запуск фон-потока
  `self._load_f1_benchmark(new_tid)` → `f1_benchmark.load(new_tid, int(config.F1_SEASON))`.
- **Завершение круга** (в `_update_telemetry`, где вызывается `recorder.on_lap_complete`): после записи
  вызвать `self._update_f1_benchmark()`:
  - `if not f1_benchmark.ready: return`.
  - `cmp = f1_benchmark.compare(self.recorder.laps())`; если `None` → return.
  - `state["f1_benchmark"] = {gap_ms, f1_driver, f1_time_ms, player_best_ms, event, year}` (HUD).
  - `self.set_analytics_context(f1_benchmark.context_line(cmp))` (живёт в `commentator.analytics_context`).
  - **PB-детект:** если `player_best_ms < self._f1_best_ms` (или `_f1_best_ms is None`):
    `self._f1_best_ms = player_best_ms`; положить в очередь событие
    `{"event_code":"F1_BENCH","priority":"normal","phrase": f1_benchmark.pb_line(cmp), "color":"#34D399","driver":""}`.
- **Passthrough готовой фразы** в `_commentary_loop`: в начале генерации
  `phrase = event.get("phrase") or ""` (до radio/strategist/broadcast/create) — preset-фраза
  короткозамыкает генерацию, но проходит очередь/min_gap/фид/голос как обычно.
- Сброс на `SSTA`: `self._f1_best_ms = None` (эталон НЕ сбрасываем — он по трассе).

### 3.4 UI
- `state["f1_benchmark"]` уходит в `/api/state`.
- `lib/api.ts`: тип `F1Benchmark = {gap_ms, f1_driver, f1_time_ms, player_best_ms, event, year}` (nullable),
  поле `f1_benchmark?: F1Benchmark | null` в `SpotterState`.
- Компактный реадаут «Эталон F1: +1.5с ({driver})» — в **живом Race-view** (это и есть HUD).
  Точный компонент Race-view фиксируется в плане (прочитать перед правкой). Debrief — не трогаем
  (там пост-гонка; live-HUD ему не нужен).

## 4. Модель данных
```python
# reference (в F1Benchmark); source ∈ {"fastest_lap","pole"}
{"driver": "Ферстаппен", "time_ms": 79846, "year": 2025, "event": "Italian Grand Prix",
 "source": "fastest_lap"}

# compare(player_laps)
{"gap_ms": 1500, "player_best_ms": 81346, "player_best_lap": 18,
 "f1_time_ms": 79846, "f1_driver": "Ферстаппен", "event": "...", "year": 2025}

# state["f1_benchmark"]  (для HUD; None пока нет эталона/кругов)
{"gap_ms": 1500, "f1_driver": "Ферстаппен", "f1_time_ms": 79846,
 "player_best_ms": 81346, "event": "...", "year": 2025}
```

## 5. Поток данных
SESSION (track_id сменился) → фон-поток `load` → Jolpica (кэш) → `reference`.
LAP_DATA (круг завершён) → `compare(recorder.laps())` → `state["f1_benchmark"]` + `set_analytics_context`.
Новый личный лучший → preset-phrase событие → `_commentary_loop` → голос + фид.

## 6. Обработка ошибок / края
- Jolpica недоступна → `get_json` отдаёт stale-кэш или `None` → `load` вернёт False → фича off.
- Нет circuit в `TRACK_ID_TO_CIRCUIT` / нет данных за год (и за год−1) → off.
- Фон-`load` бросил → лог, engine цел (поток обёрнут try/except).
- `compare` без кругов/эталона → `None` (HUD не трогаем).
- Сравнение в памяти, мгновенно; сеть только в фоне (не из потока телеметрии — правило проекта).
- PB-реплика детерминирована (offline-safe), LLM не нужен; пассивный контекст лишь обогащает обычные фразы.

## 7. Тестирование
- `tests/test_ergast_fastest_lap.py`: `_laptime_to_ms` («1:21.046»→81046, «58.4»→58400, мусор→None);
  `get_circuit_fastest_lap` парсит rank=="1" (fake get_json), нет данных → None.
- `tests/test_f1_benchmark.py`: `load` ставит reference (fake client) + fallback года + **фолбэк на поул**
  (fastest пуст → берётся pole, `source=="pole"`); `compare` считает gap/best; not-ready → None;
  `context_line`/`pb_line` содержат имя в родительном, корректный `{ref}` по source, и времена; `reset`.
- `tests/test_engine_f1_benchmark.py` (фикстура engine как в test_engine_ambient): preset-phrase
  passthrough в `_commentary_loop`; `_update_f1_benchmark` пишет `state["f1_benchmark"]`; PB-триггер
  кладёт событие один раз на улучшение.
- Полный прогон `pytest` зелёный; `npx tsc --noEmit` чисто.

## 8. Вне рамок (будущее)
- Сектора/по-угловое сравнение (нужен FastF1/телеметрия — отдельная фича).
- Поул как альтернативный эталон (квалификация Jolpica).
- Выбор конкретного пилота-референса; «карьерный» трекинг прогресса к эталону.
