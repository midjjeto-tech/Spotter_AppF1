# Коуч пилотажа, фаза 2 (эталонный круг) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Научить коуча сравнивать текущий круг с эталонным по каждому повороту — точка торможения, минимальная скорость, момент газа, время — и говорить о том, что действительно техника, а не топливо.

**Architecture:** Метрики поворота копятся автоматом на тике внутри уже существующего `_coach_tick` (там уже разрешён поворот и есть вводы пилота). На завершении круга словарь метрик сравнивается с эталоном через нормализацию «сверх медианы по кругу», результат проходит то же правило повтора, что и фаза 1, и превращается в одну реплику. Эталон — карьерный лучший круг из архива сессий; отдельного хранилища нет.

**Tech Stack:** Python 3, pytest; фронт — Next.js static export в `NewSpotterUI/`, собирается в `webui/`.

**Спека:** `docs/superpowers/specs/2026-08-07-driving-coach-phase2-reference.md`

---

## Важно до начала

Проект под git, но коммиты в этом плане не предписаны — вместо них в конце каждой задачи прогон целевых тестов. Перед полным прогоном сверять `mtime` затронутых файлов: параллельная сессия сейчас переписывает `new_tts/piper_tts.py`, и три падения в `tests/test_voice_cast.py` к этой работе отношения не имеют.

Пороги значимости в Task 4 — предварительные, помечены в коде как некалиброванные, как и пороги фазы 1.

---

## Task 1: `current_lap_time_ms` из LapData

**Files:**
- Modify: `core/packets.py` (`parse_player_lap`)
- Test: `tests/test_packets_lap_time.py` (создать)

- [ ] **Step 1: Написать падающий тест**

```python
"""m_currentLapTimeInMS (LapData, офсет +4) — время текущего круга.

Нужно коучу для дельты по повороту: время на входе в зону и на выходе.
Соседние офсеты этой структуры уже подтверждены (m_lapDistance @20,
m_carPosition @32, m_currentLapNum @33), поэтому риск здесь несопоставим с
реконструированной раскладкой MotionEx.
"""
import struct

from core import packets
from core.packets import HEADER_SIZE, LAP_DATA_SIZE


def _lap_buf(cars: int = 22) -> bytearray:
    return bytearray(HEADER_SIZE + cars * LAP_DATA_SIZE)


def test_current_lap_time_parsed():
    buf = _lap_buf()
    struct.pack_into("<I", buf, HEADER_SIZE + 4, 34567)

    out = packets.parse_player_lap(bytes(buf), 0)

    assert out["current_lap_time_ms"] == 34567


def test_current_lap_time_read_at_correct_stride():
    buf = _lap_buf()
    struct.pack_into("<I", buf, HEADER_SIZE + LAP_DATA_SIZE + 4, 11111)

    out = packets.parse_player_lap(bytes(buf), 1)

    assert out["current_lap_time_ms"] == 11111


def test_absurd_current_lap_time_dropped():
    """Больше часа на круге — мусор из смещённого пакета, не время."""
    buf = _lap_buf()
    struct.pack_into("<I", buf, HEADER_SIZE + 4, 4_000_000)

    out = packets.parse_player_lap(bytes(buf), 0)

    assert "current_lap_time_ms" not in out
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `python -m pytest tests/test_packets_lap_time.py -q`
Expected: FAIL — `KeyError: 'current_lap_time_ms'`

- [ ] **Step 3: Реализовать**

В `parse_player_lap`, рядом с разбором `last_lap_ms`:

```python
    # m_currentLapTimeInMS @+4 (uint32) — время ТЕКУЩЕГО круга. Нужно коучу
    # для времени прохождения поворота (core/coach_ai/reference.py). Санити-
    # предел тот же по духу, что у скорости/передачи: час на круге означает
    # смещённый пакет, а не медленный круг.
    current_lap_time_ms = struct.unpack_from("<I", data, base + 4)[0]
    if 0 <= current_lap_time_ms <= 3_600_000:
        result["current_lap_time_ms"] = current_lap_time_ms
```

(`result` в этой функции создаётся ниже — вставить присваивание после его создания, сохранив порядок остальных полей.)

- [ ] **Step 4: Прогнать тесты**

Run: `python -m pytest tests/test_packets_lap_time.py tests/test_packets_gaps_tyre.py -q`
Expected: PASS

---

## Task 2: Модели метрик и дельт

**Files:**
- Modify: `core/coach_ai/models.py`
- Test: покрывается тестами Task 3–4

- [ ] **Step 1: Добавить датаклассы**

```python
@dataclass
class CornerMetrics:
    """Как пилот проехал ОДИН поворот. Четыре числа, из которых собирается
    эталон: хранить сырую трассу телеметрии для этого не нужно."""
    corner_id: int
    brake_point_m: float | None      # где нажал тормоз
    min_speed_kmh: float | None      # скорость в самой медленной точке
    throttle_point_m: float | None   # где открыл газ после минимума
    duration_ms: int | None          # время прохождения зоны поворота

    def usable(self) -> bool:
        """Годится ли запись в эталон. Минимум и время есть у ЛЮБОГО
        проеханного поворота; торможение и газ бывают не во всех (пологие
        связки проходятся без тормоза) — их отсутствие не повод выбрасывать
        поворот целиком, такая метрика просто не сравнивается."""
        return self.min_speed_kmh is not None and (self.duration_ms or 0) > 0

    def to_dict(self) -> dict:
        return {
            "corner_id": self.corner_id, "brake_point_m": self.brake_point_m,
            "min_speed_kmh": self.min_speed_kmh,
            "throttle_point_m": self.throttle_point_m,
            "duration_ms": self.duration_ms,
        }

    @staticmethod
    def from_dict(raw: dict) -> "CornerMetrics":
        return CornerMetrics(
            corner_id=raw["corner_id"], brake_point_m=raw.get("brake_point_m"),
            min_speed_kmh=raw.get("min_speed_kmh"),
            throttle_point_m=raw.get("throttle_point_m"),
            duration_ms=raw.get("duration_ms"),
        )


@dataclass
class CornerDelta:
    """Отклонение одной метрики в одном повороте от эталона — уже
    нормализованное (см. §6 спеки).

    `raw` — сырая разница с эталоном, её показывает дебриф.
    `badness` — превышение сверх медианы по кругу, приведённое к «плохому»
    знаку: положительное всегда означает «здесь хуже эталона». Именно по нему
    решается, о чём говорить.
    """
    corner_id: int
    corner_name: str | None
    metric: str          # "duration" | "brake" | "min_speed" | "throttle"
    raw: float
    badness: float
```

- [ ] **Step 2: Проверить импорт**

Run: `python -c "from core.coach_ai.models import CornerMetrics, CornerDelta; print(CornerMetrics(3, None, 120.0, None, 4200).usable())"`
Expected: `True`

---

## Task 3: Захват метрик круга

**Files:**
- Create: `core/coach_ai/reference.py`
- Test: `tests/test_coach_reference.py` (создать)

- [ ] **Step 1: Написать падающий тест**

```python
"""Захват метрик поворота (core/coach_ai/reference.py)."""
import pytest

from core.coach_ai.reference import LapTracer


def _drive(tracer, samples):
    """samples: (corner_id, phase, dist_m, time_ms, brake, throttle, speed)."""
    for s in samples:
        tracer.tick(corner_id=s[0], phase=s[1], lap_distance_m=s[2],
                    lap_time_ms=s[3], brake_pct=s[4], throttle_pct=s[5],
                    speed_kmh=s[6])


def test_brake_point_is_first_sample_over_threshold():
    t = LapTracer()
    _drive(t, [
        (3, "braking", 100.0, 1000, 0.0, 100.0, 300),
        (3, "braking", 110.0, 1100, 60.0, 0.0, 290),   # тормоз здесь
        (3, "braking", 120.0, 1200, 90.0, 0.0, 250),
        (3, "apex",    130.0, 1400, 10.0, 0.0, 120),
        (3, "exit",    140.0, 1600, 0.0, 80.0, 150),
        (None, "straight", 200.0, 1800, 0.0, 100.0, 250),
    ])
    m = t.finish_lap()[3]
    assert m.brake_point_m == pytest.approx(110.0)


def test_min_speed_is_taken_inside_the_corner_body_only():
    """Скорость на подходе ещё падает — минимумом считается точка ВНУТРИ
    поворота, иначе эталон запомнил бы конец прямой."""
    t = LapTracer()
    _drive(t, [
        (3, "braking", 100.0, 1000, 90.0, 0.0, 90),    # ниже, но это подход
        (3, "entry",   120.0, 1200, 50.0, 0.0, 160),
        (3, "apex",    130.0, 1400, 0.0, 20.0, 120),
        (3, "exit",    140.0, 1600, 0.0, 80.0, 150),
        (None, "straight", 200.0, 1800, 0.0, 100.0, 250),
    ])
    assert t.finish_lap()[3].min_speed_kmh == pytest.approx(120)


def test_throttle_point_is_after_the_minimum_not_before():
    t = LapTracer()
    _drive(t, [
        (3, "braking", 100.0, 1000, 0.0, 90.0, 300),   # газ ДО поворота
        (3, "entry",   120.0, 1200, 80.0, 0.0, 160),
        (3, "apex",    130.0, 1400, 0.0, 10.0, 120),
        (3, "exit",    140.0, 1600, 0.0, 70.0, 150),   # настоящее открытие
        (None, "straight", 200.0, 1800, 0.0, 100.0, 250),
    ])
    assert t.finish_lap()[3].throttle_point_m == pytest.approx(140.0)


def test_duration_is_zone_exit_minus_entry():
    t = LapTracer()
    _drive(t, [
        (3, "braking", 100.0, 1000, 90.0, 0.0, 300),
        (3, "apex",    130.0, 1400, 0.0, 20.0, 120),
        (3, "exit",    140.0, 1700, 0.0, 80.0, 150),
        (None, "straight", 200.0, 1800, 0.0, 100.0, 250),
    ])
    assert t.finish_lap()[3].duration_ms == 700


def test_corner_without_speed_sample_is_dropped():
    t = LapTracer()
    _drive(t, [(3, "braking", 100.0, 1000, 90.0, 0.0, 300)])
    assert t.finish_lap() == {}


def test_flashback_drops_the_corner_in_progress():
    """Дистанция прыгнула назад — это флэшбек. Запись обрывка эталону вредна."""
    t = LapTracer()
    _drive(t, [
        (3, "braking", 100.0, 1000, 90.0, 0.0, 300),
        (3, "apex",    130.0, 1400, 0.0, 20.0, 120),
        (3, "apex",     40.0, 1500, 0.0, 20.0, 120),   # откат
        (None, "straight", 200.0, 1800, 0.0, 100.0, 250),
    ])
    assert t.finish_lap() == {}


def test_two_corners_recorded_separately():
    t = LapTracer()
    _drive(t, [
        (3, "braking", 100.0, 1000, 90.0, 0.0, 300),
        (3, "apex",    130.0, 1400, 0.0, 20.0, 120),
        (7, "braking", 300.0, 2000, 90.0, 0.0, 280),
        (7, "apex",    330.0, 2400, 0.0, 20.0, 100),
        (None, "straight", 400.0, 2600, 0.0, 100.0, 250),
    ])
    out = t.finish_lap()
    assert set(out) == {3, 7}
    assert out[7].min_speed_kmh == pytest.approx(100)


def test_finish_lap_closes_the_corner_still_in_progress():
    """Финишная черта внутри поворота — обычное дело на многих трассах."""
    t = LapTracer()
    _drive(t, [
        (3, "braking", 100.0, 1000, 90.0, 0.0, 300),
        (3, "apex",    130.0, 1400, 0.0, 20.0, 120),
    ])
    assert 3 in t.finish_lap()


def test_finish_lap_resets_state():
    t = LapTracer()
    _drive(t, [
        (3, "braking", 100.0, 1000, 90.0, 0.0, 300),
        (3, "apex",    130.0, 1400, 0.0, 20.0, 120),
    ])
    t.finish_lap()
    assert t.finish_lap() == {}
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `python -m pytest tests/test_coach_reference.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.coach_ai.reference'`

- [ ] **Step 3: Реализовать**

```python
"""
core/coach_ai/reference.py
===========================
Захват метрик поворота на тике. Один автомат на круг: пока машина внутри зоны
поворота, ведёт четыре числа; на выходе из зоны закрывает запись.

Хранить сырую трассу телеметрии не нужно — эталон это ~80 чисел на круг, и они
уезжают в файл сессии рядом с картой ошибок.
"""
from __future__ import annotations

from core.coach_ai.models import CornerMetrics

BRAKE_ON_PCT = 15.0        # ниже — это подтормаживание, не точка торможения
THROTTLE_ON_PCT = 40.0     # ниже — поддерживающий газ, не разгон
#: Откат дистанции больше этого = флэшбек или пересечение финиша, а не движение.
DISTANCE_REWIND_M = 5.0


class _Corner:
    __slots__ = ("corner_id", "entry_ms", "exit_ms", "brake_m", "min_speed",
                 "min_speed_m", "throttle_m")

    def __init__(self, corner_id: int, lap_time_ms: int) -> None:
        self.corner_id = corner_id
        self.entry_ms = lap_time_ms
        self.exit_ms = lap_time_ms
        self.brake_m: float | None = None
        self.min_speed: float | None = None
        self.min_speed_m: float | None = None
        self.throttle_m: float | None = None


class LapTracer:
    """Один экземпляр на сессию. `tick()` зовётся на каждом тике телеметрии,
    `finish_lap()` — на пересечении финишной черты."""

    def __init__(self) -> None:
        self._done: dict[int, CornerMetrics] = {}
        self._cur: _Corner | None = None
        self._last_distance_m: float | None = None

    def reset(self) -> None:
        self._done.clear()
        self._cur = None
        self._last_distance_m = None

    def tick(self, corner_id: int | None, phase: str, lap_distance_m: float,
             lap_time_ms: int, brake_pct: float, throttle_pct: float,
             speed_kmh: float | None) -> None:
        if self._rewound(lap_distance_m):
            # Флэшбек: поворот в работе описывает уже несуществующий проезд.
            self._cur = None
            self._last_distance_m = lap_distance_m
            return
        self._last_distance_m = lap_distance_m

        if corner_id is None:
            self._close()
            return
        if self._cur is None or self._cur.corner_id != corner_id:
            self._close()
            self._cur = _Corner(corner_id, lap_time_ms)

        cur = self._cur
        cur.exit_ms = lap_time_ms

        if cur.brake_m is None and brake_pct >= BRAKE_ON_PCT:
            cur.brake_m = lap_distance_m

        # Минимум ищем ВНУТРИ поворота: на подходе скорость ещё падает, и её
        # минимум был бы концом прямой, а не апексом.
        if phase != "braking" and speed_kmh is not None:
            if cur.min_speed is None or speed_kmh < cur.min_speed:
                cur.min_speed = speed_kmh
                cur.min_speed_m = lap_distance_m
                # Газ до минимума — это не разгон из поворота.
                cur.throttle_m = None

        if (cur.min_speed is not None and cur.throttle_m is None
                and throttle_pct >= THROTTLE_ON_PCT):
            cur.throttle_m = lap_distance_m

    def finish_lap(self) -> dict[int, CornerMetrics]:
        """Метрики круга. Поворот, не закрывшийся до финишной черты, всё равно
        засчитывается — на многих трассах она лежит внутри связки."""
        self._close()
        out = self._done
        self._done = {}
        self._cur = None
        self._last_distance_m = None
        return out

    def _rewound(self, lap_distance_m: float) -> bool:
        return (self._last_distance_m is not None
                and lap_distance_m < self._last_distance_m - DISTANCE_REWIND_M)

    def _close(self) -> None:
        cur = self._cur
        self._cur = None
        if cur is None:
            return
        metrics = CornerMetrics(
            corner_id=cur.corner_id, brake_point_m=cur.brake_m,
            min_speed_kmh=cur.min_speed, throttle_point_m=cur.throttle_m,
            duration_ms=cur.exit_ms - cur.entry_ms,
        )
        if metrics.usable():
            self._done[cur.corner_id] = metrics
```

- [ ] **Step 4: Прогнать тесты**

Run: `python -m pytest tests/test_coach_reference.py -q`
Expected: PASS, 9 passed

---

## Task 4: Нормализованное сравнение

**Files:**
- Create: `core/coach_ai/compare.py`
- Test: `tests/test_coach_compare.py` (создать)

Это ядро фазы 2. Тесты на нормализацию обязательны — именно она отличает полезный коуч от бесполезного.

- [ ] **Step 1: Написать падающий тест**

```python
"""Нормализованное сравнение с эталоном (core/coach_ai/compare.py)."""
from core.coach_ai.compare import compare_lap
from core.coach_ai.models import CornerMetrics


def _lap(spec: dict) -> dict[int, CornerMetrics]:
    """spec: {corner_id: (brake_m, min_speed, throttle_m, duration_ms)}"""
    return {cid: CornerMetrics(cid, *vals) for cid, vals in spec.items()}


def _flat(n: int, duration: int) -> dict:
    return {i: (100.0 * i, 120.0, 100.0 * i + 40, duration) for i in range(1, n + 1)}


def test_uniform_slowness_produces_no_advice():
    """Медленнее на полсекунды в КАЖДОМ повороте — это топливо, не техника."""
    ref = _lap(_flat(8, 4000))
    cur = _lap(_flat(8, 4500))

    assert compare_lap(cur, ref, {}) is None


def test_local_loss_is_reported_even_under_uniform_slowness():
    """Общее отставание есть, но в третьем оно втрое больше — вот это техника."""
    ref = _lap(_flat(8, 4000))
    spec = _flat(8, 4500)
    spec[3] = (300.0, 120.0, 340.0, 6000)
    cur = _lap(spec)

    advice = compare_lap(cur, ref, {3: "Turn 3"})

    assert advice is not None
    assert advice.corner_id == 3
    assert advice.metric == "duration"
    assert advice.corner_name == "Turn 3"
    assert advice.badness > 0


def test_too_few_comparable_corners_stays_silent():
    """Меньше пяти общих поворотов — медиана неустойчива, молчим."""
    ref = _lap(_flat(4, 4000))
    spec = _flat(4, 4000)
    spec[3] = (300.0, 120.0, 340.0, 6000)
    cur = _lap(spec)

    assert compare_lap(cur, ref, {}) is None


def test_early_braking_is_reported():
    ref = _lap(_flat(8, 4000))
    spec = _flat(8, 4000)
    spec[5] = (500.0 - 30.0, 120.0, 540.0, 4000)   # тормозит на 30 м раньше
    cur = _lap(spec)

    advice = compare_lap(cur, ref, {})

    assert advice.corner_id == 5
    assert advice.metric == "brake"
    assert advice.raw < 0


def test_later_braking_than_reference_is_not_a_mistake():
    """Тормозить ПОЗЖЕ эталона — не ошибка, а прогресс. Молчим."""
    ref = _lap(_flat(8, 4000))
    spec = _flat(8, 4000)
    spec[5] = (500.0 + 30.0, 120.0, 540.0, 4000)
    cur = _lap(spec)

    assert compare_lap(cur, ref, {}) is None


def test_slow_apex_is_reported():
    ref = _lap(_flat(8, 4000))
    spec = _flat(8, 4000)
    spec[2] = (200.0, 100.0, 240.0, 4000)   # на 20 км/ч медленнее в апексе
    cur = _lap(spec)

    advice = compare_lap(cur, ref, {})

    assert advice.corner_id == 2
    assert advice.metric == "min_speed"


def test_late_throttle_is_reported():
    ref = _lap(_flat(8, 4000))
    spec = _flat(8, 4000)
    spec[6] = (600.0, 120.0, 640.0 + 40.0, 4000)
    cur = _lap(spec)

    advice = compare_lap(cur, ref, {})

    assert advice.corner_id == 6
    assert advice.metric == "throttle"
    assert advice.raw > 0


def test_missing_metric_on_either_side_is_skipped():
    """Пологая связка без торможения не должна давать сравнение по тормозу."""
    ref = _lap(_flat(8, 4000))
    ref[4] = CornerMetrics(4, None, 120.0, 440.0, 4000)
    spec = _flat(8, 4000)
    spec[4] = (0.0, 120.0, 440.0, 4000)
    cur = _lap(spec)

    advice = compare_lap(cur, ref, {})

    assert advice is None


def test_deltas_table_covers_every_common_corner():
    from core.coach_ai.compare import corner_deltas

    ref = _lap(_flat(8, 4000))
    cur = _lap(_flat(8, 4200))

    rows = corner_deltas(cur, ref, {})

    assert len(rows) == 8
    assert all(r["duration_ms"] == 200 for r in rows)
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `python -m pytest tests/test_coach_compare.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.coach_ai.compare'`

- [ ] **Step 3: Реализовать**

```python
"""
core/coach_ai/compare.py
=========================
Сравнение круга с эталоном. Главное здесь — НОРМАЛИЗАЦИЯ.

Карьерный лучший круг почти всегда квалификационный: пустой бак, свежая резина.
Сравнение в лоб даёт отчёт «ты медленнее везде» — правду, из которой ничего не
следует. Поэтому смотрим не на отклонение, а на превышение СВЕРХ МЕДИАННОГО по
кругу: равномерное отставание съедается медианой и молчит, локальная потеря
остаётся видна.

Медиана, а не среднее: один вылет не должен утаскивать базу.

Пороги значимости НЕ откалиброваны на живых данных — как и пороги фазы 1.
"""
from __future__ import annotations

from statistics import median

from core.coach_ai.models import CornerDelta, CornerMetrics

#: Меньше — медиана неустойчива, сравнение не публикуется вовсе.
MIN_COMPARABLE_CORNERS = 5

#: (поле метрик, знак «плохого», порог значимости). Знак приводит превышение к
#: правилу «положительное = хуже эталона»: тормозить позже и проходить апекс
#: быстрее — это прогресс, а не ошибка.
_METRICS: dict[str, tuple[str, float, float]] = {
    "duration":  ("duration_ms",       1.0, 150.0),   # мс
    "brake":     ("brake_point_m",    -1.0,  12.0),   # м
    "min_speed": ("min_speed_kmh",    -1.0,   6.0),   # км/ч
    "throttle":  ("throttle_point_m",  1.0,  15.0),   # м
}


def _raw_deltas(current: dict[int, CornerMetrics],
                reference: dict[int, CornerMetrics],
                field: str) -> dict[int, float]:
    """Сырые разницы по одной метрике для поворотов, где она есть с ОБЕИХ
    сторон."""
    out: dict[int, float] = {}
    for corner_id, cur in current.items():
        ref = reference.get(corner_id)
        if ref is None:
            continue
        a, b = getattr(cur, field), getattr(ref, field)
        if a is None or b is None:
            continue
        out[corner_id] = float(a) - float(b)
    return out


def compare_lap(current: dict[int, CornerMetrics],
                reference: dict[int, CornerMetrics],
                corner_names: dict[int, str]) -> CornerDelta | None:
    """Самое выраженное отклонение круга от эталона, либо None.

    Метрики в разных единицах, поэтому ранжируются не по величине превышения, а
    по отношению превышения к собственному порогу значимости — иначе метры
    всегда обыгрывали бы километры в час."""
    best: CornerDelta | None = None
    best_ratio = 1.0     # ниже порога не публикуем вовсе

    for metric, (field, sign, threshold) in _METRICS.items():
        deltas = _raw_deltas(current, reference, field)
        if len(deltas) < MIN_COMPARABLE_CORNERS:
            continue
        base = median(deltas.values())
        for corner_id, raw in deltas.items():
            badness = (raw - base) * sign
            ratio = badness / threshold
            if ratio > best_ratio:
                best_ratio = ratio
                best = CornerDelta(
                    corner_id=corner_id,
                    corner_name=corner_names.get(corner_id),
                    metric=metric, raw=round(raw, 1),
                    badness=round(badness, 1),
                )
    return best


def corner_deltas(current: dict[int, CornerMetrics],
                  reference: dict[int, CornerMetrics],
                  corner_names: dict[int, str]) -> list[dict]:
    """Плоская таблица для дебрифа: сырые разницы по всем общим поворотам."""
    rows: list[dict] = []
    for corner_id in sorted(set(current) & set(reference)):
        cur, ref = current[corner_id], reference[corner_id]
        row = {"corner_id": corner_id,
               "corner_name": corner_names.get(corner_id)}
        for metric, (field, _sign, _thr) in _METRICS.items():
            a, b = getattr(cur, field), getattr(ref, field)
            key = "duration_ms" if metric == "duration" else f"{metric}_delta"
            row[key] = None if a is None or b is None else round(float(a) - float(b), 1)
        rows.append(row)
    return rows
```

- [ ] **Step 4: Прогнать тесты**

Run: `python -m pytest tests/test_coach_compare.py -q`
Expected: PASS, 9 passed

---

## Task 5: Общее правило повтора для обеих фаз

**Files:**
- Create: `core/coach_ai/repeat.py`
- Modify: `core/coach_ai/corner_log.py` (использовать общий гейт)
- Test: `tests/test_coach_repeat.py` (создать); существующий `tests/test_coach_corner_log.py` обязан остаться зелёным без правок

Правило «три круга из пяти, потом молчание пять» теперь нужно дважды. Двух копий быть не должно: разойдясь, они дадут коучу два разных характера в одной функции.

- [ ] **Step 1: Написать падающий тест**

```python
"""Общее правило повтора (core/coach_ai/repeat.py)."""
from core.coach_ai.repeat import RepeatGate


def test_single_observation_does_not_fire():
    g = RepeatGate()
    assert g.observe("a", lap=1) is False


def test_three_of_five_laps_fire():
    g = RepeatGate()
    g.observe("a", lap=1)
    g.observe("a", lap=2)
    assert g.observe("a", lap=3) is True


def test_same_lap_counts_once():
    g = RepeatGate()
    g.observe("a", lap=1)
    g.observe("a", lap=1)
    assert g.observe("a", lap=1) is False


def test_spread_beyond_window_does_not_fire():
    g = RepeatGate()
    g.observe("a", lap=1)
    g.observe("a", lap=4)
    assert g.observe("a", lap=9) is False


def test_signatures_are_independent():
    g = RepeatGate()
    g.observe("a", lap=1)
    g.observe("b", lap=2)
    assert g.observe("a", lap=3) is False


def test_cooldown_blocks_the_next_lap():
    g = RepeatGate()
    for lap in (1, 2, 3):
        g.observe("a", lap=lap)
    assert g.observe("a", lap=4) is False


def test_fires_again_after_cooldown():
    g = RepeatGate()
    for lap in (1, 2, 3, 4, 5, 6, 7):
        g.observe("a", lap=lap)
    assert g.observe("a", lap=8) is True


def test_reset_clears_state():
    g = RepeatGate()
    g.observe("a", lap=1)
    g.observe("a", lap=2)
    g.reset()
    assert g.observe("a", lap=3) is False
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `python -m pytest tests/test_coach_repeat.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.coach_ai.repeat'`

- [ ] **Step 3: Реализовать**

```python
"""
core/coach_ai/repeat.py
========================
Правило «о чём стоит сказать вслух»: одна и та же тема на REPEAT_LAPS кругах из
последних WINDOW_LAPS, затем молчание COOLDOWN_LAPS кругов.

Живёт отдельным модулем, потому что нужно обеим фазам коуча — срывам сцепления
(фаза 1) и отклонениям от эталона (фаза 2). Две копии этого правила разошлись бы
и дали коучу два разных характера внутри одной функции.
"""
from __future__ import annotations

WINDOW_LAPS = 5
REPEAT_LAPS = 3
#: Пилот не перестроит привычку за круг, а повторённый совет раздражает быстрее,
#: чем помогает.
COOLDOWN_LAPS = 5


class RepeatGate:
    def __init__(self) -> None:
        self._laps: dict[object, list[int]] = {}
        self._fired_on_lap: dict[object, int] = {}

    def reset(self) -> None:
        self._laps.clear()
        self._fired_on_lap.clear()

    def observe(self, signature: object, lap: int) -> bool:
        """Записать наблюдение. True — пора сказать."""
        laps = self._laps.setdefault(signature, [])
        # Несколько наблюдений на одном круге — это один круг: иначе один
        # особенно неудачный круг выдавался бы за привычку.
        if lap not in laps:
            laps.append(lap)

        recent = [x for x in laps if lap - x < WINDOW_LAPS]
        if len(recent) < REPEAT_LAPS:
            return False

        fired = self._fired_on_lap.get(signature)
        if fired is not None and lap - fired < COOLDOWN_LAPS:
            return False

        self._fired_on_lap[signature] = lap
        return True
```

- [ ] **Step 4: Перевести `CornerLog` на общий гейт**

В `core/coach_ai/corner_log.py` убрать `WINDOW_LAPS` / `REPEAT_LAPS` / `ADVICE_COOLDOWN_LAPS`, `_laps_by_signature`, `_advised_on_lap`, и переписать через гейт:

```python
from core.coach_ai.repeat import RepeatGate

class CornerLog:
    def __init__(self) -> None:
        self._all: list[CornerMistake] = []
        self._gate = RepeatGate()

    def reset(self) -> None:
        self._all.clear()
        self._gate.reset()

    def add(self, mistake: CornerMistake) -> CornerMistake | None:
        """Записать ошибку. Вернуть её же, если пора сказать вживую.

        Ошибка попадает в карту дебрифа ВСЕГДА, независимо от того, дошло ли
        дело до реплики."""
        self._all.append(mistake)
        if self._gate.observe(mistake.signature(), mistake.lap):
            return mistake
        return None
```

Остальные методы (`map_rows`, `top_corners`) не трогать.

- [ ] **Step 5: Прогнать тесты обеих фаз**

Run: `python -m pytest tests/test_coach_repeat.py tests/test_coach_corner_log.py tests/test_coach_wiring.py -q`
Expected: PASS — `test_coach_corner_log.py` должен пройти БЕЗ правок, это и есть доказательство, что поведение не изменилось

---

## Task 6: Карьерный эталон из архива

**Files:**
- Create: `core/coach_ai/reference_store.py`
- Test: `tests/test_coach_reference_store.py` (создать)

- [ ] **Step 1: Написать падающий тест**

```python
"""Карьерный эталон из архива сессий (core/coach_ai/reference_store.py)."""
from core.coach_ai import reference_store as store


def _session(track_id: int, lap_ms: int, corners: dict) -> dict:
    return {"track_id": track_id,
            "reference_lap": {"lap_time_ms": lap_ms, "corners": corners}}


_CORNER = {"corner_id": 3, "brake_point_m": 100.0, "min_speed_kmh": 120.0,
           "throttle_point_m": 140.0, "duration_ms": 4000}


def _patch(monkeypatch, sessions: list[dict]):
    summaries = [{"path": str(i), "track_id": s["track_id"]}
                 for i, s in enumerate(sessions)]
    monkeypatch.setattr(store.archive, "list_game_sessions", lambda: summaries)
    monkeypatch.setattr(store.archive, "load_game_session",
                        lambda path: sessions[int(path)])


def test_returns_fastest_lap_for_the_track(monkeypatch):
    _patch(monkeypatch, [
        _session(1, 95000, {"3": _CORNER}),
        _session(1, 91000, {"3": {**_CORNER, "min_speed_kmh": 130.0}}),
        _session(2, 80000, {"3": _CORNER}),
    ])

    ref = store.load_career_reference(track_id=1)

    assert ref.lap_time_ms == 91000
    assert ref.corners[3].min_speed_kmh == 130.0


def test_returns_none_when_track_never_visited(monkeypatch):
    _patch(monkeypatch, [_session(2, 80000, {"3": _CORNER})])
    assert store.load_career_reference(track_id=1) is None


def test_sessions_without_reference_lap_are_skipped(monkeypatch):
    """Сессии, записанные до фазы 2, эталона не содержат и не должны ронять
    загрузку."""
    old = {"track_id": 1, "player_laps": [{"lap": 1, "last_lap_ms": 90000}]}
    _patch(monkeypatch, [old, _session(1, 95000, {"3": _CORNER})])

    ref = store.load_career_reference(track_id=1)

    assert ref.lap_time_ms == 95000


def test_corrupt_reference_entry_is_skipped(monkeypatch):
    _patch(monkeypatch, [
        _session(1, 95000, {"3": {"corner_id": 3}}),   # без метрик
        _session(1, 96000, {"3": _CORNER}),
    ])

    ref = store.load_career_reference(track_id=1)

    assert ref.lap_time_ms == 96000
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `python -m pytest tests/test_coach_reference_store.py -q`
Expected: FAIL — модуля нет

- [ ] **Step 3: Реализовать**

```python
"""
core/coach_ai/reference_store.py
=================================
Карьерный эталон — самый быстрый записанный круг на трассе, со всеми его
метриками поворотов. Источник тот же, что у core/career_memory.py: архив
игровых сессий, без сети и без своей базы.

Тип сессии НЕ фильтруется (в отличие от career_memory, который берёт только
гонки): нормализация в compare.py нейтрализует разницу в топливе и резине, а
выбрасывать квалификационные круги значило бы выбрасывать лучшую технику
пилота.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from analytics import archive
from core.coach_ai.models import CornerMetrics

_log = logging.getLogger(__name__)


@dataclass
class ReferenceLap:
    lap_time_ms: int
    corners: dict[int, CornerMetrics]
    source: str      # "career" | "session"


def parse_corners(raw: dict) -> dict[int, CornerMetrics]:
    """JSON-ключи всегда строки — приводим к int. Битую запись пропускаем, а
    не роняем загрузку: один испорченный файл не должен лишать пилота эталона."""
    out: dict[int, CornerMetrics] = {}
    for value in (raw or {}).values():
        try:
            metrics = CornerMetrics.from_dict(value)
        except (KeyError, TypeError):
            continue
        if metrics.usable():
            out[metrics.corner_id] = metrics
    return out


def load_career_reference(track_id: int) -> ReferenceLap | None:
    """Самый быстрый круг на трассе среди всех сессий с записанным эталоном."""
    best: ReferenceLap | None = None
    for summary in archive.list_game_sessions():
        if summary.get("track_id") != track_id:
            continue
        data = archive.load_game_session(summary["path"])
        if not data:
            continue
        raw = data.get("reference_lap") or {}
        lap_ms = raw.get("lap_time_ms") or 0
        if lap_ms <= 0:
            continue
        corners = parse_corners(raw.get("corners"))
        if not corners:
            continue
        if best is None or lap_ms < best.lap_time_ms:
            best = ReferenceLap(lap_time_ms=lap_ms, corners=corners,
                                source="career")
    return best
```

- [ ] **Step 4: Прогнать тесты**

Run: `python -m pytest tests/test_coach_reference_store.py -q`
Expected: PASS, 4 passed

---

## Task 7: Фразы `coach.ref_*`

**Files:**
- Modify: `core/radio/phrases.py` (после блока `coach.offtrack`)
- Test: `tests/test_radio_phrases.py` (дописать)

- [ ] **Step 1: Написать падающий тест**

```python
_COACH_REF_CODES = [
    "coach.ref_brake_early", "coach.ref_apex_slow",
    "coach.ref_throttle_late", "coach.ref_losing_time",
]


@pytest.mark.parametrize("code", _COACH_REF_CODES)
def test_coach_reference_spec_exists(code):
    assert code in phrases.codes()


@pytest.mark.parametrize("code", _COACH_REF_CODES)
def test_coach_reference_spec_has_enough_variants(code):
    assert len(phrases.spec_for(code).variants) >= 6


@pytest.mark.parametrize("code", _COACH_REF_CODES)
def test_coach_reference_spec_is_never_critical(code):
    assert phrases.spec_for(code).urgency != policy.URGENCY_CRITICAL


def test_reference_specs_do_not_promise_a_number_they_lack():
    """Формулировка не должна требовать подстановки — трекер отдаёт поворот, а
    величину отклонения мы намеренно не зачитываем: «на 12 метров раньше» пилот
    в повороте не применит, ему нужно направление."""
    for code in _COACH_REF_CODES:
        for variant in phrases.spec_for(code).variants:
            assert "{" not in variant, f"{code}: {variant!r}"
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `python -m pytest tests/test_radio_phrases.py -k coach_reference -q`
Expected: FAIL — `KeyError`

- [ ] **Step 3: Реализовать**

После спеки `coach.offtrack` добавить:

```python
    # ── Коуч, фаза 2: отклонения от эталонного круга ─────────────────────────
    # Величину отклонения НЕ зачитываем: «на двенадцать метров раньше» пилот в
    # повороте не применит, ему нужно направление. Поворот называет движок
    # отдельным полем черновика, как и в фазе 1.
    _spec("coach.ref_brake_early", _N, (
        "Тормозишь раньше, чем можешь.",
        "Здесь можно тормозить позже.",
        "Оттягивай торможение в этом повороте.",
        "Ты рано на тормозе, попробуй глубже.",
        "Есть запас по торможению.",
        "Тормоз здесь можно оттянуть.",
    ), action="coach_ref_brake"),
    _spec("coach.ref_apex_slow", _N, (
        "Проходишь этот поворот медленнее обычного.",
        "Здесь ты теряешь скорость в апексе.",
        "Скорость в повороте ниже твоей нормы.",
        "Можно нести больше скорости внутрь.",
        "В апексе есть запас по скорости.",
        "Здесь ты едешь осторожнее, чем умеешь.",
    ), action="coach_ref_apex"),
    _spec("coach.ref_throttle_late", _N, (
        "Поздно открываешь газ на выходе.",
        "Здесь можно раньше на газ.",
        "Разгон из этого поворота запаздывает.",
        "Открывай газ пораньше на выходе.",
        "Ты медлишь с газом в этом повороте.",
        "Выход можно начинать раньше.",
    ), action="coach_ref_throttle"),
    _spec("coach.ref_losing_time", _N, (
        "В этом повороте теряешь больше всего.",
        "Здесь уходит основное время.",
        "Этот поворот даётся хуже остальных.",
        "Основная потеря круга здесь.",
        "Тут ты теряешь заметно больше, чем везде.",
        "Этот поворот стоит тебе времени.",
    ), action="coach_ref_time"),
```

- [ ] **Step 4: Прогнать тесты**

Run: `python -m pytest tests/test_radio_phrases.py -q`
Expected: PASS

---

## Task 8: Проводка в движок

**Files:**
- Modify: `core/engine.py`
- Modify: `core/session_recorder.py`
- Test: `tests/test_coach_reference_wiring.py` (создать)

- [ ] **Step 1: Написать падающий тест**

```python
"""Проводка эталонного сравнения: круг -> дельты -> реплика."""
import pytest

import core.engine as eng_mod
from core.coach_ai.models import CornerMetrics
from core.coach_ai.reference_store import ReferenceLap
from core.engine import F1Engine


@pytest.fixture
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _lap(duration_by_corner: dict[int, int]) -> dict[int, CornerMetrics]:
    return {cid: CornerMetrics(cid, 100.0 * cid, 120.0, 100.0 * cid + 40, ms)
            for cid, ms in duration_by_corner.items()}


def _flat(ms: int) -> dict[int, int]:
    return {i: ms for i in range(1, 9)}


def _capture(engine, monkeypatch):
    drafts, codes = [], []
    monkeypatch.setattr(engine._commentary_events, "publish", drafts.append)
    monkeypatch.setattr(engine, "_render_engineer_phrase",
                        lambda draft, code, *a, **kw: (codes.append(code), "ф")[1])
    return drafts, codes


def test_repeated_local_loss_publishes_reference_advice(engine, monkeypatch):
    engine.settings["driving_coach_enabled"] = True
    drafts, codes = _capture(engine, monkeypatch)
    engine.coach_reference = ReferenceLap(90000, _lap(_flat(4000)), "career")

    slow = _flat(4000)
    slow[3] = 6000
    for lap in (1, 2, 3):
        engine._compare_lap_to_reference(_lap(slow), lap=lap)

    assert codes == ["coach.ref_losing_time"]
    assert len(drafts) == 1
    assert drafts[0]["corner_id"] == 3
    assert drafts[0].get("priority") != "critical"


def test_uniform_slowness_never_speaks(engine, monkeypatch):
    engine.settings["driving_coach_enabled"] = True
    drafts, _ = _capture(engine, monkeypatch)
    engine.coach_reference = ReferenceLap(90000, _lap(_flat(4000)), "career")

    for lap in (1, 2, 3, 4, 5):
        engine._compare_lap_to_reference(_lap(_flat(5000)), lap=lap)

    assert drafts == []


def test_no_reference_means_silence(engine, monkeypatch):
    engine.settings["driving_coach_enabled"] = True
    drafts, _ = _capture(engine, monkeypatch)
    engine.coach_reference = None

    for lap in (1, 2, 3):
        engine._compare_lap_to_reference(_lap(_flat(4000)), lap=lap)

    assert drafts == []


def test_disabled_coach_stays_silent(engine, monkeypatch):
    engine.settings["driving_coach_enabled"] = False
    drafts, _ = _capture(engine, monkeypatch)
    engine.coach_reference = ReferenceLap(90000, _lap(_flat(4000)), "career")

    slow = _flat(4000)
    slow[3] = 6000
    for lap in (1, 2, 3):
        engine._compare_lap_to_reference(_lap(slow), lap=lap)

    assert drafts == []


def test_fastest_lap_of_the_session_becomes_the_reference(engine):
    """Пока карьерного эталона нет, эталоном служит лучший круг сессии."""
    engine.coach_reference = None
    engine._note_lap_reference(_lap(_flat(4000)), lap_time_ms=95000)
    engine._note_lap_reference(_lap(_flat(3800)), lap_time_ms=91000)

    assert engine.coach_reference is not None
    assert engine.coach_reference.lap_time_ms == 91000
    assert engine.coach_reference.source == "session"


def test_career_reference_is_not_replaced_by_a_slower_session_lap(engine):
    engine.coach_reference = ReferenceLap(89000, _lap(_flat(3500)), "career")
    engine._note_lap_reference(_lap(_flat(4000)), lap_time_ms=95000)

    assert engine.coach_reference.source == "career"
    assert engine.coach_reference.lap_time_ms == 89000
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `python -m pytest tests/test_coach_reference_wiring.py -q`
Expected: FAIL — `AttributeError: 'F1Engine' object has no attribute 'coach_reference'`

- [ ] **Step 3: Реализовать**

Импорты рядом с импортами фазы 1:

```python
from core.coach_ai.compare import compare_lap, corner_deltas
from core.coach_ai.reference import LapTracer
from core.coach_ai.reference_store import ReferenceLap, load_career_reference
from core.coach_ai.repeat import RepeatGate
```

Карта метрики в код банка — рядом с `_COACH_PHRASE_CODE`:

```python
# Метрика отклонения от эталона -> семантический код банка.
_COACH_REFERENCE_CODE: dict[str, str] = {
    "brake": "coach.ref_brake_early",
    "min_speed": "coach.ref_apex_slow",
    "throttle": "coach.ref_throttle_late",
    "duration": "coach.ref_losing_time",
}
```

В `__init__`, рядом с `self.coach_slip` / `self.coach_log`:

```python
        self.coach_tracer = LapTracer()
        self.coach_reference: ReferenceLap | None = None
        self.coach_reference_gate = RepeatGate()
        self._coach_last_deltas: list[dict] = []
```

В `_coach_tick`, после вычисления `track_ctx` и до детекторов, кормить трейсер (там уже есть и поворот, и вводы пилота — второй проход по геометрии не нужен):

```python
        self.coach_tracer.tick(
            corner_id=corner.id if corner else None,
            phase=track_ctx.phase if track_ctx else "straight",
            lap_distance_m=self._lap_distance_m or 0.0,
            lap_time_ms=self._player_hud.get("current_lap_time_ms", 0),
            brake_pct=self._player_hud.get("brake_pct", 0.0),
            throttle_pct=self._player_hud.get("throttle_pct", 0.0),
            speed_kmh=self._player_speed_kmh,
        )
```

Новые методы рядом с `_emit_coach_advice`:

```python
    def _note_lap_reference(self, metrics: dict, lap_time_ms: int) -> None:
        """Кандидат в эталон. Карьерный эталон сессионным не перебивается:
        цель должна быть фиксированной, иначе она уезжает вместе с формой."""
        if not metrics or lap_time_ms <= 0:
            return
        cur = self.coach_reference
        if cur is not None and lap_time_ms >= cur.lap_time_ms:
            return
        self.coach_reference = ReferenceLap(
            lap_time_ms=lap_time_ms, corners=metrics, source="session")

    def _compare_lap_to_reference(self, metrics: dict, lap: int) -> None:
        """Круг завершён: сравнить с эталоном, при устойчивом отклонении —
        сказать. Таблица дельт считается всегда, она нужна дебрифу."""
        reference = self.coach_reference
        if not metrics or reference is None:
            return
        names = self._corner_names()
        self._coach_last_deltas = corner_deltas(metrics, reference.corners, names)

        advice = compare_lap(metrics, reference.corners, names)
        if advice is None:
            return
        if not self.coach_reference_gate.observe(
                (advice.metric, advice.corner_id), lap):
            return
        if not self._get_setting("driving_coach_enabled", False):
            return
        code = _COACH_REFERENCE_CODE.get(advice.metric)
        if code is None:
            return
        draft = {
            "event_code": "COACH_REFERENCE",
            "priority": "normal",
            "speaker": SPEAKER_ENGINEER,
            "driver": "", "color": "#38BDF8",
            "corner": advice.corner_name,
            "corner_id": advice.corner_id,
        }
        draft["phrase"] = self._render_engineer_phrase(draft, code)
        if draft["phrase"]:
            self._commentary_events.publish(draft)

    def _corner_names(self) -> dict[int, str]:
        if self._track_manager is None:
            return {}
        return {c.id: c.name for c in self._track_manager.corners()}
```

`TrackManager` сейчас не отдаёт список поворотов — добавить в `core/track_ai/track_manager.py`:

```python
    def corners(self) -> list[Corner]:
        """Разметка активной трассы. Нужна коучу, чтобы называть повороты по
        имени, не таща сюда загрузчик треков."""
        return list(self._track.corners)
```

(и импорт `Corner` в этом файле.)

На завершении круга — рядом с `self.recorder.on_lap_complete(...)`:

```python
                        lap_metrics = self.coach_tracer.finish_lap()
                        self._note_lap_reference(lap_metrics, lms)
                        self._compare_lap_to_reference(lap_metrics, self._prev_lap)
```

Порядок важен: сначала кандидат в эталон, потом сравнение — иначе первый же круг сессии сравнивался бы сам с собой.

При смене трассы, там же, где создаётся `TrackManager`:

```python
                    self.coach_reference = load_career_reference(self._track_id)
```

В блоке сброса сессии, рядом с `self.coach_log.reset()`:

```python
            self.coach_tracer.reset()
            self.coach_reference_gate.reset()
            self._coach_last_deltas = []
```

`current_lap_time_ms` довезти до `_player_hud` — добавить ключ в кортеж `_hud_key` в `_apply_telemetry_delta`.

- [ ] **Step 4: Прогнать тесты**

Run: `python -m pytest tests/test_coach_reference_wiring.py tests/test_coach_wiring.py -q`
Expected: PASS

---

## Task 9: Сохранение эталона и дебриф

**Files:**
- Modify: `core/session_recorder.py`, `core/engine.py`
- Modify: `NewSpotterUI/lib/api.ts`, `NewSpotterUI/components/spotter/views/debrief.tsx`
- Test: `tests/test_session_recorder_laps.py` (дописать)

- [ ] **Step 1: Написать падающий тест**

```python
def test_finalize_stores_reference_lap(monkeypatch):
    rec = SessionRecorder()
    rec.on_lap_complete(lap_num=1, last_lap_ms=91000,
                        s1_ms=30000, s2_ms=31000, s3_ms=30000)
    rec.set_reference_lap(lap_time_ms=91000, corners={
        3: {"corner_id": 3, "brake_point_m": 100.0, "min_speed_kmh": 120.0,
            "throttle_point_m": 140.0, "duration_ms": 4000}})

    saved = _finalize_captured(rec, monkeypatch)

    assert saved["reference_lap"]["lap_time_ms"] == 91000
    assert saved["reference_lap"]["corners"]["3"]["min_speed_kmh"] == 120.0


def test_finalize_without_reference_lap_writes_nothing_misleading(monkeypatch):
    rec = SessionRecorder()
    rec.on_lap_complete(lap_num=1, last_lap_ms=91000,
                        s1_ms=30000, s2_ms=31000, s3_ms=30000)

    saved = _finalize_captured(rec, monkeypatch)

    assert saved["reference_lap"] is None
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `python -m pytest tests/test_session_recorder_laps.py -k reference -q`
Expected: FAIL — `AttributeError: set_reference_lap`

- [ ] **Step 3: Реализовать в рекордере**

```python
    def set_reference_lap(self, lap_time_ms: int, corners: dict) -> None:
        """Метрики лучшего круга сессии. Ключи словаря приводим к строкам явно:
        JSON всё равно это сделает, а читатель (reference_store) рассчитывает
        именно на строки."""
        self._reference_lap = {
            "lap_time_ms": lap_time_ms,
            "corners": {str(cid): body for cid, body in corners.items()},
        }
```

С инициализацией `self._reference_lap: dict | None = None` в `__init__` и `reset()`, и `"reference_lap": self._reference_lap` в словаре `finalize`.

В `core/engine.py`, рядом с `self.recorder.set_coach_map(...)`:

```python
            if self.coach_reference is not None:
                self.recorder.set_reference_lap(
                    lap_time_ms=self.coach_reference.lap_time_ms,
                    corners={cid: m.to_dict()
                             for cid, m in self.coach_reference.corners.items()},
                )
```

- [ ] **Step 4: Отдать дельты в живое состояние**

В вызове `self._ui_state.set_analysis(...)` дополнить `coach_ai`:

```python
                "reference_deltas": self._coach_last_deltas[:8],
                "reference_source": (
                    self.coach_reference.source if self.coach_reference else None),
```

Полную таблицу не шлём по той же причине, что и карту ошибок: восемь окон опрашивают `/api/state` каждые 250 мс.

- [ ] **Step 5: Типы и блок дебрифа**

В `lib/api.ts` дополнить `CoachAIState`:

```ts
  /** Отклонения от эталонного круга по поворотам (фаза 2). */
  reference_deltas?: CoachReferenceDelta[]
  reference_source?: "career" | "session" | null
```

с типом рядом:

```ts
export type CoachReferenceDelta = {
  corner_id: number
  corner_name: string | null
  duration_ms: number | null
  brake_delta: number | null
  min_speed_delta: number | null
  throttle_delta: number | null
}
```

В `debrief.tsx` добавить секцию после «Где теряется время»:

```tsx
{referenceDeltas.length > 0 && (
  <Panel label="Против эталона" action={
    <span className="label-mono text-[10px] text-muted-foreground">
      {coach?.reference_source === "career" ? "лучший на трассе" : "лучший в сессии"}
    </span>
  }>
    <div className="flex flex-col gap-1.5">
      {referenceDeltas.map((d) => (
        <div key={d.corner_id} className="flex items-baseline justify-between gap-4 text-xs">
          <span className="text-foreground">{d.corner_name ?? `Поворот ${d.corner_id}`}</span>
          <span className="label-mono text-muted-foreground">
            {d.duration_ms == null ? "—"
              : `${d.duration_ms >= 0 ? "+" : ""}${(d.duration_ms / 1000).toFixed(2)}с`}
            {d.brake_delta != null && ` · тормоз ${d.brake_delta >= 0 ? "+" : ""}${Math.round(d.brake_delta)}м`}
          </span>
        </div>
      ))}
    </div>
  </Panel>
)}
```

с `const referenceDeltas = coach?.reference_deltas ?? []` рядом с `topCorners`.

- [ ] **Step 6: Проверить и собрать**

Run: `cd NewSpotterUI; pnpm exec tsc --noEmit`
Expected: чисто

Run: `cd NewSpotterUI; pnpm build`
Expected: сборка проходит

Run: `robocopy NewSpotterUI\out webui /MIR`
Expected: exit 1 или 3 — успех

- [ ] **Step 7: Полный прогон**

Run: `python -m pytest -p no:warnings -q`
Expected: без новых падений; три падения в `tests/test_voice_cast.py` принадлежат параллельной сессии по Piper — не чинить
