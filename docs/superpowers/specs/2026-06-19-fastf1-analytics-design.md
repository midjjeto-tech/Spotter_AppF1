# FastF1 Analytics Layer — Design Spec
**Дата:** 2026-06-19  
**Статус:** approved

---

## Executive Summary

Добавляем `analytics/` пакет для постгоночного сравнения: игровая сессия F1 25 (UDP-телеметрия) vs реальный GP из FastF1. Результат — comparison JSON + краткая строка для Qwen-комментатора. Существующая архитектура не ломается: `analytics/` — отдельный слой, вызываемый из UI и `web_server.py`.

---

## Scope

**In scope:**
- Запись лучшего круга игрока (last_lap_ms + секторы) из UDP во время игры
- Загрузка реального GP из FastF1 (laps + weather + race control, без telemetry)
- Best-lap comparison: игрок vs реальный быстрейший круг
- Сохранение обеих сторон и comparison в `DATA_DIR/`
- Краткий контекст для Qwen (≤ 250 символов)
- Новая вкладка «Архив» в UI
- Покрытие всех 24 трасс F1 2025 календаря; graceful fallback для остальных

**Out of scope:**
- Покруговое сравнение всей сессии
- Скоростная телеметрия (Speed/Throttle/Brake из FastF1)
- Исторические сезоны (только 2025)
- Соревновательный рейтинг / онлайн

---

## Новые файлы

### `analytics/__init__.py`
Пустой, делает папку пакетом.

### `analytics/loader.py`

**Константа `TRACK_ID_TO_GP`** — маппинг `m_trackId` из UDP Session пакета F1 25 → `(gp_name, fastf1_event_name)`:

> **⚠️ ОЖИДАЕМЫЙ ПОРЯДОК — НЕ ВЕРИФИЦИРОВАН.** Реальные `m_trackId` из F1 25 UDP необходимо проверить на live-пакетах перед релизом. Константа спроектирована так, чтобы замена значений не ломала архитектуру: меняем только эту таблицу.

```python
# (gp_name для FastF1 fuzzy-match, fastf1_event_name для архива и UI)
TRACK_ID_TO_GP: dict[int, tuple[str, str]] = {
    0:  ("Melbourne",    "Australian Grand Prix"),
    1:  ("Shanghai",     "Chinese Grand Prix"),
    2:  ("Suzuka",       "Japanese Grand Prix"),
    3:  ("Sakhir",       "Bahrain Grand Prix"),
    4:  ("Jeddah",       "Saudi Arabian Grand Prix"),
    5:  ("Miami",        "Miami Grand Prix"),
    6:  ("Imola",        "Emilia-Romagna Grand Prix"),
    7:  ("Monaco",       "Monaco Grand Prix"),
    8:  ("Barcelona",    "Spanish Grand Prix"),
    9:  ("Montreal",     "Canadian Grand Prix"),
    10: ("Spielberg",    "Austrian Grand Prix"),
    11: ("Silverstone",  "British Grand Prix"),
    12: ("Spa",          "Belgian Grand Prix"),
    13: ("Budapest",     "Hungarian Grand Prix"),
    14: ("Zandvoort",    "Dutch Grand Prix"),
    15: ("Monza",        "Italian Grand Prix"),
    16: ("Baku",         "Azerbaijan Grand Prix"),
    17: ("Singapore",    "Singapore Grand Prix"),
    18: ("Austin",       "United States Grand Prix"),
    19: ("Mexico City",  "Mexico City Grand Prix"),
    20: ("São Paulo",    "São Paulo Grand Prix"),
    21: ("Las Vegas",    "Las Vegas Grand Prix"),
    22: ("Lusail",       "Qatar Grand Prix"),
    23: ("Abu Dhabi",    "Abu Dhabi Grand Prix"),
}
FASTF1_CACHE_DIR = DATA_DIR / "fastf1_cache"
```

`loader.load_f1_session` использует `gp_name` для `fastf1.get_session(year, gp_name, stype)`.  
`fastf1_event_name` пишется в нормализованный JSON и отображается в UI.

**Функция:**
```python
def load_f1_session(track_id: int, year: int = 2025,
                    session_type: str = "R") -> tuple[object | None, str | None]:
    """Возвращает (session, error_string). session=None при ошибке."""
```

Обработка ошибок — явная, возвращает `(None, reason)`:
- `track_id` не в `TRACK_ID_TO_GP` → `(None, "no_fastf1_data")`
- `fastf1.get_session` бросает исключение → `(None, "session_not_found")`
- `session.load()` бросает `fastf1.RateLimitExceededError` → `(None, "rate_limit")`
- Любое другое исключение → `(None, "load_error: <str(exc)>")`
- Успех → `(session, None)`

Кэш FastF1 включается один раз при импорте модуля:
```python
FASTF1_CACHE_DIR.mkdir(parents=True, exist_ok=True)
fastf1.Cache.enable_cache(str(FASTF1_CACHE_DIR))
```

---

### `analytics/normalizer.py`

**Фиксированные поля** — всегда присутствуют в выходном dict, даже если значение `None`:

```python
F1_DATA_SCHEMA = {
    "event": str | None,            # fastf1_event_name из TRACK_ID_TO_GP
    "year": int | None,
    "session": str | None,          # "Race" / "Qualifying" / ...
    "weather": {
        "air_temp": float | None,
        "track_temp": float | None,
        "rainfall": bool | None,
    },
    "total_results_count": int,     # сколько пилотов финишировало (len results)
    "results_top10": list[{         # топ-10 для UI-таблицы
        "pos": int,
        "driver": str,
        "team": str,
        "gap_s": float | None,      # None для победителя
        "fastest_lap_ms": int | None,
    }],
    "results": list[...],           # полный список (все финишировавшие), тот же формат
    "fastest_lap": {
        "driver": str | None,
        "lap": int | None,
        "time_ms": int | None,
        "s1_ms": int | None,
        "s2_ms": int | None,
        "s3_ms": int | None,
    },
    "best_sectors": {
        "s1_ms": int | None,        # min по всем кругам всех пилотов
        "s2_ms": int | None,
        "s3_ms": int | None,
    },
    "safety_cars": int,             # default 0
    "penalties": int,               # default 0
}
```

`results_top10 = results[:10]` — вычисляется при нормализации, не при чтении из архива.

**Функция:**
```python
def normalize(session) -> dict:
    """FastF1 Session → plain dict по схеме выше. Никогда не бросает исключений."""
```

Если поле недоступно (нет данных, KeyError, пустой DataFrame) — подставляем `None` / `0` / `[]`. Все `timedelta` → `int` (миллисекунды). Все `datetime` → ISO-строка.

---

### `analytics/archive.py`

Только чтение/запись JSON. Без бизнес-логики.

```python
DATA_DIR / "race_archive" / f"{year}_{track_id}_{stype}_f1.json"
DATA_DIR / "game_sessions" / f"{timestamp}.json"          # YYYY-MM-DD_HH-MM-SS
DATA_DIR / "race_archive" / f"{game_stem}_{track_id}_{year}_{stype}_compare.json"
```

**API:**
```python
def save_f1(track_id, year, stype, data: dict) -> Path
def load_f1(track_id, year, stype) -> dict | None        # None если файл не найден

def save_game_session(data: dict) -> Path
def load_game_session(path: str | Path) -> dict | None
def list_game_sessions() -> list[dict]  # [{"path", "track_name", "timestamp", "final_position"}]

def save_compare(game_path, track_id, year, stype, data: dict) -> Path
def load_compare(compare_path: str | Path) -> dict | None
```

Все функции атомарны: запись через `tempfile` в той же папке → `os.replace()` (та же логика что в `voice/cache.py`).

---

### `analytics/comparator.py`

Best-lap сравнение. Принимает `game: dict` и `f1: dict`.

**Алгоритм:**
1. Берём `valid_laps = [l for l in game["player_laps"] if l["last_lap_ms"] > 0]`
2. `best_player = min(valid_laps, key=lambda l: l["last_lap_ms"])` — или `None`
3. `f1_fastest = f1["fastest_lap"]`
4. Секторное сравнение активно если все три `s1_ms / s2_ms / s3_ms > 0` у обоих источников

**Правило `partial`:**
- `partial = True` если:
  - `best_player is None` → `source_coverage["player"] = "none"`
  - у `best_player` хотя бы одно из s1/s2/s3 равно `0` → `source_coverage["player"] = "partial"`
  - у `f1_fastest` хотя бы одно из s1/s2/s3 равно `None` → `source_coverage["f1"] = "partial"`
- `gap_ms` и `qwen_context` присутствуют **всегда** (даже при `partial=True`)
- Поле `sectors` отсутствует если `partial=True` по секторам

**Фиксированные поля выхода:**
```python
{
    "comparison_basis": "best_lap",
    "source_coverage": {"player": "full"|"partial"|"none", "f1": "full"|"partial"|"none"},
    "player_best_lap_ms": int | None,
    "player_best_lap_lap_number": int | None,
    "f1_fastest_ms": int | None,
    "f1_best_lap_driver": str | None,
    "gap_ms": int | None,
    "sectors": {   # отсутствует если partial по секторам
        "s1": {"player_ms": int, "f1_ms": int, "gap_ms": int},
        "s2": {...},
        "s3": {...},
    },
    "partial": bool,
    "qwen_context": str,   # всегда, даже если "нет данных FastF1 для этой трассы"
}
```

---

### `analytics/context.py`

```python
def build_qwen_context(compare: dict, f1_meta: dict) -> str:
    """Возвращает строку ≤ 250 символов для Qwen. Никогда не бросает исключений."""
```

**Жёсткие fallback-шаблоны** (приоритет от верхнего к нижнему):

| Условие | Шаблон |
|---------|--------|
| `source_coverage["f1"] == "none"` | `"Данные реального GP для этой трассы недоступны."` |
| `source_coverage["player"] == "none"` | `"{event} {year}: победил {winner}. Быстрейший круг {fl_driver} {fl_time}. Игровые данные не записаны."` |
| `partial=True` (нет секторов) | `"{event} {year}: победил {winner}. Быстрейший круг {fl_driver} {fl_time}. Твой лучший — {player_time}, отставание {gap}с."` |
| Полные данные | `"{event} {year}: победил {winner}. Быстрейший круг {fl_driver} {fl_time} (круг {fl_lap}). Твой лучший — {player_time} (круг {player_lap}), отставание {gap}с. Теряешь в {worst_sector} (+{sector_gap}с)."` |

- `{worst_sector}` = сектор с максимальным `gap_ms` из трёх
- Все времена форматируются как `M:SS.mmm` (например `1:31.4`)
- Если строка превышает 250 символов — `worst_sector` блок обрезается первым

---

## Изменения в существующих файлах

### `core/session_recorder.py` (новый)

```python
class SessionRecorder:
    def on_lap_complete(self, lap_num: int, last_lap_ms: int,
                        s1_ms: int, s2_ms: int, s3_ms: int) -> None
    def finalize(self, track_id: int, track_name: str, session_type: str,
                 final_position: int | None, events: list[str]) -> Path | None
    def reset(self) -> None
```

- `on_lap_complete` вызывается когда `current_lap` инкрементировался в `_update_telemetry`
- `finalize` вызывается при событии `CHQF` или `SEND` → сохраняет через `archive.save_game_session()`
- `reset` вызывается при `SSTA` (новая сессия)
- Если `finalize` не вызван (краш) — данные теряются; это приемлемо для MVP

### `core/packets.py`

`parse_player_lap(data, player_idx)` расширяется:
```python
return {
    "position": data[base + 32],
    "current_lap": data[base + 33],
    "last_lap_ms": struct.unpack_from("<I", data, base + 0)[0],   # uint32
    "s1_ms": struct.unpack_from("<H", data, base + X)[0],         # uint16, offset уточняется
    "s2_ms": struct.unpack_from("<H", data, base + Y)[0],
    "s3_ms": struct.unpack_from("<H", data, base + Z)[0],
}
```

**Важно:** точные смещения X, Y, Z для sector times F1 25 определяются при реализации через диагностику live-пакетов (аналогично фиксу position offset 28→32).

### `core/engine.py`

- Создать `self.recorder = SessionRecorder()` в `__init__`
- В `_update_telemetry`: отслеживать `prev_lap` → при инкременте вызывать `recorder.on_lap_complete()`
- При событии `SSTA` → `recorder.reset()`
- При событии `CHQF` / `SEND` → `recorder.finalize(track_id, ...)`
- `track_id` берётся из Session пакета (`parse_session` расширяется)

### `web_server.py`

Три новых endpoint:
```
GET  /api/sessions
     → list_game_sessions()
     → [{"path", "track_name", "timestamp", "final_position"}, ...]

POST /api/load_f1
     body: {"track_id": int, "year": int, "stype": str, "game_session_path": str}
     → loader + normalizer + archive.save_f1 + comparator + context
     → возвращает:
        {
          "f1_meta":    { ...нормализованный F1 dict... },
          "game_meta":  { "track_name", "timestamp", "final_position", "total_laps" },
          "compare":    { ...comparison dict с qwen_context... },
          "compare_id": "game_stem_trackid_year_stype_compare.json"
        }
     → при ошибке: {"error": "rate_limit"|"no_fastf1_data"|"load_error: ..."}

GET  /api/archive/<compare_id>
     → load_compare(compare_id)
     → тот же формат что POST /api/load_f1, из кэша (без повторного запроса к FastF1)
```

`compare_id` достаточен для повторного открытия сравнения без повторной загрузки FastF1.

### `index.html`

Новая вкладка «Архив» (nav-item + section):
- Dropdown: выбор записанной игровой сессии из `list_game_sessions()`
- Поля: год (2025), тип сессии (R/Q/FP1)
- Кнопка «Загрузить FastF1» → POST `/api/load_f1`
- Таблица результатов реального GP (топ-10)
- Блок сравнения: «Твой лучший круг vs быстрейший реального GP» + секторный профиль
- Строка `qwen_context` — показывается как цитата комментатора
- Состояние `partial=true` → серая плашка «Неполные данные, секторное сравнение недоступно»

---

## Graceful Degradation

| Ситуация | Поведение |
|----------|-----------|
| track_id не в TRACK_ID_TO_GP | source_coverage["f1"]="none", partial=true, архив сохраняется |
| FastF1 rate limit / сеть недоступна | (None, "rate_limit"), UI показывает ошибку, повтор через кнопку |
| FastF1 данные есть, но сектора пустые | source_coverage["f1"]="partial", sectors не выводятся |
| Игрок не завершил гонку (нет CHQF) | game_session не сохраняется, compare невозможен |
| valid_laps пустой (все круги=0) | source_coverage["player"]="none", qwen_context сообщает об этом |
| Данные есть, но сектора игрока=0 | source_coverage["player"]="partial", gap_ms считается, sectors пропускается |

---

## Qwen Integration

`commentator/brain.py` получает опциональный `analytics_context: str | None`.  
Если контекст загружен (`/api/load_f1` вызван) — он инжектируется в промпт как однострочный префикс.  
Контекст не меняется до следующей загрузки FastF1 или перезапуска приложения.

---

## Критерии готовности

- [ ] `analytics/` пакет импортируется без ошибок
- [ ] `loader.load_f1_session(3)` (Bahrain) возвращает сессию и нормализуется
- [ ] `archive.save_game_session` создаёт валидный JSON
- [ ] `comparator.compare` возвращает все фиксированные поля при любых входных данных
- [ ] `partial=True` при отсутствующих секторах, `gap_ms` всегда присутствует
- [ ] Все 24 трассы в `TRACK_ID_TO_GP`, неизвестный track_id → graceful fallback
- [ ] `/api/load_f1` отвечает ≤ 30 сек при первом запросе (сеть), ≤ 1 сек из кэша
- [ ] Вкладка «Архив» отображает результаты и comparison без ошибок JS
- [ ] `qwen_context` присутствует в ответе всегда, длина ≤ 250 символов
