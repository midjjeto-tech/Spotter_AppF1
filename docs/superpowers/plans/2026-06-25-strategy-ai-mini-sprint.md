# Strategy AI Mini-Sprint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Strategy AI realism with pace history, opponent pit detection, confidence thresholds, and fuel delta model — without changing any HTTP API paths or UI components.

**Architecture:** Four isolated units — (1) `PaceTracker` + `FuelTracker` classes added to `analysis.py`; (2) new `opponents.py` with gap-change-based pit detection; (3) `strategy.py` wires all trackers, adds `MIN_CONFIDENCE_EMIT=0.55` filter, adds `fuel_mode`/`pace_trend` to `get_state()`; (4) 14 new tests in `test_strategy_sprint.py`. No telemetry parser changes, no API endpoint changes, no UI changes.

**Tech Stack:** Python 3.12, `collections.deque`, pytest (`py -3.12 -m pytest`)

---

## File Map

| File | Change |
|---|---|
| `core/strategy_ai/analysis.py` | + `LapRecord` dataclass, `PaceTracker` class, `FuelTracker` class |
| `core/strategy_ai/opponents.py` | **New** — `OpponentPitDetector` class |
| `core/strategy_ai/strategy.py` | Wire trackers; add confidence filter; add `cover_opponent` event; expose `fuel_mode`/`pace_trend` in `get_state()` |
| `tests/test_strategy_sprint.py` | **New** — 14 tests for all mini-sprint features |

---

## Task A: PaceTracker + FuelTracker in analysis.py

**Files:**
- Modify: `core/strategy_ai/analysis.py`
- Test: `tests/test_strategy_sprint.py`

### Step A-1: Write the failing tests

Create `tests/test_strategy_sprint.py` with the pace and fuel tests only (opponents and integration come later):

```python
"""tests/test_strategy_sprint.py — Strategy AI mini-sprint feature tests."""
import pytest
from core.strategy_ai.analysis import LapRecord, PaceTracker, FuelTracker


# ---------------------------------------------------------------------------
# PaceTracker
# ---------------------------------------------------------------------------

def test_pace_tracker_stable_with_less_than_3_laps():
    t = PaceTracker()
    t.push(LapRecord(lap_number=1, lap_time_ms=90_000, tyre_compound="M", tyre_age=1))
    t.push(LapRecord(lap_number=2, lap_time_ms=90_200, tyre_compound="M", tyre_age=2))
    assert t.trend() == "stable"        # only 2 laps — not enough for trend


def test_pace_tracker_rising_trend():
    t = PaceTracker()
    for i, ms in enumerate([90_000, 90_300, 90_600], start=1):
        t.push(LapRecord(lap_number=i, lap_time_ms=ms, tyre_compound="M", tyre_age=i))
    assert t.trend() == "rising"        # getting slower = tyres degrading


def test_pace_tracker_falling_trend():
    t = PaceTracker()
    for i, ms in enumerate([91_000, 90_700, 90_400], start=1):
        t.push(LapRecord(lap_number=i, lap_time_ms=ms, tyre_compound="M", tyre_age=i))
    assert t.trend() == "falling"       # getting faster = good form


def test_pace_tracker_delta():
    t = PaceTracker()
    t.push(LapRecord(lap_number=1, lap_time_ms=90_000, tyre_compound="M", tyre_age=1))
    t.push(LapRecord(lap_number=2, lap_time_ms=90_400, tyre_compound="M", tyre_age=2))
    assert t.pace_delta() == 400        # slowed by 400ms


def test_pace_tracker_no_data_returns_none():
    t = PaceTracker()
    assert t.pace_delta() is None
    assert t.trend() == "stable"


# ---------------------------------------------------------------------------
# FuelTracker
# ---------------------------------------------------------------------------

def test_fuel_tracker_actual_per_lap():
    t = FuelTracker()
    t.push(lap_number=1, fuel_kg=30.0)
    t.push(lap_number=4, fuel_kg=24.6)
    assert abs(t.actual_per_lap() - 1.8) < 0.01   # (30.0 - 24.6) / 3 = 1.8


def test_fuel_tracker_attack_mode():
    t = FuelTracker()
    t.push(lap_number=1, fuel_kg=30.0)
    t.push(lap_number=3, fuel_kg=26.8)             # 1.6 kg/lap rate
    # 10 laps remaining → project 26.8 - 1.6*10 = 10.8 → surplus > 2 kg
    assert t.fuel_mode(laps_remaining=10) == "attack"


def test_fuel_tracker_save_mode():
    t = FuelTracker()
    t.push(lap_number=1, fuel_kg=30.0)
    t.push(lap_number=3, fuel_kg=26.0)             # 2.0 kg/lap rate
    # 20 laps remaining → project 26.0 - 2.0*20 = -14 → deficit
    assert t.fuel_mode(laps_remaining=20) == "save"


def test_fuel_tracker_normal_mode():
    t = FuelTracker()
    t.push(lap_number=1, fuel_kg=30.0)
    t.push(lap_number=3, fuel_kg=26.4)             # 1.8 kg/lap rate
    # 5 laps remaining → project 26.4 - 1.8*5 = 17.4 → big surplus (attack? no)
    # Wait: 17.4 > 2.0, so this would be "attack". Let me check with tight margin:
    # 14 laps remaining → project 26.4 - 1.8*14 = 1.2 → 0 < 1.2 < 2 → normal
    assert t.fuel_mode(laps_remaining=14) == "normal"
```

- [ ] **Step A-1a: Run tests to verify they FAIL**

```
py -3.12 -m pytest tests/test_strategy_sprint.py -v
```
Expected: `ImportError: cannot import name 'LapRecord' from 'core.strategy_ai.analysis'`

### Step A-2: Implement PaceTracker and FuelTracker in analysis.py

Add at the top of `core/strategy_ai/analysis.py` after the existing imports:

```python
from collections import deque
from dataclasses import dataclass
```

Then add after the constants block (after `FUEL_LOW_KG = 2.0`), before the `pace_mode()` function:

```python

@dataclass
class LapRecord:
    lap_number: int
    lap_time_ms: int
    tyre_compound: str | None
    tyre_age: int | None


class PaceTracker:
    """Rolling window of last N laps — used to compute pace delta and trend."""
    _WINDOW = 5
    _TREND_THRESHOLD_MS = 200

    def __init__(self) -> None:
        self._laps: deque[LapRecord] = deque(maxlen=self._WINDOW)

    def push(self, record: LapRecord) -> None:
        self._laps.append(record)

    def pace_delta(self) -> int | None:
        """Last lap minus previous lap (ms). Positive = slowing."""
        if len(self._laps) < 2:
            return None
        return self._laps[-1].lap_time_ms - self._laps[-2].lap_time_ms

    def trend(self) -> str:
        """'rising'|'falling'|'stable' based on last 3 laps."""
        if len(self._laps) < 3:
            return "stable"
        recent = list(self._laps)[-3:]
        d1 = recent[1].lap_time_ms - recent[0].lap_time_ms
        d2 = recent[2].lap_time_ms - recent[1].lap_time_ms
        thr = self._TREND_THRESHOLD_MS
        if d1 > thr and d2 > thr:
            return "rising"    # getting slower (tyre degradation)
        if d1 < -thr and d2 < -thr:
            return "falling"   # getting faster
        return "stable"

    def has_data(self) -> bool:
        return len(self._laps) >= 2


class FuelTracker:
    """Rolling window of fuel readings — computes actual per-lap consumption."""
    _WINDOW = 4

    def __init__(self) -> None:
        self._readings: deque[tuple[int, float]] = deque(maxlen=self._WINDOW)
        # entries: (lap_number, fuel_kg)

    def push(self, lap_number: int, fuel_kg: float) -> None:
        self._readings.append((lap_number, fuel_kg))

    def actual_per_lap(self) -> float | None:
        """Average fuel consumption rate (kg/lap). None if less than 2 readings."""
        if len(self._readings) < 2:
            return None
        oldest = self._readings[0]
        newest = self._readings[-1]
        laps = newest[0] - oldest[0]
        if laps <= 0:
            return None
        return (oldest[1] - newest[1]) / laps

    def fuel_mode(self, laps_remaining: int | None) -> str:
        """'attack'|'normal'|'save' based on projected finish fuel."""
        if laps_remaining is None or laps_remaining <= 0:
            return "normal"
        rate = self.actual_per_lap()
        if rate is None:
            return "normal"
        current = self._readings[-1][1]
        projected = current - rate * laps_remaining
        if projected > 2.0:
            return "attack"
        if projected < 0.0:
            return "save"
        return "normal"
```

- [ ] **Step A-2a: Run tests — expect pass**

```
py -3.12 -m pytest tests/test_strategy_sprint.py -v -k "pace or fuel"
```
Expected: 8 passed.

- [ ] **Step A-2b: Run full suite — no regressions**

```
py -3.12 -m pytest tests/ --ignore=tests/test_gpt.py -q
```
Expected: 262 passed (unchanged from Task 8 baseline).

---

## Task B: OpponentPitDetector in opponents.py

**Files:**
- Create: `core/strategy_ai/opponents.py`
- Modify: `tests/test_strategy_sprint.py`

### Step B-1: Add opponent tests

Append to `tests/test_strategy_sprint.py`:

```python
# ---------------------------------------------------------------------------
# OpponentPitDetector
# ---------------------------------------------------------------------------

from core.strategy_ai.opponents import OpponentPitDetector


def test_opponent_no_pit_on_small_gap_change():
    d = OpponentPitDetector()
    d.update(gap_front_ms=2_000)
    d.update(gap_front_ms=2_500)    # +500ms — normal racing
    assert d.opponent_pitted is False


def test_opponent_detects_pit_on_large_gap_jump():
    d = OpponentPitDetector()
    d.update(gap_front_ms=2_000)
    d.update(gap_front_ms=25_000)   # +23000ms — opponent pitted
    assert d.opponent_pitted is True


def test_opponent_cover_recommended_with_worn_tyres():
    d = OpponentPitDetector()
    d.update(gap_front_ms=2_000)
    d.update(gap_front_ms=25_000)
    ok, conf = d.should_cover(our_tyre_status="worn")
    assert ok is True
    assert conf >= 0.6


def test_opponent_no_cover_with_fresh_tyres():
    d = OpponentPitDetector()
    d.update(gap_front_ms=2_000)
    d.update(gap_front_ms=25_000)
    ok, conf = d.should_cover(our_tyre_status="fresh")
    assert ok is False
    assert conf == 0.0
```

- [ ] **Step B-1a: Run to verify FAIL**

```
py -3.12 -m pytest tests/test_strategy_sprint.py::test_opponent_no_pit_on_small_gap_change -v
```
Expected: `ModuleNotFoundError: No module named 'core.strategy_ai.opponents'`

### Step B-2: Create core/strategy_ai/opponents.py

```python
"""
core/strategy_ai/opponents.py
================================
Detect when the car ahead has pitted using gap_front_ms changes.
No UDP parser changes needed — a sudden gap increase > PIT_GAP_THRESHOLD_MS
is a reliable signal that the car ahead entered the pit lane.
"""
from __future__ import annotations

PIT_GAP_THRESHOLD_MS = 12_000
COVER_WINDOW = 10     # updates (~10 s at 1 update/s) the signal stays active


class OpponentPitDetector:
    """Detect opponent pit from gap_front_ms changes."""

    def __init__(self) -> None:
        self._prev_gap: int | None = None
        self._cover_counter: int = 0

    def update(self, gap_front_ms: int | None) -> None:
        if gap_front_ms is None:
            return
        if self._prev_gap is not None:
            delta = gap_front_ms - self._prev_gap
            if delta > PIT_GAP_THRESHOLD_MS:
                self._cover_counter = COVER_WINDOW
            elif self._cover_counter > 0:
                self._cover_counter -= 1
        self._prev_gap = gap_front_ms

    @property
    def opponent_pitted(self) -> bool:
        return self._cover_counter > 0

    def should_cover(self, our_tyre_status: str) -> tuple[bool, float]:
        """Return (cover_recommended, confidence).

        Only recommend covering if opponent pitted AND our tyres need changing.
        """
        if not self.opponent_pitted:
            return False, 0.0
        if our_tyre_status not in ("worn", "critical", "cliff"):
            return False, 0.0
        conf = 0.75 if our_tyre_status == "cliff" else 0.65
        return True, conf
```

- [ ] **Step B-2a: Run opponent tests — expect pass**

```
py -3.12 -m pytest tests/test_strategy_sprint.py -v -k "opponent"
```
Expected: 4 passed.

- [ ] **Step B-2b: Run full suite**

```
py -3.12 -m pytest tests/ --ignore=tests/test_gpt.py -q
```
Expected: 262 passed.

---

## Task C: Integrate everything in strategy.py

**Files:**
- Modify: `core/strategy_ai/strategy.py`
- Modify: `tests/test_strategy_sprint.py`

### Step C-1: Add integration tests

Append to `tests/test_strategy_sprint.py`:

```python
# ---------------------------------------------------------------------------
# StrategyAnalyzer — confidence filter + cover event + new state fields
# ---------------------------------------------------------------------------

from core.strategy_ai.strategy import StrategyAnalyzer


def _snapshot(**kw) -> dict:
    defaults = {
        "player_lap": 15,
        "total_laps": 50,
        "player_pos": 5,
        "gap_front_ms": 2_000,
        "gap_behind_ms": 3_000,
        "gap_leader_ms": 15_000,
        "tyre_compound": "M",
        "tyre_age": 10,
        "tyre_wear": 30.0,
        "last_lap_ms": 90_000,
        "fuel": 20.0,
    }
    return {**defaults, **kw}


def test_confidence_filter_blocks_low_conf_event():
    """Events below MIN_CONFIDENCE_EMIT should not be returned."""
    # detect_overcut fires with ~0.5 conf for a mid-range gap → should be blocked
    a = StrategyAnalyzer()
    ev = a.update(_snapshot(
        tyre_age=10, tyre_wear=30.0,     # fresh — no pit, no undercut
        gap_front_ms=5_000,              # overcut range but barely → low conf
        tyre_compound="H",
    ))
    # Either None or, if emitted, confidence must be >= 0.55
    if ev is not None:
        assert ev.confidence >= 0.55


def test_confidence_filter_allows_high_conf_event():
    """A clearly critical tyre situation must fire at ≥ 0.55."""
    a = StrategyAnalyzer()
    ev = a.update(_snapshot(
        tyre_age=40, tyre_wear=80.0,     # cliff status → pit_window fires at 0.92
        laps_remaining=10,
    ))
    assert ev is not None
    assert ev.confidence >= 0.55


def test_cover_event_when_opponent_pits_and_tyres_worn():
    """When gap_front jumps > 12s and our tyres are worn → cover event."""
    a = StrategyAnalyzer()
    # Prime the detector: first update with small gap
    a.update(_snapshot(gap_front_ms=2_000, tyre_age=25, tyre_wear=52.0))
    # Second update: gap jumped → opponent pitted
    ev = a.update(_snapshot(gap_front_ms=28_000, tyre_age=26, tyre_wear=54.0))
    assert ev is not None
    assert ev.type == "cover_opponent"
    assert ev.confidence >= 0.6


def test_get_state_has_fuel_mode_and_pace_trend():
    """get_state() must include fuel_mode and pace_trend keys."""
    a = StrategyAnalyzer()
    a.update(_snapshot())
    s = a.get_state()
    assert "fuel_mode" in s
    assert "pace_trend" in s
    assert s["fuel_mode"] in ("attack", "normal", "save")
    assert s["pace_trend"] in ("rising", "falling", "stable")
```

- [ ] **Step C-1a: Run to verify FAIL**

```
py -3.12 -m pytest tests/test_strategy_sprint.py -v -k "confidence or cover or fuel_mode"
```
Expected: failures on missing keys / wrong behavior.

### Step C-2: Rewrite strategy.py

Replace `core/strategy_ai/strategy.py` with:

```python
"""
core/strategy_ai/strategy.py
==============================
StrategyAnalyzer: orchestrates tyre, pit-window and pace logic.
Called once per telemetry snapshot (~1 s). Must complete in <5 ms.
No I/O, no network, no LLM.
"""
from __future__ import annotations

from core.strategy_ai.analysis import (
    FuelTracker,
    LapRecord,
    PaceTracker,
    fuel_save_recommended,
    pace_mode,
)
from core.strategy_ai.models import StrategyAIState, StrategyDecision, StrategyEvent
from core.strategy_ai.opponents import OpponentPitDetector
from core.strategy_ai.pit_window import (
    detect_overcut,
    detect_pit_window,
    detect_undercut,
)
from core.strategy_ai.tyres import tyre_status

# Events below this threshold are silently dropped — avoids noisy low-confidence chatter.
MIN_CONFIDENCE_EMIT = 0.55

_ADVICE_RU: dict[str, str] = {
    "cover_opponent":     "Соперник в боксах! Прикрой — пора в пит-стоп.",
    "undercut_available": "Андеркат возможен — готовься к пит-стопу.",
    "overcut_available":  "Оверкат: держись на трассе, соперник в боксах.",
    "pit_window_open":    "Окно пит-стопа открыто.",
    "tyre_degradation":   "Береги шины, темп шин растёт.",
    "push_pace":          "Можно давить — шины держат.",
    "fuel_save":          "Экономь топливо до финиша.",
    "hold_pace":          "Держи стабильный темп.",
}


class StrategyAnalyzer:
    """Single-instance, stateful race strategy engine."""

    def __init__(self) -> None:
        self._prev_player_lap: int | None = None
        self._prev_lap_ms: int | None = None
        self._pace_tracker = PaceTracker()
        self._fuel_tracker = FuelTracker()
        self._pit_detector = OpponentPitDetector()
        self._state = StrategyAIState(
            action="hold",
            confidence=0.0,
            reason="hold_pace",
            advice=None,
            mode="HOLD",
            tyre_status="unknown",
            current_event=None,
        )

    def update(self, snapshot: dict) -> StrategyEvent | None:
        """Analyse one telemetry snapshot. Returns StrategyEvent or None.

        snapshot keys (all optional):
            player_lap, total_laps, player_pos,
            gap_front_ms, gap_behind_ms, gap_leader_ms,
            tyre_compound, tyre_age, tyre_wear,
            last_lap_ms, fuel
        """
        player_lap = snapshot.get("player_lap")
        total_laps = snapshot.get("total_laps")
        gap_front = snapshot.get("gap_front_ms")
        gap_behind = snapshot.get("gap_behind_ms")
        compound = snapshot.get("tyre_compound")
        tyre_age = snapshot.get("tyre_age")
        tyre_wear = snapshot.get("tyre_wear")
        last_lap = snapshot.get("last_lap_ms")
        fuel = snapshot.get("fuel")

        laps_remaining = None
        if player_lap is not None and total_laps:
            laps_remaining = total_laps - player_lap

        t_status = tyre_status(tyre_age, tyre_wear, compound)

        # --- Update pace tracker on new lap ---
        if last_lap is not None:
            prev = self._prev_lap_ms
            self._prev_lap_ms = last_lap
        else:
            prev = self._prev_lap_ms

        if (
            player_lap is not None
            and player_lap != self._prev_player_lap
            and last_lap is not None
        ):
            self._pace_tracker.push(LapRecord(
                lap_number=player_lap,
                lap_time_ms=last_lap,
                tyre_compound=compound,
                tyre_age=tyre_age,
            ))
            self._prev_player_lap = player_lap

        # --- Update fuel tracker ---
        if fuel is not None and player_lap is not None:
            self._fuel_tracker.push(player_lap, fuel)

        # --- Update opponent pit detector ---
        self._pit_detector.update(gap_front)

        # --- Decision tree ---
        event: StrategyEvent | None = None
        decision = StrategyDecision(action="hold", confidence=0.4, reason="hold_pace")

        # Priority 1: Cover opponent pit
        cover_ok, cover_conf = self._pit_detector.should_cover(t_status)
        if cover_ok:
            decision = StrategyDecision(
                action="pit",
                confidence=cover_conf,
                reason="cover_opponent",
                data={
                    "gap_front_s": round(gap_front / 1000.0, 2) if gap_front else None,
                    "tyre_age": tyre_age,
                    "tyre_status": t_status,
                },
            )
            event = StrategyEvent(
                type="cover_opponent",
                priority="high",
                confidence=cover_conf,
                decision=decision,
                data=dict(decision.data),
            )

        # Priority 2: Undercut
        if not event:
            ok, conf = detect_undercut(
                gap_front, tyre_age, tyre_wear, laps_remaining, compound)
            if ok:
                decision = StrategyDecision(
                    action="pit",
                    confidence=conf,
                    reason="undercut_available",
                    data={
                        "gap_front_s": round(gap_front / 1000.0, 2) if gap_front else None,
                        "laps_remaining": laps_remaining,
                        "tyre_age": tyre_age,
                        "tyre_wear": tyre_wear,
                    },
                )
                event = StrategyEvent(
                    type="undercut",
                    priority="high" if conf > 0.75 else "medium",
                    confidence=conf,
                    decision=decision,
                    data=dict(decision.data),
                )

        # Priority 3: Pit window
        if not event:
            open_win, conf, laps_to_pit = detect_pit_window(
                tyre_age, tyre_wear, laps_remaining, compound)
            if open_win:
                decision = StrategyDecision(
                    action="pit",
                    confidence=conf,
                    reason="pit_window_open",
                    data={
                        "laps_to_pit": laps_to_pit,
                        "laps_remaining": laps_remaining,
                        "tyre_age": tyre_age,
                        "tyre_wear": tyre_wear,
                    },
                )
                event = StrategyEvent(
                    type="pit_window",
                    priority="high" if conf > 0.8 else "medium",
                    confidence=conf,
                    decision=decision,
                    data=dict(decision.data),
                )

        # Priority 4: Overcut
        if not event:
            ok, conf = detect_overcut(
                gap_front, tyre_age, tyre_wear, laps_remaining, compound)
            if ok:
                decision = StrategyDecision(
                    action="hold",
                    confidence=conf,
                    reason="overcut_available",
                    data={
                        "gap_front_s": round(gap_front / 1000.0, 2) if gap_front else None,
                        "laps_remaining": laps_remaining,
                    },
                )
                event = StrategyEvent(
                    type="overcut",
                    priority="medium",
                    confidence=conf,
                    decision=decision,
                    data=dict(decision.data),
                )

        # Priority 5: Fuel save
        if not event:
            fuel_ok, fuel_conf = fuel_save_recommended(fuel, laps_remaining)
            if fuel_ok:
                decision = StrategyDecision(
                    action="save",
                    confidence=fuel_conf,
                    reason="fuel_save",
                    data={"fuel": fuel, "laps_remaining": laps_remaining},
                )
                event = StrategyEvent(
                    type="fuel_save",
                    priority="medium",
                    confidence=fuel_conf,
                    decision=decision,
                    data=dict(decision.data),
                )

        # Priority 6: Pace mode
        if not event:
            mode, mode_conf = pace_mode(
                last_lap, prev, gap_front, gap_behind,
                tyre_age, tyre_wear, compound)
            if mode == "save":
                decision = StrategyDecision(
                    action="save",
                    confidence=mode_conf,
                    reason="tyre_degradation",
                    data={
                        "tyre_age": tyre_age,
                        "tyre_wear": tyre_wear,
                        "laps_remaining": laps_remaining,
                    },
                )
                event = StrategyEvent(
                    type="tyre_save",
                    priority="low",
                    confidence=mode_conf,
                    decision=decision,
                    data=dict(decision.data),
                )
            elif mode == "push":
                decision = StrategyDecision(
                    action="push",
                    confidence=mode_conf,
                    reason="push_pace",
                    data={
                        "gap_front_s": round(gap_front / 1000.0, 2) if gap_front else None,
                    },
                )
                event = StrategyEvent(
                    type="push_pace",
                    priority="low",
                    confidence=mode_conf,
                    decision=decision,
                    data=dict(decision.data),
                )

        # --- Confidence filter: drop low-confidence events ---
        if event is not None and event.confidence < MIN_CONFIDENCE_EMIT:
            event = None
            decision = StrategyDecision(action="hold", confidence=0.4, reason="hold_pace")

        # --- Build advice string ---
        mode_map = {"pit": "PIT", "push": "PUSH", "save": "SAVE", "hold": "HOLD"}
        advice = _ADVICE_RU.get(decision.reason)
        if event and event.type == "pit_window" and decision.data.get("laps_to_pit") is not None:
            n = int(decision.data["laps_to_pit"])
            if n % 10 == 1 and n % 100 != 11:
                advice = f"Пит через {n} круг."
            elif 2 <= n % 10 <= 4 and n % 100 not in (12, 13, 14):
                advice = f"Пит через {n} круга."
            else:
                advice = f"Пит через {n} кругов."

        self._state = StrategyAIState(
            action=decision.action,
            confidence=decision.confidence,
            reason=decision.reason,
            advice=advice,
            mode=mode_map.get(decision.action, "HOLD"),
            tyre_status=t_status,
            current_event=event,
        )
        return event

    def get_state(self) -> dict:
        """Return serialisable dict for API / engine state."""
        s = self._state
        event_dict = None
        if s.current_event:
            e = s.current_event
            event_dict = {
                "type": e.type,
                "priority": e.priority,
                "confidence": e.confidence,
                "action": e.decision.action,
                "reason": e.decision.reason,
                "data": e.data,
            }
        laps_remaining = None
        # Compute laps_remaining from internal state for tracker queries
        _state_event = s.current_event
        lr = (_state_event.data.get("laps_remaining") if _state_event else None)
        return {
            "action": s.action,
            "confidence": s.confidence,
            "reason": s.reason,
            "advice": s.advice,
            "mode": s.mode,
            "tyre_status": s.tyre_status,
            "current_event": event_dict,
            "fuel_mode": self._fuel_tracker.fuel_mode(lr),
            "pace_trend": self._pace_tracker.trend(),
        }
```

- [ ] **Step C-2a: Run integration tests — expect pass**

```
py -3.12 -m pytest tests/test_strategy_sprint.py -v
```
Expected: 14 passed.

- [ ] **Step C-2b: Run full test suite**

```
py -3.12 -m pytest tests/ --ignore=tests/test_gpt.py -q
```
Expected: **276 passed** (262 + 14 new).

---

## Task D: Final validation

- [ ] **Step D-1: Run full suite one final time**

```
py -3.12 -m pytest tests/ --ignore=tests/test_gpt.py -v --tb=short 2>&1 | tail -20
```
Expected: all 276 tests passed, 0 failed.

- [ ] **Step D-2: Update CONTEXT.md counter**

The counter was reset to `0/2` after Task 8. This mini-sprint counts as 1 task.
Open `CONTEXT.md`, find the counter line, increment to `1/2`.
Add a new section under the task log:

```markdown
## Mini-Sprint: Strategy AI Realism (2026-06-25)
- PaceTracker: rolling 5-lap history, trend (rising/falling/stable), pace_delta
- FuelTracker: actual per-lap consumption rate, fuel_mode (attack/normal/save)  
- OpponentPitDetector: gap-change-based pit detection, cover recommendation
- MIN_CONFIDENCE_EMIT = 0.55: low-confidence events suppressed
- get_state() now includes fuel_mode + pace_trend
- 14 new tests in tests/test_strategy_sprint.py
```

---

## Self-Review

**Spec coverage check:**
1. Pace delta tracking ✅ — `PaceTracker` stores last 5 laps, computes delta and trend (Task A)
2. Opponent strategy tracking ✅ — `opponents.py`, `OpponentPitDetector`, undercut/cover detection (Task B)
3. Safety margins ✅ — `MIN_CONFIDENCE_EMIT = 0.55` filter in `strategy.py` (Task C)
4. Fuel model ✅ — `FuelTracker` with actual rate + modes attack/normal/save (Task A + C)
5. Tests ✅ — 14 tests: pace trend, fuel mode, opponent undercut, false-pit prevention, confidence filtering (Task D)

**"Do not change API" ✅** — only new optional fields added to `get_state()` dict; no endpoint changes

**"Do not change UI" ✅** — no `.tsx`/`.ts` files touched

**Type consistency ✅** — `LapRecord` defined in Task A, used in Task A tests and Task C code; `FuelTracker.fuel_mode()` returns `str`, matches `get_state()["fuel_mode"]` type
