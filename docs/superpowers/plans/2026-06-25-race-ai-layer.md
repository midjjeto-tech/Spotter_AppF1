# Race Situation Intelligence Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic race analysis layer (`core/race_ai/`) between the telemetry parser and the LLM commentator, so the app can detect threats, battles, and race intensity from raw UDP data — before any AI call.

**Architecture:** Pure Python analysis runs inside `_maybe_snapshot()` (already called per LAP_DATA packet, once per ~1s). The analyzer receives a plain dict snapshot built from existing engine fields (`_player_gap_behind`, `_player_drs_active`, etc.), computes a `RaceEvent`, and puts it into the existing `event_queue`. The current commentary pipeline (brain.py → LLM or templates) handles the event unchanged.

**Tech Stack:** Python 3.12 dataclasses, `collections.deque`, `struct` (already used), `pytest`. No external dependencies. No network calls. Target latency <5ms per `update()`.

---

## Data Available in engine.py (no new parsing needed)

| Field | Source | Used for |
|---|---|---|
| `_player_gap_behind` | `parse_lap_data` gaps_front[car_behind] | Threat distance (ms) |
| `_player_gap_front` | `parse_player_lap` gap_front_ms | Gap to car ahead (ms) |
| `_player_pos` | `parse_player_lap` position | Player position |
| `_player_lap` | `parse_player_lap` current_lap | Current lap |
| `_total_laps` | `parse_session` total_laps | Laps remaining calc |
| `_player_drs_active` | **NEW** — set from DRSE/DRSD events | DRS flag for threat |
| `_player_tyre_age` | `parse_player_status` tyre_age | Tyre warning trigger |
| `_player_tyre_wear` | `parse_player_damage` tyre_wear | Tyre warning trigger |
| driver behind name | `race_state.driver(idx_behind)["name"]` | Event driver field |

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `core/race_ai/__init__.py` | Package marker |
| Create | `core/race_ai/models.py` | `RaceEvent`, `RaceAIState` dataclasses |
| Create | `core/race_ai/sectors.py` | `get_sector(pct) -> int` |
| Create | `core/race_ai/threat.py` | `detect_threat(...) -> (bool, float)` |
| Create | `core/race_ai/intensity.py` | `calculate_intensity(...) -> int`, `get_mode(int) -> str` |
| Create | `core/race_ai/battles.py` | `BattleDetector` class with `update()` |
| Create | `core/race_ai/decisions.py` | `make_decision(event, ...) -> dict` |
| Create | `core/race_ai/analyzer.py` | `RaceAnalyzer` — orchestrates above |
| Create | `commentator/engineer.py` | `get_message(event_type, data) -> str` — no LLM |
| Modify | `commentator/templates.py` | Add ATTACK/BATTLE/FINAL_LAP/TYRE_WARN cases |
| Modify | `core/engine.py` | Add `_player_drs_active`, `RaceAnalyzer`, `get_race_ai_state()` |
| Modify | `web_server.py` | Add `GET /api/race-ai` |
| Create | `tests/test_race_ai.py` | Unit tests for all components |

---

## Task 1: models.py

**Files:**
- Create: `core/race_ai/__init__.py`
- Create: `core/race_ai/models.py`

- [ ] **Step 1: Create `core/race_ai/__init__.py`** (empty file)

```python
```

- [ ] **Step 2: Create `core/race_ai/models.py`**

```python
"""
core/race_ai/models.py
=======================
Data types shared by all race_ai modules.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class RaceEvent:
    """One deterministic race situation detected from telemetry."""
    type: str           # "attack" | "battle" | "tyre_warning" | "final_lap"
    priority: str       # "high" | "medium" | "low"
    confidence: float   # 0.0–1.0
    driver: str         # name of attacking / relevant driver
    target: str         # "player" or driver name
    data: dict = field(default_factory=dict)


@dataclass
class RaceAIState:
    """Current snapshot of race intelligence — returned by /api/race-ai."""
    intensity: int              # 0–100
    mode: str                   # "CALM" | "RACE" | "BATTLE" | "CLIMAX"
    current_event: RaceEvent | None
    threat: str | None          # human-readable, e.g. "Sainz атакует (0.8с)"
    advice: str | None          # human-readable, e.g. "cover_inside"
```

- [ ] **Step 3: Verify imports work**

```
py -3.12 -c "from core.race_ai.models import RaceEvent, RaceAIState; print('OK')"
```

Expected output: `OK`

---

## Task 2: sectors.py

**Files:**
- Create: `core/race_ai/sectors.py`
- Test: `tests/test_race_ai.py` (first 2 tests)

- [ ] **Step 1: Write failing test for sectors**

Create `tests/test_race_ai.py`:

```python
"""Tests for Race Situation Intelligence Layer."""
import pytest
from core.race_ai.sectors import get_sector


def test_sector_boundaries():
    assert get_sector(0.00) == 1
    assert get_sector(0.15) == 1
    assert get_sector(0.329) == 1
    assert get_sector(0.33) == 2
    assert get_sector(0.55) == 2
    assert get_sector(0.669) == 2
    assert get_sector(0.67) == 3
    assert get_sector(0.88) == 3
    assert get_sector(1.00) == 3


def test_sector_clamps_invalid():
    assert get_sector(-0.1) == 1   # below 0 → sector 1
    assert get_sector(1.5) == 3    # above 1 → sector 3
```

- [ ] **Step 2: Run test to verify it fails**

```
py -3.12 -m pytest tests/test_race_ai.py::test_sector_boundaries -v
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'core.race_ai.sectors'`

- [ ] **Step 3: Create `core/race_ai/sectors.py`**

```python
"""
core/race_ai/sectors.py
========================
Determine race sector (1, 2, 3) from lap distance percentage.
"""


def get_sector(lap_distance_pct: float) -> int:
    """Return sector number (1, 2, or 3) for a given lap completion fraction.

    Boundaries: 0–33% → S1, 33–67% → S2, 67–100% → S3.
    Values outside [0, 1] clamp gracefully.
    """
    if lap_distance_pct < 0.33:
        return 1
    if lap_distance_pct < 0.67:
        return 2
    return 3
```

- [ ] **Step 4: Run tests to verify they pass**

```
py -3.12 -m pytest tests/test_race_ai.py -v
```

Expected: `2 passed`

---

## Task 3: threat.py

**Files:**
- Create: `core/race_ai/threat.py`
- Modify: `tests/test_race_ai.py` (add 4 tests)

- [ ] **Step 1: Add threat detection tests**

Append to `tests/test_race_ai.py`:

```python
from core.race_ai.threat import detect_threat

THREAT_GAP = 900   # ms — safely under 1000ms threshold


def test_no_threat_when_gap_large():
    is_threat, conf = detect_threat(gap_behind_ms=1500, drs_active=False,
                                    gap_closing=False, laps_remaining=None)
    assert is_threat is False
    assert conf == 0.0


def test_threat_when_gap_below_1s():
    is_threat, conf = detect_threat(gap_behind_ms=THREAT_GAP, drs_active=False,
                                    gap_closing=False, laps_remaining=None)
    assert is_threat is True
    assert 0.4 < conf < 0.7   # base confidence only


def test_drs_increases_confidence():
    _, conf_no_drs = detect_threat(THREAT_GAP, False, False, None)
    _, conf_drs    = detect_threat(THREAT_GAP, True,  False, None)
    assert conf_drs > conf_no_drs


def test_missing_gap_no_threat():
    is_threat, conf = detect_threat(gap_behind_ms=None, drs_active=True,
                                    gap_closing=True, laps_remaining=3)
    assert is_threat is False
    assert conf == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

```
py -3.12 -m pytest tests/test_race_ai.py -k "threat" -v
```

Expected: `FAILED` — `ModuleNotFoundError`

- [ ] **Step 3: Create `core/race_ai/threat.py`**

```python
"""
core/race_ai/threat.py
=======================
Detect whether an opponent behind the player poses an attack threat.
"""

THREAT_GAP_MS = 1000   # gap below this (ms) → potential threat


def detect_threat(
    gap_behind_ms: int | None,
    drs_active: bool,
    gap_closing: bool,
    laps_remaining: int | None,
) -> tuple[bool, float]:
    """Return (is_threat, confidence).

    Confidence starts at 0.5 for any gap < 1s; increases with DRS, closing
    speed, final laps, and proximity.
    """
    if gap_behind_ms is None or gap_behind_ms <= 0 or gap_behind_ms >= THREAT_GAP_MS:
        return False, 0.0

    confidence = 0.5
    if drs_active:
        confidence += 0.15
    if gap_closing:
        confidence += 0.15
    if laps_remaining is not None and laps_remaining <= 5:
        confidence += 0.10
    if gap_behind_ms < 500:
        confidence += 0.10   # < 0.5s — very close

    return True, min(confidence, 1.0)
```

- [ ] **Step 4: Run all tests to verify they pass**

```
py -3.12 -m pytest tests/test_race_ai.py -v
```

Expected: `6 passed`

---

## Task 4: intensity.py

**Files:**
- Create: `core/race_ai/intensity.py`
- Modify: `tests/test_race_ai.py` (add 6 tests)

- [ ] **Step 1: Add intensity tests**

Append to `tests/test_race_ai.py`:

```python
from core.race_ai.intensity import calculate_intensity, get_mode


def test_intensity_zero_when_no_inputs():
    score = calculate_intensity(
        gap_behind_ms=None, drs_active=False,
        position_battle=False, laps_remaining=None,
        total_laps=None)
    assert score == 0


def test_intensity_adds_points():
    score = calculate_intensity(
        gap_behind_ms=800, drs_active=True,
        position_battle=True, laps_remaining=3,
        total_laps=50)
    assert score == 80   # 20+20+20+20 (final laps)


def test_intensity_clamped_to_100():
    score = calculate_intensity(
        gap_behind_ms=100, drs_active=True,
        position_battle=True, laps_remaining=2,
        total_laps=50, fastest_lap_set=True)
    assert score == 100


@pytest.mark.parametrize("intensity,expected_mode", [
    (10,  "CALM"),
    (40,  "RACE"),
    (70,  "BATTLE"),
    (90,  "CLIMAX"),
])
def test_mode_thresholds(intensity, expected_mode):
    assert get_mode(intensity) == expected_mode
```

- [ ] **Step 2: Run tests to verify they fail**

```
py -3.12 -m pytest tests/test_race_ai.py -k "intensity or mode" -v
```

Expected: `FAILED` — `ModuleNotFoundError`

- [ ] **Step 3: Create `core/race_ai/intensity.py`**

```python
"""
core/race_ai/intensity.py
==========================
Race intensity score (0–100) and named mode.
"""


def calculate_intensity(
    gap_behind_ms: int | None,
    drs_active: bool,
    position_battle: bool,
    laps_remaining: int | None,
    total_laps: int | None,
    fastest_lap_set: bool = False,
) -> int:
    """Score race intensity 0–100.

    +20 close gap (< 1s)
    +20 DRS active
    +20 active position battle (sustained proximity)
    +20 final laps (≤ 10% of race remaining, minimum 3 laps)
    +10 fastest lap just set
    Clamped to [0, 100].
    """
    score = 0
    if gap_behind_ms is not None and 0 < gap_behind_ms < 1000:
        score += 20
    if drs_active:
        score += 20
    if position_battle:
        score += 20
    if (laps_remaining is not None and total_laps is not None and total_laps > 0
            and laps_remaining <= max(3, total_laps // 10)):
        score += 20
    if fastest_lap_set:
        score += 10
    return min(score, 100)


def get_mode(intensity: int) -> str:
    """Map 0–100 intensity to named mode."""
    if intensity < 25:
        return "CALM"
    if intensity < 60:
        return "RACE"
    if intensity < 85:
        return "BATTLE"
    return "CLIMAX"
```

- [ ] **Step 4: Run all tests**

```
py -3.12 -m pytest tests/test_race_ai.py -v
```

Expected: `12 passed`

---

## Task 5: battles.py

**Files:**
- Create: `core/race_ai/battles.py`
- Modify: `tests/test_race_ai.py` (add 3 tests)

- [ ] **Step 1: Add battle detection tests**

Append to `tests/test_race_ai.py`:

```python
from core.race_ai.battles import BattleDetector


def test_battle_not_active_initially():
    det = BattleDetector()
    state = det.update(gap_behind_ms=2000, driver_behind="Sainz", player_driver="player")
    assert state.active is False


def test_battle_activates_after_sustained_proximity():
    det = BattleDetector()
    for _ in range(5):   # 5 readings within 1s gap
        state = det.update(800, "Sainz", "player")
    assert state.active is True
    assert "Sainz" in state.cars or "player" in state.cars


def test_battle_no_crash_on_none_gap():
    det = BattleDetector()
    state = det.update(gap_behind_ms=None, driver_behind="Norris", player_driver="player")
    assert state.active is False
    assert isinstance(state.intensity, int)
```

- [ ] **Step 2: Run tests to verify they fail**

```
py -3.12 -m pytest tests/test_race_ai.py -k "battle" -v
```

Expected: `FAILED` — `ModuleNotFoundError`

- [ ] **Step 3: Create `core/race_ai/battles.py`**

```python
"""
core/race_ai/battles.py
========================
Detect sustained battles — two cars within 1 second for multiple readings.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

BATTLE_GAP_MS = 1000
BATTLE_MIN_READINGS = 3   # readings within gap to count as active battle


@dataclass
class BattleState:
    active: bool
    cars: list[str]
    intensity: int   # 0–100, fraction of recent readings that were close


class BattleDetector:
    """Track proximity history to distinguish a momentary gap drop from a real battle."""

    def __init__(self, history_size: int = 10):
        self._history: deque[bool] = deque(maxlen=history_size)

    def update(
        self,
        gap_behind_ms: int | None,
        driver_behind: str,
        player_driver: str,
    ) -> BattleState:
        """Record one telemetry reading and return current battle state."""
        is_close = (gap_behind_ms is not None
                    and 0 < gap_behind_ms < BATTLE_GAP_MS)
        self._history.append(is_close)

        close_count = sum(self._history)
        active = close_count >= BATTLE_MIN_READINGS
        intensity = (int(close_count / len(self._history) * 100)
                     if self._history else 0)

        return BattleState(
            active=active,
            cars=[player_driver, driver_behind],
            intensity=intensity,
        )
```

- [ ] **Step 4: Run all tests**

```
py -3.12 -m pytest tests/test_race_ai.py -v
```

Expected: `15 passed`

---

## Task 6: decisions.py

**Files:**
- Create: `core/race_ai/decisions.py`
- Modify: `tests/test_race_ai.py` (add 3 tests)

- [ ] **Step 1: Add decision tests**

Append to `tests/test_race_ai.py`:

```python
from core.race_ai.decisions import make_decision
from core.race_ai.models import RaceEvent


def _make_attack(drs=False):
    return RaceEvent(type="attack", priority="high", confidence=0.8,
                     driver="Sainz", target="player", data={"drs": drs})


def test_attack_with_drs_returns_cover_inside():
    d = make_decision(_make_attack(drs=True), gap_front_ms=1500, gap_closing=True)
    assert d["action"] == "defend"
    assert d["advice"] == "cover_inside"


def test_attack_without_drs_returns_hold_line():
    d = make_decision(_make_attack(drs=False), gap_front_ms=1500, gap_closing=False)
    assert d["action"] == "defend"
    assert d["advice"] == "hold_line"


def test_tyre_warning_returns_pit_advice():
    event = RaceEvent(type="tyre_warning", priority="medium", confidence=0.8,
                      driver="player", target="", data={"age": 35, "wear": 75.0})
    d = make_decision(event, gap_front_ms=None, gap_closing=False)
    assert d["action"] == "pit"
```

- [ ] **Step 2: Run tests to verify they fail**

```
py -3.12 -m pytest tests/test_race_ai.py -k "decision" -v
```

Expected: `FAILED`

- [ ] **Step 3: Create `core/race_ai/decisions.py`**

```python
"""
core/race_ai/decisions.py
==========================
Convert a RaceEvent into a concrete action and advice string.
"""
from __future__ import annotations

from core.race_ai.models import RaceEvent

# Maps (event_type, drs) -> (action, advice)
_ATTACK_RULES: dict[bool, tuple[str, str]] = {
    True:  ("defend", "cover_inside"),
    False: ("defend", "hold_line"),
}


def make_decision(
    event: RaceEvent,
    gap_front_ms: int | None,
    gap_closing: bool,
) -> dict[str, str]:
    """Return {"action": ..., "advice": ...} for a given race event."""
    t = event.type

    if t == "attack":
        drs = bool(event.data.get("drs"))
        action, advice = _ATTACK_RULES[drs]
        return {"action": action, "advice": advice}

    if t == "battle":
        return {"action": "defend",
                "advice": "maintain_pace" if gap_closing else "monitor"}

    if t == "tyre_warning":
        return {"action": "pit", "advice": "consider_pit"}

    if t == "final_lap":
        return {"action": "push", "advice": "maximum_attack"}

    # Generic: decide by gap to car ahead
    if gap_front_ms is not None and gap_front_ms < 500:
        return {"action": "push", "advice": "attack_ahead"}
    return {"action": "hold_line", "advice": "focus"}
```

- [ ] **Step 4: Run all tests**

```
py -3.12 -m pytest tests/test_race_ai.py -v
```

Expected: `18 passed`

---

## Task 7: analyzer.py

**Files:**
- Create: `core/race_ai/analyzer.py`
- Modify: `tests/test_race_ai.py` (add 5 tests)

- [ ] **Step 1: Add analyzer tests**

Append to `tests/test_race_ai.py`:

```python
from core.race_ai.analyzer import RaceAnalyzer


def _snapshot(gap_behind=None, gap_front=None, drs=False,
              pos=5, lap=10, total=50, driver_behind="Sainz",
              tyre_age=None, tyre_wear=None):
    return {
        "gap_behind_ms": gap_behind,
        "gap_front_ms": gap_front,
        "drs_active": drs,
        "player_pos": pos,
        "player_lap": lap,
        "total_laps": total,
        "driver_behind": driver_behind,
        "tyre_age": tyre_age,
        "tyre_wear": tyre_wear,
    }


def test_attack_event_on_close_gap():
    ra = RaceAnalyzer()
    event = ra.update(_snapshot(gap_behind=800))
    assert event is not None
    assert event.type == "attack"
    assert event.driver == "Sainz"


def test_no_event_when_gap_large():
    ra = RaceAnalyzer()
    event = ra.update(_snapshot(gap_behind=3000))
    assert event is None


def test_missing_telemetry_no_crash():
    ra = RaceAnalyzer()
    event = ra.update({})   # empty snapshot — must not raise
    assert event is None


def test_get_state_returns_dict():
    ra = RaceAnalyzer()
    ra.update(_snapshot(gap_behind=700, drs=True))
    s = ra.get_state()
    assert "intensity" in s
    assert "mode" in s
    assert "threat" in s
    assert "advice" in s


def test_tyre_warning_event():
    ra = RaceAnalyzer()
    event = ra.update(_snapshot(tyre_age=35, tyre_wear=65.0))
    assert event is not None
    assert event.type == "tyre_warning"
```

- [ ] **Step 2: Run tests to verify they fail**

```
py -3.12 -m pytest tests/test_race_ai.py -k "analyzer or attack_event or no_event or missing_telemetry or get_state or tyre_warning" -v
```

Expected: `FAILED`

- [ ] **Step 3: Create `core/race_ai/analyzer.py`**

```python
"""
core/race_ai/analyzer.py
=========================
RaceAnalyzer: orchestrates threat, battle, intensity, and decision logic.
Called once per telemetry snapshot (~1 s). Must complete in <5 ms.
No I/O, no network, no LLM.
"""
from __future__ import annotations

from core.race_ai.models import RaceEvent, RaceAIState
from core.race_ai.threat import detect_threat
from core.race_ai.intensity import calculate_intensity, get_mode
from core.race_ai.battles import BattleDetector
from core.race_ai.decisions import make_decision

TYRE_AGE_WARN = 30    # laps
TYRE_WEAR_WARN = 60.0 # percent


class RaceAnalyzer:
    """Single-instance, stateful race intelligence engine."""

    def __init__(self):
        self.battle_detector = BattleDetector()
        self._state = RaceAIState(
            intensity=0, mode="CALM", current_event=None,
            threat=None, advice=None)
        self._prev_gap_behind: int | None = None

    def update(self, snapshot: dict) -> RaceEvent | None:
        """Analyse one telemetry snapshot. Returns RaceEvent or None."""
        gap_behind   = snapshot.get("gap_behind_ms")
        gap_front    = snapshot.get("gap_front_ms")
        drs_active   = bool(snapshot.get("drs_active", False))
        player_pos   = snapshot.get("player_pos")
        player_lap   = snapshot.get("player_lap")
        total_laps   = snapshot.get("total_laps")
        driver_behind = snapshot.get("driver_behind") or "оппонент"
        tyre_age     = snapshot.get("tyre_age")
        tyre_wear    = snapshot.get("tyre_wear")

        gap_closing = (
            self._prev_gap_behind is not None
            and gap_behind is not None
            and gap_behind < self._prev_gap_behind)
        self._prev_gap_behind = gap_behind

        laps_remaining = None
        if player_lap and total_laps:
            laps_remaining = total_laps - player_lap

        is_threat, confidence = detect_threat(
            gap_behind, drs_active, gap_closing, laps_remaining)

        battle = self.battle_detector.update(gap_behind, driver_behind, "player")

        intensity = calculate_intensity(
            gap_behind, drs_active, battle.active, laps_remaining, total_laps)
        mode = get_mode(intensity)

        event: RaceEvent | None = None

        if is_threat:
            event = RaceEvent(
                type="attack",
                priority="high" if confidence > 0.7 else "medium",
                confidence=confidence,
                driver=driver_behind,
                target="player",
                data={
                    "gap": round(gap_behind / 1000.0, 2) if gap_behind else None,
                    "drs": drs_active,
                    "closing": gap_closing,
                    "intensity": intensity,
                },
            )
        elif battle.active:
            event = RaceEvent(
                type="battle",
                priority="medium",
                confidence=0.7,
                driver=driver_behind,
                target="player",
                data={"intensity": battle.intensity,
                      "gap": round(gap_behind / 1000.0, 2) if gap_behind else None},
            )
        elif laps_remaining is not None and laps_remaining <= 3:
            event = RaceEvent(
                type="final_lap",
                priority="medium",
                confidence=1.0,
                driver="player",
                target="",
                data={"laps_remaining": laps_remaining},
            )
        elif (tyre_age is not None and tyre_age > TYRE_AGE_WARN
              and tyre_wear is not None and tyre_wear > TYRE_WEAR_WARN):
            event = RaceEvent(
                type="tyre_warning",
                priority="medium",
                confidence=0.85,
                driver="player",
                target="",
                data={"age": tyre_age, "wear": tyre_wear},
            )

        threat_text: str | None = None
        advice_text: str | None = None

        if event:
            decision = make_decision(event, gap_front, gap_closing)
            advice_text = decision.get("advice")

        if is_threat and gap_behind:
            threat_text = f"{driver_behind} атакует ({gap_behind / 1000:.1f}с)"

        self._state = RaceAIState(
            intensity=intensity,
            mode=mode,
            current_event=event,
            threat=threat_text,
            advice=advice_text,
        )
        return event

    def get_state(self) -> dict:
        s = self._state
        event_dict = None
        if s.current_event:
            e = s.current_event
            event_dict = {
                "type": e.type, "priority": e.priority,
                "confidence": e.confidence, "driver": e.driver,
                "target": e.target, "data": e.data,
            }
        return {
            "intensity": s.intensity,
            "mode": s.mode,
            "current_event": event_dict,
            "threat": s.threat,
            "advice": s.advice,
        }
```

- [ ] **Step 4: Run all tests**

```
py -3.12 -m pytest tests/test_race_ai.py -v
```

Expected: `23 passed`

---

## Task 8: commentator/engineer.py

**Files:**
- Create: `commentator/engineer.py`
- Modify: `commentator/templates.py` — add race_ai event codes

- [ ] **Step 1: Create `commentator/engineer.py`**

```python
"""
commentator/engineer.py
========================
Template-only engineer messages for race_ai events. No LLM. Max 20 words.
"""
from __future__ import annotations

import random

_MESSAGES: dict[str, list[str]] = {
    "attack": [
        "Соперник атакует. DRS активен. Защищай позицию.",
        "Он рядом. Готовься к защите.",
        "Смотри в зеркала. Он давит.",
    ],
    "attack_high": [
        "Он на крыле! Немедленно защищай.",
        "Атака! Держи позицию, закрой внутреннюю.",
    ],
    "battle": [
        "Борьба продолжается. Сохраняй темп.",
        "Он не уходит. Контролируй зеркала.",
    ],
    "tyre_warning": [
        "Пора заезжать в боксы. Шины на исходе.",
        "Износ критический. Думаем о пит-стопе.",
    ],
    "final_lap": [
        "Финальные круги. Максимальный темп.",
        "Последние круги — выжми всё.",
    ],
    "stable": [
        "Отрыв стабилен.",
        "Ситуация под контролем.",
    ],
}


def get_message(event_type: str, data: dict | None = None) -> str:
    """Return a random template message for the given race_ai event type.

    High-confidence attacks get a more urgent variant.
    Falls back to "stable" message for unknown types.
    """
    data = data or {}
    confidence = data.get("confidence", 0.5)

    if event_type == "attack" and confidence > 0.75:
        pool = _MESSAGES.get("attack_high", _MESSAGES["attack"])
    else:
        pool = _MESSAGES.get(event_type, _MESSAGES["stable"])

    return random.choice(pool)
```

- [ ] **Step 2: Add RACE_AI event codes to `commentator/templates.py`**

Find the `render()` function or the `SIMPLE` dict in `commentator/templates.py`. Add the following at an appropriate place (before the `render()` function, or inside it as a new branch):

First read the current templates.py to find the right place to insert:
```
py -3.12 -c "import commentator.templates as t; print(dir(t))"
```

Then add this dict to templates.py and update render():

```python
# In templates.py — add this import at the top:
from commentator import engineer as _engineer

# Add these codes to the SIMPLE dict (or handle in render()):
# RACE_AI event codes — delegated to engineer.py templates:
#   "ATTACK", "BATTLE", "TYRE_WARN", "FINAL_LAP"

# In the render() function, add BEFORE the existing SIMPLE lookup:
    if event.get("event_code") in ("ATTACK", "BATTLE", "TYRE_WARN", "FINAL_LAP"):
        return _engineer.get_message(
            event.get("race_ai_type", event["event_code"].lower()),
            event.get("race_ai_data"),
        )
```

The exact insertion point depends on the current templates.py structure — read it first.

- [ ] **Step 3: Verify engineer imports and basic call**

```
py -3.12 -c "from commentator.engineer import get_message; print(get_message('attack', {'confidence': 0.9}))"
```

Expected: one of the high-urgency attack messages.

---

## Task 9: engine.py integration

**Files:**
- Modify: `core/engine.py`

Four small changes, each surgical:

- [ ] **Step 1: Add `_player_drs_active` field and DRS event tracking**

In `__init__`, after the other `_player_*` fields (around line 94), add:
```python
self._player_drs_active: bool = False
```

In `_update_telemetry`, in the `if packet_id == PACKET_EVENT:` block — but that's in `_telemetry_loop`, not `_update_telemetry`. Actually DRS events come as DRSE/DRSD in `_telemetry_loop`. Find where `event = parse_event(data)` is handled and add:

```python
# DRS tracking for race_ai (inside the PACKET_EVENT handling block,
# after `event = parse_event(data)`, before queue put)
if event is not None:
    code = event.get("event_code")
    if code == "DRSE":
        self._player_drs_active = True
    elif code == "DRSD":
        self._player_drs_active = False
```

(This block already exists at lines ~639-689. Add the DRS tracking after `event = parse_event(data)` and `if event is None: continue`.)

- [ ] **Step 2: Add RaceAnalyzer import and instantiation**

At the top of engine.py, add import:
```python
from core.race_ai.analyzer import RaceAnalyzer
```

In `__init__`, after `self.timeline = RaceTimeline(...)`:
```python
self.race_analyzer = RaceAnalyzer()
```

Also add state key in `self.state`:
```python
"race_ai": {"intensity": 0, "mode": "CALM", "current_event": None,
             "threat": None, "advice": None},
```

- [ ] **Step 3: Call race_analyzer in `_maybe_snapshot`**

`_maybe_snapshot` is called once per LAP_DATA packet (throttled to ~1s). At the **end** of `_maybe_snapshot`, after the `self.timeline.record_snapshot(...)` call, add:

```python
# Build snapshot for race_ai (extract name of driver behind player)
driver_behind_name = None
if self._player_pos is not None:
    idx_behind = next(
        (i for i, p in self._positions.items() if p == self._player_pos + 1),
        None)
    if idx_behind is not None:
        driver_behind_name = self.race_state.driver(idx_behind)["name"]

snapshot = {
    "gap_behind_ms": self._player_gap_behind,
    "gap_front_ms": self._player_gap_front,
    "drs_active": self._player_drs_active,
    "player_pos": self._player_pos,
    "player_lap": self._player_lap,
    "total_laps": getattr(self, "_total_laps", None),
    "driver_behind": driver_behind_name or "оппонент",
    "tyre_age": self._player_tyre_age,
    "tyre_wear": self._player_tyre_wear,
}
race_event = self.race_analyzer.update(snapshot)
with self.state_lock:
    self.state["race_ai"] = self.race_analyzer.get_state()

if race_event is not None:
    # Convert RaceEvent → event dict for commentary queue
    event_code = {
        "attack":       "ATTACK",
        "battle":       "BATTLE",
        "tyre_warning": "TYRE_WARN",
        "final_lap":    "FINAL_LAP",
    }.get(race_event.type, "ATTACK")
    self.event_queue.put({
        "event_code": event_code,
        "priority": race_event.priority,
        "driver": race_event.driver,
        "color": "#E4002B",
        "race_ai_type": race_event.type,
        "race_ai_data": {**race_event.data, "confidence": race_event.confidence},
    })
```

**IMPORTANT:** This adds an event per snapshot (~1s). To avoid spamming, add a cooldown to `_maybe_snapshot`:

```python
# After race_event = self.race_analyzer.update(snapshot)
if race_event is not None:
    now = time.time()
    last_ra = getattr(self, "_last_race_ai_event_t", 0.0)
    if now - last_ra >= 8.0:   # minimum 8s between race_ai events
        self._last_race_ai_event_t = now
        self.event_queue.put({ ... })
```

Add `self._last_race_ai_event_t: float = 0.0` to `__init__`.

- [ ] **Step 4: Add `get_race_ai_state()` method**

Add this method to F1Engine (near `get_state()`):

```python
def get_race_ai_state(self) -> dict:
    with self.state_lock:
        return dict(self.state.get("race_ai", {}))
```

- [ ] **Step 5: Verify engine imports OK**

```
py -3.12 -c "from core.engine import F1Engine; print('OK')"
```

Expected: `OK` (no ImportError)

---

## Task 10: web_server.py — GET /api/race-ai

**Files:**
- Modify: `web_server.py`

- [ ] **Step 1: Add endpoint**

Find where other `@app.route('/api/...')` endpoints are defined in `web_server.py`. Add:

```python
@app.route('/api/race-ai')
def api_race_ai():
    try:
        data = engine.get_race_ai_state()
        return json_response(data)
    except Exception as exc:
        return json_response({"error": str(exc)}, status=500)
```

(`json_response` is the existing helper in web_server.py — check its name and use it.)

- [ ] **Step 2: Verify endpoint accessible**

```
py -3.12 -c "
import sys; sys.argv=['']
from web_server import app
# Quick route check — don't start server
routes = [str(r) for r in app.routes]
print([r for r in routes if 'race' in r])
"
```

Expected: `['/api/race-ai']` in output.

---

## Task 11: Run full test suite

- [ ] **Step 1: Run all project tests**

```
py -3.12 -m pytest -q
```

Expected: all existing tests pass, plus the 23 new race_ai tests.
If any previously-passing tests fail, investigate before committing.

- [ ] **Step 2: Verify no import errors in key modules**

```
py -3.12 -m py_compile core/race_ai/models.py core/race_ai/sectors.py core/race_ai/threat.py core/race_ai/intensity.py core/race_ai/battles.py core/race_ai/decisions.py core/race_ai/analyzer.py commentator/engineer.py core/engine.py web_server.py
```

Expected: no output (silent = clean)

- [ ] **Step 3: Commit**

```
git init   # project is not under git — ask user first
# OR save files as-is (no git in this project per CONTEXT.md)
```

Note: Per CONTEXT.md, this project is **NOT under git**. No git commands needed. Just confirm all files are saved.

---

## Self-Review Checklist

### Spec Coverage

| Requirement | Task |
|---|---|
| `core/race_ai/` module with 7 files | Tasks 1–7 |
| `RaceEvent` dataclass with type/priority/confidence/driver/target/data | Task 1 |
| Threat detection: gap < 1s, DRS, closing speed, final laps | Task 3 |
| Sector detection from lap_distance_pct | Task 2 |
| Battle detection: 2 cars within 1s, repeated proximity | Task 5 |
| Intensity 0–100 with CALM/RACE/BATTLE/CLIMAX modes | Task 4 |
| Decision engine: attack → defend, etc. | Task 6 |
| Engineer messages (no LLM, templates) | Task 8 |
| Integration into engine.py (after race_state update, non-blocking) | Task 9 |
| `GET /api/race-ai` returning intensity/mode/event/threat/advice | Task 10 |
| Tests: gap 0.8 creates attack, DRS increases threat, sector, intensity, missing telem | Tasks 2–7, 11 |
| Performance: <5ms, no LLM, no network, pure Python | Enforced in analyzer.py design |
| Telemetry thread not blocked (queue used, cooldown 8s) | Task 9 step 3 |

**Gap:** UI panel ("Race Intelligence") — deferred. The Next.js frontend is a separate concern. The `/api/race-ai` endpoint (Task 10) provides all data needed; UI can consume it in a follow-up session.

### Type Consistency

- `RaceEvent` defined in `models.py` (Task 1), imported in `decisions.py` (Task 6) and `analyzer.py` (Task 7) — consistent.
- `BattleState` defined in `battles.py` (Task 5), used inside `analyzer.py` (Task 7) — consistent.
- `RaceAIState` defined in `models.py` (Task 1), used in `analyzer.py` (Task 7) — consistent.
- `get_sector` takes `float`, returns `int` — used in Tasks 2, 11 — consistent.
- Snapshot dict keys: `gap_behind_ms`, `gap_front_ms`, `drs_active`, `player_pos`, `player_lap`, `total_laps`, `driver_behind`, `tyre_age`, `tyre_wear` — defined in Task 9, matched in Task 7 analyzer.update().

### Placeholder Scan

No TBDs or incomplete steps found.
