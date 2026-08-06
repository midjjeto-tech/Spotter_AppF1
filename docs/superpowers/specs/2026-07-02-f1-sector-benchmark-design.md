# F1 Sector Benchmark (real-race best sectors) — Design Spec

**Дата:** 2026-07-02
**Статус:** утверждён (дизайн), готов к плану реализации
**Источник:** решение пользователя «идти вглубь F1 25» — усилить уже уникальную killer-фичу
(Real-F1 Benchmark, `docs/superpowers/specs/2026-06-29-real-f1-benchmark-design.md`) реальными
секторными данными, а не только гэпом по полному кругу.

## 1. Обзор

Real-F1 Benchmark сегодня сравнивает игрока с реальным Гран-при только по **полному кругу**
(Ergast/Jolpica секторов не отдаёт). Эта фича добавляет **посекторное** сравнение: «лучшие
секторы гонки» (фиолетовые секторы трансляции — минимум по каждому сектору среди всех кругов
реальной гонки) из **OpenF1** — независимо от того, кто именно ехал быстрейший круг целиком.

Явно НЕ пытаемся сопоставить «тот же круг/тот же пилот», что дал полный-круг-эталон — это
отдельная, более простая и более надёжная метрика («лучшее время сектора N за всю гонку»),
без нужды в маппинге имён пилотов между Ergast и OpenF1.

## 2. Цели и не-цели

**Цели**
- Секторный эталон (мин. по S1/S2/S3 среди всех кругов реальной гонки) из OpenF1, с тем же
  graceful-деградацией, что и остальной Real-F1 Benchmark.
- HUD: 3 чипа в панели «Эталон F1» (зелёный при `gap_ms ≤ 0`, тот же критерий, что у полного круга).
- Голосовая реплика — **только** когда игрок бьёт СВОЙ ЖЕ лучший результат сектора за сессию
  (анти-спам, зеркалит существующий `pb_line`, не каждый круг).
- Post-Race Story: новый факт `weak_sector_vs_f1` — сектор с наибольшим средним гэпом к
  реальному F1 за гонку. **Отдельно** от существующего `weak_sector` (coach_ai) — тот про
  собственный темп игрока, этот про реальный F1; не путать и не сливать в одну цифру.
- Voice Q&A получает секторную сводку бесплатно через уже существующий `analytics_context`.
- `compare()` **всегда** возвращает ключ `"sectors"` (словарь или `None`) — предсказуемый тип
  для всех потребителей (HUD/Story/Voice), без `hasattr`-проверок.

**Не-цели (YAGNI v1)**
- Секторы/сравнение «того же круга/пилота», что дал полный-круг-эталон (см. Обзор — отклонено
  как более хрупкое: нужен второй маппинг имён между Ergast и OpenF1).
- Фильтрация кругов под Safety Car через `/race_control` (см. §3.1 — SC-круги медленные, они
  physически не могут выиграть MIN(), явная фильтрация не нужна).
- По-угловое/телеметрическое сравнение (FastF1) — осознанно отклонено на этапе брейншторма,
  требует pandas.
- Секторы для квалификации/практики — только гонка (как весь Real-F1 Benchmark сегодня).

## 3. Архитектура (юниты и границы)

### 3.1 `core/openf1_client.py` (новый) — `OpenF1Client`

Зеркалит `JolpicaClient` (диск-кэш, rate-limit, retry+backoff, отдаёт устаревший кэш при сбое
сети). Два публичных метода:

- `get_session_key(year: int, circuit_id: str) -> int | None` — трасса+год → session_key OpenF1.
  Внутри — маленькая таблица `CIRCUIT_ID_TO_OPENF1_NAME` (Ergast `circuit_id`, например
  `"monza"`, → короткое имя трассы в OpenF1 `/v1/sessions?year=&session_name=Race`; строки не
  гарантированно идентичны Ergast, отсюда отдельная таблица, не переиспользование
  `TRACK_ID_TO_CIRCUIT`). Неизвестная трасса → `None` (лог: `"no session_key mapping"`).
- `get_best_sectors(session_key: int) -> dict[int, int] | None` — один запрос
  `/v1/laps?session_key={key}`, затем **валидный круг** для MIN — это запись, где:
  - `duration_sector_1/2/3` не `None` и не `0` (OpenF1 возвращает `null` для невалидных секторов
    невыполненных/повреждённых кругов — а не 0; ноль тоже отбрасываем как защиту);
  - `is_pit_out_lap` не `True` (круг после выезда из боксов — заведомо не быстрейший).
  Safety Car отдельно НЕ фильтруем (см. §2 не-цели) — SC-круги медленные и физически не victory
  MIN(), фильтрация избыточна для v1.
  Секунды (float, формат OpenF1) → мс (int), как везде в проекте. Пустой/битый ответ → `None`.
- **Кэш TTL — практически бессрочный.** Гонка завершена → её секторные времена не изменятся
  никогда (в отличие от Ergast, где «текущий сезон» может обновляться — ростер пилотов, очки
  и т.п.). `OPENF1_TTL_DAYS` = очень большое число (напр. 3650 — 10 лет), одна константа, БЕЗ
  аналога `ERGAST_TTL_CURRENT_SECONDS` (нет «текущей» гонки, которую можно перезапрашивать —
  эталоном всегда служит УЖЕ завершённая гонка этого года или прошлого).
- **Логирование состояния** на каждую попытку (для прод-диагностики, почему HUD без чипов):
  INFO `"OpenF1 OK: session=%s sectors=%s"` при успехе; WARNING `"OpenF1 unavailable: %s"` при
  сетевом сбое; WARNING `"OpenF1: no session_key mapping for %s/%s"` при неизвестной трассе.

### 3.2 Расширение `core/f1_benchmark.py`

`F1Benchmark.__init__(self, client=None, openf1_client=None)` — `openf1_client` инъектируется
(тесты), лениво создаётся как `OpenF1Client()`, как и `_c`/`JolpicaClient` сегодня.

`load(track_id, year)` — существующая логика полного круга/поула **без изменений** (источник
истины остаётся Ergast/Jolpica, OpenF1 не критичен для core-метрики). **После** успешного
нахождения `self.reference`, дополнительно (в том же вызове, тот же фоновый поток engine'а):
```python
circuit = TRACK_ID_TO_CIRCUIT.get(track_id)
session_key = self._openf1.get_session_key(self.reference["year"], circuit)
sector_ms = self._openf1.get_best_sectors(session_key) if session_key else None
self.reference["sector_ms"] = sector_ms   # dict{1,2,3} | None — сбой НЕ валит load()
```
Если `load()` в принципе не нашёл полного-круга-эталон (트расса не в календаре) — секторы не
пробуем вообще, `self.reference` остаётся `None`, как сегодня.

`compare(player_laps)` — существующие поля без изменений, плюс **всегда** присутствующий ключ:
```python
"sectors": {
    1: {"player_ms": int, "gap_ms": int},
    2: {"player_ms": int, "gap_ms": int},
    3: {"player_ms": int, "gap_ms": int},
} | None   # None если reference["sector_ms"] is None ИЛИ игрок не проехал круг с валидными s1/s2/s3
```
`gap_ms = player_ms - reference_ms` (тот же знак-конвенция, что у полного круга: отрицательный
= игрок быстрее). Все значения — **строго `int` мс**, без `float`, без исключений.

### 3.3 `core/engine.py` — анти-спам живая реплика

Новое поле `self._f1_best_sector_ms: dict[int, int] = {}` (личный лучший результат ИГРОКА по
каждому сектору за сессию; отдельно от `self._f1_best_ms` — полного круга). Сброс вместе с
`_f1_best_ms` на `SSTA`.

В `_update_f1_benchmark()` (после существующей логики полного-круга-PB, использует тот же
`cmp = self.f1_benchmark.compare(...)`), если `cmp["sectors"] is not None`:
```python
improved: list[int] = []
for n, s in cmp["sectors"].items():
    best_so_far = self._f1_best_sector_ms.get(n)          # None на первом круге сессии — считается PB (как _f1_best_ms)
    if best_so_far is None or s["player_ms"] < best_so_far:
        self._f1_best_sector_ms[n] = s["player_ms"]
        improved.append(n)
if improved:
    # если PB сразу в НЕСКОЛЬКИХ секторах одного круга — говорим ОДИН раз,
    # про сектор с наименьшим (самым «глубоким в плюс») gap_ms к реальному F1 —
    # это самое впечатляющее достижение ОТНОСИТЕЛЬНО РЕАЛЬНОГО ГОНЩИКА,
    # а не просто самый большой прогресс относительно себя же.
    best_n = min(improved, key=lambda n: cmp["sectors"][n]["gap_ms"])
    self.event_queue.put({
        "event_code": "F1_SECTOR_BENCH", "priority": "normal",
        "phrase": self.f1_benchmark.sector_pb_line(best_n, cmp["sectors"][best_n]),
        "color": "#34D399", "driver": ""})
```
`F1Benchmark.sector_pb_line(sector_n, sector_cmp)` (новый метод, зеркалит `pb_line`):
`"Сектор {n} — твой лучший в сессии, {gap} эталона гонки!"` (быстрее/медленнее по знаку gap_ms,
как в `pb_line`). `F1_SECTOR_BENCH` роутится в commentary, как `F1_BENCH` — без правок в router.

### 3.4 HUD — `state["f1_benchmark"]["sectors"]` + `race.tsx`

`_update_f1_benchmark()` кладёт `cmp["sectors"]` в `state["f1_benchmark"]["sectors"]` (тем же
словарём, что вернул `compare()` — `None` включительно). В панели «Эталон F1» (`race.tsx`) — три
маленьких чипа под существующей строкой гэпа, рендерятся только если `sectors` не `None`;
зелёный при том же критерии `gap_ms <= 0`, что уже используется для полного круга.

### 3.5 Post-Race Story

`RaceStoryCollector.facts()` — новый ключ `weak_sector_vs_f1: int | None` (1/2/3 — сектор с
наибольшим **средним** `gap_ms` к реальному F1 среди кругов гонки, где `sectors` был доступен;
`None` если данных не было ни разу). Отдельное поле от существующего `weak_sector` (`coach_ai`,
про собственный темп) — оба идут в факт-блок раздельно, `commentator/story.py::_format_facts`
получает новую строку (по образцу существующей `weak_sector`: `f"- Слабее эталона F1 в секторе
S{weak_sector_vs_f1}"`), не трогая существующую.

### 3.6 Voice Q&A

Без изменений кода — `commentator.analytics_context` (через `F1Benchmark.context_line`, который
дополняется секторной сводкой, если `sectors` доступны) уже прокидывается в
`_query.answer_question(..., gp_context=self.commentator.analytics_context)`.

## 4. Модель данных

```python
# F1Benchmark.reference (после load())
{
    "driver": str, "time_ms": int, "year": int, "event": str, "source": "fastest_lap"|"pole",
    "sector_ms": {1: int, 2: int, 3: int} | None,   # новое
}

# F1Benchmark.compare() -> dict (существующие поля без изменений) +
{
    "sectors": {
        1: {"player_ms": int, "gap_ms": int},
        2: {"player_ms": int, "gap_ms": int},
        3: {"player_ms": int, "gap_ms": int},
    } | None,
}
```

## 5. Обработка ошибок / граничные случаи

| Ситуация | Поведение |
|---|---|
| OpenF1 недоступен (сеть/таймаут) | `sector_ms=None`, лог WARNING; полный-круг-бенчмарк работает как сегодня; HUD без чипов, без секторной реплики, Story без `weak_sector_vs_f1`, Voice Q&A без секторов в контексте. |
| Трасса не в `CIRCUIT_ID_TO_OPENF1_NAME` | `session_key=None` → `sector_ms=None`, лог WARNING «no session_key mapping», деградация как выше. |
| Круг с `duration_sector_N is None/0` или `is_pit_out_lap=True` | Исключается из MIN(); если валидных кругов совсем нет — `sector_ms=None`. |
| Safety Car круги | Не фильтруются явно (не-цель v1) — физически не могут выиграть MIN(), т.к. медленнее чистых кругов. |
| Игрок не проехал круг с валидными s1/s2/s3 (авария/выезд с трассы) | Для ЭТОГО круга `compare()["sectors"] = None`; предыдущий `_f1_best_sector_ms` не трогаем. |
| Несколько PB-секторов в одном круге игрока | Одна реплика — про сектор с наименьшим `gap_ms` (ближе всего к/лучше реального F1), не про самый большой числовой прогресс. |
| Первый круг сессии | Считается PB автоматически для каждого сектора (симметрично существующему `_f1_best_ms is None` на полном круге) — может сразу зафаерить реплику, если ещё и обгоняет референс. |
| `compare()` вызван при `reference is None` (эталон не загрузился) | Возвращает `None` целиком (существующее поведение, без изменений). |

## 6. Конфиг (`config.py`)

```python
OPENF1_BASE_URL = "https://api.openf1.org/v1"
OPENF1_CACHE_DIR = os.path.join(DATA_DIR, "openf1_cache")
OPENF1_TTL_DAYS = 3650          # практически бессрочно — завершённая гонка не меняется
OPENF1_MIN_INTERVAL = 2.0       # rate-limit, как ERGAST_MIN_INTERVAL
OPENF1_MAX_RETRIES = 3
OPENF1_TIMEOUT = 8.0
```

## 7. Тестирование

- `tests/test_openf1_client.py` (новый, по образцу `test_ergast_client.py`): кэш/refetch, TTL
  (фактически не истекает), stale-offline, `get_session_key` (найдено/не найдено), парсинг
  `get_best_sectors` (MIN среди валидных кругов), **явный тест на «странный» круг**
  (`duration_sector_2=None`/`0`, `is_pit_out_lap=True` — исключается из MIN), сетевой сбой → `None`.
- `tests/test_f1_benchmark.py` (расширение): `compare()` всегда содержит ключ `"sectors"`
  (словарь либо `None`, никогда не отсутствует); гэп по сектору = `player_ms - reference_ms`.
- `tests/test_engine_f1_benchmark.py` (расширение): реплика фаерит на первом же круге, если он
  PB и обгоняет референс (холодный старт); реплика НЕ фаерит на некруге без улучшения; **тест на
  несколько PB-секторов в одном круге** — ровно одна реплика в `event_queue`, про сектор с
  минимальным `gap_ms`, не про все три и не про случайный.
- `tests/test_story_collector.py`/`test_story_generator.py` (расширение): `weak_sector_vs_f1`
  вычисляется корректно и не путается с существующим `weak_sector`.
- Полный `pytest` + `npx tsc --noEmit` зелёные.

## 8. Вне рамок (будущее)

- «Тот же круг/пилот» для секторов (см. §2) — если понадобится точность, отдельная итерация с
  маппингом имён пилотов Ergast↔OpenF1.
- Фильтрация Safety Car через `/race_control`.
- По-угловое/телеметрическое сравнение (FastF1, требует pandas).
- Секторы для квалификации/практики.
