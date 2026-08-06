# Соперники: недавняя ошибка + свежесть резины — дизайн

Дата: 2026-07-07
Статус: утверждён пользователем (диалог 2026-07-07), реализация — по плану в
`docs/superpowers/plans/`.

## Проблема

Из «Известных gotchas» CONTEXT.md и design-спеки Race Memory v1
(`docs/superpowers/specs/2026-07-05-race-memory-design.md`) — «кто недавно
ошибся» и «свежесть резины соперника» были сознательно отложены: F1 25 UDP
парсится только для машины ИГРОКА (`core/packets.py::parse_player_status`/
`parse_player_damage`), для соперников `tyre_age`/повреждения не читаются
вообще.

Расследование в этой сессии показало: это решение объёма, не техническое
ограничение. Пакеты `LapData`/`CarStatus`/`CarDamage` уже содержат данные всех
22 машин — `parse_lap_data()` уже проходит по всем машинам (для позиций/кругов),
а `parse_player_telemetry`/`parse_player_status`/`parse_player_damage` жёстко
берут срез только `player_idx` из того же по структуре пакета.

## Согласованный объём

- **Оба признака сразу** (в отличие от Race Memory v1, где отложили оба из-за
  отсутствия телеметрии — здесь именно телеметрию и добавляем):
  свежесть резины соперника (`tyre_age`) и «соперник недавно ошибся».
- **Критерий «ошибки»** (у F1 25 нет отдельного игрового события на это) — два
  сигнала вместе:
  1. Резкий скачок повреждений кузова у соперника (переиспользуется существующий
     порог заметности 20%, `_DAMAGE_NOTICEABLE_THRESHOLD` из `engine.py`) —
     самый надёжный сигнал, контакт/вылет почти всегда оставляет след.
  2. Резкая потеря позиции **без** реального пит-стопа в этот тик.
- **Способ подачи в эфир — только контекстный факт**, как `battle_count`/
  `driver_style` в Race Memory v1: попадает в `focus`/`markers` планировщика
  ТОЛЬКО для `OVTK`, когда игрок и так уже обгоняет/его обгоняет эта машина.
  Никакого отдельного объявления по факту чужой ошибки/резины — не плодим
  новый тип события, не плодим анти-спам флаг на 22 машины.
- **Побочный фикс, вытекающий из объёма:** `RivalTracker.pit_count` сейчас —
  эвристика («скачок позиции ≥8 = предполагаем пит»), без проверки реального
  `pit_status`. Чтобы отличить настоящий пит от спина/вылета для сигнала (2)
  выше, заводим реальный `pit_status` по всем машинам — и раз он появился,
  `pit_count` переключается на него же вместо эвристики (иначе пришлось бы
  держать в трекере два независимых механизма на один и тот же скачок позиции).
  Это меняет численное поведение существующей метрики в Rivals-панели.
- **НЕ в этом цикле:** свежесть резины/ошибки не всплывают вне `OVTK`
  (например, в общей Rivals-панели как отдельная воцируемая реплика) — только
  описательный факт внутри уже существующего события. UI-панель соперников
  получает оба новых поля в JSON (`tyre_age`, `recent_mistake`) для видимости,
  но без новой логики отображения сверх уже существующей таблицы.
- **`score_importance()` не меняется** — оба признака чисто описательные, не
  модификаторы важности (тот же принцип, что у `battle_count`/`style`).

## Дизайн

### 1. `core/packets.py` — разбор всех машин вместо только игрока

`parse_lap_data()` дополняется полем `pit_status` (то же `data[base+34]`, что
уже читает `parse_player_lap` для игрока, теперь по всем машинам заодно с
позициями/кругами):

```python
def parse_lap_data(data: bytes) -> dict:
    positions: dict[int, int] = {}
    laps: dict[int, int] = {}
    gaps_front: dict[int, int] = {}
    pit_status: dict[int, int] = {}
    for idx in range(22):
        base = HEADER_SIZE + idx * LAP_DATA_SIZE
        if base + 35 > len(data):
            break
        positions[idx] = data[base + 32]
        laps[idx] = data[base + 33]
        pit_status[idx] = data[base + 34]
        gaps_front[idx] = _lap_delta_ms(data, base, 14, 16)
    leader_idx = next((i for i, p in positions.items() if p == 1), None)
    return {"positions": positions, "laps": laps, "pit_status": pit_status,
            "leader_idx": leader_idx, "gaps_front": gaps_front}
```

Общая логика статуса/повреждений выносится в приватные хелперы на один
автомобиль — оба существующих `parse_player_*` и новые `parse_*_all`
используют их, магические офсеты не дублируются:

```python
def _car_status_fields(data: bytes, base: int) -> dict:
    fuel = struct.unpack_from("<f", data, base + 5)[0]
    out = {"fuel": round(fuel, 1)}
    if base + 28 <= len(data):
        visual = data[base + 26]
        out["tyre_compound"] = TYRE_VISUAL.get(visual, "?")
        out["tyre_age"] = data[base + 27]
    return out


def parse_player_status(data: bytes, player_idx: int) -> dict:
    base = HEADER_SIZE + player_idx * CAR_STATUS_SIZE
    if base + 9 > len(data):
        return {}
    return _car_status_fields(data, base)


def parse_car_status_all(data: bytes) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for idx in range(22):
        base = HEADER_SIZE + idx * CAR_STATUS_SIZE
        if base + 9 > len(data):
            break
        out[idx] = _car_status_fields(data, base)
    return out
```

```python
def _car_damage_fields(data: bytes, base: int) -> dict:
    wear = struct.unpack_from("<ffff", data, base + 0)
    avg = sum(wear) / 4.0
    wing = max(data[base + 24], data[base + 25], data[base + 26])
    floor = max(data[base + 27], data[base + 28], data[base + 29])
    gearbox = data[base + 32]
    engine = data[base + 33]
    return {"tyre_wear": round(avg, 1), "wing_damage": wing,
            "floor_damage": floor, "gearbox_damage": gearbox,
            "engine_damage": engine}


def parse_player_damage(data: bytes, player_idx: int) -> dict:
    body = len(data) - HEADER_SIZE
    if body <= 0:
        return {}
    stride = body // 22
    if not (24 <= stride <= 80):
        return {}
    base = HEADER_SIZE + player_idx * stride
    if base + 34 > len(data):
        return {}
    return _car_damage_fields(data, base)


def parse_car_damage_all(data: bytes) -> dict[int, dict]:
    body = len(data) - HEADER_SIZE
    if body <= 0:
        return {}
    stride = body // 22
    if not (24 <= stride <= 80):
        return {}
    out: dict[int, dict] = {}
    for idx in range(22):
        base = HEADER_SIZE + idx * stride
        if base + 34 > len(data):
            break
        out[idx] = _car_damage_fields(data, base)
    return out
```

**Поведение существующих `parse_player_status`/`parse_player_damage` не
меняется** — тот же результат для тех же входов, они просто делегируют в общий
хелпер.

### 2. `core/rivals/models.py` — новые поля профиля

```python
@dataclass
class RivalProfile:
    vehicle_idx: int
    driver: str
    team: str
    pit_count: int
    lap_count: int
    current_position: int
    style: str
    nearby: bool
    position_history: deque = field(default_factory=lambda: deque(maxlen=10))
    tyre_age: int | None = None
    body_damage: float = 0.0
    pit_status: int = 0
    mistake_at: float | None = None
```

### 3. `core/rivals/tracker.py` — детект + аксессоры

`update()` получает параметр `now: float` (время передаёт вызывающий код —
трекер остаётся детерминированным/тестируемым, тот же принцип, что и у
остальной `race_state`/`planner` логики). Старый порог `_PIT_DROP_THRESHOLD`
переименован в `_POSITION_LOSS_THRESHOLD` — смысл изменился (раньше «предполагаем
пит», теперь «большая потеря позиции», пит теперь детектится отдельно, по
реальному полю):

```python
_POSITION_LOSS_THRESHOLD = 8       # было _PIT_DROP_THRESHOLD, тот же порог
_MISTAKE_RECENCY_WINDOW = 60.0     # секунд — сколько "недавняя ошибка" ещё актуальна
```

```python
def update(self, grid: list[dict], player_vehicle_idx: int, now: float) -> None:
    ...  # существующая часть (player_pos, регистрация профиля) не меняется
    for entry in grid:
        vi = entry["vehicle_idx"]
        if vi == player_vehicle_idx:
            continue
        pos = entry.get("position", 0)
        pit_status = entry.get("pit_status", 0)
        ...  # регистрация профиля не меняется

        profile = self._profiles[vi]
        ...  # driver/team update не меняется

        prev_pos = profile.current_position
        prev_pit = profile.pit_status
        profile.current_position = pos
        profile.pit_status = pit_status
        profile.lap_count = lap
        profile.nearby = player_pos > 0 and abs(pos - player_pos) <= _NEARBY_WINDOW

        if pos > 0:
            profile.position_history.append(pos)

        entered_pit = prev_pit == 0 and pit_status != 0
        if entered_pit:
            profile.pit_count += 1
        elif (prev_pos > 0 and pos > 0
              and pos - prev_pos >= _POSITION_LOSS_THRESHOLD
              and pit_status == 0):
            profile.mistake_at = now

        profile.style = _classify_style(profile.position_history)
```

```python
def update_tyre(self, vehicle_idx: int, age: int) -> None:
    """Возраст резины соперника — приходит с CarStatus-тиков, независимо от
    update() (другой тип пакета). Молча игнорирует машину, ещё не встреченную
    через update() (LapData) — догонит на следующем тике, не критично."""
    profile = self._profiles.get(vehicle_idx)
    if profile:
        profile.tyre_age = age


def update_damage(self, vehicle_idx: int, body_damage: float,
                   threshold: float, now: float) -> None:
    """threshold передаётся вызывающим кодом — переиспользует тот же порог
    заметности, что уже применяется к повреждениям игрока (не второй дубль
    магического числа 20 в двух модулях)."""
    profile = self._profiles.get(vehicle_idx)
    if profile is None:
        return
    if body_damage >= threshold and profile.body_damage < threshold:
        profile.mistake_at = now
    profile.body_damage = body_damage


def get_recent_mistake(self, vehicle_idx: int | None, now: float,
                        window: float = _MISTAKE_RECENCY_WINDOW) -> bool:
    if vehicle_idx is None:
        return False
    profile = self._profiles.get(vehicle_idx)
    if profile is None or profile.mistake_at is None:
        return False
    return (now - profile.mistake_at) <= window


def get_tyre_age(self, vehicle_idx: int | None) -> int | None:
    if vehicle_idx is None:
        return None
    profile = self._profiles.get(vehicle_idx)
    return profile.tyre_age if profile else None
```

`get_state()` — каждая запись `rivals` дополняется `tyre_age`/`recent_mistake`
(видимость в UI-панели соперников; `recent_mistake` считается на момент вызова
`get_state()` через тот же `get_recent_mistake`, с `now=time.time()` от
вызывающего кода в `engine.py`):

```python
{
    ...  # существующие поля
    "tyre_age": p.tyre_age,
    "recent_mistake": self.get_recent_mistake(p.vehicle_idx, now),
}
```

### 4. `core/engine.py` — проводка

В ветке `PACKET_LAP_DATA`, при сборке `grid` (там же, где уже кладутся
`vehicle_idx`/`position`/`driver`/`team`/`color`/`lap`):

```python
grid.append({
    ...  # существующие поля
    "pit_status": lap_info.get("pit_status", {}).get(vehicle_idx, 0),
})
...
self.rival_tracker.update(grid, player_vehicle_idx=self._player_car_index,
                           now=time.time())
```

В ветке `PACKET_CAR_STATUS`, после существующего разбора игрока:

```python
elif packet_id == PACKET_CAR_STATUS and self._player_car_index < 22:
    telem.update(parse_player_status(data, self._player_car_index))
    for idx, st in parse_car_status_all(data).items():
        if idx != self._player_car_index and st.get("tyre_age") is not None:
            self.rival_tracker.update_tyre(idx, st["tyre_age"])
```

В ветке `PACKET_CAR_DAMAGE`, после существующего разбора игрока:

```python
elif packet_id == PACKET_CAR_DAMAGE and self._player_car_index < 22:
    dmg = parse_player_damage(data, self._player_car_index)
    ...  # существующая логика игрока не меняется
    now = time.time()
    for idx, d in parse_car_damage_all(data).items():
        if idx == self._player_car_index:
            continue
        body = max(d.get("wing_damage", 0), d.get("floor_damage", 0),
                   d.get("gearbox_damage", 0), d.get("engine_damage", 0))
        self.rival_tracker.update_damage(
            idx, body, threshold=_DAMAGE_NOTICEABLE_THRESHOLD, now=now)
```

В точке enrichment `OVTK` (там же, где уже пишутся `driver_style`/
`target_style` из Race Memory v1):

```python
enriched = self.race_state.enrich(event)
if enriched.get("event_code") == "OVTK":
    now = time.time()
    overtaking_idx = enriched.get("overtaking_idx")
    being_overtaken_idx = enriched.get("being_overtaken_idx")
    enriched["driver_style"] = self.rival_tracker.get_style(overtaking_idx)
    enriched["target_style"] = self.rival_tracker.get_style(being_overtaken_idx)
    enriched["driver_recent_mistake"] = self.rival_tracker.get_recent_mistake(overtaking_idx, now)
    enriched["target_recent_mistake"] = self.rival_tracker.get_recent_mistake(being_overtaken_idx, now)
    enriched["driver_tyre_age"] = self.rival_tracker.get_tyre_age(overtaking_idx)
    enriched["target_tyre_age"] = self.rival_tracker.get_tyre_age(being_overtaken_idx)
self.race_state.record_event(event)
```

### 5. `commentator/planner.py::build_plan()` — маркеры

Новая константа рядом с `_STYLE_PHRASES`:

```python
_TYRE_AGE_GAP_THRESHOLD = 5   # кругов разницы, чтобы факт был достоин упоминания
```

Добавляется в тот же список `markers`, что уже собирает «финальные круги»/
«N-я попытка обгона» (Race Memory v1 / final-laps сессия):

```python
if event.get("driver_recent_mistake"):
    markers.append(f"{driver} только что ошибся")
if event.get("target_recent_mistake"):
    markers.append(f"{target} только что ошибся")

d_age = event.get("driver_tyre_age")
t_age = event.get("target_tyre_age")
if d_age is not None and t_age is not None and abs(d_age - t_age) >= _TYRE_AGE_GAP_THRESHOLD:
    fresher = driver if d_age < t_age else target
    markers.append(f"{fresher} на более свежей резине")
```

Пример итоговой строки в насыщенном случае: `"атака (последние 2 круга гонки,
3-я попытка обгона, Пиастри только что ошибся, Норрис на более свежей
резине): Норрис (в ударе) и Пиастри (теряет темп)"`. `must_mention`/
`reaction`/`length`/`emotion` не меняются — маркеры влияют только на `focus`,
тот же принцип, что и в Race Memory v1.

## Файлы

| Файл | Действие |
|---|---|
| `core/packets.py` | `parse_lap_data()` — поле `pit_status`; `_car_status_fields`/`_car_damage_fields` (новые приватные хелперы); `parse_car_status_all`/`parse_car_damage_all` (новые); `parse_player_status`/`parse_player_damage` — делегируют в хелперы, поведение не меняется |
| `core/rivals/models.py` | `RivalProfile` — новые поля `tyre_age`, `body_damage`, `pit_status`, `mistake_at` |
| `core/rivals/tracker.py` | `update()` — параметр `now`, реальный пит вместо эвристики, детект скачка-без-пита; `update_tyre()`, `update_damage()`, `get_recent_mistake()`, `get_tyre_age()` (новые); `get_state()` — новые поля в rival-записях |
| `core/engine.py` | `grid` получает `pit_status`; `PACKET_CAR_STATUS`/`PACKET_CAR_DAMAGE` — проводка в `rival_tracker.update_tyre/update_damage`; `OVTK`-enrichment — 4 новых поля |
| `commentator/planner.py` | `_TYRE_AGE_GAP_THRESHOLD`; маркеры ошибки/резины в `build_plan()` |
| `tests/test_packets_gaps_tyre.py` | тесты на `pit_status` во всех машинах, `parse_car_status_all`, `parse_car_damage_all` |
| `tests/test_rivals.py` | **переписать** тесты пит-детекта (сейчас проверяют старую эвристику — станут неверными); новые тесты на `update_tyre`/`update_damage`/`get_recent_mistake`/`get_tyre_age`, окно давности, реальный пит НЕ считается ошибкой |
| `tests/test_planner.py` | тесты на новые маркеры по отдельности/вместе, отсутствие полей не ломает `build_plan` |
| `CONTEXT.md` | запись новой сессии, снятие пункта из «Известных gotchas»/Race Memory backlog |

## Отказоустойчивость

Вся новая логика — чистые синхронные операции без сети/I/O, тот же характер,
что у остального `race_state`/`planner`/`tracker`. `get_recent_mistake`/
`get_tyre_age` безопасны для `None`/незнакомого `vehicle_idx` (возвращают
`False`/`None`, не бросают) — тот же контракт, что уже есть у `get_style()`.
`update_tyre`/`update_damage` безопасно no-op для ещё не зарегистрированного
`vehicle_idx` (профиль появится на следующем `LapData`-тике, догонит сам).
Парсер по-прежнему не роняет процесс на битых/укороченных пакетах — те же
guard-и (`base + N > len(data)`), что уже используются везде в `packets.py`.

## Верификация

- Новые/переписанные тесты (см. таблицу выше). Особое внимание:
  `test_pit_detected_on_large_position_drop` и смежные — раньше проверяли
  «скачок позиции = пит», теперь пит нужно явно смоделировать через
  `pit_status`, а «скачок без пита» — отдельный новый тест на `mistake_at`.
- Полный прогон: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q` —
  текущий бейслайн 945 passed, 1 skipped (сессия Phrase Bank Expansion,
  2026-07-05) должен остаться зелёным (с поправкой на переписанные тесты пит-
  детекта) плюс новые тесты.
- Импорт-смоук: `core.packets, core.rivals.tracker, core.engine,
  commentator.planner`.
