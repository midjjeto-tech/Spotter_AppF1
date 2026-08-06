# In-game HUD: Radar + Relative — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Два новых виджета in-game HUD — Radar (ближние машины слева/справа)
и Relative (отрыв в секундах до нескольких ближайших соперников, не только
P±1), используя данные, которые движок уже считает, но сейчас выбрасывает.

**Architecture:** `core/engine.py::_spotter_tick()` уже проецирует мировые
координаты соперников на ось игрока на каждом Motion-тике — добавляем
параллельный, более широкий проход и сохраняем снимок на `self._radar`.
`core/packets.py::parse_lap_data()` уже парсит `gaps_front` для всех 22 машин —
протаскиваем это значение в `grid`-строки движка. `core/overlay.py` получает
два новых поля в ответе (`radar`, `relative`), `core/ui_state.py` перестаёт
резать `grid` до 5 строк раньше времени. Фронтенд — два новых виджета в
существующей drag-системе `NewSpotterUI/components/spotter/overlay/in-game-overlay.tsx`.

**Tech Stack:** Python 3.12 / pytest (backend), Next.js 16 / React 19 /
TypeScript / Tailwind v4 (frontend, статический экспорт в `webui/`).

**Спека:** `docs/superpowers/specs/2026-07-22-overlay-radar-relative-design.md`.

**Проект НЕ под git** — шаги "Commit" опущены, как в предыдущих планах этого
проекта.

---

### Task 1: `core/overlay.py` — `_relative_rows()` + поля `radar`/`relative`

**Files:**
- Modify: `core/overlay.py`
- Test: `tests/test_overlay.py`

Чистая функция, не зависит от остальных задач — `build_overlay_state` уже
принимает произвольный `snapshot`-словарь, новые ключи просто отсутствуют
до Task 2/3, дефолт `[]` покрывает это.

- [x] **Step 1: Написать падающие тесты**

Добавить в `tests/test_overlay.py` (после `test_build_grid_top5_fewer_than_5`,
перед `test_build_speed_and_position`):

```python
# ---------------------------------------------------------------------------
# radar / relative
# ---------------------------------------------------------------------------

def test_build_radar_passes_through_from_snapshot():
    radar = [{"vehicle_idx": 12, "side": "left", "lateral_m": 1.8, "longitudinal_m": -3.2}]
    result = build_overlay_state({"radar": radar})
    assert result["radar"] == radar


def test_build_radar_defaults_to_empty_list():
    result = build_overlay_state({})
    assert result["radar"] == []


def test_relative_rows_player_in_middle_of_pack():
    # 8 машин, игрок на P5 — ahead=3/behind=3 не упирается в край пелотона
    # (P1 намеренно НЕ входит в окно, чтобы отдельно проверить, что окно
    # действительно ограничено 3 позициями, а не "до лидера").
    grid = [
        {"position": 1, "driver": "A", "team": "T", "color": "#111", "gap_front_ms": 0},
        {"position": 2, "driver": "B", "team": "T", "color": "#222", "gap_front_ms": 500},
        {"position": 3, "driver": "C", "team": "T", "color": "#333", "gap_front_ms": 700},
        {"position": 4, "driver": "D", "team": "T", "color": "#444", "gap_front_ms": 900},
        {"position": 5, "driver": "E", "team": "T", "color": "#555", "gap_front_ms": 1100},
        {"position": 6, "driver": "F", "team": "T", "color": "#666", "gap_front_ms": 600},
        {"position": 7, "driver": "G", "team": "T", "color": "#777", "gap_front_ms": 800},
        {"position": 8, "driver": "H", "team": "T", "color": "#888", "gap_front_ms": 400},
    ]
    result = build_overlay_state({"grid": grid, "position": 5})
    rows = result["relative"]
    assert [r["position"] for r in rows] == [2, 3, 4, 5, 6, 7, 8]

    row4 = next(r for r in rows if r["position"] == 4)
    assert row4["ahead"] is True
    assert row4["gap_to_player_ms"] == 900  # непосредственный сосед — сырой gap_front

    row2 = next(r for r in rows if r["position"] == 2)
    assert row2["ahead"] is True
    assert row2["gap_to_player_ms"] == 900 + 700 + 500  # накопленный, не сырой gap_front своей строки

    player_row = next(r for r in rows if r["position"] == 5)
    assert player_row["ahead"] is None
    assert player_row["gap_to_player_ms"] is None
    assert player_row["gap_to_player_str"] == "—"

    row6 = next(r for r in rows if r["position"] == 6)
    assert row6["ahead"] is False
    assert row6["gap_to_player_ms"] == 600
    assert row6["gap_to_player_str"] == "+0.600"

    row8 = next(r for r in rows if r["position"] == 8)
    assert row8["ahead"] is False
    assert row8["gap_to_player_ms"] == 600 + 800 + 400


def test_relative_rows_player_leading_has_no_ahead_rows():
    grid = [
        {"position": 1, "driver": "A", "team": "T", "color": "#111", "gap_front_ms": 0},
        {"position": 2, "driver": "B", "team": "T", "color": "#222", "gap_front_ms": 500},
    ]
    result = build_overlay_state({"grid": grid, "position": 1})
    rows = result["relative"]
    assert [r["position"] for r in rows] == [1, 2]
    assert rows[0]["ahead"] is None


def test_relative_rows_player_last_has_no_behind_rows():
    grid = [
        {"position": 1, "driver": "A", "team": "T", "color": "#111", "gap_front_ms": 0},
        {"position": 2, "driver": "B", "team": "T", "color": "#222", "gap_front_ms": 500},
    ]
    result = build_overlay_state({"grid": grid, "position": 2})
    rows = result["relative"]
    assert [r["position"] for r in rows] == [1, 2]
    assert rows[-1]["ahead"] is None


def test_relative_rows_gap_in_grid_stops_accumulation():
    # Позиция 3 отсутствует (сошла машина/неполный тик). P2 физически
    # присутствует в grid, но "дыра" на P3 должна остановить накопление
    # ДО того, как накопитель дойдёт до P2 — иначе получим гэп, посчитанный
    # через неизвестный (сошедшая машина) промежуток.
    grid = [
        {"position": 1, "driver": "A", "team": "T", "color": "#111", "gap_front_ms": 0},
        {"position": 2, "driver": "B", "team": "T", "color": "#222", "gap_front_ms": 500},
        {"position": 4, "driver": "D", "team": "T", "color": "#444", "gap_front_ms": 900},
        {"position": 5, "driver": "E", "team": "T", "color": "#555", "gap_front_ms": 300},
        {"position": 6, "driver": "F", "team": "T", "color": "#666", "gap_front_ms": 200},
    ]
    result = build_overlay_state({"grid": grid, "position": 5})
    rows = result["relative"]
    # P2 существует в grid, но недостижим из-за дыры на P3 — не должен попасть
    # в результат, хотя формально "ahead" диапазон (3 позиции) его бы охватил.
    assert [r["position"] for r in rows] == [4, 5, 6]


def test_relative_rows_unknown_player_position_returns_empty():
    grid = [{"position": 1, "driver": "A", "team": "T", "color": "#111", "gap_front_ms": 0}]
    result = build_overlay_state({"grid": grid, "position": None})
    assert result["relative"] == []
```

- [x] **Step 2: Запустить тесты — убедиться, что падают**

Run: `py -3.12 -u -m pytest tests/test_overlay.py -k "radar or relative" -v`
Expected: FAIL — `KeyError: 'radar'` / `KeyError: 'relative'` (ключей ещё нет
в возвращаемом словаре).

- [x] **Step 3: Реализовать `_relative_rows()` и подключить оба поля**

В `core/overlay.py` добавить после `_compound_color` (перед `build_overlay_state`):

```python
def _relative_rows(grid: list[dict], player_position: int | None,
                    *, ahead: int = 3, behind: int = 3) -> list[dict]:
    """Строки вокруг игрока с накопленным гэпом (сумма gap_front_ms между
    позициями от игрока до целевой строки) — не сырым gap_front_ms целевой
    строки (тот — гэп только к её непосредственному соседу впереди)."""
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
        rows.append({**row, "gap_to_player_ms": cumulative,
                     "gap_to_player_str": _fmt_gap_ms(cumulative), "ahead": True})
    rows.reverse()
    rows.append({**player_row, "gap_to_player_ms": None,
                 "gap_to_player_str": _fmt_gap_ms(None), "ahead": None})

    cumulative = 0
    for pos in range(player_position + 1, player_position + behind + 1):
        row = by_pos.get(pos)
        if row is None:
            break
        cumulative += row.get("gap_front_ms") or 0
        rows.append({**row, "gap_to_player_ms": cumulative,
                     "gap_to_player_str": _fmt_gap_ms(cumulative), "ahead": False})
    return rows
```

В `build_overlay_state`, в возвращаемом словаре (после `"grid_top5": grid_top5,`)
добавить:

```python
        "radar":       snapshot.get("radar", []),
        "relative":    _relative_rows(grid_raw, snapshot.get("position")),
```

- [x] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `py -3.12 -u -m pytest tests/test_overlay.py -v`
Expected: PASS (все тесты файла, включая новые и уже существующие
`test_build_minimal_snapshot`/`test_build_grid_top5` и т.п.).

Также обновить `test_build_minimal_snapshot` — добавить в список обязательных
ключей:

```python
    assert "radar" in result
    assert "relative" in result
```

---

### Task 2: `core/ui_state.py` — поле `radar` в `OverlayTelemetry` + полный `grid`

**Files:**
- Modify: `core/ui_state.py:1-7` (импорт), `:77-88` (`OverlayTelemetry`), `:293-310` (`overlay()`)
- Test: `tests/test_ui_state.py`

- [x] **Step 1: Написать падающий тест**

Добавить в `tests/test_ui_state.py` (в конец файла):

```python
def test_overlay_exposes_relative_rows_beyond_top5():
    projection = _projection()
    grid = [
        {"position": i, "driver": f"D{i}", "team": "T", "color": "#000",
         "gap_front_ms": 500}
        for i in range(1, 8)
    ]
    projection.set_race({"leader": "D1", "grid": grid})

    overlay = projection.overlay(OverlayTelemetry(
        position=6, lap_current=10, lap_total=50, speed_kmh=300,
        drs_active=True, gap_leader_ms=1000, gap_front_ms=500,
        gap_behind_ms=800, tyre_compound="S", tyre_age=12, tyre_wear=70.0,
        radar=[],
    ))

    # Игрок на P6 — вне топ-5 по позиции, но relative должен видеть его
    # соседей (P5/P7), значит build_overlay_state получил ПОЛНЫЙ grid, а не
    # обрезанный до 5 элементов до вызова.
    positions_in_relative = [row["position"] for row in overlay["relative"]]
    assert 5 in positions_in_relative
    assert 7 in positions_in_relative
    assert len(overlay["grid_top5"]) == 5
```

Также обновить существующий `test_overlay_uses_consistent_public_and_telemetry_snapshot` —
добавить обязательный новый аргумент:

```python
    overlay = projection.overlay(OverlayTelemetry(
        position=3, lap_current=10, lap_total=50, speed_kmh=300,
        drs_active=True, gap_leader_ms=1000, gap_front_ms=500,
        gap_behind_ms=800, tyre_compound="S", tyre_age=12, tyre_wear=70.0,
        radar=[],
    ))
```

- [x] **Step 2: Запустить тесты — убедиться, что падают**

Run: `py -3.12 -u -m pytest tests/test_ui_state.py -v`
Expected: FAIL — `TypeError: OverlayTelemetry.__init__() got an unexpected
keyword argument 'radar'` (поля ещё нет в датаклассе).

- [x] **Step 3: Добавить поле и убрать преждевременный срез grid**

В `core/ui_state.py` заменить импорт (строка 6):

```python
from dataclasses import asdict, dataclass, field
```

В `OverlayTelemetry` (после `tyre_wear: float | None`) добавить:

```python
    radar: list[dict] = field(default_factory=list)
```

В `overlay()` заменить:

```python
            "grid": list(race.get("grid", []))[:5],
```

на:

```python
            "grid": list(race.get("grid", [])),
```

- [x] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `py -3.12 -u -m pytest tests/test_ui_state.py -v`
Expected: PASS.

---

### Task 3: `core/engine.py` — `gap_front_ms` в строках `grid`

**Files:**
- Modify: `core/engine.py:1184-1195` (сборка `grid` в lap_data-хендлере)
- Test: `tests/test_engine_grid_gap_front.py` (новый)

- [x] **Step 1: Написать падающий тест**

Создать `tests/test_engine_grid_gap_front.py`:

```python
"""core/engine.py: gap_front_ms (уже парсится parse_lap_data для всех 22
машин) должен долетать до grid-строк движка, не только до gap игрока.
См. docs/superpowers/specs/2026-07-22-overlay-radar-relative-design.md."""
import struct

import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.packets import HEADER_SIZE, LAP_DATA_SIZE, PACKET_LAP_DATA
from tests.telemetry import consume_f1_packet


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _lap_buf_with_positions_and_gaps(cars: dict[int, dict]) -> bytes:
    buf = bytearray(HEADER_SIZE + 22 * LAP_DATA_SIZE)
    for idx, c in cars.items():
        base = HEADER_SIZE + idx * LAP_DATA_SIZE
        buf[base + 32] = c["position"]
        buf[base + 33] = c.get("lap", 1)
        struct.pack_into("<H", buf, base + 14, c.get("gap_front_ms", 0) & 0xFFFF)
    return bytes(buf)


def test_grid_rows_carry_each_cars_own_gap_to_car_in_front(engine):
    engine._player_car_index = 0

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
        _lap_buf_with_positions_and_gaps({
            0: {"position": 1, "gap_front_ms": 0},
            1: {"position": 2, "gap_front_ms": 742},
            2: {"position": 3, "gap_front_ms": 1106},
        }))

    by_pos = {row["position"]: row for row in engine._current_grid}
    assert by_pos[2]["gap_front_ms"] == 742
    assert by_pos[3]["gap_front_ms"] == 1106
```

- [x] **Step 2: Запустить тест — убедиться, что падает**

Run: `py -3.12 -u -m pytest tests/test_engine_grid_gap_front.py -v`
Expected: FAIL — `KeyError: 'gap_front_ms'` (поля ещё нет в строках `grid`).

- [x] **Step 3: Протащить `gap_front_ms` в сборку `grid`**

В `core/engine.py`, в блоке `elif delta.kind == "lap_data":` заменить:

```python
            positions = lap_info.get("positions", {})
            if any(v > 0 for v in positions.values()):
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
```

на:

```python
            positions = lap_info.get("positions", {})
            if any(v > 0 for v in positions.values()):
                gaps_front = lap_info.get("gaps_front", {})
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
                        "gap_front_ms": gaps_front.get(vehicle_idx),
                    })
```

- [x] **Step 4: Запустить тест — убедиться, что проходит**

Run: `py -3.12 -u -m pytest tests/test_engine_grid_gap_front.py -v`
Expected: PASS.

- [x] **Step 5: Полный прогон — убедиться, что ничего не сломано**

Run: `py -3.12 -u -m pytest tests/test_engine_rivals.py tests/test_engine_leader_change.py -v`
Expected: PASS (эти файлы тоже строят `grid`/используют lap_data — новое
поле в словаре не должно ломать существующие ассерты по другим ключам).

---

### Task 4: `core/engine.py` — снимок Radar в `_spotter_tick`

**Files:**
- Modify: `core/engine.py:208` (инициализация), `:850-896` (`_spotter_tick`)
- Test: `tests/test_engine_spotter.py`

- [x] **Step 1: Написать падающие тесты**

Добавить в `tests/test_engine_spotter.py` (в конец файла, после
`test_flashback_resets_spotter`):

```python
def test_radar_captures_car_within_wide_window_with_signed_direction(engine):
    engine._player_car_index = 0
    engine._race_engineer.spotter_tracker.reset()
    _drain(engine)

    # 20м по lap_distance — за пределами LONGITUDINAL_WINDOW_M (6м, голосовой
    # споттер должен молчать), но внутри RADAR_WINDOW_M (25м) — радар должен
    # это увидеть.
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf_with_distance({0: 100.0, 1: 120.0}))
    _drain(engine)

    from core.packets import parse_motion_all
    motion = _motion_buf({0: (0.0, 0.0, 1.0, 0.0), 1: (2.0, 0.0, 0.0, 0.0)})
    engine._spotter_tick(parse_motion_all(motion))

    # Голосовой споттер молчит (вне его узкого окна) — существующее поведение.
    assert not [e for e in _drain(engine) if e["event_code"].startswith("SPOTTER_")]

    # Радар видит машину: она впереди (120 > 100) и справа (совпадает с
    # существующим геометрическим тестом test_close_car_on_right_produces_spotter_event).
    assert len(engine._radar) == 1
    contact = engine._radar[0]
    assert contact["vehicle_idx"] == 1
    assert contact["side"] == "right"
    assert contact["longitudinal_m"] == pytest.approx(20.0)
    assert contact["lateral_m"] == pytest.approx(2.0)
    engine._race_engineer.spotter_tracker.reset()


def test_radar_excludes_car_beyond_radar_window(engine):
    engine._player_car_index = 0
    engine._race_engineer.spotter_tracker.reset()
    _drain(engine)

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf_with_distance({0: 100.0, 1: 200.0}))
    _drain(engine)

    from core.packets import parse_motion_all
    motion = _motion_buf({0: (0.0, 0.0, 1.0, 0.0), 1: (2.0, 0.0, 0.0, 0.0)})
    engine._spotter_tick(parse_motion_all(motion))

    assert engine._radar == []
    engine._race_engineer.spotter_tracker.reset()


def test_radar_does_not_change_existing_voice_spotter_candidates(engine):
    # Регрессия: широкий радар-проход не должен подсунуть более широкий набор
    # кандидатов в SpotterTracker (узкое окно голосового споттера — отдельное).
    engine._player_car_index = 0
    engine._race_engineer.spotter_tracker.reset()
    _drain(engine)

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf_with_distance({0: 100.0, 1: 150.0}))
    _drain(engine)

    from core.packets import parse_motion_all
    motion = _motion_buf({0: (0.0, 0.0, 1.0, 0.0), 1: (2.0, 0.0, 0.0, 0.0)})
    engine._spotter_tick(parse_motion_all(motion))

    assert not [e for e in _drain(engine) if e["event_code"].startswith("SPOTTER_")]
    assert engine._radar == []  # тоже вне RADAR_WINDOW_M (25м) — 50м разница
    engine._race_engineer.spotter_tracker.reset()
```

- [x] **Step 2: Запустить тесты — убедиться, что падают**

Run: `py -3.12 -u -m pytest tests/test_engine_spotter.py -v`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute '_radar'`.

- [x] **Step 3: Инициализировать `self._radar` и расширить `_spotter_tick`**

В `core/engine.py`, рядом с `self._current_grid: list[dict] = []` (строка 208)
добавить:

```python
        self._radar: list[dict] = []
```

Добавить константу модульного уровня рядом с остальными импортами
(после блока `from core.strategy_ai.spotter import (...)`, строка 61):

```python
RADAR_WINDOW_M = 25.0  # шире голосового LONGITUDINAL_WINDOW_M — только для HUD-радара
```

Заменить тело `_spotter_tick` (строки 858-880 — от `player = motion_all...`
до `candidates.append((abs(lateral), side))`) на:

```python
        player = motion_all.get(self._player_car_index)
        if player is None:
            return
        player_dist = self._lap_distances.get(self._player_car_index)
        if player_dist is None:
            return

        candidates: list[tuple[float, str]] = []
        radar: list[dict] = []
        for idx, m in motion_all.items():
            if idx == self._player_car_index:
                continue
            rival_dist = self._lap_distances.get(idx)
            if rival_dist is None:
                continue
            longitudinal = rival_dist - player_dist  # знак: + впереди, - позади
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
            if abs(longitudinal) <= LONGITUDINAL_WINDOW_M:
                candidates.append((abs(lateral), side))

        self._radar = sorted(radar, key=lambda c: abs(c["longitudinal_m"]))[:6]
```

Остальная часть метода (`phrase = self._race_engineer.spotter_advisory(...)`
и далее) не меняется.

**Примечание к спеке:** явный сброс `self._radar` на SSTA/CHQF/flashback НЕ
добавляется — как и `self._lap_distances`/`self._current_grid`, это
"последнее известное значение с любого тика", тот же паттерн, что уже
принят в проекте (см. `docs/superpowers/specs/2026-07-18-real-spotter-motion-design.md`,
раздел про DRS). Уточнение спеки, не изменение поведения по сути.

- [x] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `py -3.12 -u -m pytest tests/test_engine_spotter.py -v`
Expected: PASS (все тесты файла, включая существующие 5).

---

### Task 5: `core/engine.py` — `self._radar` в `get_overlay_state()`

**Files:**
- Modify: `core/engine.py:2452-2466`

Прямое продолжение Task 4 — без этого шага `self._radar` посчитан, но
никогда не попадает в `/api/overlay`.

- [x] **Step 1: Написать падающий тест**

Добавить в `tests/test_engine_spotter.py` (после тестов Task 4):

```python
def test_get_overlay_state_exposes_radar(engine):
    engine._player_car_index = 0
    engine._radar = [{"vehicle_idx": 1, "side": "left", "lateral_m": 2.0, "longitudinal_m": -3.0}]

    overlay = engine.get_overlay_state()

    assert overlay["radar"] == [{"vehicle_idx": 1, "side": "left", "lateral_m": 2.0, "longitudinal_m": -3.0}]
    engine._radar = []
```

- [x] **Step 2: Запустить тест — убедиться, что падает**

Run: `py -3.12 -u -m pytest tests/test_engine_spotter.py -k test_get_overlay_state_exposes_radar -v`
Expected: FAIL — `overlay["radar"] == []` (значение не проброшено).

- [x] **Step 3: Передать `radar` в `OverlayTelemetry`**

В `core/engine.py::get_overlay_state()` добавить аргумент:

```python
    def get_overlay_state(self) -> dict:
        """Build consolidated Broadcast Overlay HUD dict for /api/overlay."""
        return self._ui_state.overlay(OverlayTelemetry(
            position=self._player_pos,
            lap_current=self._player_lap,
            lap_total=getattr(self, "_total_laps", None),
            speed_kmh=self._player_speed_kmh,
            drs_active=self._player_drs_active,
            gap_leader_ms=self._player_gap_leader,
            gap_front_ms=self._player_gap_front,
            gap_behind_ms=self._player_gap_behind,
            tyre_compound=self._player_tyre_compound,
            tyre_age=self._player_tyre_age,
            tyre_wear=self._player_tyre_wear,
            radar=self._radar,
        ))
```

- [x] **Step 4: Запустить тест — убедиться, что проходит**

Run: `py -3.12 -u -m pytest tests/test_engine_spotter.py -v`
Expected: PASS (весь файл).

- [x] **Step 5: Полный backend-прогон**

Run: `py -3.12 -u -m pytest -q`
Expected: зелёный, тот же 1 skip и те же известные YandexSpeech warnings,
что и до начала работы (см. верификацию в конце плана — здесь только
промежуточная проверка, что предыдущие 5 задач ничего не сломали).

---

### Task 6: `NewSpotterUI/lib/api.ts` — типы `radar`/`relative`

**Files:**
- Modify: `NewSpotterUI/lib/api.ts:249-262` (`OverlayState`)

- [x] **Step 1: Добавить типы**

После `export type OverlayStrategy = {...}` (строка 247) добавить:

```typescript
export type OverlayRadarContact = {
  vehicle_idx: number
  side: "left" | "right"
  lateral_m: number
  longitudinal_m: number
}

export type OverlayRelativeRow = {
  vehicle_idx: number
  position: number
  driver: string
  team: string
  color: string
  gap_to_player_ms: number | null
  gap_to_player_str: string
  ahead: boolean | null
}
```

В `OverlayState` (после `grid_top5: Array<...>`) добавить:

```typescript
  radar: OverlayRadarContact[]
  relative: OverlayRelativeRow[]
```

- [x] **Step 2: Проверить типы**

Run (из `NewSpotterUI/`): `pnpm exec tsc --noEmit`
Expected: ошибка в `in-game-overlay.tsx` — `PREVIEW_OVERLAY` не удовлетворяет
`OverlayState` (не хватает `radar`/`relative`). Это ожидаемо — исправляется
в Task 7.

---

### Task 7: `in-game-overlay.tsx` — виджеты Radar и Relative

**Files:**
- Modify: `NewSpotterUI/components/spotter/overlay/in-game-overlay.tsx`

- [x] **Step 1: Расширить типы виджетов и раскладку**

Заменить:

```typescript
type WidgetId = "timing" | "telemetry" | "strategy" | "radio"
```

на:

```typescript
type WidgetId = "timing" | "telemetry" | "strategy" | "radio" | "radar" | "relative"
```

Заменить:

```typescript
const WIDGET_SIZE: Record<WidgetId, { width: number; height: number }> = {
  timing: { width: 284, height: 150 },
  telemetry: { width: 300, height: 150 },
  strategy: { width: 330, height: 190 },
  radio: { width: 560, height: 260 },
}

const DEFAULT_LAYOUT: Layout = {
  timing: { x: 38, y: 48 },
  telemetry: { x: 38, y: 690 },
  strategy: { x: 1390, y: 48 },
  radio: { x: 520, y: 720 },
}
```

на:

```typescript
const WIDGET_SIZE: Record<WidgetId, { width: number; height: number }> = {
  timing: { width: 284, height: 150 },
  telemetry: { width: 300, height: 150 },
  strategy: { width: 330, height: 190 },
  radio: { width: 560, height: 260 },
  radar: { width: 180, height: 212 },
  relative: { width: 240, height: 220 },
}

const DEFAULT_LAYOUT: Layout = {
  timing: { x: 38, y: 48 },
  telemetry: { x: 38, y: 690 },
  strategy: { x: 1390, y: 48 },
  radio: { x: 520, y: 720 },
  radar: { x: 1390, y: 260 },
  relative: { x: 1030, y: 48 },
}
```

Заменить:

```typescript
function fittedDefaultLayout(): Layout {
  if (typeof window === "undefined") return DEFAULT_LAYOUT
  return {
    timing: { x: 32, y: 32 },
    telemetry: { x: 32, y: Math.max(220, window.innerHeight - 190) },
    strategy: { x: Math.max(32, window.innerWidth - 362), y: 32 },
    radio: {
      x: Math.max(32, Math.round((window.innerWidth - 560) / 2)),
      y: Math.max(220, window.innerHeight - 360),
    },
  }
}
```

на:

```typescript
function fittedDefaultLayout(): Layout {
  if (typeof window === "undefined") return DEFAULT_LAYOUT
  return {
    timing: { x: 32, y: 32 },
    telemetry: { x: 32, y: Math.max(220, window.innerHeight - 190) },
    strategy: { x: Math.max(32, window.innerWidth - 362), y: 32 },
    radio: {
      x: Math.max(32, Math.round((window.innerWidth - 560) / 2)),
      y: Math.max(220, window.innerHeight - 360),
    },
    radar: { x: Math.max(32, window.innerWidth - 362), y: 250 },
    relative: { x: Math.max(32, window.innerWidth - 620), y: 32 },
  }
}
```

- [x] **Step 2: Добавить preview-данные**

В `PREVIEW_OVERLAY` (после `leader: "VERSTAPPEN",`) добавить:

```typescript
  radar: [
    { vehicle_idx: 55, side: "left", lateral_m: 2.1, longitudinal_m: -4.5 },
    { vehicle_idx: 63, side: "right", lateral_m: 1.6, longitudinal_m: 8.0 },
  ],
  relative: [
    { vehicle_idx: 33, position: 1, driver: "VERSTAPPEN", team: "Red Bull Racing", color: "#3671C6", gap_to_player_ms: 24500, gap_to_player_str: "+24.500", ahead: true },
    { vehicle_idx: 16, position: 2, driver: "LECLERC", team: "Ferrari", color: "#E8002D", gap_to_player_ms: 12100, gap_to_player_str: "+12.100", ahead: true },
    { vehicle_idx: 4, position: 3, driver: "NORRIS", team: "McLaren", color: "#FF8000", gap_to_player_ms: 6840, gap_to_player_str: "+6.840", ahead: true },
    { vehicle_idx: 44, position: 4, driver: "HAMILTON", team: "Mercedes", color: "#27F4D2", gap_to_player_ms: null, gap_to_player_str: "—", ahead: null },
    { vehicle_idx: 63, position: 5, driver: "RUSSELL", team: "Mercedes", color: "#27F4D2", gap_to_player_ms: 742, gap_to_player_str: "+0.742", ahead: false },
    { vehicle_idx: 55, position: 6, driver: "SAINZ", team: "Ferrari", color: "#E8002D", gap_to_player_ms: 1848, gap_to_player_str: "+1.848", ahead: false },
  ],
```

- [x] **Step 3: Добавить компоненты `RadarWidget` и `RelativeWidget`**

После функции `DriverBadge` (перед `function Frame(`) добавить:

```tsx
function RadarWidget({ contacts }: { contacts: OverlayState["radar"] }) {
  const RANGE_M = 25
  const SIZE = 148
  const HALF = SIZE / 2
  return (
    <div className="flex items-center justify-center p-4">
      <div className="relative rounded-full border border-white/15 bg-black/40" style={{ width: SIZE, height: SIZE }}>
        <div className="absolute left-1/2 top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#ff244d]" />
        {contacts.map((car) => {
          const signedLateral = car.side === "right" ? car.lateral_m : -car.lateral_m
          const x = Math.max(6, Math.min(SIZE - 6, HALF + (signedLateral / RANGE_M) * HALF))
          const y = Math.max(6, Math.min(SIZE - 6, HALF - (car.longitudinal_m / RANGE_M) * HALF))
          return (
            <div
              key={car.vehicle_idx}
              className="absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-cyan-300"
              style={{ left: x, top: y }}
            />
          )
        })}
      </div>
    </div>
  )
}

function RelativeWidget({ rows }: { rows: OverlayState["relative"] }) {
  return (
    <div className="divide-y divide-white/10">
      {rows.map((row) => (
        <div
          key={row.vehicle_idx}
          className={cn(
            "flex items-center justify-between gap-2 px-3 py-1.5 font-mono text-xs",
            row.ahead === null && "bg-white/10 font-bold",
          )}
        >
          <div className="flex min-w-0 items-center gap-2">
            <span className="w-5 shrink-0 text-white/45">P{row.position}</span>
            <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: row.color }} />
            <span className="truncate">{row.driver}</span>
          </div>
          <span className={cn("shrink-0 tabular-nums", row.ahead === null ? "text-white/45" : row.ahead ? "text-cyan-200" : "text-white/70")}>
            {row.gap_to_player_str}
          </span>
        </div>
      ))}
    </div>
  )
}
```

- [x] **Step 4: Отрендерить оба виджета**

В `InGameOverlay`, после блока `{showHud && <Frame id="strategy" ...>}` (перед
`{showRadio && (`) добавить:

```tsx
      {showHud && overlay && overlay.radar.length > 0 && (
        <Frame id="radar" title="RADAR" editMode={editMode} position={layout.radar} onMove={moveWidget} className="w-[180px]">
          <RadarWidget contacts={overlay.radar} />
        </Frame>
      )}

      {showHud && overlay && overlay.relative.length > 0 && (
        <Frame id="relative" title="RELATIVE" editMode={editMode} position={layout.relative} onMove={moveWidget} className="w-[240px]">
          <RelativeWidget rows={overlay.relative} />
        </Frame>
      )}
```

- [x] **Step 5: Типы и сборка**

Run (из `NewSpotterUI/`): `pnpm exec tsc --noEmit`
Expected: без ошибок.

Run: `pnpm build`
Expected: успешно, статический экспорт обновлён (`NewSpotterUI/out/overlay.html`
и т.д.).

- [x] **Step 6: Визуальная проверка в браузере**

Открыть собранный `NewSpotterUI/out/overlay.html?preview=1` (или через
`preview_start`/Browser pane) на 1920×1080 — оба новых виджета должны быть
видны, не перекрывать существующие 4, точки радара — по сторонам от
центральной красной, строка игрока в Relative — подсвечена.

---

### Task 8: Синхронизация production-сборки + полная верификация

**Files:**
- Copy: `NewSpotterUI/out/*` → `webui/*` (тот же процесс, что в предыдущих
  UI-сессиях, см. `CODEX_CLAUDE_HANDOFF.md`)

- [x] **Step 1: Полный backend-прогон**

Run: `py -3.12 -u -m pytest -q`
Expected: зелёный, тот же 1 skip, только уже известные YandexSpeech warnings
(без новых failures/errors).

- [x] **Step 2: Синхронизировать статический экспорт в `webui/`**

Скопировать содержимое `NewSpotterUI/out/` в `webui/` (полная замена,
как в предыдущих UI-сессиях — см. `CODEX_CLAUDE_HANDOFF.md`, "SHA-256 diff = 0"
как критерий успеха).

- [x] **Step 3: Живая проверка пользователем**

Запустить `py -3.12 app.pyw`, в игре (F1 25, borderless/windowed) проверить:
- Radar показывает машины слева/справа на реалистичной дистанции,
  визуально совпадает с миникартой игры (калибровка `RADAR_WINDOW_M`).
- Relative показывает читаемый список с правильным отрывом, строка игрока
  выделена.
- Оба виджета можно перетащить в режиме редактора (`Ctrl+Alt+O`), позиция
  сохраняется между перезапусками (тот же `localStorage`, что у остальных
  виджетов).

- [x] **Step 4: Обновить `CONTEXT.md`**

Добавить короткую запись в раздел «На чём остановились» (по образцу
соседних записей 2026-07-21) — Radar + Relative добавлены в in-game HUD,
данные переиспользуют уже существующие `_spotter_tick`/`gaps_front`, iRacing
пока не поддерживается (нет мировых координат/дельт в текущей телеметрии).

---

## Самопроверка плана

- **Покрытие спеки:** п.1 (Radar-проход) → Task 4; п.2 (gap_front_ms в grid) →
  Task 3; п.3 (полный grid в overlay()) → Task 2; п.4 (`_relative_rows`/поля
  ответа) → Task 1; п.5 (типы API) → Task 6; п.6 (виджеты) → Task 7; п.7
  (iRacing-ограничение) — не требует кода, зафиксировано в Task 8 Step 4 и
  описано в спеке.
- **Плейсхолдеров нет** — везде полный код, конкретные пути и строки.
- **Согласованность типов:** `radar`/`relative` — одинаковые имена полей и
  формы данных во всех слоях (Python-снапшот → `OverlayTelemetry` →
  `build_overlay_state` → TypeScript `OverlayState` → компоненты).
