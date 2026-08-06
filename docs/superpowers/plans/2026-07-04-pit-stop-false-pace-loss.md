# Pit-Stop False Pace-Loss Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the commentator from narrating a pit stop's inherently long lap time and growing gap-to-leader as genuine on-track pace loss.

**Architecture:** Parse the previously-unread `m_pitStatus` telemetry byte, accumulate a per-lap "was pitting observed at any point during this lap" flag in `core/engine.py`, and thread it into the three places that build pace/gap narratives from raw lap-time and gap deltas: `commentator/timeline.py` (ambient commentary — suppress misleading trend lines, add an explicit pit-stop phase tag), `core/coach_ai` (skip feeding pit-affected laps into the coach entirely), and `core/f1_benchmark.py::race_weak_sector()` (filter pit-affected laps from the sector-gap average). `core/career_memory.py` needs no change — its `min()`-based selection is already structurally immune.

**Tech Stack:** Python 3.12, standard library, pytest.

> ⚠️ **Репозиторий НЕ под git** (`Is a git repository: false`). Шаги «Commit» заменены на **Checkpoint** — прогон тестов задачи. Команды тестов: `py -3.12 -m pytest ... -q`.

**Спека:** [`docs/superpowers/specs/2026-07-04-pit-stop-false-pace-loss-design.md`](../specs/2026-07-04-pit-stop-false-pace-loss-design.md).

---

## Файловая структура

| Файл | Действие | Ответственность |
|------|----------|-----------------|
| `core/packets.py` | изменить | `parse_player_lap()` — добавить `pit_status` |
| `diag_lap_offsets.py` | изменить | вывести байт 34 живьём для верификации оффсета |
| `core/session_recorder.py` | изменить | `on_lap_complete(pit_lap=...)` |
| `core/engine.py` | изменить | накопление флага пит-круга, проводка в recorder/driver_coach/timeline |
| `core/f1_benchmark.py` | изменить | `race_weak_sector()` игнорирует пит-круги |
| `commentator/timeline.py` | изменить | `pit_status`/`pit_lap` в снимке, подавление тренда/отрывов, фаза-тэг |
| `tests/test_packets_gaps_tyre.py` | изменить | +тест `pit_status` |
| `tests/test_session_recorder_laps.py` | изменить | обновить ожидаемый словарь + новый тест `pit_lap` |
| `tests/test_engine_pit_tracking.py` | создать | |
| `tests/test_f1_benchmark.py` | изменить | +тест игнорирования пит-круга в `race_weak_sector` |
| `tests/test_timeline.py` | изменить | +тесты pit_status/pit_lap |

---

## Task 1: `core/packets.py` — парсинг `pit_status`

**Files:**
- Modify: `core/packets.py`
- Modify: `diag_lap_offsets.py`
- Modify: `tests/test_packets_gaps_tyre.py`

- [ ] **Step 1: Write the failing test**

Добавить в конец `tests/test_packets_gaps_tyre.py`:

```python
@pytest.mark.parametrize("raw, expected", [(0, 0), (1, 1), (2, 2)])
def test_parse_player_lap_pit_status(raw, expected):
    buf = _buf(HEADER_SIZE + LAP_DATA_SIZE)
    base = HEADER_SIZE
    buf[base + 32] = 3          # позиция (непустой пакет)
    buf[base + 33] = 5          # текущий круг
    buf[base + 34] = raw        # m_pitStatus
    out = packets.parse_player_lap(buf, 0)
    assert out["pit_status"] == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_packets_gaps_tyre.py -q`
Expected: FAIL — `KeyError: 'pit_status'`

- [ ] **Step 3: Implement**

В `core/packets.py`, найти в `parse_player_lap()` возвращаемый словарь:

```python
    return {
        "position": data[base + 32],
        "current_lap": data[base + 33],
        "last_lap_ms": last_lap_ms,
        "s1_ms": s1_ms,
        "s2_ms": s2_ms,
        "s3_ms": s3_ms,
        # отрывы (мс): к машине впереди (@14/16) и к лидеру гонки (@17/19)
        "gap_front_ms": _lap_delta_ms(data, base, 14, 16),
        "gap_leader_ms": _lap_delta_ms(data, base, 17, 19),
        "lap_distance_m": lap_distance_m,
    }
```

Заменить на:

```python
    return {
        "position": data[base + 32],
        "current_lap": data[base + 33],
        # m_pitStatus @34: 0=нет, 1=заезжает в пит-лейн, 2=в зоне пит-лейн
        # (сразу после m_carPosition@32/m_currentLapNum@33 — F1 25 LapData спека).
        "pit_status": data[base + 34],
        "last_lap_ms": last_lap_ms,
        "s1_ms": s1_ms,
        "s2_ms": s2_ms,
        "s3_ms": s3_ms,
        # отрывы (мс): к машине впереди (@14/16) и к лидеру гонки (@17/19)
        "gap_front_ms": _lap_delta_ms(data, base, 14, 16),
        "gap_leader_ms": _lap_delta_ms(data, base, 17, 19),
        "lap_distance_m": lap_distance_m,
    }
```

**Важно:** `base + 34` уже меньше проверяемой длины пакета (`if base + 34 > len(data): return {}` в начале функции гарантирует, что байт 34 доступен — граница проверки та же, что уже использовалась для `position`/`current_lap`, менять не нужно).

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_packets_gaps_tyre.py -q`
Expected: PASS (все тесты файла, включая 3 новых параметризованных)

- [ ] **Step 5: Верификация живьём (диагностика оффсета)**

В `diag_lap_offsets.py`, найти:

```python
    print(f"\nlast_lap_ms={last_ms} ({last_ms/1000:.3f}s)  lap={data[base+33]}")
```

Заменить на:

```python
    print(f"\nlast_lap_ms={last_ms} ({last_ms/1000:.3f}s)  lap={data[base+33]}"
         f"  pit_status={data[base+34]}")
```

Это не тестируется автоматически (файл — ручной диагностический скрипт для живого прогона игры, как и остальной файл), но следует уже установленной в этом файле практике сверки оффсетов с реальной телеметрией перед тем, как полагаться на них.

- [ ] **Step 6: Checkpoint** — тесты задачи зелёные.

---

## Task 2: `core/session_recorder.py` — поле `pit_lap`

**Files:**
- Modify: `core/session_recorder.py`
- Modify: `tests/test_session_recorder_laps.py`

- [ ] **Step 1: Update the existing test (it will break otherwise) + add a new one**

Заменить весь файл `tests/test_session_recorder_laps.py`:

```python
from core.session_recorder import SessionRecorder


def test_laps_accessor_returns_copy():
    r = SessionRecorder()
    r.on_lap_complete(1, 95000, 30000, 33000, 32000)
    laps = r.laps()
    assert laps == [{"lap": 1, "last_lap_ms": 95000,
                     "s1_ms": 30000, "s2_ms": 33000, "s3_ms": 32000,
                     "pit_lap": False}]
    laps.append({"x": 1})            # мутация копии не трогает внутренний список
    assert len(r.laps()) == 1


def test_on_lap_complete_records_pit_lap_flag():
    r = SessionRecorder()
    r.on_lap_complete(1, 95000, 30000, 33000, 32000, pit_lap=True)
    assert r.laps()[0]["pit_lap"] is True
```

**Важно:** первый тест уже существовал и проверял точное равенство словаря — добавление
поля `pit_lap` в `on_lap_complete()` без обновления ЭТОГО теста сломает его (новый ключ
появится в реальном выводе, но не в ожидаемом словаре). Обновление теста — часть этой
задачи, не отдельный баг.

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_session_recorder_laps.py -q`
Expected: FAIL — первый тест: словари не совпадают (нет ключа `pit_lap` в реальном выводе);
второй тест: `TypeError: on_lap_complete() got an unexpected keyword argument 'pit_lap'`

- [ ] **Step 3: Implement**

В `core/session_recorder.py`, найти:

```python
    def on_lap_complete(self, lap_num: int, last_lap_ms: int,
                        s1_ms: int, s2_ms: int, s3_ms: int) -> None:
        self._laps.append({"lap": lap_num, "last_lap_ms": last_lap_ms,
                           "s1_ms": s1_ms, "s2_ms": s2_ms, "s3_ms": s3_ms})
```

Заменить на:

```python
    def on_lap_complete(self, lap_num: int, last_lap_ms: int,
                        s1_ms: int, s2_ms: int, s3_ms: int,
                        pit_lap: bool = False) -> None:
        self._laps.append({"lap": lap_num, "last_lap_ms": last_lap_ms,
                           "s1_ms": s1_ms, "s2_ms": s2_ms, "s3_ms": s3_ms,
                           "pit_lap": pit_lap})
```

`pit_lap` — было ли пит-событие (`pit_status != 0`) в любой момент этого круга (не
только в конце) — истинность решается на стороне вызывающего кода (`core/engine.py`,
Task 3), эта функция просто хранит переданное значение. Дефолт `False` сохраняет
обратную совместимость позиционных вызовов без пятого аргумента.

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_session_recorder_laps.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Checkpoint** — тесты задачи зелёные.

---

## Task 3: `core/engine.py` — накопление флага пит-круга

**Files:**
- Modify: `core/engine.py`
- Test: `tests/test_engine_pit_tracking.py` (новый)

- [ ] **Step 1: Write the failing tests**

Реальный метод, обрабатывающий один UDP-пакет — `_update_telemetry(self, header: dict,
packet_id: int, data: bytes)` (НЕ `_process_packet` — этого метода не существует).
`PACKET_LAP_DATA = 2` (константа в `core.packets`). Тесты используют `position=0` в
буфере намеренно — это заставляет `any(v > 0 for v in positions.values())` внутри
`_update_telemetry` быть `False`, пропуская построение grid/`rival_tracker.update()`
(не нужны для этих тестов и требуют отдельной инициализации `race_state`).

```python
# tests/test_engine_pit_tracking.py
import struct

import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.packets import HEADER_SIZE, LAP_DATA_SIZE, PACKET_LAP_DATA


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _lap_buf(*, current_lap=5, pit_status=0, last_lap_ms=0):
    """Минимальный однокруговой LapData-буфер. position=0 намеренно — см. коммент
    перед этим блоком (пропускаем grid/rival_tracker, не нужные для этих тестов)."""
    buf = bytearray(HEADER_SIZE + LAP_DATA_SIZE)
    base = HEADER_SIZE
    struct.pack_into("<I", buf, base + 0, last_lap_ms)
    buf[base + 33] = current_lap
    buf[base + 34] = pit_status
    return bytes(buf)


def test_current_lap_pit_accumulates_and_live_status_tracked(engine):
    engine._player_car_index = 0
    engine._prev_lap = 5          # совпадает с current_lap ниже -> круг НЕ завершается
    engine._current_lap_pit = False
    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(current_lap=5, pit_status=0))
    assert engine._current_lap_pit is False
    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(current_lap=5, pit_status=1))
    assert engine._current_lap_pit is True
    assert engine._player_pit_status == 1
    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(current_lap=5, pit_status=0))
    assert engine._current_lap_pit is True   # не сбрасывается тиком без pit_status
    assert engine._player_pit_status == 0    # но живой статус обновился


def test_lap_complete_passes_pit_lap_to_recorder_and_skips_coach(engine):
    engine._player_car_index = 0
    engine._prev_lap = 4
    engine._current_lap_pit = True
    engine.recorder.reset()

    calls = []
    class _StubCoach:
        def add_lap(self, **kw):
            calls.append(kw)
        def get_state(self):
            return {}   # _maybe_snapshot() зовёт это безусловно — стаб должен его иметь
    engine.driver_coach = _StubCoach()

    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(current_lap=5, pit_status=0, last_lap_ms=125000))

    laps = engine.recorder.laps()
    assert len(laps) == 1 and laps[0]["pit_lap"] is True
    assert engine._current_lap_pit is False        # сброшен для следующего круга
    assert engine._last_completed_lap_was_pit is True
    assert calls == []                             # driver_coach пропущен для пит-круга


def test_driver_coach_called_for_normal_lap(engine):
    engine._player_car_index = 0
    engine._prev_lap = 4
    engine._current_lap_pit = False
    engine.recorder.reset()

    calls = []
    class _StubCoach:
        def add_lap(self, **kw):
            calls.append(kw)
        def get_state(self):
            return {}
    engine.driver_coach = _StubCoach()

    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(current_lap=5, pit_status=0, last_lap_ms=91000))

    assert len(calls) == 1
    assert engine.recorder.laps()[-1]["pit_lap"] is False


def test_snapshot_receives_pit_status_and_pit_lap(engine):
    engine._player_car_index = 0
    engine._last_snap_t = 0.0    # снять троттлинг _maybe_snapshot()
    engine._prev_lap = 4
    engine._current_lap_pit = True
    engine.recorder.reset()
    engine.driver_coach = type("_StubCoach", (), {
        "add_lap": lambda self, **kw: None,
        "get_state": lambda self: {},   # _maybe_snapshot() зовёт это безусловно
    })()

    engine._update_telemetry({"player_car_index": 0}, PACKET_LAP_DATA,
                             _lap_buf(current_lap=5, pit_status=0, last_lap_ms=125000))

    snap = engine.timeline._snapshots[-1]
    assert snap.get("pit_lap") is True    # ретроспективно — только что завершённый круг был пит-кругом
    assert snap.get("pit_status") == 0    # живой статус — уже выехали из боксов
```

**Важно про SSTA-сброс (Step 6 ниже):** в этой кодовой базе нет прецедента тестировать
сброс состояния через синтетический байтовый SSTA-пакет — даже уже существующие сбросы
`f1_benchmark`/`career_memory` на SSTA (см. `core/engine.py`) проверялись при код-ревью
чтением диффа, не юнит-тестом через `_update_telemetry`. Не изобретай такой тест здесь —
корректность двух новых строк в Step 6 проверяется тем же способом (ревьюер читает код,
убеждается что новые поля сброшены рядом с уже существующим `self._prev_lap = 0`).

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_engine_pit_tracking.py -q`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute '_current_lap_pit'`

- [ ] **Step 3: Init state**

Найти:

```python
        self._lap_distance_m: float | None = None
        self._game_year: int = 0
        self._prev_lap: int = 0
```

Заменить на:

```python
        self._lap_distance_m: float | None = None
        self._game_year: int = 0
        self._prev_lap: int = 0
        # Пит-стоп: накопление ИЛИ по тикам одного круга (см. design spec §2 —
        # 'pit_status' живой на момент тика, но круг мог включать заезд в боксы
        # ЗАДОЛГО до пересечения финишной черты, когда pit_status уже снова 0).
        self._current_lap_pit: bool = False
        self._last_completed_lap_was_pit: bool = False
```

Найти (в блоке "Отрывы (мс) и состояние шин игрока для timeline", чуть ниже):

```python
        self._player_gap_leader: int | None = None
        self._player_gap_front: int | None = None
        self._player_gap_behind: int | None = None
        self._player_tyre_compound: str | None = None
```

Заменить на:

```python
        self._player_gap_leader: int | None = None
        self._player_gap_front: int | None = None
        self._player_gap_behind: int | None = None
        self._player_pit_status: int | None = None
        self._player_tyre_compound: str | None = None
```

- [ ] **Step 4: Live pit_status tracking + lap-completion wiring**

Найти:

```python
                # Отрывы: к машине впереди и к лидеру — из пакета игрока;
                # к машине сзади — gap_front той машины, что на позицию ниже.
                self._player_gap_front = pl.get("gap_front_ms")
                self._player_gap_leader = pl.get("gap_leader_ms")
```

Заменить на:

```python
                # Отрывы: к машине впереди и к лидеру — из пакета игрока;
                # к машине сзади — gap_front той машины, что на позицию ниже.
                self._player_gap_front = pl.get("gap_front_ms")
                self._player_gap_leader = pl.get("gap_leader_ms")
                self._player_pit_status = pl.get("pit_status")
                if pl.get("pit_status"):
                    self._current_lap_pit = True
```

Найти:

```python
                    if cur > self._prev_lap and self._prev_lap > 0 and lms > 0:
                        self.recorder.on_lap_complete(
                            lap_num=self._prev_lap,
                            last_lap_ms=lms,
                            s1_ms=pl.get("s1_ms", 0),
                            s2_ms=pl.get("s2_ms", 0),
                            s3_ms=pl.get("s3_ms", 0),
                        )
                        self.driver_coach.add_lap(
                            lap_number=self._prev_lap,
                            lap_time_ms=lms,
                            s1_ms=pl.get("s1_ms", 0),
                            s2_ms=pl.get("s2_ms", 0),
                            s3_ms=pl.get("s3_ms", 0),
                            tyre_compound=self._player_tyre_compound,
                            tyre_age=self._player_tyre_age,
                            tyre_wear=self._player_tyre_wear,
                        )
                        self._update_f1_benchmark()
                        self._update_career_memory()
                    if cur > 0:
                        self._prev_lap = cur
```

Заменить на:

```python
                    if cur > self._prev_lap and self._prev_lap > 0 and lms > 0:
                        lap_was_pit = self._current_lap_pit
                        self.recorder.on_lap_complete(
                            lap_num=self._prev_lap,
                            last_lap_ms=lms,
                            s1_ms=pl.get("s1_ms", 0),
                            s2_ms=pl.get("s2_ms", 0),
                            s3_ms=pl.get("s3_ms", 0),
                            pit_lap=lap_was_pit,
                        )
                        # Пит-круг искажает consistency/pace_delta/tyre_advice/
                        # weak_sector (все построены на дельтах СМЕЖНЫХ кругов
                        # или скользящем среднем) — не кормим coach вообще, а не
                        # патчим internal-логику analyzer.py под этот edge case.
                        if not lap_was_pit:
                            self.driver_coach.add_lap(
                                lap_number=self._prev_lap,
                                lap_time_ms=lms,
                                s1_ms=pl.get("s1_ms", 0),
                                s2_ms=pl.get("s2_ms", 0),
                                s3_ms=pl.get("s3_ms", 0),
                                tyre_compound=self._player_tyre_compound,
                                tyre_age=self._player_tyre_age,
                                tyre_wear=self._player_tyre_wear,
                            )
                        self._last_completed_lap_was_pit = lap_was_pit
                        self._current_lap_pit = False
                        self._update_f1_benchmark()
                        self._update_career_memory()
                    if cur > 0:
                        self._prev_lap = cur
```

- [ ] **Step 5: `_maybe_snapshot()` передаёт pit_status/pit_lap в timeline**

Найти:

```python
            self.timeline.record_snapshot(
                lap=self._player_lap, position=self._player_pos,
                leader=self._leader_name, grid=grid,
                last_lap_ms=self._player_pace_ms, fuel=self._player_fuel,
                total_laps=getattr(self, "_total_laps", None),
                gap_leader_ms=self._player_gap_leader,
                gap_front_ms=self._player_gap_front,
                gap_behind_ms=self._player_gap_behind,
                tyre_compound=self._player_tyre_compound,
                tyre_age=self._player_tyre_age,
                tyre_wear=self._player_tyre_wear,
                session_type=self._session_type)
```

Заменить на:

```python
            self.timeline.record_snapshot(
                lap=self._player_lap, position=self._player_pos,
                leader=self._leader_name, grid=grid,
                last_lap_ms=self._player_pace_ms, fuel=self._player_fuel,
                total_laps=getattr(self, "_total_laps", None),
                gap_leader_ms=self._player_gap_leader,
                gap_front_ms=self._player_gap_front,
                gap_behind_ms=self._player_gap_behind,
                tyre_compound=self._player_tyre_compound,
                tyre_age=self._player_tyre_age,
                tyre_wear=self._player_tyre_wear,
                session_type=self._session_type,
                pit_status=getattr(self, "_player_pit_status", None),
                pit_lap=self._last_completed_lap_was_pit)
```

- [ ] **Step 6: Сброс на SSTA**

Найти:

```python
                self._session_events = []
                self._prev_lap = 0
                self.story_collector.reset()
```

Заменить на:

```python
                self._session_events = []
                self._prev_lap = 0
                self._current_lap_pit = False
                self._last_completed_lap_was_pit = False
                self.story_collector.reset()
```

- [ ] **Step 7: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_engine_pit_tracking.py -q`
Expected: PASS (4 passed)

- [ ] **Step 8: Regression check**

Run: `py -3.12 -m pytest tests/test_engine_f1_benchmark.py tests/test_engine_career_memory.py tests/test_engine_story.py tests/test_packets_gaps_tyre.py -q`
Expected: PASS, без изменений в счёте.

- [ ] **Step 9: Checkpoint** — тесты задачи и регрессии зелёные.

---

## Task 4: `core/f1_benchmark.py` — `race_weak_sector()` игнорирует пит-круги

**Files:**
- Modify: `core/f1_benchmark.py`
- Modify: `tests/test_f1_benchmark.py`

- [ ] **Step 1: Write the failing test**

Добавить в `tests/test_f1_benchmark.py` рядом с существующими тестами `race_weak_sector`:

```python
def test_race_weak_sector_ignores_pit_laps():
    """Пит-круг с огромным (искажённым) гэпом не должен ложно назначить сектор
    слабым — он исключается из усреднения целиком."""
    openf1 = _OpenF1(sectors={1: 27000, 2: 38000, 3: 26000})
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=openf1)
    b.load(11, 2025)
    laps = [
        {"s1_ms": 27100, "s2_ms": 38100, "s3_ms": 26050},                  # обычный круг, s1 гэп +100 (наибольший из "чистых")
        {"s1_ms": 27050, "s2_ms": 38900, "s3_ms": 91000, "pit_lap": True}, # пит-круг: искажённый s3, огромный гэп
    ]
    # Без исключения пит-круга s3 дал бы гэп +65000 и "выиграл" бы как самый слабый —
    # с исключением побеждает s1 (+100 среди оставшегося одного чистого круга).
    assert b.race_weak_sector(laps) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_f1_benchmark.py -q`
Expected: FAIL — без фильтра пит-круг участвует в усреднении, S3 побеждает
(`assert 3 == 1` fails)

- [ ] **Step 3: Implement**

Найти в `core/f1_benchmark.py`:

```python
    def race_weak_sector(self, player_laps: list[dict]) -> int | None:
        """Сектор с наибольшим СРЕДНИМ гэпом к эталону среди кругов гонки (для
        Post-Race Story: weak_sector_vs_f1 — НЕ то же самое, что coach_ai.weak_sector,
        который про собственный темп игрока, а не про реальный F1). None — эталонных
        секторов нет ИЛИ ни один круг не дал валидных s1/s2/s3.
        При равенстве средних гэпов между секторами возвращается сектор с наименьшим
        номером (детерминированно — первый максимум в порядке 1→2→3)."""
        ref_sectors = (self.reference or {}).get("sector_ms")
        if not ref_sectors:
            return None
        totals = {1: 0, 2: 0, 3: 0}
        counts = {1: 0, 2: 0, 3: 0}
        for lap in player_laps:
            for n in (1, 2, 3):
                v = lap.get(f"s{n}_ms")
                if v:
                    totals[n] += v - ref_sectors[n]
                    counts[n] += 1
```

Заменить на:

```python
    def race_weak_sector(self, player_laps: list[dict]) -> int | None:
        """Сектор с наибольшим СРЕДНИМ гэпом к эталону среди кругов гонки (для
        Post-Race Story: weak_sector_vs_f1 — НЕ то же самое, что coach_ai.weak_sector,
        который про собственный темп игрока, а не про реальный F1). None — эталонных
        секторов нет ИЛИ ни один круг не дал валидных s1/s2/s3.
        Пит-круги (pit_lap=True) исключаются из усреднения — их секторные времена
        искажены пит-лейном, а не отражают реальный темп на трассе.
        При равенстве средних гэпов между секторами возвращается сектор с наименьшим
        номером (детерминированно — первый максимум в порядке 1→2→3)."""
        ref_sectors = (self.reference or {}).get("sector_ms")
        if not ref_sectors:
            return None
        totals = {1: 0, 2: 0, 3: 0}
        counts = {1: 0, 2: 0, 3: 0}
        for lap in player_laps:
            if lap.get("pit_lap"):
                continue
            for n in (1, 2, 3):
                v = lap.get(f"s{n}_ms")
                if v:
                    totals[n] += v - ref_sectors[n]
                    counts[n] += 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_f1_benchmark.py -q`
Expected: PASS (все тесты файла, включая новый)

- [ ] **Step 5: Checkpoint** — тесты задачи зелёные.

---

## Task 5: `commentator/timeline.py` — подавление тренда/отрывов, фаза-тэг

**Files:**
- Modify: `commentator/timeline.py`
- Modify: `tests/test_timeline.py`

- [ ] **Step 1: Write the failing tests**

Добавить в конец `tests/test_timeline.py`:

```python
# --------------------------------------------------------------------------- #
# Секция ПИТ-СТОП (pit_status live + pit_lap ретроспективно)
# --------------------------------------------------------------------------- #

def test_pace_trend_suppressed_when_last_lap_was_pit():
    t = RaceTimeline()
    t.record_snapshot(lap=8, position=3, last_lap_ms=93000)
    t.record_snapshot(lap=9, position=4, last_lap_ms=125000, pit_lap=True)
    out = t.render()
    assert "ТЕМП: круг 2:05" in out    # голое время всё же есть (125000мс = 2:05.000)
    assert "замедляется" not in out
    assert "рушится" not in out
    assert "ускоряется" not in out


def test_pace_trend_suppressed_when_prev_lap_was_pit():
    """Сравнение НЕ должно случиться и в обратную сторону — после пит-круга
    следующий обычный круг не должен показать ложное 'резкое ускорение'."""
    t = RaceTimeline()
    t.record_snapshot(lap=9, position=4, last_lap_ms=125000, pit_lap=True)
    t.record_snapshot(lap=10, position=3, last_lap_ms=91000, pit_lap=False)
    out = t.render()
    assert "ускоряется" not in out
    assert "замедляется" not in out


def test_pace_trend_normal_when_neither_lap_was_pit():
    t = RaceTimeline()
    t.record_snapshot(lap=8, position=3, last_lap_ms=93000, pit_lap=False)
    t.record_snapshot(lap=9, position=4, last_lap_ms=92000, pit_lap=False)
    out = t.render()
    assert "ускоряется" in out


def test_gaps_section_hidden_while_pit_status_active():
    t = RaceTimeline()
    t.record_snapshot(lap=12, position=3, pit_status=1,
                      gap_leader_ms=15300, gap_front_ms=1800, gap_behind_ms=900)
    out = t.render()
    assert "ОТРЫВЫ:" not in out


def test_gaps_section_shown_when_not_pitting():
    t = RaceTimeline()
    t.record_snapshot(lap=12, position=3, pit_status=0,
                      gap_leader_ms=15300, gap_front_ms=1800, gap_behind_ms=900)
    out = t.render()
    assert "ОТРЫВЫ:" in out


def test_pit_stop_phase_line_appears_when_pitting():
    t = RaceTimeline()
    t.record_snapshot(lap=12, position=3, total_laps=58, pit_status=1)
    out = t.render()
    assert "ФАЗА: ПИТ-СТОП" in out


def test_pit_stop_phase_line_absent_when_not_pitting():
    t = RaceTimeline()
    t.record_snapshot(lap=12, position=3, total_laps=58, pit_status=0)
    out = t.render()
    assert "ПИТ-СТОП" not in out


def test_pit_stop_phase_line_coexists_with_lap_ratio_phase():
    """Поздний пит-стоп — остаётся 'концовкой' И отдельно помечается пит-стопом."""
    t = RaceTimeline()
    t.record_snapshot(lap=56, position=2, total_laps=58, pit_status=2)
    out = t.render()
    assert "концовка" in out
    assert "ФАЗА: ПИТ-СТОП" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_timeline.py -q`
Expected: FAIL — `TypeError: record_snapshot() got an unexpected keyword argument 'pit_lap'`

- [ ] **Step 3: `record_snapshot()` — новые параметры**

Найти:

```python
    def record_snapshot(self, *, lap: int | None, position: int | None,
                        leader: str | None = None, grid: list[dict] | None = None,
                        last_lap_ms: int | None = None, fuel=None,
                        total_laps: int | None = None,
                        gap_leader_ms: int | None = None,
                        gap_front_ms: int | None = None,
                        gap_behind_ms: int | None = None,
                        tyre_compound: str | None = None,
                        tyre_age: int | None = None,
                        tyre_wear: float | None = None,
                        session_type: str | None = None) -> None:
        """Снимок ситуации: позиция, соседи, темп, ОТРЫВЫ по времени (мс) и ШИНЫ
        (компаунд/возраст/износ). Соседи (имена) — из grid по позиции. Снимки
        дедуплицируются по кругу: тот же круг — обновляем последний, иначе новый."""
        ahead = behind = None
        if grid and position:
            by_pos = {g.get("position"): g.get("driver")
                      for g in grid if g.get("position")}
            ahead = by_pos.get(position - 1)
            behind = by_pos.get(position + 1)

        snap = {
            "lap": lap,
            "position": position,
            "leader": leader,
            "ahead": ahead,
            "behind": behind,
            "last_lap_ms": last_lap_ms,
            "fuel": fuel,
            "total_laps": total_laps,
            "gap_leader_ms": gap_leader_ms,
            "gap_front_ms": gap_front_ms,
            "gap_behind_ms": gap_behind_ms,
            "tyre_compound": tyre_compound,
            "tyre_age": tyre_age,
            "tyre_wear": tyre_wear,
            "session_type": session_type,
        }
```

Заменить на:

```python
    def record_snapshot(self, *, lap: int | None, position: int | None,
                        leader: str | None = None, grid: list[dict] | None = None,
                        last_lap_ms: int | None = None, fuel=None,
                        total_laps: int | None = None,
                        gap_leader_ms: int | None = None,
                        gap_front_ms: int | None = None,
                        gap_behind_ms: int | None = None,
                        tyre_compound: str | None = None,
                        tyre_age: int | None = None,
                        tyre_wear: float | None = None,
                        session_type: str | None = None,
                        pit_status: int | None = None,
                        pit_lap: bool | None = None) -> None:
        """Снимок ситуации: позиция, соседи, темп, ОТРЫВЫ по времени (мс) и ШИНЫ
        (компаунд/возраст/износ). Соседи (имена) — из grid по позиции. Снимки
        дедуплицируются по кругу: тот же круг — обновляем последний, иначе новый.

        pit_status — ЖИВОЙ статус на момент снимка (0/1/2); используется для
        подавления ОТРЫВОВ и фаза-тэга "ПИТ-СТОП" (эти значения искажены, только
        пока машина реально в боксах СЕЙЧАС).
        pit_lap — было ли пит-событие в ходе круга, чьё last_lap_ms несёт этот
        снимок (РЕТРОСПЕКТИВНО — круг мог завершиться уже после выезда из боксов,
        когда pit_status снова 0); используется для подавления ТЕМП-тренда."""
        ahead = behind = None
        if grid and position:
            by_pos = {g.get("position"): g.get("driver")
                      for g in grid if g.get("position")}
            ahead = by_pos.get(position - 1)
            behind = by_pos.get(position + 1)

        snap = {
            "lap": lap,
            "position": position,
            "leader": leader,
            "ahead": ahead,
            "behind": behind,
            "last_lap_ms": last_lap_ms,
            "fuel": fuel,
            "total_laps": total_laps,
            "gap_leader_ms": gap_leader_ms,
            "gap_front_ms": gap_front_ms,
            "gap_behind_ms": gap_behind_ms,
            "tyre_compound": tyre_compound,
            "tyre_age": tyre_age,
            "tyre_wear": tyre_wear,
            "session_type": session_type,
            "pit_status": pit_status,
            "pit_lap": pit_lap,
        }
```

- [ ] **Step 4: `_pace_trend()` — подавление на пит-кругах**

Найти:

```python
    def _pace_trend(self) -> str | None:
        """Тренд темпа по последним временам кругов: ускоряется/замедляется/ровно."""
        times = [s["last_lap_ms"] for s in self._snapshots
                 if s.get("last_lap_ms")]
        if len(times) < 2:
            return None
        prev, last = times[-2], times[-1]
        delta = last - prev
        sign = "+" if delta >= 0 else "−"
        tag = "замедляется" if delta > 250 else ("ускоряется" if delta < -250 else "ровно")
        return f"{tag} ({sign}{abs(delta) / 1000:.1f}с к прошлому кругу)"
```

Заменить на:

```python
    def _pace_trend(self) -> str | None:
        """Тренд темпа по последним временам кругов: ускоряется/замедляется/ровно.
        None, если хотя бы один из двух сравниваемых кругов был пит-кругом —
        искажённое пит-стопом время не показатель темпа на трассе (ни в форме
        'замедлился', ни в форме ложного 'резко ускорился' сразу после боксов)."""
        entries = [(s["last_lap_ms"], s.get("pit_lap", False))
                  for s in self._snapshots if s.get("last_lap_ms")]
        if len(entries) < 2:
            return None
        (prev, prev_pit), (last, last_pit) = entries[-2], entries[-1]
        if prev_pit or last_pit:
            return None
        delta = last - prev
        sign = "+" if delta >= 0 else "−"
        tag = "замедляется" if delta > 250 else ("ускоряется" if delta < -250 else "ровно")
        return f"{tag} ({sign}{abs(delta) / 1000:.1f}с к прошлому кругу)"
```

- [ ] **Step 5: `render()` — подавление ОТРЫВОВ + фаза-тэг**

Найти:

```python
        elif lap and total and total > 0:
            ratio = lap / total
            if ratio <= 0.15:
                phase = "старт гонки"
            elif ratio <= 0.50:
                phase = "середина гонки"
            elif ratio <= 0.85:
                phase = "финальные круги"
            else:
                phase = "концовка, последние круги"
            lines.append(f"ФАЗА: {phase} ({lap}/{total}).")

        neigh: list[str] = []
```

Заменить на:

```python
        elif lap and total and total > 0:
            ratio = lap / total
            if ratio <= 0.15:
                phase = "старт гонки"
            elif ratio <= 0.50:
                phase = "середина гонки"
            elif ratio <= 0.85:
                phase = "финальные круги"
            else:
                phase = "концовка, последние круги"
            lines.append(f"ФАЗА: {phase} ({lap}/{total}).")

        # Пит-стоп — отдельная строка, НЕ замена лап-based фазы выше (поздний
        # пит-стоп остаётся одновременно и "концовкой", и "пит-стопом").
        if cur.get("pit_status"):
            lines.append("ФАЗА: ПИТ-СТОП — трасса не в счёт, не считай это потерей темпа.")

        neigh: list[str] = []
```

Найти:

```python
        # --- Отрывы по времени ---
        pos = cur.get("position")
        gaps: list[str] = []
        gl = _fmt_gap(cur.get("gap_leader_ms"))
        if gl and pos and pos > 1:
            gaps.append(f"до лидера +{gl}")
        gf = _fmt_gap(cur.get("gap_front_ms"))
        if gf:
            ftrend = self._gap_front_trend()
            gaps.append(f"до машины впереди +{gf}" + (f" ({ftrend})" if ftrend else ""))
        gb = _fmt_gap(cur.get("gap_behind_ms"))
        if gb:
            gaps.append(f"сзади в {gb}")
        if gaps:
            lines.append("ОТРЫВЫ: " + ", ".join(gaps) + ".")
```

Заменить на:

```python
        # --- Отрывы по времени (подавляем во время пит-стопа — отрыв искусственно
        # растёт, пока машина стоит в боксах, это не потеря темпа на трассе) ---
        if not cur.get("pit_status"):
            pos = cur.get("position")
            gaps: list[str] = []
            gl = _fmt_gap(cur.get("gap_leader_ms"))
            if gl and pos and pos > 1:
                gaps.append(f"до лидера +{gl}")
            gf = _fmt_gap(cur.get("gap_front_ms"))
            if gf:
                ftrend = self._gap_front_trend()
                gaps.append(f"до машины впереди +{gf}" + (f" ({ftrend})" if ftrend else ""))
            gb = _fmt_gap(cur.get("gap_behind_ms"))
            if gb:
                gaps.append(f"сзади в {gb}")
            if gaps:
                lines.append("ОТРЫВЫ: " + ", ".join(gaps) + ".")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_timeline.py -q`
Expected: PASS (все тесты файла, включая 8 новых)

- [ ] **Step 7: Checkpoint** — тесты задачи зелёные.

---

## Task 6: Полная верификация + CONTEXT.md

**Files:**
- Modify: `CONTEXT.md`

- [ ] **Step 1: Полный прогон тестов**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: все тесты проходят (бейслайн 756 passed + 1 skipped перед этой фичей; плюс
новые тесты из Tasks 1-5: 3 packets + 1 session_recorder (файл идёт с 1 теста на 2,
т.е. +1 новый) + 4 engine_pit_tracking + 1 f1_benchmark + 8 timeline = +17, итого 773
passed + 1 skipped). Если итоговая строка не пропечаталась — считать через
`grep -o '[.sF]' <лог> | sort | uniq -c`.

- [ ] **Step 2: Import smoke test**

Run: `py -3.12 -c "import core.engine, core.packets, core.session_recorder, core.f1_benchmark, commentator.timeline"`
Expected: без ошибок

- [ ] **Step 3: Обновить CONTEXT.md**

Прочитать текущий `CONTEXT.md` целиком (следовать существующей структуре и
конвенции ~100-пунктового лимита + архивации старейшей из последних трёх сессий,
как уже установлено). Добавить запись новой сессии: что сделано (5 задач — packets,
session_recorder, engine, f1_benchmark, timeline), новый тест-бейслайн, явно
зафиксировать:
- `pit_status` (живой, из телеметрии) vs `pit_lap` (ретроспективный, накопленный
  ИЛИ по кругу) — РАЗНЫЕ механизмы для РАЗНЫХ типов данных (живые отрывы vs
  завершённые времена кругов), не путать одно с другим при будущих правках.
- `core/coach_ai/analyzer.py` НЕ изменялся — пит-круги просто не попадают в
  `driver_coach.add_lap()` вообще (пропуск на уровне вызова в engine.py).
- `core/career_memory.py` НЕ изменялся — `min()`-отбор структурно иммунен,
  явно проверено и задокументировано, а не молча пропущено.
- Новое поле `pit_lap` в архивных JSON сессий (`player_laps[].pit_lap`) — старые
  архивы без этого поля читаются как `pit_lap=False`/`None` (безопасный дефолт).

- [ ] **Step 4: Checkpoint** — полный прогон зелёный, CONTEXT.md обновлён.
