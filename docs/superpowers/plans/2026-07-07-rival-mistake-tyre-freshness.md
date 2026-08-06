# Rival Mistake + Tyre Freshness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse opponent tyre age and detect opponent "recent mistake" (damage spike or big position loss without a real pit stop), then surface both as descriptive markers in the LLM directive for `OVTK` events only — exactly like `battle_count`/`driver_style` from Race Memory v1.

**Architecture:** Extend the existing all-cars `LapData` parser with a real `pit_status` field, add two new all-cars parsers (`parse_car_status_all`, `parse_car_damage_all`) that share offset logic with the existing player-only parsers, feed the results into `RivalTracker` (which gains mistake/tyre-age tracking), and read those facts back into `commentator/planner.py::build_plan()` at the same `OVTK` enrichment point already used for style/battle_count.

**Tech Stack:** Python 3.12, pytest, no new dependencies.

**Design doc:** `docs/superpowers/specs/2026-07-07-rival-mistake-tyre-freshness-design.md`

**Note on git:** this project is not under version control (see `CONTEXT.md`). Per the user's decision this cycle, task steps end with a "Checkpoint" (verify + move on) instead of a git commit — do not run `git commit`.

---

### Task 1: `parse_lap_data()` — real `pit_status` for all cars

**Files:**
- Modify: `core/packets.py:284-301` (`parse_lap_data`)
- Test: `tests/test_packets_gaps_tyre.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_packets_gaps_tyre.py` (near `test_parse_lap_data_positions_and_gaps`):

```python
def test_parse_lap_data_pit_status_for_all_cars():
    buf = _buf(HEADER_SIZE + 22 * LAP_DATA_SIZE)

    base0 = HEADER_SIZE + 0 * LAP_DATA_SIZE
    buf[base0 + 32] = 1
    buf[base0 + 34] = 0                                # не в боксах

    base1 = HEADER_SIZE + 1 * LAP_DATA_SIZE
    buf[base1 + 32] = 2
    buf[base1 + 34] = 1                                # в пит-лейне

    out = packets.parse_lap_data(buf)
    assert out["pit_status"][0] == 0
    assert out["pit_status"][1] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_packets_gaps_tyre.py::test_parse_lap_data_pit_status_for_all_cars -v`
Expected: FAIL with `KeyError: 'pit_status'`

- [ ] **Step 3: Implement**

Replace `parse_lap_data` in `core/packets.py` with:

```python
def parse_lap_data(data: bytes) -> dict:
    """Позиции всех машин + лидер (P1) + отрыв к машине впереди (для расчёта соседей)
    + реальный pit_status (для RivalTracker — отличать настоящий пит от ошибки/спина).
    F1 25 LapData: m_carPosition на offset 32, m_currentLapNum на 33, m_pitStatus на 34.
    deltaToCarInFront: msPart@14 + minutesPart@16 (формат как у секторов).
    PacketLapData не имеет numActiveCars — данные 22 машин начинаются сразу после header."""
    positions: dict[int, int] = {}
    laps: dict[int, int] = {}
    gaps_front: dict[int, int] = {}   # idx -> мс отрыва до машины впереди
    pit_status: dict[int, int] = {}
    for idx in range(22):
        base = HEADER_SIZE + idx * LAP_DATA_SIZE
        if base + 35 > len(data):
            break
        positions[idx] = data[base + 32]  # m_carPosition
        laps[idx] = data[base + 33]       # m_currentLapNum
        pit_status[idx] = data[base + 34]  # m_pitStatus: 0=нет, 1=заезжает, 2=в пит-лейн
        gaps_front[idx] = _lap_delta_ms(data, base, 14, 16)
    leader_idx = next((i for i, p in positions.items() if p == 1), None)
    return {"positions": positions, "laps": laps, "pit_status": pit_status,
            "leader_idx": leader_idx, "gaps_front": gaps_front}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_packets_gaps_tyre.py -v`
Expected: all PASS, including `test_parse_lap_data_positions_and_gaps` (unchanged — guard was `base+34`, now `base+35`, still true for the same buffer sizes used by that test)

- [ ] **Step 5: Checkpoint**

Confirm both `parse_lap_data` tests pass, no other test file references `parse_lap_data` output shape (grep confirmed only this file and `core/engine.py` use it — engine.py is Task 10). Move to Task 2.

---

### Task 2: `parse_car_status_all()` — tyre age for all cars

**Files:**
- Modify: `core/packets.py:386-401` (`parse_player_status`)
- Test: `tests/test_packets_gaps_tyre.py`

- [ ] **Step 1: Write the failing test**

```python
def test_parse_car_status_all_tyre_age_per_car():
    buf = _buf(HEADER_SIZE + 22 * CAR_STATUS_SIZE)
    base0 = HEADER_SIZE + 0 * CAR_STATUS_SIZE
    buf[base0 + 26] = 16          # visual compound = soft
    buf[base0 + 27] = 3           # tyre age
    base1 = HEADER_SIZE + 1 * CAR_STATUS_SIZE
    buf[base1 + 26] = 17          # medium
    buf[base1 + 27] = 12

    out = packets.parse_car_status_all(buf)
    assert out[0]["tyre_age"] == 3
    assert out[0]["tyre_compound"] == "S"
    assert out[1]["tyre_age"] == 12
    assert out[1]["tyre_compound"] == "M"


def test_parse_car_status_all_matches_parse_player_status():
    """parse_player_status делегирует в тот же хелпер — результат идентичен
    для того же car_idx."""
    buf = _buf(HEADER_SIZE + 22 * CAR_STATUS_SIZE)
    base1 = HEADER_SIZE + 1 * CAR_STATUS_SIZE
    buf[base1 + 26] = 18
    buf[base1 + 27] = 7
    struct.pack_into("<f", buf, base1 + 5, 42.5)

    all_out = packets.parse_car_status_all(buf)
    single_out = packets.parse_player_status(buf, 1)
    assert all_out[1] == single_out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_packets_gaps_tyre.py::test_parse_car_status_all_tyre_age_per_car -v`
Expected: FAIL with `AttributeError: module 'core.packets' has no attribute 'parse_car_status_all'`

- [ ] **Step 3: Implement**

Replace `parse_player_status` in `core/packets.py` with:

```python
def _car_status_fields(data: bytes, base: int) -> dict:
    """Топливо + шины (компаунд/возраст) для ОДНОЙ машины на офсете `base`.
    Общий хелпер для parse_player_status (один car_idx) и parse_car_status_all
    (все 22) — офсеты не дублируются в двух местах."""
    fuel = struct.unpack_from("<f", data, base + 5)[0]
    out = {"fuel": round(fuel, 1)}
    if base + 28 <= len(data):
        visual = data[base + 26]
        out["tyre_compound"] = TYRE_VISUAL.get(visual, "?")
        out["tyre_age"] = data[base + 27]
    return out


def parse_player_status(data: bytes, player_idx: int) -> dict:
    """Топливо + шины (компаунд/возраст) из Car Status (packet 7) для игрока.
    F1 25: m_fuelInTank@5, m_visualTyreCompound@26, m_tyresAgeLaps@27.

    PacketCarStatusData = header + CarStatusData[22], NO numActiveCars prefix
    (only PacketParticipantsData has one). Same framing as parse_lap_data."""
    base = HEADER_SIZE + player_idx * CAR_STATUS_SIZE
    if base + 9 > len(data):
        return {}
    return _car_status_fields(data, base)


def parse_car_status_all(data: bytes) -> dict[int, dict]:
    """Как parse_player_status, но для всех 22 машин — нужно RivalTracker для
    свежести резины соперника (design spec 2026-07-07-rival-mistake-tyre-freshness)."""
    out: dict[int, dict] = {}
    for idx in range(22):
        base = HEADER_SIZE + idx * CAR_STATUS_SIZE
        if base + 9 > len(data):
            break
        out[idx] = _car_status_fields(data, base)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_packets_gaps_tyre.py -v`
Expected: all PASS, including existing `test_parse_player_status_tyre_compound` (unchanged behavior)

- [ ] **Step 5: Checkpoint**

Move to Task 3.

---

### Task 3: `parse_car_damage_all()` — body damage for all cars

**Files:**
- Modify: `core/packets.py:404-435` (`parse_player_damage`)
- Test: `tests/test_packets_gaps_tyre.py`

- [ ] **Step 1: Write the failing test**

```python
def test_parse_car_damage_all_categories_per_car():
    stride = 42
    buf = _buf(HEADER_SIZE + 22 * stride)
    base1 = HEADER_SIZE + 1 * stride
    buf[base1 + 24] = 45          # wing
    buf[base1 + 27] = 10          # floor
    buf[base1 + 32] = 5           # gearbox
    buf[base1 + 33] = 0           # engine

    out = packets.parse_car_damage_all(buf)
    assert out[1]["wing_damage"] == 45
    assert out[1]["floor_damage"] == 10
    assert out[0]["wing_damage"] == 0     # car 0 untouched


def test_parse_car_damage_all_matches_parse_player_damage():
    stride = 42
    buf = _buf(HEADER_SIZE + 22 * stride)
    base1 = HEADER_SIZE + 1 * stride
    struct.pack_into("<ffff", buf, base1 + 0, 10.0, 10.0, 10.0, 10.0)
    buf[base1 + 24] = 20

    all_out = packets.parse_car_damage_all(buf)
    single_out = packets.parse_player_damage(buf, 1)
    assert all_out[1] == single_out


def test_parse_car_damage_all_bad_stride_guard():
    assert packets.parse_car_damage_all(_buf(HEADER_SIZE + 22 * 10)) == {}
    assert packets.parse_car_damage_all(_buf(HEADER_SIZE)) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_packets_gaps_tyre.py::test_parse_car_damage_all_categories_per_car -v`
Expected: FAIL with `AttributeError: module 'core.packets' has no attribute 'parse_car_damage_all'`

- [ ] **Step 3: Implement**

Replace `parse_player_damage` in `core/packets.py` with:

```python
def _car_damage_fields(data: bytes, base: int) -> dict:
    """Износ шин + категории повреждений кузова для ОДНОЙ машины на офсете
    `base`. Общий хелпер для parse_player_damage (один car_idx) и
    parse_car_damage_all (все 22) — офсеты не дублируются в двух местах."""
    wear = struct.unpack_from("<ffff", data, base + 0)   # RL, RR, FL, FR
    avg = sum(wear) / 4.0
    wing = max(data[base + 24], data[base + 25], data[base + 26])
    floor = max(data[base + 27], data[base + 28], data[base + 29])
    gearbox = data[base + 32]
    engine = data[base + 33]
    return {
        "tyre_wear": round(avg, 1),
        "wing_damage": wing,
        "floor_damage": floor,
        "gearbox_damage": gearbox,
        "engine_damage": engine,
    }


def parse_player_damage(data: bytes, player_idx: int) -> dict:
    """Износ шин + категории повреждений кузова из Car Damage (packet 10) для
    игрока. Офсеты 24-33 подтверждены косвенно: уже существующий тест этого
    файла использует stride=42 как "правдоподобный размер структуры", что
    совпадает с полной раскладкой полей F1 25 CarDamageData (42 байта на
    машину) — тем не менее сверить с реальной телеметрией через
    diag_lap_offsets.py перед тем, как полностью полагаться (см. design spec
    docs/superpowers/specs/2026-07-05-damage-and-collisions-design.md §2).
    Шаг машины выводим из длины пакета (numCars нет, как и в LapData) — без
    хардкода размера."""
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
    """Как parse_player_damage, но для всех 22 машин — нужно RivalTracker для
    детекта "соперник только что ошибся" (design spec
    2026-07-07-rival-mistake-tyre-freshness)."""
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

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_packets_gaps_tyre.py -v`
Expected: all PASS, including existing `test_parse_player_damage_*` tests (unchanged behavior)

- [ ] **Step 5: Checkpoint**

Move to Task 4.

---

### Task 4: `RivalProfile` — new fields

**Files:**
- Modify: `core/rivals/models.py`
- Test: `tests/test_rivals.py`

- [ ] **Step 1: Write the failing test**

Add near `test_rival_profile_fields` in `tests/test_rivals.py`:

```python
def test_rival_profile_new_fields_default():
    profile = RivalProfile(
        vehicle_idx=3, driver="Carlos Sainz", team="Ferrari",
        pit_count=0, lap_count=1, current_position=5,
        style="consistent", nearby=False,
    )
    assert profile.tyre_age is None
    assert profile.body_damage == 0.0
    assert profile.pit_status == 0
    assert profile.mistake_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_rivals.py::test_rival_profile_new_fields_default -v`
Expected: FAIL with `AttributeError: 'RivalProfile' object has no attribute 'tyre_age'`

- [ ] **Step 3: Implement**

In `core/rivals/models.py`, replace the `RivalProfile` dataclass with:

```python
@dataclass
class RivalProfile:
    vehicle_idx: int
    driver: str
    team: str
    pit_count: int
    lap_count: int
    current_position: int
    style: str                          # "consistent"|"aggressive"|"charging"|"fading"
    nearby: bool                        # within ±3 positions of player
    position_history: deque = field(default_factory=lambda: deque(maxlen=10))
    tyre_age: int | None = None
    body_damage: float = 0.0
    pit_status: int = 0                 # последний известный m_pitStatus (0/1/2)
    mistake_at: float | None = None     # timestamp последней детектированной ошибки
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_rivals.py -v`
Expected: all PASS (existing `RivalProfile`/`RivalSnapshot` tests unaffected — new fields have defaults)

- [ ] **Step 5: Checkpoint**

Move to Task 5.

---

### Task 5: `RivalTracker.update()` — real pit detection replaces heuristic

**Files:**
- Modify: `core/rivals/tracker.py`
- Test: `tests/test_rivals.py`

This task changes existing behavior: `pit_count` used to increment on any big
position jump (heuristic); now it increments only on a real `pit_status`
transition. The three existing pit tests must be rewritten to supply
`pit_status` explicitly — a jump without it is no longer a pit (Task 6 turns
it into a mistake signal instead).

- [ ] **Step 1: Update the `_grid` helper and rewrite the failing tests**

Replace the `_grid` helper and the three pit-detection tests in
`tests/test_rivals.py`:

```python
def _grid(*entries) -> list[dict]:
    """Build a grid list from (vehicle_idx, position, lap, driver) or
    (vehicle_idx, position, lap, driver, pit_status) tuples. pit_status
    defaults to 0 (not in the pit lane) when omitted."""
    out = []
    for e in entries:
        vi, pos, lap, drv = e[:4]
        pit_status = e[4] if len(e) > 4 else 0
        out.append({"vehicle_idx": vi, "position": pos, "lap": lap,
                     "driver": drv, "team": "Team", "color": "#fff",
                     "pit_status": pit_status})
    return out


# --- pit detection (real pit_status, not position-jump heuristic) ---

def test_pit_detected_on_real_pit_status_transition():
    t = RivalTracker()
    t.update(_grid((0, 1, 5, "Player"), (1, 3, 5, "Sainz", 0)), player_vehicle_idx=0, now=1.0)
    t.update(_grid((0, 1, 6, "Player"), (1, 18, 6, "Sainz", 1)), player_vehicle_idx=0, now=2.0)
    state = t.get_state()
    sainz = next(r for r in state["rivals"] if r["driver"] == "Sainz")
    assert sainz["pit_count"] == 1


def test_pit_not_counted_from_position_jump_without_pit_status():
    """Раньше pit_count считался эвристикой по размеру скачка позиции — теперь
    только по реальному pit_status. Большой скачок БЕЗ пита — сигнал "ошибка",
    не пит (см. test_mistake_detected_on_large_position_loss_without_pit,
    Task 6)."""
    t = RivalTracker()
    t.update(_grid((0, 1, 5, "Player"), (1, 3, 5, "Sainz", 0)), player_vehicle_idx=0, now=1.0)
    t.update(_grid((0, 1, 6, "Player"), (1, 18, 6, "Sainz", 0)), player_vehicle_idx=0, now=2.0)
    state = t.get_state()
    sainz = next(r for r in state["rivals"] if r["driver"] == "Sainz")
    assert sainz["pit_count"] == 0


def test_pit_not_detected_on_small_position_change():
    t = RivalTracker()
    t.update(_grid((0, 1, 5, "Player"), (1, 3, 5, "Sainz", 0)), player_vehicle_idx=0, now=1.0)
    t.update(_grid((0, 1, 6, "Player"), (1, 5, 6, "Sainz", 0)), player_vehicle_idx=0, now=2.0)
    state = t.get_state()
    sainz = next(r for r in state["rivals"] if r["driver"] == "Sainz")
    assert sainz["pit_count"] == 0


def test_pit_count_increments_on_each_real_pit_entry():
    t = RivalTracker()
    for g in [
        _grid((0, 1, 5, "Player"), (1, 3, 5, "Sainz", 0)),
        _grid((0, 1, 6, "Player"), (1, 18, 6, "Sainz", 1)),   # заезд 1
        _grid((0, 1, 6, "Player"), (1, 8, 7, "Sainz", 0)),    # выехал
        _grid((0, 1, 7, "Player"), (1, 3, 7, "Sainz", 0)),
        _grid((0, 1, 8, "Player"), (1, 19, 8, "Sainz", 1)),   # заезд 2
    ]:
        t.update(g, player_vehicle_idx=0, now=1.0)
    sainz = next(r for r in t.get_state()["rivals"] if r["driver"] == "Sainz")
    assert sainz["pit_count"] == 2
```

Delete the old `test_pit_detected_on_large_position_drop`, old
`test_pit_not_detected_on_small_position_change`, and old
`test_pit_count_increments` (replaced by the four above). All other existing
tests in the file (`test_tracker_registers_rivals`,
`test_tracker_player_excluded`, `test_tracker_nearby_flag`,
`test_nearby_count`, `test_style_*`, `test_get_state_has_all_keys`,
`test_rival_entry_has_all_fields`, `test_get_style_*`) call
`t.update(grid, player_vehicle_idx=0)` without `now` — leave them unchanged,
`now` gets a default value in Step 3 so they keep passing untouched.

- [ ] **Step 2: Run tests to verify the new/changed ones fail**

Run: `py -3.12 -m pytest tests/test_rivals.py -v`
Expected: the 4 pit tests FAIL (`TypeError: update() got an unexpected keyword argument 'now'` or wrong `pit_count`); all other tests still PASS

- [ ] **Step 3: Implement**

In `core/rivals/tracker.py`, rename the threshold and rewrite `update()`:

```python
_NEARBY_WINDOW = 3          # positions ±N = nearby
_POSITION_LOSS_THRESHOLD = 8   # was _PIT_DROP_THRESHOLD — big position loss without
                                # a real pit_status is now a "mistake" signal, not a pit
_MIN_HISTORY_STYLE = 4      # need at least N ticks for style judgment
_STYLE_VARIANCE_HIGH = 4.0  # std dev threshold for "aggressive"
_STYLE_TREND_THRESHOLD = 2  # avg delta > this magnitude = charging/fading
_MISTAKE_RECENCY_WINDOW = 60.0   # seconds — how long a detected mistake stays "recent"
```

```python
    def update(self, grid: list[dict], player_vehicle_idx: int, now: float = 0.0) -> None:
        player_pos = 0
        for entry in grid:
            if entry["vehicle_idx"] == player_vehicle_idx:
                player_pos = entry["position"]
                break
        self._player_position = player_pos

        for entry in grid:
            vi = entry["vehicle_idx"]
            if vi == player_vehicle_idx:
                continue
            pos = entry.get("position", 0)
            lap = entry.get("lap", 0)
            pit_status = entry.get("pit_status", 0)
            driver = entry.get("driver", f"Car #{vi}")
            team = entry.get("team", "—")

            if vi not in self._profiles:
                self._profiles[vi] = RivalProfile(
                    vehicle_idx=vi,
                    driver=driver,
                    team=team,
                    pit_count=0,
                    lap_count=lap,
                    current_position=pos,
                    style="consistent",
                    nearby=False,
                )

            profile = self._profiles[vi]
            if driver and driver != f"Car #{vi}":
                profile.driver = driver
                profile.team = team

            prev_pos = profile.current_position
            prev_pit_status = profile.pit_status
            profile.current_position = pos
            profile.pit_status = pit_status
            profile.lap_count = lap
            profile.nearby = player_pos > 0 and abs(pos - player_pos) <= _NEARBY_WINDOW

            if pos > 0:
                profile.position_history.append(pos)

            entered_pit = prev_pit_status == 0 and pit_status != 0
            if entered_pit:
                profile.pit_count += 1
            elif (prev_pos > 0 and pos > 0
                  and pos - prev_pos >= _POSITION_LOSS_THRESHOLD
                  and pit_status == 0):
                profile.mistake_at = now

            profile.style = _classify_style(profile.position_history)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_rivals.py -v`
Expected: all PASS

- [ ] **Step 5: Checkpoint**

Move to Task 6.

---

### Task 6: Mistake signal — verify it via `get_recent_mistake` (accessor added in Task 8)

Task 5's implementation already sets `mistake_at` on a big position loss
without a pit. This task just adds the test proving it, using the profile
field directly (the public accessor `get_recent_mistake` is added in Task 8 —
testing the field here keeps Task 5 and Task 8 independently verifiable).

**Files:**
- Test: `tests/test_rivals.py`

- [ ] **Step 1: Write the test**

```python
def test_mistake_timestamp_set_on_large_position_loss_without_pit():
    t = RivalTracker()
    t.update(_grid((0, 1, 5, "Player"), (1, 3, 5, "Sainz", 0)), player_vehicle_idx=0, now=1.0)
    t.update(_grid((0, 1, 6, "Player"), (1, 18, 6, "Sainz", 0)), player_vehicle_idx=0, now=42.0)
    assert t._profiles[1].mistake_at == 42.0


def test_mistake_timestamp_not_set_on_real_pit_transition():
    t = RivalTracker()
    t.update(_grid((0, 1, 5, "Player"), (1, 3, 5, "Sainz", 0)), player_vehicle_idx=0, now=1.0)
    t.update(_grid((0, 1, 6, "Player"), (1, 18, 6, "Sainz", 1)), player_vehicle_idx=0, now=42.0)
    assert t._profiles[1].mistake_at is None
```

- [ ] **Step 2: Run test**

Run: `py -3.12 -m pytest tests/test_rivals.py::test_mistake_timestamp_set_on_large_position_loss_without_pit tests/test_rivals.py::test_mistake_timestamp_not_set_on_real_pit_transition -v`
Expected: both PASS already (Task 5's implementation covers this) — this step is a verification checkpoint, not new production code.

- [ ] **Step 3: Checkpoint**

If either test fails, re-check Task 5's `update()` body against the code
above before proceeding — do not modify `update()` further here. Move to
Task 7.

---

### Task 7: `update_tyre()` / `get_tyre_age()`

**Files:**
- Modify: `core/rivals/tracker.py`
- Test: `tests/test_rivals.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_update_tyre_sets_age_for_known_rival():
    t = RivalTracker()
    t.update(_grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz")), player_vehicle_idx=0, now=1.0)
    t.update_tyre(1, 12)
    assert t.get_tyre_age(1) == 12


def test_update_tyre_noop_for_unknown_rival():
    t = RivalTracker()
    t.update_tyre(99, 5)          # no profile yet — must not raise
    assert t.get_tyre_age(99) is None


def test_get_tyre_age_returns_none_for_none_vehicle_idx():
    t = RivalTracker()
    assert t.get_tyre_age(None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_rivals.py::test_update_tyre_sets_age_for_known_rival -v`
Expected: FAIL with `AttributeError: 'RivalTracker' object has no attribute 'update_tyre'`

- [ ] **Step 3: Implement**

Add to `core/rivals/tracker.py`, after `get_style()`:

```python
    def update_tyre(self, vehicle_idx: int, age: int) -> None:
        """Возраст резины соперника — приходит с CarStatus-тиков, независимо от
        update() (другой тип UDP-пакета). Молча игнорирует машину, ещё не
        встреченную через update() (LapData) — профиль появится на следующем
        тике, ничего страшного."""
        profile = self._profiles.get(vehicle_idx)
        if profile:
            profile.tyre_age = age

    def get_tyre_age(self, vehicle_idx: int | None) -> int | None:
        if vehicle_idx is None:
            return None
        profile = self._profiles.get(vehicle_idx)
        return profile.tyre_age if profile else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_rivals.py -v`
Expected: all PASS

- [ ] **Step 5: Checkpoint**

Move to Task 8.

---

### Task 8: `update_damage()` / `get_recent_mistake()`

**Files:**
- Modify: `core/rivals/tracker.py`
- Test: `tests/test_rivals.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_update_damage_sets_mistake_on_threshold_cross():
    t = RivalTracker()
    t.update(_grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz")), player_vehicle_idx=0, now=1.0)
    t.update_damage(1, body_damage=45, threshold=20, now=5.0)
    assert t.get_recent_mistake(1, now=5.0) is True


def test_update_damage_no_mistake_below_threshold():
    t = RivalTracker()
    t.update(_grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz")), player_vehicle_idx=0, now=1.0)
    t.update_damage(1, body_damage=10, threshold=20, now=5.0)
    assert t.get_recent_mistake(1, now=5.0) is False


def test_update_damage_only_flags_on_threshold_cross_not_every_tick():
    t = RivalTracker()
    t.update(_grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz")), player_vehicle_idx=0, now=1.0)
    t.update_damage(1, body_damage=45, threshold=20, now=5.0)
    t.update_damage(1, body_damage=46, threshold=20, now=50.0)   # already above, no re-trigger
    assert t._profiles[1].mistake_at == 5.0


def test_update_damage_noop_for_unknown_rival():
    t = RivalTracker()
    t.update_damage(99, body_damage=90, threshold=20, now=1.0)   # must not raise
    assert t.get_recent_mistake(99, now=1.0) is False


def test_get_recent_mistake_expires_after_window():
    t = RivalTracker()
    t.update(_grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz")), player_vehicle_idx=0, now=1.0)
    t.update_damage(1, body_damage=45, threshold=20, now=5.0)
    assert t.get_recent_mistake(1, now=5.0 + 60.0) is True     # exactly at window edge
    assert t.get_recent_mistake(1, now=5.0 + 61.0) is False    # past the window


def test_get_recent_mistake_false_when_never_set():
    t = RivalTracker()
    t.update(_grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz")), player_vehicle_idx=0, now=1.0)
    assert t.get_recent_mistake(1, now=1.0) is False


def test_get_recent_mistake_false_for_none_vehicle_idx():
    t = RivalTracker()
    assert t.get_recent_mistake(None, now=1.0) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_rivals.py::test_update_damage_sets_mistake_on_threshold_cross -v`
Expected: FAIL with `AttributeError: 'RivalTracker' object has no attribute 'update_damage'`

- [ ] **Step 3: Implement**

Add to `core/rivals/tracker.py`, after `update_tyre`/`get_tyre_age`:

```python
    def update_damage(self, vehicle_idx: int, body_damage: float,
                       threshold: float, now: float) -> None:
        """body_damage — max(wing, floor, gearbox, engine) severity 0-100 для
        этой машины. threshold передаётся вызывающим кодом — переиспользует
        тот же порог заметности, что уже применяется к повреждениям игрока
        (core/engine.py::_DAMAGE_NOTICEABLE_THRESHOLD), не второй дубль
        магического числа в другом модуле."""
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_rivals.py -v`
Expected: all PASS

- [ ] **Step 5: Checkpoint**

Move to Task 9.

---

### Task 9: `get_state()` exposes `tyre_age` / `recent_mistake`

**Files:**
- Modify: `core/rivals/tracker.py:84-102` (`get_state`)
- Test: `tests/test_rivals.py`

- [ ] **Step 1: Write the failing test**

```python
def test_get_state_rival_entry_has_tyre_age_and_recent_mistake():
    t = RivalTracker()
    t.update(_grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz")), player_vehicle_idx=0, now=1.0)
    t.update_tyre(1, 8)
    t.update_damage(1, body_damage=50, threshold=20, now=1.0)
    rival = t.get_state(now=1.0)["rivals"][0]
    assert rival["tyre_age"] == 8
    assert rival["recent_mistake"] is True
```

Also update every OTHER call to `t.get_state()` in the file that comes after
a `mistake_at` could plausibly be set — none of the existing tests trigger a
mistake, so `get_state()` needs a `now` parameter with a safe default (Step 3
gives it `now: float = 0.0`), keeping every pre-existing `t.get_state()` call
(no `now` argument) unchanged and still passing.

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_rivals.py::test_get_state_rival_entry_has_tyre_age_and_recent_mistake -v`
Expected: FAIL with `TypeError: get_state() got an unexpected keyword argument 'now'`

- [ ] **Step 3: Implement**

Replace `get_state` in `core/rivals/tracker.py`:

```python
    def get_state(self, now: float = 0.0) -> dict:
        rivals = [
            {
                "driver": p.driver,
                "team": p.team,
                "position": p.current_position,
                "lap": p.lap_count,
                "pit_count": p.pit_count,
                "style": p.style,
                "nearby": p.nearby,
                "tyre_age": p.tyre_age,
                "recent_mistake": self.get_recent_mistake(p.vehicle_idx, now),
            }
            for p in sorted(self._profiles.values(), key=lambda x: x.current_position)
        ]
        nearby_count = sum(1 for r in rivals if r["nearby"])
        return {
            "rivals": rivals,
            "rival_count": len(rivals),
            "nearby_count": nearby_count,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_rivals.py -v`
Expected: all PASS

- [ ] **Step 5: Checkpoint**

Full file check: `py -3.12 -m pytest tests/test_rivals.py -v` — count passed
tests, confirm none skipped/failed. Move to Task 10.

---

### Task 10: `core/engine.py` — thread `pit_status` into `RivalTracker.update()`

**Files:**
- Modify: `core/engine.py:787-818` (`PACKET_LAP_DATA` branch)
- Test: `tests/test_engine_rivals.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/test_engine_rivals.py`:

```python
"""tests/test_engine_rivals.py — engine wiring for opponent tyre-age/mistake
detection (design spec 2026-07-07-rival-mistake-tyre-freshness)."""
import struct
import time

import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.packets import (
    HEADER_SIZE, LAP_DATA_SIZE, CAR_STATUS_SIZE,
    PACKET_LAP_DATA, PACKET_CAR_STATUS, PACKET_CAR_DAMAGE,
)
from core.rivals.tracker import RivalTracker


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _lap_buf_multi(cars: dict[int, dict]) -> bytes:
    buf = bytearray(HEADER_SIZE + 22 * LAP_DATA_SIZE)
    for idx, c in cars.items():
        base = HEADER_SIZE + idx * LAP_DATA_SIZE
        buf[base + 32] = c.get("position", 0)
        buf[base + 33] = c.get("lap", 0)
        buf[base + 34] = c.get("pit_status", 0)
    return bytes(buf)


def test_lap_data_threads_pit_status_into_rival_tracker(engine):
    engine._player_car_index = 0
    engine.rival_tracker = RivalTracker()
    engine._update_telemetry(
        {"player_car_index": 0}, PACKET_LAP_DATA,
        _lap_buf_multi({0: {"position": 1, "lap": 5}, 1: {"position": 3, "lap": 5}}))
    engine._update_telemetry(
        {"player_car_index": 0}, PACKET_LAP_DATA,
        _lap_buf_multi({0: {"position": 1, "lap": 6},
                        1: {"position": 18, "lap": 6, "pit_status": 1}}))
    rivals = engine.rival_tracker.get_state()["rivals"]
    sainz = next(r for r in rivals if r["position"] == 18)
    assert sainz["pit_count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_engine_rivals.py::test_lap_data_threads_pit_status_into_rival_tracker -v`
Expected: FAIL — `pit_count == 0` (grid entries don't carry `pit_status` yet, so
`RivalTracker` always sees `pit_status=0` via its own `.get(..., 0)` default)

- [ ] **Step 3: Implement**

In `core/engine.py`, in the `PACKET_LAP_DATA` branch, change the `grid.append`
call and the `rival_tracker.update` call (lines 796-818):

```python
                grid = []
                for vehicle_idx, position in sorted(positions.items(), key=lambda item: item[1] or 999):
                    driver_info = self.race_state.driver(vehicle_idx)
                    grid.append({
                        "vehicle_idx": vehicle_idx,
                        "position": position,
                        "driver": driver_info["name"],
                        "team": driver_info["team"],
                        "color": driver_info["color"],
                        "lap": lap_info.get("laps", {}).get(vehicle_idx, 0),
                        "pit_status": lap_info.get("pit_status", {}).get(vehicle_idx, 0),
                    })
                leader_name = self.race_state.driver(self._leader_idx)["name"] if self._leader_idx is not None else "—"
                self._leader_name = leader_name
                race_data = {
                    "leader": leader_name,
                    "leader_idx": self._leader_idx,
                    "grid": grid,
                    "last_update": datetime.now().strftime("%H:%M:%S"),
                }
                with self.state_lock:
                    self.state["race"] = race_data
                self._save_race_cache(race_data)
                self.rival_tracker.update(
                    grid,
                    player_vehicle_idx=self._player_car_index,
                    now=time.time(),
                )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_engine_rivals.py -v`
Expected: PASS

- [ ] **Step 5: Checkpoint**

Run the full pit-tracking regression: `py -3.12 -m pytest tests/test_engine_pit_tracking.py -v`
Expected: all PASS unchanged (that file drives `PACKET_LAP_DATA` with
`position=0` on purpose, so the new `grid`/`rival_tracker` code path is never
exercised there — confirms this change doesn't disturb the player-side pit
logic). Move to Task 11.

---

### Task 11: `core/engine.py` — thread rival tyre age from `CarStatus`

**Files:**
- Modify: `core/engine.py:889-890` (`PACKET_CAR_STATUS` branch)
- Modify: `core/engine.py:26-33` (imports)
- Test: `tests/test_engine_rivals.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_engine_rivals.py`:

```python
def _status_buf_multi(cars: dict[int, dict]) -> bytes:
    buf = bytearray(HEADER_SIZE + 22 * CAR_STATUS_SIZE)
    for idx, c in cars.items():
        base = HEADER_SIZE + idx * CAR_STATUS_SIZE
        struct.pack_into("<f", buf, base + 5, c.get("fuel", 50.0))
        buf[base + 26] = c.get("tyre_visual", 16)
        buf[base + 27] = c.get("tyre_age", 0)
    return bytes(buf)


def test_car_status_threads_tyre_age_into_rival_tracker(engine):
    engine._player_car_index = 0
    engine.rival_tracker = RivalTracker()
    engine.rival_tracker.update(
        [{"vehicle_idx": 0, "position": 1, "lap": 5, "driver": "Player", "team": "T", "color": "#fff"},
         {"vehicle_idx": 1, "position": 2, "lap": 5, "driver": "Sainz", "team": "Ferrari", "color": "#fff"}],
        player_vehicle_idx=0, now=1.0)

    engine._update_telemetry(
        {"player_car_index": 0}, PACKET_CAR_STATUS,
        _status_buf_multi({0: {"tyre_age": 3}, 1: {"tyre_age": 12}}))

    assert engine.rival_tracker.get_tyre_age(1) == 12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_engine_rivals.py::test_car_status_threads_tyre_age_into_rival_tracker -v`
Expected: FAIL — `get_tyre_age(1) is None` (engine doesn't call `update_tyre` yet)

- [ ] **Step 3: Implement**

In `core/engine.py`, add `parse_car_status_all` to the import block (line 29):

```python
from core.packets import (
    parse_header, parse_participants, parse_event,
    parse_session, parse_lap_data, parse_player_lap,
    parse_player_telemetry, parse_player_status, parse_player_damage,
    parse_car_status_all, parse_car_damage_all,
    PACKET_PARTICIPANTS, PACKET_EVENT, PACKET_SESSION,
    PACKET_LAP_DATA, PACKET_CAR_TELEMETRY, PACKET_CAR_STATUS, PACKET_CAR_DAMAGE,
    HEADER_SIZE,
)
```

Then change the `PACKET_CAR_STATUS` branch (line 889-890):

```python
        elif packet_id == PACKET_CAR_STATUS and self._player_car_index < 22:
            telem.update(parse_player_status(data, self._player_car_index))
            for idx, st in parse_car_status_all(data).items():
                if idx != self._player_car_index and st.get("tyre_age") is not None:
                    self.rival_tracker.update_tyre(idx, st["tyre_age"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_engine_rivals.py -v`
Expected: PASS

- [ ] **Step 5: Checkpoint**

Move to Task 12.

---

### Task 12: `core/engine.py` — thread rival damage-as-mistake from `CarDamage`

**Files:**
- Modify: `core/engine.py:892-898` (`PACKET_CAR_DAMAGE` branch)
- Test: `tests/test_engine_rivals.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_engine_rivals.py`:

```python
def _damage_buf_multi(cars: dict[int, dict], stride: int = 42) -> bytes:
    buf = bytearray(HEADER_SIZE + 22 * stride)
    for idx, c in cars.items():
        base = HEADER_SIZE + idx * stride
        buf[base + 24] = c.get("wing", 0)
        buf[base + 27] = c.get("floor", 0)
        buf[base + 32] = c.get("gearbox", 0)
        buf[base + 33] = c.get("engine", 0)
    return bytes(buf)


def test_car_damage_threads_body_damage_as_mistake_for_rivals(engine):
    engine._player_car_index = 0
    engine.rival_tracker = RivalTracker()
    engine.rival_tracker.update(
        [{"vehicle_idx": 0, "position": 1, "lap": 5, "driver": "Player", "team": "T", "color": "#fff"},
         {"vehicle_idx": 1, "position": 2, "lap": 5, "driver": "Sainz", "team": "Ferrari", "color": "#fff"}],
        player_vehicle_idx=0, now=1.0)

    engine._update_telemetry(
        {"player_car_index": 0}, PACKET_CAR_DAMAGE,
        _damage_buf_multi({0: {}, 1: {"wing": 45}}))

    assert engine.rival_tracker.get_recent_mistake(1, now=time.time()) is True


def test_car_damage_below_threshold_is_not_a_mistake_for_rivals(engine):
    engine._player_car_index = 0
    engine.rival_tracker = RivalTracker()
    engine.rival_tracker.update(
        [{"vehicle_idx": 0, "position": 1, "lap": 5, "driver": "Player", "team": "T", "color": "#fff"},
         {"vehicle_idx": 1, "position": 2, "lap": 5, "driver": "Sainz", "team": "Ferrari", "color": "#fff"}],
        player_vehicle_idx=0, now=1.0)

    engine._update_telemetry(
        {"player_car_index": 0}, PACKET_CAR_DAMAGE,
        _damage_buf_multi({0: {}, 1: {"wing": 5}}))

    assert engine.rival_tracker.get_recent_mistake(1, now=time.time()) is False
```

- [ ] **Step 2: Run tests to verify the first one fails**

Run: `py -3.12 -m pytest tests/test_engine_rivals.py::test_car_damage_threads_body_damage_as_mistake_for_rivals -v`
Expected: FAIL — `get_recent_mistake(1, ...) is False` (engine doesn't call `update_damage` for rivals yet)

- [ ] **Step 3: Implement**

In `core/engine.py`, change the `PACKET_CAR_DAMAGE` branch (lines 892-898):

```python
        elif packet_id == PACKET_CAR_DAMAGE and self._player_car_index < 22:
            dmg = parse_player_damage(data, self._player_car_index)
            if dmg.get("tyre_wear") is not None:
                self._player_tyre_wear = dmg["tyre_wear"]
            # нет полей для state.telemetry — снимок подтянет износ на следующем LAP_DATA
            if dmg:
                self._update_damage(dmg)
            now = time.time()
            for idx, d in parse_car_damage_all(data).items():
                if idx == self._player_car_index:
                    continue
                body = max(d.get("wing_damage", 0), d.get("floor_damage", 0),
                           d.get("gearbox_damage", 0), d.get("engine_damage", 0))
                self.rival_tracker.update_damage(
                    idx, body, threshold=_DAMAGE_NOTICEABLE_THRESHOLD, now=now)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_engine_rivals.py -v`
Expected: all PASS

- [ ] **Step 5: Checkpoint**

Run: `py -3.12 -m pytest tests/test_engine_damage.py -v`
Expected: all PASS unchanged (player damage path untouched — new code is a
separate loop after the existing `_update_damage(dmg)` call). Move to Task 13.

---

### Task 13: `core/engine.py` — `OVTK` enrichment gets the 4 new fields

**Files:**
- Modify: `core/engine.py:1427-1436`
- Test: no dedicated engine-level test (see note)

Following the exact precedent set by `driver_style`/`target_style` in Race
Memory v1 (same enrichment block, no dedicated engine-level test — the
underlying accessors are already fully unit-tested in `test_rivals.py`, and
the consumption of these fields is fully unit-tested in `test_planner.py`,
Task 14). This is plain glue code, no more complex than the existing
neighboring lines.

- [ ] **Step 1: Implement**

Replace the enrichment block in `core/engine.py`:

```python
            enriched = self.race_state.enrich(event)
            # COLL тоже двухмашинное событие (vehicle1_idx/vehicle2_idx), но стиль
            # соперника сознательно ограничен OVTK (design spec 2026-07-05-race-memory)
            # — не забыто, не техническое ограничение get_style().
            if enriched.get("event_code") == "OVTK":
                overtaking_idx = enriched.get("overtaking_idx")
                being_overtaken_idx = enriched.get("being_overtaken_idx")
                now = time.time()
                enriched["driver_style"] = self.rival_tracker.get_style(overtaking_idx)
                enriched["target_style"] = self.rival_tracker.get_style(being_overtaken_idx)
                enriched["driver_recent_mistake"] = self.rival_tracker.get_recent_mistake(overtaking_idx, now)
                enriched["target_recent_mistake"] = self.rival_tracker.get_recent_mistake(being_overtaken_idx, now)
                enriched["driver_tyre_age"] = self.rival_tracker.get_tyre_age(overtaking_idx)
                enriched["target_tyre_age"] = self.rival_tracker.get_tyre_age(being_overtaken_idx)
            self.race_state.record_event(event)
```

- [ ] **Step 2: Run the existing planner-wiring regression**

Run: `py -3.12 -m pytest tests/test_engine_planner.py -v`
Expected: all PASS unchanged (this block isn't exercised by these tests, they
call `_plan_context`/`_enqueue_event` directly — confirms no accidental
breakage of the surrounding code)

- [ ] **Step 3: Checkpoint**

Move to Task 14.

---

### Task 14: `commentator/planner.py` — mistake + tyre-freshness markers

**Files:**
- Modify: `commentator/planner.py:120-190`
- Test: `tests/test_planner.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_planner.py`, after `test_build_plan_battle_count_marker_and_style_suffix_combine`:

```python
# --------------------------------------------------------------------------- #
# build_plan: недавняя ошибка соперника + свежесть резины (2026-07-07)
# --------------------------------------------------------------------------- #

def test_build_plan_driver_recent_mistake_marker():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "driver_recent_mistake": True}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака (Норрис только что ошибся): Норрис и Пиастри"


def test_build_plan_target_recent_mistake_marker():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "target_recent_mistake": True}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака (Пиастри только что ошибся): Норрис и Пиастри"


def test_build_plan_no_mistake_marker_when_false():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "driver_recent_mistake": False, "target_recent_mistake": False}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака: Норрис и Пиастри"


def test_build_plan_tyre_age_gap_marker_driver_fresher():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "driver_tyre_age": 2, "target_tyre_age": 10}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака (Норрис на более свежей резине): Норрис и Пиастри"


def test_build_plan_tyre_age_gap_marker_target_fresher():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "driver_tyre_age": 15, "target_tyre_age": 3}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака (Пиастри на более свежей резине): Норрис и Пиастри"


def test_build_plan_no_tyre_age_marker_below_threshold():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "driver_tyre_age": 5, "target_tyre_age": 7}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака: Норрис и Пиастри"


def test_build_plan_no_tyre_age_marker_when_one_side_missing():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "driver_tyre_age": 2, "target_tyre_age": None}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == "атака: Норрис и Пиастри"


def test_build_plan_missing_mistake_and_tyre_fields_unaffected():
    """Событие без driver_recent_mistake/target_recent_mistake/*_tyre_age
    (сегодняшний путь) ведёт себя как раньше."""
    event = {"event_code": "PIT_EXIT", "tyre_compound": "M"}
    plan = build_plan(event, importance=60, persona="tv")
    assert plan.focus == "выезд из боксов: свежий комплект M"


def test_build_plan_mistake_and_tyre_and_battle_markers_combine():
    event = {"event_code": "OVTK", "driver": "Норрис", "target": "Пиастри",
             "battle": True, "battle_count": 3, "laps_remaining": 2,
             "target_recent_mistake": True,
             "driver_tyre_age": 2, "target_tyre_age": 10}
    plan = build_plan(event, importance=50, persona="tv")
    assert plan.focus == (
        "атака (последние 2 круга гонки, 3-я попытка обгона, "
        "Пиастри только что ошибся, Норрис на более свежей резине): "
        "Норрис и Пиастри")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_planner.py::test_build_plan_driver_recent_mistake_marker -v`
Expected: FAIL — `plan.focus == "атака: Норрис и Пиастри"` (marker not added yet)

- [ ] **Step 3: Implement**

In `commentator/planner.py`, add the threshold constant near `_STYLE_PHRASES` (after line 124):

```python
_TYRE_AGE_GAP_THRESHOLD = 5   # круга разницы, чтобы факт был достоин упоминания
```

Then, inside `build_plan()`, extend the `markers` block (replace lines 184-190):

```python
    markers: list[str] = []
    if final_laps:
        markers.append(f"последние {laps_remaining} круга гонки")
    battle_count = event.get("battle_count", 0)
    if battle and battle_count:   # battle УЖЕ порогует по BATTLE_THRESHOLD — не дублируем здесь
        markers.append(f"{battle_count}-я попытка обгона")
    if event.get("driver_recent_mistake"):
        markers.append(f"{driver} только что ошибся")
    if event.get("target_recent_mistake"):
        markers.append(f"{target} только что ошибся")
    driver_tyre_age = event.get("driver_tyre_age")
    target_tyre_age = event.get("target_tyre_age")
    if (driver_tyre_age is not None and target_tyre_age is not None
            and abs(driver_tyre_age - target_tyre_age) >= _TYRE_AGE_GAP_THRESHOLD):
        fresher = driver if driver_tyre_age < target_tyre_age else target
        markers.append(f"{fresher} на более свежей резине")
    focus_reaction = f"{reaction} ({', '.join(markers)})" if markers else reaction
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_planner.py -v`
Expected: all PASS

- [ ] **Step 5: Checkpoint**

Move to Task 15.

---

### Task 15: Full regression + `CONTEXT.md` session note

**Files:**
- Modify: `CONTEXT.md`
- No code changes

- [ ] **Step 1: Run the full test suite**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: 0 failed. Note the exact "N passed, M skipped" line (baseline before
this feature was 945 passed, 1 skipped) — call this count `<TOTAL>` below.

- [ ] **Step 2: Import smoke test**

Run: `py -3.12 -c "import core.packets, core.rivals.tracker, core.engine, commentator.planner"`
Expected: no output, exit code 0

- [ ] **Step 3: Add a new session section to `CONTEXT.md`**

Insert a new section directly above the line
`## Сессия 2026-07-05 (продолжение) — Phrase Bank Expansion...` (i.e. as the
newest entry, following this file's existing convention of newest-session-on-top
under "На чём остановились"):

```markdown
## Сессия 2026-07-07 — Соперники: недавняя ошибка + свежесть резины, 5/5 ✅

Закрывает оба пункта, отложенных design-спекой Race Memory v1 (`docs/superpowers/
specs/2026-07-05-race-memory-design.md`) из-за отсутствия чужой телеметрии —
«кто недавно ошибся» и «свежая резина соперника». Расследование показало: это
было решение объёма, не техническое ограничение — `LapData`/`CarStatus`/
`CarDamage` уже несут данные всех 22 машин, `core/packets.py` просто читал
только срез игрока. План: `docs/superpowers/plans/2026-07-07-rival-mistake-
tyre-freshness.md`, спека: `docs/superpowers/specs/2026-07-07-rival-mistake-
tyre-freshness-design.md`.

- **`core/packets.py`** — `parse_lap_data()` дополнен реальным `pit_status` по
  всем машинам; новые `parse_car_status_all()`/`parse_car_damage_all()`
  переиспользуют общие хелперы `_car_status_fields`/`_car_damage_fields` с
  существующими `parse_player_status`/`parse_player_damage` — офсеты не
  задублированы.
- **`core/rivals/tracker.py`** — `pit_count` переключён с эвристики
  (скачок позиции ≥8 = предполагаем пит) на реальный `pit_status`; резкая
  потеря позиции БЕЗ реального пита теперь пишет `mistake_at`, как и резкий
  скачок повреждений кузова (`update_damage`, порог заметности 20% —
  переиспользован из `core/engine.py::_DAMAGE_NOTICEABLE_THRESHOLD`, не
  задублирован). Новые аксессоры `get_recent_mistake()`/`get_tyre_age()`,
  окно давности ошибки 60с.
- **`core/engine.py`** — `grid` для `RivalTracker.update()` несёт реальный
  `pit_status`; `PACKET_CAR_STATUS`/`PACKET_CAR_DAMAGE` прокидывают данные
  соперников в `update_tyre`/`update_damage`; `OVTK`-enrichment получил 4
  новых поля (`driver_recent_mistake`, `target_recent_mistake`,
  `driver_tyre_age`, `target_tyre_age`) — тем же путём, что уже используется
  для `driver_style`/`target_style`.
- **`commentator/planner.py`** — оба факта попадают в `focus` ТОЛЬКО как
  описательные маркеры для `OVTK` (как `battle_count`/`style` в Race Memory
  v1) — никакого отдельного объявления по факту чужой ошибки/резины.
  `_TYRE_AGE_GAP_THRESHOLD=5` кругов.

**Побочный эффект, о котором стоит знать:** `pit_count` в Rivals-панели UI
теперь считается точнее (по реальному телеметрийному биту, не по размеру
скачка позиции) — численные значения могут отличаться от того, что было
раньше на той же гонке.

**Верификация:** полный прогон `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
— **<TOTAL>** (было 945 passed, 1 skipped, сессия Phrase Bank Expansion,
2026-07-05). Импорт-смоук (`core.packets, core.rivals.tracker, core.engine,
commentator.planner`) — без ошибок.
```

Replace `<TOTAL>` with the actual line from Step 1.

- [ ] **Step 4: Update the "На чём остановились" counter**

In the "На чём остановились" section (near the top of `CONTEXT.md`), replace
its content to reflect this session is closed and reset the task counter to
`0 / 0`, following the same style as the previous reset after Phrase Bank
Expansion (mention what was closed: both Race Memory v1 backlog items).

- [ ] **Step 5: Checkpoint (final)**

Confirm `CONTEXT.md` renders correctly (no broken markdown tables), full
suite green, import smoke clean. Feature complete.

---

## Plan Self-Review Notes

- **Spec coverage:** all 5 design sections (packets parsing, `RivalProfile`,
  `RivalTracker`, `engine.py` wiring, `planner.py` markers) map 1:1 to Tasks
  1-3, 4, 5-9, 10-13, 14. The `get_state()` UI-visibility addition from the
  spec is Task 9. The `pit_count` behavior-change caveat from the spec is
  called out explicitly in Task 5 and in the Task 15 CONTEXT.md note.
- **No dedicated engine-level test for the `OVTK` enrichment glue (Task 13):**
  intentional, matches the existing precedent for `driver_style`/`target_style`
  (no engine-level test exists for those either — grep confirms). The
  accessors it calls are fully covered in Task 5-9, and its consumers are
  fully covered in Task 14.
- **Type/signature consistency check:** `RivalTracker.update(grid,
  player_vehicle_idx, now=0.0)`, `update_tyre(vehicle_idx, age)`,
  `update_damage(vehicle_idx, body_damage, threshold, now)`,
  `get_recent_mistake(vehicle_idx, now, window=60.0)`,
  `get_tyre_age(vehicle_idx)`, `get_state(now=0.0)` — same names/parameter
  order used consistently across Tasks 5-13 and in `tests/test_engine_rivals.py`.
