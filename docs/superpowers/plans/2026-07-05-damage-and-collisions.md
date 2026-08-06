# Damage Tracking & Collision Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse the player's car-damage telemetry (currently only tyre wear is read) into 4 simple HUD categories, and register F1 25's `COLL` (collision) event so the commentator reacts to crashes the player is involved in.

**Architecture:** Extend `core/packets.py` to read 8 additional damage bytes (grouped into 4 categories: wings, floor/aero, gearbox, engine) and parse the previously-unregistered `COLL` event. `core/race_state.py::enrich()` gains a branch to resolve `COLL`'s two vehicle indices into driver names (mirroring the existing `OVTK` branch), after which the collision flows through the app's existing generic event→commentary pipeline with zero new plumbing (same mechanism already used for overtakes, penalties, retirements). Damage severity is a *derived* condition (not a raw game event), so it follows the `F1_BENCH`/`CAREER_PB` pattern instead: a per-category anti-spam flag in `core/engine.py`, firing an explicit, hand-written voice line once per race when a category first crosses a "noticeable" threshold.

**Tech Stack:** Python 3.12, standard library, pytest; frontend — Next/React (`NewSpotterUI`).

> ⚠️ **Репозиторий НЕ под git** (`Is a git repository: false`). Шаги «Commit» заменены на **Checkpoint** — прогон тестов задачи. Команды тестов: `py -3.12 -m pytest ... -q`.

**Спека:** [`docs/superpowers/specs/2026-07-05-damage-and-collisions-design.md`](../specs/2026-07-05-damage-and-collisions-design.md).

---

## Файловая структура

| Файл | Действие | Ответственность |
|------|----------|-----------------|
| `core/packets.py` | изменить | `parse_player_damage()` — 4 категории; `EVENT_DESCRIPTIONS`/`CRITICAL_EVENTS`/`parse_event()` — `COLL` |
| `core/race_state.py` | изменить | `enrich()` — резолвит имена для `COLL` |
| `core/engine.py` | изменить | `_event_involves()` — `COLL`; трекинг повреждений + анти-спам + `state["damage"]` |
| `NewSpotterUI/lib/api.ts` | изменить | `DamageState` |
| `NewSpotterUI/components/spotter/views/race.tsx` | изменить | панель «Повреждения» |
| `tests/test_packets_gaps_tyre.py` | изменить | +тесты категорий повреждений и `COLL` |
| `tests/test_race_state.py` | создать | |
| `tests/test_engine_damage.py` | создать | |

---

## Task 1: `core/packets.py` — категории повреждений + событие `COLL`

**Files:**
- Modify: `core/packets.py`
- Modify: `tests/test_packets_gaps_tyre.py`

- [ ] **Step 1: Write the failing tests**

Добавить в конец `tests/test_packets_gaps_tyre.py`:

```python
def test_parse_player_damage_categories():
    stride = 42
    buf = _buf(HEADER_SIZE + 22 * stride)
    base = HEADER_SIZE  # player_idx=0

    struct.pack_into("<ffff", buf, base + 0, 20.0, 24.0, 28.0, 32.0)  # tyre_wear (уже покрыт)
    buf[base + 24] = 15   # front-left wing
    buf[base + 25] = 40   # front-right wing — максимум группы "крылья"
    buf[base + 26] = 10   # rear wing
    buf[base + 27] = 5    # floor
    buf[base + 28] = 60   # diffuser — максимум группы "аэро/пол"
    buf[base + 29] = 30   # sidepod
    buf[base + 32] = 22   # gearbox
    buf[base + 33] = 77   # engine

    out = packets.parse_player_damage(buf, 0)
    assert out["tyre_wear"] == 26.0        # среднее, поведение не изменилось
    assert out["wing_damage"] == 40
    assert out["floor_damage"] == 60
    assert out["gearbox_damage"] == 22
    assert out["engine_damage"] == 77


def test_parse_player_damage_categories_second_car():
    """Второй по счёту автомобиль (player_idx=1) — офсет-логика (stride) не ломается
    при переходе за одну машину."""
    stride = 42
    buf = _buf(HEADER_SIZE + 22 * stride)
    base = HEADER_SIZE + 1 * stride
    buf[base + 24] = 5
    buf[base + 25] = 5
    buf[base + 26] = 90   # rear wing — максимум
    buf[base + 32] = 12
    buf[base + 33] = 3

    out = packets.parse_player_damage(buf, 1)
    assert out["wing_damage"] == 90
    assert out["gearbox_damage"] == 12
    assert out["engine_damage"] == 3


def test_parse_event_collision():
    buf = _buf(HEADER_SIZE + 4 + 2)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"COLL"
    buf[HEADER_SIZE + 4] = 3       # vehicle1_idx
    buf[HEADER_SIZE + 5] = 7       # vehicle2_idx
    out = packets.parse_event(bytes(buf))
    assert out["event_code"] == "COLL"
    assert out["vehicle1_idx"] == 3
    assert out["vehicle2_idx"] == 7
    assert out["priority"] == "critical"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_packets_gaps_tyre.py -q`
Expected: FAIL — `KeyError: 'wing_damage'` (и `AttributeError`/`assert None ==` для `COLL`,
т.к. `parse_event()` вернёт `None` — код нерелевантен без `EVENT_DESCRIPTIONS["COLL"]`)

- [ ] **Step 3: Implement `parse_player_damage()`**

Найти:

```python
def parse_player_damage(data: bytes, player_idx: int) -> dict:
    """Износ шин из Car Damage (packet 10). m_tyresWear[4] (float %) — ПЕРВОЕ поле
    структуры (@0), поэтому устойчиво к точному размеру struct. Шаг машины выводим
    из длины пакета (numCars нет, как и в LapData) — без хардкода размера."""
    body = len(data) - HEADER_SIZE
    if body <= 0:
        return {}
    stride = body // 22
    if not (24 <= stride <= 80):          # sanity: правдоподобный размер CarDamageData
        return {}
    base = HEADER_SIZE + player_idx * stride
    if base + 16 > len(data):
        return {}
    wear = struct.unpack_from("<ffff", data, base + 0)   # RL, RR, FL, FR
    avg = sum(wear) / 4.0
    return {"tyre_wear": round(avg, 1)}
```

Заменить на:

```python
def parse_player_damage(data: bytes, player_idx: int) -> dict:
    """Износ шин + категории повреждений кузова из Car Damage (packet 10).
    m_tyresWear[4] (float %) — ПЕРВОЕ поле структуры (@0). Категории повреждений —
    сгруппированный максимум среди своих полей (одно сильно повреждённое крыло важнее
    среднего трёх). Офсеты 24-33 подтверждены косвенно: уже существующий тест этого
    файла использует stride=42 как "правдоподобный размер структуры", что совпадает
    с полной раскладкой полей F1 25 CarDamageData (42 байта на машину) — тем не менее
    сверить с реальной телеметрией через diag_lap_offsets.py перед тем, как полностью
    полагаться (см. design spec docs/superpowers/specs/2026-07-05-damage-and-collisions-design.md §2).
    Шаг машины выводим из длины пакета (numCars нет, как и в LapData) — без хардкода размера."""
    body = len(data) - HEADER_SIZE
    if body <= 0:
        return {}
    stride = body // 22
    if not (24 <= stride <= 80):          # sanity: правдоподобный размер CarDamageData
        return {}
    base = HEADER_SIZE + player_idx * stride
    if base + 34 > len(data):             # расширено с +16: нужны байты до engine@33 включительно
        return {}
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
```

**Важно:** граница проверки расширена с `base + 16` до `base + 34` — байты 24-33 теперь
обязательны для непустого результата. Для реальных 22-машинных пакетов (`stride`
всегда получается 42 при штатном размере) это никогда не отбрасывает валидные данные
(`base + stride <= len(data)` по построению `stride = body // 22`, а `stride=42 > 34`).
Отбрасывает только гипотетические пакеты с `24 <= stride < 34` — синтетический
краевой случай вне реальной телеметрии; возврат `{}` (без данных вообще, включая
`tyre_wear`) в этом случае — осознанный консервативный выбор, а не регресс.

- [ ] **Step 4: Implement event registration for `COLL`**

Найти:

```python
    "FLBK": "Flashback",
    "OVTK": "Обгон",
}
```

Заменить на:

```python
    "FLBK": "Flashback",
    "OVTK": "Обгон",
    "COLL": "Столкновение",
}
```

Найти:

```python
CRITICAL_EVENTS = {"PENA", "RTMT", "CHQF", "RCWN"}
```

Заменить на:

```python
CRITICAL_EVENTS = {"PENA", "RTMT", "CHQF", "RCWN", "COLL"}
```

Найти:

```python
    elif code == "OVTK" and len(payload) >= 2:
        overtaking, overtaken = struct.unpack_from("<BB", payload, 0)
        details = {"overtaking_idx": overtaking, "being_overtaken_idx": overtaken}

    return {
```

Заменить на:

```python
    elif code == "OVTK" and len(payload) >= 2:
        overtaking, overtaken = struct.unpack_from("<BB", payload, 0)
        details = {"overtaking_idx": overtaking, "being_overtaken_idx": overtaken}

    elif code == "COLL" and len(payload) >= 2:
        v1, v2 = struct.unpack_from("<BB", payload, 0)
        details = {"vehicle1_idx": v1, "vehicle2_idx": v2}

    return {
```

- [ ] **Step 5: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_packets_gaps_tyre.py -q`
Expected: PASS (все тесты файла, включая новые)

- [ ] **Step 6: Верификация живьём (диагностика оффсетов повреждений)**

В `diag_lap_offsets.py`, найти:

```python
    print(f"\nlast_lap_ms={last_ms} ({last_ms/1000:.3f}s)  lap={data[base+33]}"
         f"  pit_status={data[base+34]}")
```

Заменить на:

```python
    print(f"\nlast_lap_ms={last_ms} ({last_ms/1000:.3f}s)  lap={data[base+33]}"
         f"  pit_status={data[base+34]}")
    # CarDamageData — другой пакет (packet 10), другой base/stride; не печатается
    # здесь автоматически. Для сверки байтов 24/25/26 (крылья), 27/28/29 (аэро/пол),
    # 32 (коробка), 33 (двигатель) — временно взять реальное повреждение в игре и
    # вручную сравнить со значением из parse_player_damage()'s "wing_damage" и т.п.
    # (эти байты — из ДРУГОГО типа пакета, не LapData, где выведен этот print).
```

**Важно:** этот файл диагностирует ТОЛЬКО LapData (packet 2), а поля повреждений
живут в CarDamageData (packet 10) — другой тип пакета с другим `base`/`stride`.
Если точный "Найти" текст выше не совпадает (например, если этот файл менялся
после того, как писался этот план), найди любую строку внутри `if hdr[5] != 2:
continue` (эта проверка отбирает только LapData) — комментарий-заметка о
CarDamageData просто документирует ограничение, реального парсинга не требует.

- [ ] **Step 7: Checkpoint** — тесты задачи зелёные.

---

## Task 2: `core/race_state.py` — `enrich()` резолвит имена для `COLL`

**Files:**
- Modify: `core/race_state.py`
- Test: `tests/test_race_state.py` (новый)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_race_state.py
from core.race_state import RaceState


def _make_state():
    s = RaceState()
    s.update_drivers({
        3: {"name": "Ферстаппен", "team": "Red Bull", "color": "#3671C6"},
        7: {"name": "Хэмилтон", "team": "Ferrari", "color": "#E80020"},
    })
    return s


def test_enrich_vehicle_idx_event():
    s = _make_state()
    out = s.enrich({"event_code": "RTMT", "vehicle_idx": 3})
    assert out["driver"] == "Ферстаппен"
    assert out["team"] == "Red Bull"
    assert out["color"] == "#3671C6"


def test_enrich_overtake_event():
    s = _make_state()
    out = s.enrich({"event_code": "OVTK", "overtaking_idx": 3, "being_overtaken_idx": 7})
    assert out["driver"] == "Ферстаппен"
    assert out["target"] == "Хэмилтон"


def test_enrich_collision_event_resolves_both_names():
    s = _make_state()
    out = s.enrich({"event_code": "COLL", "vehicle1_idx": 3, "vehicle2_idx": 7})
    assert out["driver"] == "Ферстаппен"
    assert out["team"] == "Red Bull"
    assert out["color"] == "#3671C6"
    assert out["target"] == "Хэмилтон"
    assert out["target_team"] == "Ferrari"


def test_enrich_collision_unknown_vehicle_falls_back_gracefully():
    s = _make_state()
    out = s.enrich({"event_code": "COLL", "vehicle1_idx": 3, "vehicle2_idx": 99})
    assert out["driver"] == "Ферстаппен"
    assert out["target"] == "гонщик"    # неизвестный vehicle_idx -> дефолт RaceState.driver()


def test_enrich_collision_does_not_set_battle_flag():
    """battle — понятие только для повторяющихся обгонов (OVTK), не для аварий."""
    s = _make_state()
    out = s.enrich({"event_code": "COLL", "vehicle1_idx": 3, "vehicle2_idx": 7})
    assert out["battle"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_race_state.py -q`
Expected: FAIL — `test_enrich_collision_*` fail: `KeyError: 'driver'` (или `'target'`) —
ветка для `vehicle1_idx` ещё не существует, `enrich()` возвращает событие как есть.
(`test_enrich_vehicle_idx_event`/`test_enrich_overtake_event` уже проходят — это
существующее поведение, не новое, но их стоит прогнать вместе для контекста.)

- [ ] **Step 3: Implement**

Найти:

```python
        if "overtaking_idx" in event:
            a = self.driver(event["overtaking_idx"])
            b = self.driver(event["being_overtaken_idx"])
            enriched["driver"] = a["name"]
            enriched["team"] = a["team"]
            enriched["color"] = a["color"]
            enriched["target"] = b["name"]
            enriched["target_team"] = b["team"]
            enriched["battle"] = self.is_battle(
                event["overtaking_idx"], event["being_overtaken_idx"]
            )

        enriched.setdefault("color", "#9CA3AF")
        enriched.setdefault("battle", False)
        return enriched
```

Заменить на:

```python
        if "overtaking_idx" in event:
            a = self.driver(event["overtaking_idx"])
            b = self.driver(event["being_overtaken_idx"])
            enriched["driver"] = a["name"]
            enriched["team"] = a["team"]
            enriched["color"] = a["color"]
            enriched["target"] = b["name"]
            enriched["target_team"] = b["team"]
            enriched["battle"] = self.is_battle(
                event["overtaking_idx"], event["being_overtaken_idx"]
            )

        if "vehicle1_idx" in event:
            a = self.driver(event["vehicle1_idx"])
            b = self.driver(event["vehicle2_idx"])
            enriched["driver"] = a["name"]
            enriched["team"] = a["team"]
            enriched["color"] = a["color"]
            enriched["target"] = b["name"]
            enriched["target_team"] = b["team"]
            # battle — только для повторяющихся обгонов (is_battle читает историю
            # OVTK-событий); для аварии это понятие не определено, оставляем дефолт.

        enriched.setdefault("color", "#9CA3AF")
        enriched.setdefault("battle", False)
        return enriched
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_race_state.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Checkpoint** — тесты задачи зелёные.

---

## Task 3: `core/engine.py` — `_event_involves()` распознаёт `COLL`

**Files:**
- Modify: `core/engine.py`
- Test: `tests/test_engine_damage.py` (новый — этот файл дополняется в Task 4, здесь только первый тест)

- [ ] **Step 1: Write the failing test**

Создать `tests/test_engine_damage.py`:

```python
# tests/test_engine_damage.py
import pytest

import core.engine as eng_mod
from core.engine import F1Engine


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def test_event_involves_collision_either_side(engine):
    event = {"event_code": "COLL", "vehicle1_idx": 3, "vehicle2_idx": 7}
    assert engine._event_involves(event, 3) is True
    assert engine._event_involves(event, 7) is True
    assert engine._event_involves(event, 12) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_engine_damage.py -q`
Expected: FAIL — `assert False is True` (текущее множество `involved` не содержит
`vehicle1_idx`/`vehicle2_idx`)

- [ ] **Step 3: Implement**

Найти:

```python
    def _event_involves(self, event: dict, vehicle_idx: int) -> bool:
        if vehicle_idx is None:
            return False
        involved = {
            event.get("vehicle_idx"),
            event.get("overtaking_idx"),
            event.get("being_overtaken_idx"),
        }
        return vehicle_idx in involved
```

Заменить на:

```python
    def _event_involves(self, event: dict, vehicle_idx: int) -> bool:
        if vehicle_idx is None:
            return False
        involved = {
            event.get("vehicle_idx"),
            event.get("overtaking_idx"),
            event.get("being_overtaken_idx"),
            event.get("vehicle1_idx"),
            event.get("vehicle2_idx"),
        }
        return vehicle_idx in involved
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_engine_damage.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Checkpoint** — тесты задачи зелёные.

---

## Task 4: `core/engine.py` — трекинг повреждений, анти-спам, `state["damage"]`

**Files:**
- Modify: `core/engine.py`
- Test: `tests/test_engine_damage.py` (расширить)

- [ ] **Step 1: Write the failing tests**

Добавить в конец `tests/test_engine_damage.py`:

```python
def test_damage_state_updates_every_tick(engine):
    engine._damage_announced = {"wing": False, "floor": False, "gearbox": False, "engine": False}
    dmg = {"wing_damage": 5, "floor_damage": 3, "gearbox_damage": 0, "engine_damage": 0}
    engine._update_damage(dmg)
    state = engine.get_state().get("damage")
    assert state == {"wing_damage": 5, "floor_damage": 3, "gearbox_damage": 0, "engine_damage": 0}


def test_damage_voice_fires_once_on_threshold_cross(engine):
    engine._damage_announced = {"wing": False, "floor": False, "gearbox": False, "engine": False}
    while not engine.event_queue.empty():
        engine.event_queue.get_nowait()

    engine._update_damage({"wing_damage": 25, "floor_damage": 0, "gearbox_damage": 0, "engine_damage": 0})
    evt = engine.event_queue.get_nowait()
    assert evt["event_code"] == "DAMAGE_WING"
    assert "крыло" in evt["phrase"].lower()
    assert engine._damage_announced["wing"] is True

    # тот же тик снова >= порога -> тишина (флаг уже True)
    engine._update_damage({"wing_damage": 30, "floor_damage": 0, "gearbox_damage": 0, "engine_damage": 0})
    assert engine.event_queue.empty()


def test_damage_voice_silent_below_threshold(engine):
    engine._damage_announced = {"wing": False, "floor": False, "gearbox": False, "engine": False}
    while not engine.event_queue.empty():
        engine.event_queue.get_nowait()
    engine._update_damage({"wing_damage": 19, "floor_damage": 0, "gearbox_damage": 0, "engine_damage": 0})
    assert engine.event_queue.empty()
    assert engine._damage_announced["wing"] is False


def test_damage_voice_refires_after_repair_and_new_damage(engine):
    engine._damage_announced = {"wing": True, "floor": False, "gearbox": False, "engine": False}
    while not engine.event_queue.empty():
        engine.event_queue.get_nowait()

    # ремонт в боксах -> падает ниже порога -> флаг сбрасывается, тишина
    engine._update_damage({"wing_damage": 0, "floor_damage": 0, "gearbox_damage": 0, "engine_damage": 0})
    assert engine.event_queue.empty()
    assert engine._damage_announced["wing"] is False

    # новая поломка того же крыла -> объявляется заново
    engine._update_damage({"wing_damage": 45, "floor_damage": 0, "gearbox_damage": 0, "engine_damage": 0})
    evt = engine.event_queue.get_nowait()
    assert evt["event_code"] == "DAMAGE_WING"
    assert engine._damage_announced["wing"] is True


def test_damage_voice_fires_independently_per_category(engine):
    engine._damage_announced = {"wing": False, "floor": False, "gearbox": False, "engine": False}
    while not engine.event_queue.empty():
        engine.event_queue.get_nowait()

    engine._update_damage({"wing_damage": 25, "floor_damage": 25, "gearbox_damage": 0, "engine_damage": 0})
    events = []
    while not engine.event_queue.empty():
        events.append(engine.event_queue.get_nowait())
    codes = {e["event_code"] for e in events}
    assert codes == {"DAMAGE_WING", "DAMAGE_FLOOR"}
```

**Примечание по SSTA-сбросу (Step 9 ниже):** в этой кодовой базе нет прецедента
тестировать сброс состояния через синтетический SSTA-пакет (см. то же решение в
Pit-Stop Fix плане) — корректность двух новых строк в Step 9 проверяется при
код-ревью чтением диффа, тем же способом, что и остальные анти-спам сбросы в этом
файле. Отдельного юнит-теста для этого не пишем.

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_engine_damage.py -q`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute '_update_damage'`

- [ ] **Step 3: Модульные константы**

Найти в начале `core/engine.py`:

```python
    parse_player_telemetry, parse_player_status, parse_player_damage,
    PACKET_PARTICIPANTS, PACKET_EVENT, PACKET_SESSION,
    PACKET_LAP_DATA, PACKET_CAR_TELEMETRY, PACKET_CAR_STATUS, PACKET_CAR_DAMAGE,
    HEADER_SIZE,
)
```

Заменить на:

```python
    parse_player_telemetry, parse_player_status, parse_player_damage,
    PACKET_PARTICIPANTS, PACKET_EVENT, PACKET_SESSION,
    PACKET_LAP_DATA, PACKET_CAR_TELEMETRY, PACKET_CAR_STATUS, PACKET_CAR_DAMAGE,
    HEADER_SIZE,
)

# Повреждения кузова: порог "заметности" (%) для голосовой реплики — ниже не
# считаем поводом объявлять (мелкие царапины — постоянный шум телеметрии).
_DAMAGE_NOTICEABLE_THRESHOLD = 20
_DAMAGE_PHRASES: dict[str, str] = {
    "wing": "Повреждено крыло!",
    "floor": "Повреждено днище!",
    "gearbox": "Проблема с коробкой передач!",
    "engine": "Проблема с двигателем!",
}
```

**Важно:** «Найти» текст выше — это конец блока импортов `from core.packets import
(...)`. Если точные соседние строки внутри этого импорта отличаются (другой набор
символов до/после), найди сам конец этого конкретного импорта и добавь два новых
модульных объявления сразу после закрывающей скобки `)`, перед первым `class`.

- [ ] **Step 4: Init state**

Найти:

```python
        self._player_tyre_wear: float | None = None
        self._player_drs_active: bool = False
        self._player_speed_kmh: float | None = None
```

Заменить на:

```python
        self._player_tyre_wear: float | None = None
        self._player_drs_active: bool = False
        self._player_speed_kmh: float | None = None

        # Повреждения кузова: анти-спам "уже объявляли" по категории за сессию
        # (сбрасывается ниже порога — деталь починили в боксах, следующая поломка
        # снова объявится). См. design spec §5.
        self._damage_announced: dict[str, bool] = {
            "wing": False, "floor": False, "gearbox": False, "engine": False,
        }
```

- [ ] **Step 5: `state["damage"]` init**

Найти:

```python
            "f1_benchmark": None,
            "career_memory": None,
```

Заменить на:

```python
            "f1_benchmark": None,
            "career_memory": None,
            "damage": None,
```

- [ ] **Step 6: `_update_damage()` — новый метод**

Найти конец метода `_event_involves` (сразу после него, перед следующим методом
`_should_commentate`):

```python
    def _event_involves(self, event: dict, vehicle_idx: int) -> bool:
        if vehicle_idx is None:
            return False
        involved = {
            event.get("vehicle_idx"),
            event.get("overtaking_idx"),
            event.get("being_overtaken_idx"),
            event.get("vehicle1_idx"),
            event.get("vehicle2_idx"),
        }
        return vehicle_idx in involved

    def _should_commentate(self, event: dict) -> bool:
```

Заменить на:

```python
    def _event_involves(self, event: dict, vehicle_idx: int) -> bool:
        if vehicle_idx is None:
            return False
        involved = {
            event.get("vehicle_idx"),
            event.get("overtaking_idx"),
            event.get("being_overtaken_idx"),
            event.get("vehicle1_idx"),
            event.get("vehicle2_idx"),
        }
        return vehicle_idx in involved

    def _update_damage(self, dmg: dict) -> None:
        """Обновить HUD-состояние повреждений + голос один раз за категорию, когда
        она впервые пересекает порог заметности (см. design spec §5). Простая
        проверка текущего значения и текущего флага — без хранения "предыдущего
        тика"; сброс происходит, когда severity падает НИЖЕ порога (ремонт в
        боксах), готовя следующее объявление при новой поломке той же детали."""
        with self.state_lock:
            self.state["damage"] = {
                "wing_damage": dmg.get("wing_damage", 0),
                "floor_damage": dmg.get("floor_damage", 0),
                "gearbox_damage": dmg.get("gearbox_damage", 0),
                "engine_damage": dmg.get("engine_damage", 0),
            }
        categories = {
            "wing": dmg.get("wing_damage", 0),
            "floor": dmg.get("floor_damage", 0),
            "gearbox": dmg.get("gearbox_damage", 0),
            "engine": dmg.get("engine_damage", 0),
        }
        for category, severity in categories.items():
            if severity >= _DAMAGE_NOTICEABLE_THRESHOLD and not self._damage_announced[category]:
                self._damage_announced[category] = True
                self.event_queue.put({
                    "event_code": f"DAMAGE_{category.upper()}", "priority": "normal",
                    "phrase": _DAMAGE_PHRASES[category],
                    "color": "#F97316", "driver": ""})
            elif severity < _DAMAGE_NOTICEABLE_THRESHOLD:
                self._damage_announced[category] = False

    def _should_commentate(self, event: dict) -> bool:
```

- [ ] **Step 7: Вызов `_update_damage()` из `PACKET_CAR_DAMAGE` branch**

Найти:

```python
        elif packet_id == PACKET_CAR_DAMAGE and self._player_car_index < 22:
            dmg = parse_player_damage(data, self._player_car_index)
            if dmg.get("tyre_wear") is not None:
                self._player_tyre_wear = dmg["tyre_wear"]
            # нет полей для state.telemetry — снимок подтянет износ на следующем LAP_DATA
```

Заменить на:

```python
        elif packet_id == PACKET_CAR_DAMAGE and self._player_car_index < 22:
            dmg = parse_player_damage(data, self._player_car_index)
            if dmg.get("tyre_wear") is not None:
                self._player_tyre_wear = dmg["tyre_wear"]
            # нет полей для state.telemetry — снимок подтянет износ на следующем LAP_DATA
            if dmg:
                self._update_damage(dmg)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_engine_damage.py -q`
Expected: PASS (6 passed — 1 из Task 3 + 5 новых из этой задачи)

- [ ] **Step 9: Сброс на SSTA**

Найти:

```python
                self._current_lap_pit = False
                self._last_completed_lap_was_pit = False
                self.story_collector.reset()
```

Заменить на:

```python
                self._current_lap_pit = False
                self._last_completed_lap_was_pit = False
                self._damage_announced = {
                    "wing": False, "floor": False, "gearbox": False, "engine": False,
                }
                self.story_collector.reset()
```

- [ ] **Step 10: Regression check**

Run: `py -3.12 -m pytest tests/test_engine_f1_benchmark.py tests/test_engine_career_memory.py tests/test_engine_pit_tracking.py tests/test_packets_gaps_tyre.py tests/test_race_state.py -q`
Expected: PASS, без изменений в счёте.

- [ ] **Step 11: Checkpoint** — тесты задачи и регрессии зелёные.

---

## Task 5: UI — панель «Повреждения»

**Files:**
- Modify: `NewSpotterUI/lib/api.ts`
- Modify: `NewSpotterUI/components/spotter/views/race.tsx`

- [ ] **Step 1: `lib/api.ts` — новый тип**

Найти:

```typescript
export type CareerMemoryState = {
  gap_ms: number
  player_best_ms: number
  best_ever_ms: number
  best_ever_date: string | null
  sectors: Record<"1" | "2" | "3", F1SectorGap> | null
}
```

Заменить на:

```typescript
export type CareerMemoryState = {
  gap_ms: number
  player_best_ms: number
  best_ever_ms: number
  best_ever_date: string | null
  sectors: Record<"1" | "2" | "3", F1SectorGap> | null
}

export type DamageState = {
  wing_damage: number
  floor_damage: number
  gearbox_damage: number
  engine_damage: number
}
```

- [ ] **Step 2: `lib/api.ts` — поле в `SpotterState`**

Найти:

```typescript
  f1_benchmark?: F1BenchmarkState | null
  career_memory?: CareerMemoryState | null
  voice_query?: VoiceQuery | null
}
```

Заменить на:

```typescript
  f1_benchmark?: F1BenchmarkState | null
  career_memory?: CareerMemoryState | null
  damage?: DamageState | null
  voice_query?: VoiceQuery | null
}
```

- [ ] **Step 3: `race.tsx` — производные значения**

Найти:

```tsx
  const career = state?.career_memory ?? null
  const careerSectors = career?.sectors ?? null
```

Заменить на:

```tsx
  const career = state?.career_memory ?? null
  const careerSectors = career?.sectors ?? null
  const damage = state?.damage ?? null
```

- [ ] **Step 4: `race.tsx` — новая панель**

Найти (закрытие панели «Личный рекорд трассы», перед панелью «Голосовой вопрос»):

```tsx
              ) : (
                <p className="text-[11px] text-muted-foreground">
                  Личный рекорд появится после первого визита на эту трассу.
                </p>
              )}
            </Panel>
            <Panel label="Голосовой вопрос">
```

Заменить на:

```tsx
              ) : (
                <p className="text-[11px] text-muted-foreground">
                  Личный рекорд появится после первого визита на эту трассу.
                </p>
              )}
            </Panel>
            <Panel label="Повреждения">
              {damage ? (
                <div className="grid grid-cols-2 gap-1.5">
                  {(
                    [
                      ["Крылья", damage.wing_damage],
                      ["Днище", damage.floor_damage],
                      ["Коробка", damage.gearbox_damage],
                      ["Двигатель", damage.engine_damage],
                    ] as const
                  ).map(([label, value]) => (
                    <div
                      key={label}
                      className={cn(
                        "rounded px-1.5 py-1 text-center",
                        value >= 20
                          ? "bg-destructive/15 text-destructive"
                          : "bg-secondary/60 text-muted-foreground",
                      )}
                    >
                      <p className="font-mono text-[9px]">{label}</p>
                      <p className="text-[11px] font-semibold tabular">{value}%</p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-[11px] text-muted-foreground">
                  Данные о повреждениях появятся после первого круга.
                </p>
              )}
            </Panel>
            <Panel label="Голосовой вопрос">
```

- [ ] **Step 5: Typecheck**

Run: `cd NewSpotterUI && npx tsc --noEmit`
Expected: без ошибок типов

- [ ] **Step 6: Checkpoint** — tsc чист.

---

## Task 6: Полная верификация + CONTEXT.md

**Files:**
- Modify: `CONTEXT.md`

- [ ] **Step 1: Полный прогон тестов**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: все тесты проходят (новые тесты этого плана: 3 packets + 5 race_state +
6 engine_damage = +14 к текущему бейслайну на момент старта этой фичи; точное
итоговое число — по факту прогона, а не арифметикой, т.к. в проекте возможны
параллельные сессии, меняющие бейслайн — см. Pit-Stop Fix CONTEXT.md запись про
находку с параллельными сессиями). Если итоговая строка не пропечаталась — считать
через `grep -o '[.sF]' <лог> | sort | uniq -c`.

- [ ] **Step 2: Полный typecheck**

Run: `cd NewSpotterUI && npx tsc --noEmit`
Expected: чисто

- [ ] **Step 3: Import smoke test**

Run: `py -3.12 -c "import core.engine, core.packets, core.race_state"`
Expected: без ошибок

- [ ] **Step 4: Обновить CONTEXT.md**

Прочитать текущий `CONTEXT.md` целиком, следовать существующей структуре/конвенции
(~100-пунктовый лимит + архивация старейшей из последних трёх сессий). Добавить
запись новой сессии: что сделано (5 задач — packets, race_state, engine × 2,
UI), новый тест-бейслайн (реальное число из Step 1), явно зафиксировать:
- `COLL` — обычное игровое событие (идёт через `parse_event()`/`enrich()`/уже
  существующий генерик-пайплайн `_should_commentate`/`event_queue`, LLM сам
  формулирует реплику по контексту, как `OVTK`/`PENA`) — НЕ как `DAMAGE_*`.
- `DAMAGE_WING`/`DAMAGE_FLOOR`/`DAMAGE_GEARBOX`/`DAMAGE_ENGINE` — деривативное,
  детерминированное состояние (как `F1_BENCH`/`CAREER_PB`), готовая фраза из
  Python, НЕ через LLM — разные механизмы для разных типов событий, не путать.
- `state["telemetry"]` НЕ содержит `tyre_compound`/`tyre_wear`/`tyre_age` — это
  распространённое неверное предположение (споткнулись об него при подготовке
  этого плана), эти поля — только приватные атрибуты движка для
  `RaceTimeline`/`driver_coach`. Повреждения кузова экспонируются через ОТДЕЛЬНЫЙ
  `state["damage"]`, не через `state["telemetry"]`.
- Байт-офсеты CarDamageData (24-33) подтверждены косвенно (существующий
  `stride=42` из старого теста), но НЕ верифицированы вживую — как и `pit_status`
  ранее, дождаться живого прогона с реальными повреждениями и сверить через
  `diag_lap_offsets.py`-подобный вывод.

- [ ] **Step 5: Checkpoint** — полный прогон зелёный, CONTEXT.md обновлён.
