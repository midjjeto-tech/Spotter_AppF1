# In-game HUD: Radar + Relative — дизайн

Дата: 2026-07-22
Статус: утверждён пользователем (диалог 2026-07-22), реализация — по плану в
`docs/superpowers/plans/`.

## Контекст

По итогам обзора конкурентов (OverTake.gg community-оверлеи для SimHub,
RaceLab.app) выявлены два наиболее ценных и наиболее дешёвых в реализации
пробела в in-game HUD (`NewSpotterUI/components/spotter/overlay/in-game-overlay.tsx`):

1. **Radar** — индикатор ближних машин слева/справа. Есть почти у всех
   конкурентов, самая частая «safety»-фича любого симрейсинг-оверлея.
2. **Relative** — список ближайших соперников (не только P±1) с именем и
   отрывом в секундах, а не абсолютный топ-5.

Обе фичи оказались дешёвыми, потому что нужные данные **уже считаются**
движком для других целей и просто выбрасываются:

- `core/engine.py::_spotter_tick()` (см. `docs/superpowers/specs/2026-07-18-real-spotter-motion-design.md`)
  на каждом Motion-тике уже проецирует мировые координаты соперников на ось
  игрока и получает `(lateral, side)` — но с окном `LONGITUDINAL_WINDOW_M = 6.0`
  м, откалиброванным под голосовой safety-колл, а не под визуальный радар,
  и результат нигде не сохраняется — используется только внутри тика и
  выбрасывается.
- `core/packets.py::parse_lap_data()` уже парсит `gaps_front` (отрыв до
  машины впереди, мс) **для всех 22 машин**, но `core/engine.py` использует
  только запись игрока (`self._player_gap_behind` и т.п.) — сами данные по
  чужим машинам никуда не попадают.

Пользователь подтвердил объём: только Radar + Relative в этом заходе.
Delta-бар (эталонный круг) и топливный калькулятор — отдельные фичи,
намеренно не входят.

## Решение

### 1. Radar — второй, более широкий проход в `_spotter_tick` (`core/engine.py`)

Существующий цикл по `motion_all` в `_spotter_tick()` уже даёт `rel_x`,
`rel_z`, `lateral`, `side` для каждой машины, прошедшей дешёвый
продольный фильтр по `lap_distance`. Не меняя порог и логику голосового
споттера (`LONGITUDINAL_WINDOW_M`, `SpotterTracker`), добавляем отдельную,
более широкую константу и параллельно копим более богатую запись:

```python
RADAR_WINDOW_M = 25.0  # видимость радара шире, чем окно голосового споттера

def _spotter_tick(self, motion_all: dict[int, dict]) -> None:
    ...
    player_dist = self._lap_distances.get(self._player_car_index)
    if player_dist is None:
        return

    candidates: list[tuple[float, str]] = []      # существующий, для голоса
    radar: list[dict] = []                         # новый, для HUD
    for idx, m in motion_all.items():
        if idx == self._player_car_index:
            continue
        rival_dist = self._lap_distances.get(idx)
        if rival_dist is None:
            continue
        longitudinal = rival_dist - player_dist    # знак: + впереди, - позади
        if abs(longitudinal) > RADAR_WINDOW_M:
            continue
        rel_x = m["world_x"] - player["world_x"]
        rel_z = m["world_z"] - player["world_z"]
        lateral = rel_x * player["right_x"] + rel_z * player["right_z"]
        side = "right" if lateral > 0 else "left"
        radar.append({
            "vehicle_idx": idx, "side": side,
            "lateral_m": round(abs(lateral), 1),
            "longitudinal_m": round(longitudinal, 1),
        })
        if abs(longitudinal) <= LONGITUDINAL_WINDOW_M:   # существующий узкий фильтр
            candidates.append((abs(lateral), side))

    self._radar = sorted(radar, key=lambda c: abs(c["longitudinal_m"]))[:6]
    ...  # существующий вызов self._race_engineer.spotter_advisory(candidates, ...) без изменений
```

`self._radar` — plain-список словарей, обновляется каждый Motion-тик,
читается синхронно из `get_overlay_state()` (без блокировки — то же самое
допущение, что уже применяется к остальным snapshot-полям движка, читаемым
из другого потока).

**Уточнение после реализации:** явный сброс `self._radar` на SSTA/CHQF/
flashback НЕ добавлен — как и `self._lap_distances`/`self._current_grid`,
это «последнее известное значение с любого тика», тот же паттерн, что уже
принят в проекте (см. план `docs/superpowers/plans/2026-07-22-overlay-radar-relative.md`,
Task 4). Раздел выше описывал первоначальное намерение до сверки с
существующей конвенцией; расхождение сознательное, не забытая доработка.

### 2. Relative — проброс `gap_front_ms` по всем машинам (`core/engine.py`, `core/packets.py`)

`parse_lap_data()` уже возвращает `gaps_front: dict[int, int]` — менять
парсинг не нужно. Меняется только сборка `grid` в lap_data-хендлере
(`core/engine.py`, там же, где сейчас строится `grid.append({...})`):

```python
gaps_front = lap_info.get("gaps_front", {})
...
grid.append({
    "vehicle_idx": vehicle_idx,
    "position": position,
    "driver": driver_info["name"],
    "team": driver_info["team"],
    "color": driver_info["color"],
    "lap": lap_info.get("laps", {}).get(vehicle_idx, 0),
    "pit_status": lap_info.get("pit_status", {}).get(vehicle_idx, 0),
    "gap_front_ms": gaps_front.get(vehicle_idx),   # новое
})
```

### 3. `core/ui_state.py::overlay()` — перестать резать `grid` до 5 раньше времени

Сейчас: `"grid": list(race.get("grid", []))[:5]` — обрезка до топ-5
происходит здесь, **до** `build_overlay_state`, поэтому если игрок не в
топ-5 (например, P12), у `build_overlay_state` физически нет данных о его
соседях. Меняем на полный список:

```python
"grid": list(race.get("grid", [])),   # полный список; топ-5 срезается ниже, в overlay.py
```

Обрезка «топ-5 по позиции» (для уже существующего виджета `RACE CONTROL` —
там сейчас пусто, `grid_top5` нигде не рендерится, но контракт трогать не
будем) переезжает внутрь `core/overlay.py::build_overlay_state`, на то же
самое место, где она и была (`grid_top5 = sorted(grid_raw, ...)[:5]`) —
поведение этого поля не меняется, меняется только то, ЧТО видит функция
до среза.

### 4. `core/overlay.py::build_overlay_state` — новые поля `radar` и `relative`

```python
def _relative_rows(grid: list[dict], player_position: int | None,
                    *, ahead: int = 3, behind: int = 3) -> list[dict]:
    """Строки вокруг игрока с НАКОПЛЕННЫМ гэпом (сумма gap_front_ms между
    позициями от игрока до целевой строки), не сырым gap_front_ms целевой
    строки (тот — гэп только к СВОЕМУ непосредственному соседу впереди)."""
    if player_position is None:
        return []
    by_pos = {row["position"]: row for row in grid if row.get("position")}
    player_row = by_pos.get(player_position)
    if player_row is None:
        return []

    rows: list[dict] = []
    cumulative = 0
    for pos in range(player_position - 1, player_position - ahead - 1, -1):
        row = by_pos.get(pos)
        if row is None:
            break
        cumulative += row.get("gap_front_ms") or 0
        rows.append({**row, "gap_to_player_ms": cumulative, "ahead": True})
    rows.reverse()
    rows.append({**player_row, "gap_to_player_ms": 0, "ahead": None})

    cumulative = 0
    for pos in range(player_position + 1, player_position + behind + 1):
        row = by_pos.get(pos)
        if row is None:
            break
        cumulative += row.get("gap_front_ms") or 0
        rows.append({**row, "gap_to_player_ms": cumulative, "ahead": False})
    return rows
```

`build_overlay_state` получает снапшот с новым ключом `radar` (список из
п.1, уже готовый) и использует `_relative_rows(grid_raw, snapshot.get("position"))`
для нового ключа `relative`. `grid_top5` считается на том же `grid_raw`,
как и раньше.

**Уточнение после реализации (найден и исправлен реальный баг на этапе
ревью):** псевдокод выше для направления «ahead» — ОШИБОЧНЫЙ, оставлен как
исторический артефакт первого черновика, не как рабочая версия. `gap_front_ms`
строки — это её СОБСТВЕННЫЙ гэп до машины ВПЕРЕДИ неё (F1 UDP
`m_deltaToCarInFront`). Значит гэп «игрок → строка N» в направлении вперёд
обязан НАЧИНАТЬСЯ с СОБСТВЕННОГО `gap_front_ms` игрока, а не строки N (тот —
гэп N до СЛЕДУЮЩЕЙ, ещё более далёкой от игрока машины). Рабочая реализация
(`core/overlay.py::_relative_rows`) накапливает через `prev_gap`, засеянный
`player_row.get("gap_front_ms")` ДО цикла, и сдвигаемый на `row.get("gap_front_ms")`
ПОСЛЕ каждого шага — направление «behind» сдвига не требует (гэп строки уже
прямо измеряет то, что нужно). Также строка игрока получает
`"gap_to_player_ms": None` (не `0` из черновика) + отдельный `"gap_to_player_str"`
через `_fmt_gap_ms`. Баг был найден только при перепроверке смежного
замечания ревью Task 3 — тесты первого черновика были написаны тем же
(ошибочным) способом мышления, поэтому прошли ревью, не поймав расхождение
с реальной семантикой. Актуальный контракт TS (п.5) — `gap_to_player_ms:
number | null`, не `number` — соответствует рабочей версии.

### 5. Контракт `/api/overlay` (обновить `NewSpotterUI/lib/api.ts::OverlayState`)

```ts
radar: { vehicle_idx: number; side: "left" | "right"; lateral_m: number; longitudinal_m: number }[]
relative: {
  vehicle_idx: number; position: number; driver: string; team: string; color: string;
  gap_to_player_ms: number; ahead: boolean | null;   // null = строка игрока
}[]
```

Оба поля — пустые списки, если данных нет (нет геймплея, iRacing — см.
ниже), фронтенд уже следует конвенции «нет данных → `—`/скрыть строку», не
подставляет фиктивные нули.

### 6. Frontend — `NewSpotterUI/components/spotter/overlay/in-game-overlay.tsx`

- **Radar** — новый `WidgetId "radar"`, компактный круглый виджет (машина
  игрока в центре, точки соперников слева/справа на расстоянии,
  пропорциональном `longitudinal_m`/`lateral_m`), тот же визуальный язык,
  что у `Frame` (тёмная панель, `border-white/15`). Пусто, если
  `overlay.radar` — пустой массив (не «нет соперников рядом», а честное
  «не показываем», как остальные виджеты при отсутствии данных).
- **Relative** — новый `WidgetId "relative"`, узкая табличная колонка
  (позиция · имя · гэп со знаком, свой ряд подсвечен). Гэп форматируется
  тем же хелпером, что и `to_front_str`/`to_behind_str` (`+`/`-` и три
  знака после точки).
- Оба — в общей системе drag/layout (`DEFAULT_LAYOUT`/`WIDGET_SIZE`/
  `fittedDefaultLayout`/`STORAGE_KEY`), как остальные 4 виджета.

### 7. iRacing — осознанное ограничение, не баг

`core/iracing_telemetry.py` сейчас опрашивает только `CarIdxPosition`,
`CarIdxLap`, `CarIdxOnPitRoad`, `CarIdxLapDistPct` — ни мировых координат,
ни готового отрыва по всем машинам оттуда сейчас не идёт. Для iRacing оба
новых поля (`radar`, `relative`) будут пустыми списками до отдельной фичи
разбора недостающей iRacing-телеметрии (`CarIdxEstTime` и т.п.) — это НЕ
входит в объём текущего изменения.

## Не входит в объём

- Delta-бар (эталонный круг) и топливный калькулятор — отдельные фичи,
  пользователь явно отложил их на следующий заход.
- iRacing-телеметрия для Radar/Relative (см. п.7).
- Изменение уже существующего порога/поведения голосового споттера
  (`LONGITUDINAL_WINDOW_M`, `SpotterTracker`, `LATERAL_ENTER_M` и т.п.) —
  Radar использует отдельную, более широкую константу, не трогая
  откалиброванные (пусть и приблизительно) safety-параметры.
- Учёт заворота `lap_distance` на финишной прямой в Radar — то же
  принятое v1-ограничение, что и в дизайне голосового споттера
  (`docs/superpowers/specs/2026-07-18-real-spotter-motion-design.md`), по
  той же причине (нет справочника длины трасс в метрах).
- Полный (не топ-5) leaderboard-виджет — вне объёма, `grid_top5` не меняет
  поведение.

## Граничные случаи

- **Игрок вне топ-5, но `grid` теперь полный** — `_relative_rows` ищет
  строку игрока по `position` в полном списке, не зависит от порядка/среза
  `grid_top5`.
- **Игрок P1 или последний** — `ahead`/`behind` диапазоны естественно
  укорачиваются (`by_pos.get(pos) is None` → `break`), без фиктивных строк.
- **Пропуск позиции в `grid`** (сошедшая машина/неполный тик) — тот же
  `break`, накопленный гэп не «перепрыгивает» через дыру с неверным числом.
- **Нет кандидатов в радиусе радара** — `self._radar = []`, виджет ничего
  не рисует (не «чисто», как у голосового споттера — это визуальный
  виджет, не событие, которому нужно явное состояние «свободно»).
- **Смена сессии/flashback** — `self._radar` сбрасывается в тех же 3
  точках, что и остальные per-tick снапшоты движка.

## Тестирование

- `tests/test_engine_spotter.py` (уже существует, см. дизайн 2026-07-18) —
  добавить кейсы на `self._radar`: содержит машины в широком окне, не
  включает машины уже вне `RADAR_WINDOW_M`, не влияет на существующие
  ассерты по `candidates`/`SpotterTracker`.
- Новый unit-тест на проброс `gap_front_ms` в `grid` (lap_data-хендлер
  engine.py) — синтетический `lap_info` с `gaps_front`, проверка, что
  значение долетает до `self._current_grid`.
- Новый unit-тест на `core/overlay.py::_relative_rows` — игрок в середине
  пелотона, игрок P1, игрок последний, дыра в позициях, накопленный гэп
  считается верно (не сырой `gap_front_ms` соседней строки).
- `tests/test_ui_state.py`/`tests/test_overlay.py` — обновить под полный
  (не срезанный до 5) `grid` на входе в `build_overlay_state`; добавить
  проверку, что `grid_top5` в ответе не изменился по поведению.
- Полный `py -3.12 -u -m pytest -q` в конце.
- Живая проверка пользователем в игре (F1 25) — визуальная калибровка
  `RADAR_WINDOW_M`, читаемость Relative-таблицы при реальных именах/гэпах.
