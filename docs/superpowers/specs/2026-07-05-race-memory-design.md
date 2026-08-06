# Race Memory (v1: wire existing signals) — дизайн

Дата: 2026-07-05
Статус: утверждён пользователем (диалог 2026-07-05), реализация — по плану в
`docs/superpowers/plans/`.

## Проблема

Из исходного 18-пунктового пожелания пользователя: «гоночная память» — кто кого
атаковал, кто недавно ошибся, кто на свежей резине, кто теряет темп. Отложено
design-спекой Comment Planner (`docs/superpowers/specs/2026-07-05-comment-planner-
importance-design.md`) на будущее.

Расследование показало: два из четырёх признаков УЖЕ вычисляются существующим
кодом, но никогда не доходят до комментатора —

- `RaceState.is_battle(a, b)` — знает про повторяющиеся обгоны между парой пилотов
  (используется только для булева флага `event["battle"]`, число попыток нигде не
  видно).
- `RivalTracker` (`core/rivals/tracker.py`) — уже классифицирует стиль каждого
  соперника (`aggressive`/`charging`/`fading`/`consistent`) по тренду позиций,
  но это живёт ТОЛЬКО в `state["rivals"]` для UI-панели, `build_plan()` его не видит.

Два других признака («кто недавно ошибся», «свежая резина соперника») ТРЕБУЮТ
новой телеметрии — F1 25 UDP парсится сейчас только для машины ИГРОКА
(`core/packets.py::parse_player_status`/`parse_player_damage`), для соперников
`tyre_compound`/повреждения не читаются вообще.

## Согласованный объём

- **v1 — только два признака, уже покрытых существующими данными:** число
  повторных попыток обгона в паре (`battle_count`) и стиль соперника-участника
  OVTK (`driver_style`/`target_style`). Никакой новой телеметрии.
- **НЕ в этом цикле:** «недавняя ошибка» и «свежая резина соперника» (нужен
  парсинг чужой телеметрии — отдельный будущий цикл, если понадобится).
- **`score_importance()` не меняется.** Оба признака — чисто описательный текст
  для директивы LLM, не новый модификатор важности.
- Стиль соперника привязывается ТОЛЬКО к `OVTK` — не расползается на все типы
  событий с известным `driver`/`target` (бессмысленно для `DAMAGE_*`/`PIT_EXIT`
  и т.п.).

## Дизайн

### 1. `core/race_state.py` — счётчик попыток вместо только bool

`is_battle()` остаётся ПУБЛИЧНЫМ методом с прежним контрактом (bool, тот же
порог `BATTLE_THRESHOLD`) — ноль риска для существующих вызывающих мест/тестов.
Подсчёт выносится во внутренний метод:

```python
def _count_recent_overtakes(self, vehicle_a: int, vehicle_b: int) -> int:
    """Сколько раз эта пара пилотов обгоняла друг друга за последние
    HISTORY_SIZE событий (см. is_battle() — тот же подсчёт, публичный контракт
    is_battle() не меняется, здесь — переиспользуемое число для build_plan())."""
    pair = frozenset((vehicle_a, vehicle_b))
    count = 0
    for past in self.history:
        if past.get("event_code") != "OVTK":
            continue
        past_pair = frozenset((past.get("overtaking_idx"), past.get("being_overtaken_idx")))
        if past_pair == pair:
            count += 1
    return count

def is_battle(self, vehicle_a: int, vehicle_b: int) -> bool:
    return self._count_recent_overtakes(vehicle_a, vehicle_b) >= BATTLE_THRESHOLD
```

В `enrich()`, в ветке `overtaking_idx` (там же, где сегодня выставляется
`enriched["battle"]`), добавляется:

```python
enriched["battle_count"] = self._count_recent_overtakes(
    event["overtaking_idx"], event["being_overtaken_idx"]
)
```

### 2. `core/rivals/tracker.py` — новый аксессор стиля

```python
def get_style(self, vehicle_idx: int | None) -> str | None:
    """Стиль соперника по vehicle_idx, если он уже профилирован (см. update()).
    None — игрок (RivalTracker профилирует всех, КРОМЕ игрока) или машина ещё
    не встречалась в этой сессии."""
    if vehicle_idx is None:
        return None
    profile = self._profiles.get(vehicle_idx)
    return profile.style if profile else None
```

### 3. `core/engine.py` — проводка `driver_style`/`target_style` для `OVTK`

Сразу после `enriched = self.race_state.enrich(event)` (до `record_event`):

```python
enriched = self.race_state.enrich(event)
if enriched.get("event_code") == "OVTK":
    enriched["driver_style"] = self.rival_tracker.get_style(enriched.get("overtaking_idx"))
    enriched["target_style"] = self.rival_tracker.get_style(enriched.get("being_overtaken_idx"))
self.race_state.record_event(event)
```

Игрок никогда не профилируется `RivalTracker` (сам трекер устроен так и раньше
этого цикла) — если игрок атакует или его атакуют, соответствующее поле
естественно останется `None` (без специальной проверки на стороне engine.py).

### 4. `commentator/planner.py::build_plan()` — композиция в `focus`

Русские фразы стиля (намеренно БЕЗ `"consistent"` — это незаметный дефолт, не
повод для реплики):

```python
_STYLE_PHRASES: dict[str, str] = {
    "aggressive": "агрессивен",
    "charging": "в ударе",
    "fading": "теряет темп",
}
```

`focus_reaction` (из прошлого цикла — final-laps-маркер) расширяется до списка
маркеров, объединяемых через запятую внутри одних скобок — а не два отдельных
`(...)(…)`:

```python
markers = []
if final_laps:
    markers.append(f"последние {laps_remaining} круга гонки")
battle_count = event.get("battle_count", 0)
if battle and battle_count:      # battle УЖЕ порогует по BATTLE_THRESHOLD — не дублируем порог здесь
    markers.append(f"{battle_count}-я попытка обгона")
focus_reaction = f"{reaction} ({', '.join(markers)})" if markers else reaction
```

Суффиксы стиля — отдельно, привязаны к конкретному имени (driver/target), не к
`focus_reaction`:

```python
driver_style = event.get("driver_style")
target_style = event.get("target_style")
driver_suffix = f" ({_STYLE_PHRASES[driver_style]})" if driver_style in _STYLE_PHRASES else ""
target_suffix = f" ({_STYLE_PHRASES[target_style]})" if target_style in _STYLE_PHRASES else ""
```

Итоговая ветка `target`-построения `focus` (единственная, где оба имени
участвуют — `driver_style`/`target_style` физически возможны только когда есть
оба имени, т.е. для `OVTK`):

```python
elif target:
    focus = f"{focus_reaction}: {driver}{driver_suffix} и {target}{target_suffix}".strip()
```

Пример итоговой строки при худшем (самом насыщенном) случае: `"атака (последние
2 круга гонки, 3-я попытка обгона): Норрис (в ударе) и Пиастри (теряет
темп)"`. `must_mention`/`reaction`/`length`/`emotion` — логика не меняется,
маркеры/суффиксы влияют только на `focus`.

## Файлы

| Файл | Действие |
|---|---|
| `core/race_state.py` | `_count_recent_overtakes()` (новый), `is_battle()` — тонкая обёртка, `enrich()` — `battle_count` на `OVTK` |
| `core/rivals/tracker.py` | `get_style()` (новый аксессор) |
| `core/engine.py` | проводка `driver_style`/`target_style` для `OVTK`, сразу после `enrich()` |
| `commentator/planner.py` | `build_plan()` — `_STYLE_PHRASES`, композиция `focus_reaction`/суффиксов |
| `tests/test_race_state.py` | тесты на `battle_count`/`is_battle()` неизменное поведение |
| `tests/test_rivals.py` | тест на `get_style()` (существующий файл — тесты `RivalTracker`) |
| `tests/test_planner.py` | тесты на маркеры/суффиксы, их комбинации |
| `CONTEXT.md` | запись новой сессии |

## Отказоустойчивость

Всё — чистые синхронные операции без сети/I/O (то же, что и вся `race_state.py`/
`planner.py`). `get_style()` безопасен для `None`/незнакомого `vehicle_idx`
(возвращает `None`, не бросает). Проводка в `engine.py` — простое присваивание,
не оборачивается в try/except (не сложнее существующих соседних строк того же
блока, которые тоже не обёрнуты).

## Верификация

- Новые тесты: `test_race_state.py` (счётчик, `is_battle()` не изменился),
  `test_rivals.py` (`get_style()` — известный/неизвестный/None
  vehicle_idx), `test_planner.py` (маркеры по отдельности и вместе, суффиксы по
  отдельности и вместе, `"consistent"` не даёт суффикса, отсутствие
  `battle_count`/`driver_style`/`target_style` на событии не ломает `build_plan`
  — уже сегодняшнее поведение через `event.get(..., default)`).
- Полный прогон: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q` — бейслайн
  888 passed, 1 skipped (сессия «Режим последних кругов/атак/пит-стопов»,
  2026-07-05) должен остаться зелёным плюс новые тесты.
