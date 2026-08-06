# Driver Performance Coach Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `core/coach_ai/` — a deterministic, LLM-free driver analysis layer that turns lap-by-lap sector data into a `DriverReport` with weak sector detection, consistency score, pace delta, and tyre advice.

**Architecture:** Three files: `models.py` (dataclasses), `analyzer.py` (all logic in `DriverCoach` class). Engine feeds completed-lap data via `add_lap()`. State exposed via `engine.state["coach_ai"]` and `GET /api/coach-ai`. UI panel on Dashboard.

**Tech Stack:** Python 3.12 dataclasses, pure math (no numpy), pytest. TypeScript/React for UI panel.

---

## Data Sources (read before touching code)

Engine detects lap completion at `core/engine.py:596`:
```python
if cur > self._prev_lap and self._prev_lap > 0 and lms > 0:
    self.recorder.on_lap_complete(
        lap_num=self._prev_lap,
        last_lap_ms=lms,
        s1_ms=pl.get("s1_ms", 0),
        s2_ms=pl.get("s2_ms", 0),
        s3_ms=pl.get("s3_ms", 0),
    )
```
We hook right after this block — same data, same lap completion trigger.

Available per completed lap: `lap_num`, `last_lap_ms`, `s1_ms`, `s2_ms`, `s3_ms`, plus `self._player_tyre_compound`, `self._player_tyre_age`, `self._player_tyre_wear`.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `core/coach_ai/__init__.py` | Create | Export `DriverCoach` |
| `core/coach_ai/models.py` | Create | `LapData`, `DriverReport` dataclasses |
| `core/coach_ai/analyzer.py` | Create | `DriverCoach`: add_lap, get_report, get_state |
| `tests/test_coach_ai.py` | Create | All coach tests |
| `core/engine.py` | Modify | Instantiate coach, call add_lap, state["coach_ai"] |
| `NewSpotterUI/lib/api.ts` | Modify | Add `CoachAIState` type + field to `SpotterState` |
| `NewSpotterUI/components/spotter/views/dashboard.tsx` | Modify | Add Coach panel |

---

## Task 1: Models

**Files:**
- Create: `core/coach_ai/__init__.py`
- Create: `core/coach_ai/models.py`
- Test: `tests/test_coach_ai.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_coach_ai.py`:

```python
"""tests/test_coach_ai.py — Driver Performance Coach unit tests."""
from core.coach_ai.models import LapData, DriverReport


def test_lap_data_fields():
    lap = LapData(
        lap_number=5,
        lap_time_ms=90_000,
        s1_ms=28_000,
        s2_ms=32_000,
        s3_ms=30_000,
        tyre_compound="M",
        tyre_age=5,
        tyre_wear=20.0,
    )
    assert lap.lap_number == 5
    assert lap.lap_time_ms == 90_000
    assert lap.s1_ms == 28_000


def test_driver_report_fields():
    report = DriverReport(
        weak_sector=2,
        lost_time_ms=350,
        consistency_score=0.85,
        pace_delta_ms=420,
        tyre_advice="ok",
        lap_count=5,
        advice="Второй сектор — слабое место.",
    )
    assert report.weak_sector == 2
    assert report.consistency_score == 0.85
    assert report.tyre_advice == "ok"
```

Run to verify FAIL:
```
py -3.12 -m pytest tests/test_coach_ai.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 2: Create `core/coach_ai/__init__.py`**

```python
from core.coach_ai.analyzer import DriverCoach

__all__ = ["DriverCoach"]
```

- [ ] **Step 3: Create `core/coach_ai/models.py`**

```python
"""
core/coach_ai/models.py
========================
Data types for the Driver Performance Coach.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LapData:
    lap_number: int
    lap_time_ms: int
    s1_ms: int
    s2_ms: int
    s3_ms: int
    tyre_compound: str | None
    tyre_age: int | None
    tyre_wear: float | None


@dataclass
class DriverReport:
    weak_sector: int | None       # 1, 2 or 3 — sector with most consistent time loss
    lost_time_ms: int | None      # ms lost in weak sector vs. session best
    consistency_score: float      # 0.0–1.0 (1.0 = perfectly consistent lap times)
    pace_delta_ms: int | None     # recent avg lap vs. session best (positive = slower)
    tyre_advice: str              # "push" | "save" | "cliff" | "ok"
    lap_count: int                # total laps fed to the coach
    advice: str | None            # Russian summary phrase (None if nothing notable)
```

- [ ] **Step 4: Run tests — should pass**

```
py -3.12 -m pytest tests/test_coach_ai.py::test_lap_data_fields tests/test_coach_ai.py::test_driver_report_fields -v
```
Expected: 2 passed.

---

## Task 2: Analyzer

**Files:**
- Create: `core/coach_ai/analyzer.py`
- Modify: `tests/test_coach_ai.py` (append new tests)

- [ ] **Step 1: Append analyzer tests to `tests/test_coach_ai.py`**

```python
from core.coach_ai.analyzer import DriverCoach


def _make_coach_with_laps(lap_times: list[int],
                           s1s: list[int] | None = None,
                           s2s: list[int] | None = None,
                           s3s: list[int] | None = None) -> DriverCoach:
    coach = DriverCoach()
    for i, ms in enumerate(lap_times):
        s1 = (s1s[i] if s1s else ms // 3)
        s2 = (s2s[i] if s2s else ms // 3)
        s3 = (s3s[i] if s3s else ms - s1 - s2)
        coach.add_lap(
            lap_number=i + 1,
            lap_time_ms=ms,
            s1_ms=s1,
            s2_ms=s2,
            s3_ms=s3,
        )
    return coach


# --- consistency ---

def test_consistency_perfect():
    coach = _make_coach_with_laps([90_000, 90_000, 90_000, 90_000])
    r = coach.get_report()
    assert r.consistency_score == 1.0


def test_consistency_low_on_varied_laps():
    # stddev / mean >> 2% → score approaches 0
    coach = _make_coach_with_laps([88_000, 92_000, 87_000, 93_000])
    r = coach.get_report()
    assert r.consistency_score < 0.5


def test_consistency_default_before_3_laps():
    coach = _make_coach_with_laps([90_000, 91_000])
    r = coach.get_report()
    assert r.consistency_score == 1.0   # insufficient data → assume consistent


# --- pace delta ---

def test_pace_delta_zero_on_single_lap():
    coach = DriverCoach()
    coach.add_lap(1, 90_000, 28_000, 32_000, 30_000)
    assert coach.get_report().pace_delta_ms is None


def test_pace_delta_positive_when_slowing():
    coach = _make_coach_with_laps([90_000, 91_000, 92_000, 93_000])
    r = coach.get_report()
    assert r.pace_delta_ms is not None
    assert r.pace_delta_ms > 0   # recent avg > session best


def test_pace_delta_negative_or_zero_when_improving():
    coach = _make_coach_with_laps([93_000, 92_000, 91_000, 90_000])
    r = coach.get_report()
    assert r.pace_delta_ms is not None
    assert r.pace_delta_ms <= 0  # recent avg ≤ session best


# --- weak sector ---

def test_weak_sector_detected():
    # S2 consistently 500ms slower than session best
    coach = DriverCoach()
    for i in range(5):
        s1 = 28_000
        s2 = 32_500 if i < 4 else 32_000   # best S2 = 32000, avg recent = 32500
        s3 = 30_000
        coach.add_lap(i + 1, s1 + s2 + s3, s1, s2, s3)
    r = coach.get_report()
    assert r.weak_sector == 2
    assert r.lost_time_ms is not None and r.lost_time_ms > 0


def test_no_weak_sector_when_consistent():
    # All sectors vary by < 100ms
    coach = DriverCoach()
    for i in range(5):
        coach.add_lap(i + 1, 90_000, 28_050, 32_000, 29_950)
    r = coach.get_report()
    assert r.weak_sector is None


def test_weak_sector_needs_3_valid_laps():
    coach = DriverCoach()
    coach.add_lap(1, 90_000, 28_000, 32_000, 30_000)
    coach.add_lap(2, 91_000, 28_500, 32_500, 30_000)
    r = coach.get_report()
    assert r.weak_sector is None   # only 2 laps — not enough


# --- tyre advice ---

def test_tyre_cliff_on_rapid_pace_rise_with_old_tyres():
    coach = DriverCoach()
    coach.add_lap(1, 90_000, 28_000, 32_000, 30_000, tyre_age=28)
    coach.add_lap(2, 90_400, 28_100, 32_200, 30_100, tyre_age=29)
    coach.add_lap(3, 90_800, 28_200, 32_400, 30_200, tyre_age=30)
    assert coach.get_report().tyre_advice == "cliff"


def test_tyre_ok_on_stable_pace():
    coach = _make_coach_with_laps([90_000, 90_100, 90_050])
    assert coach.get_report().tyre_advice == "ok"


# --- get_state contract ---

def test_get_state_has_all_keys():
    coach = DriverCoach()
    s = coach.get_state()
    for key in ("weak_sector", "lost_time_ms", "consistency_score",
                "pace_delta_ms", "tyre_advice", "lap_count", "advice"):
        assert key in s


def test_get_state_lap_count():
    coach = _make_coach_with_laps([90_000, 91_000, 92_000])
    assert coach.get_state()["lap_count"] == 3
```

Run to verify FAIL:
```
py -3.12 -m pytest tests/test_coach_ai.py -v
```
Expected: `ImportError` on `DriverCoach`

- [ ] **Step 2: Create `core/coach_ai/analyzer.py`**

```python
"""
core/coach_ai/analyzer.py
==========================
DriverCoach: per-lap sector analysis, consistency scoring, pace delta,
tyre advice. Deterministic, no LLM, <1 ms per lap.
"""
from __future__ import annotations

from core.coach_ai.models import DriverReport, LapData

_TYRE_ADVICE_THRESHOLD_MS = 300   # ms pace rise per lap = degrading
_CLIFF_MIN_TYRE_AGE = 25          # laps — beyond this, rapid rise = cliff
_WEAK_SECTOR_MIN_LOSS_MS = 100    # ignore sector differences below this
_MIN_LAPS_SECTOR = 3              # need at least 3 laps to judge sectors
_CONSISTENCY_MAX_CV = 0.02        # 2% coefficient of variation → score 0.0

_ADVICE: dict[str, str] = {
    "cliff": "Шины на пределе — готовься к пит-стопу.",
    "save":  "Темп падает — береги шины.",
    "push":  "Темп растёт — можно давить.",
}

_SECTOR_RU = {1: "первом", 2: "втором", 3: "третьем"}


class DriverCoach:
    """Stateful per-session coach. Feed laps as they complete; read report any time."""

    def __init__(self) -> None:
        self._laps: list[LapData] = []

    def add_lap(
        self,
        lap_number: int,
        lap_time_ms: int,
        s1_ms: int,
        s2_ms: int,
        s3_ms: int,
        tyre_compound: str | None = None,
        tyre_age: int | None = None,
        tyre_wear: float | None = None,
    ) -> None:
        self._laps.append(LapData(
            lap_number=lap_number,
            lap_time_ms=lap_time_ms,
            s1_ms=s1_ms,
            s2_ms=s2_ms,
            s3_ms=s3_ms,
            tyre_compound=tyre_compound,
            tyre_age=tyre_age,
            tyre_wear=tyre_wear,
        ))

    def get_report(self) -> DriverReport:
        laps = self._laps
        weak_s, lost = _weak_sector(laps)
        cons = _consistency(laps)
        delta = _pace_delta(laps)
        tyre = _tyre_advice(laps)
        adv = _build_advice(tyre, weak_s, lost, cons)
        return DriverReport(
            weak_sector=weak_s,
            lost_time_ms=lost,
            consistency_score=cons,
            pace_delta_ms=delta,
            tyre_advice=tyre,
            lap_count=len(laps),
            advice=adv,
        )

    def get_state(self) -> dict:
        r = self.get_report()
        return {
            "weak_sector": r.weak_sector,
            "lost_time_ms": r.lost_time_ms,
            "consistency_score": round(r.consistency_score, 3),
            "pace_delta_ms": r.pace_delta_ms,
            "tyre_advice": r.tyre_advice,
            "lap_count": r.lap_count,
            "advice": r.advice,
        }


# ---------------------------------------------------------------------------
# Pure functions — no side effects
# ---------------------------------------------------------------------------

def _weak_sector(laps: list[LapData]) -> tuple[int | None, int | None]:
    valid = [l for l in laps if l.s1_ms > 0 and l.s2_ms > 0 and l.s3_ms > 0]
    if len(valid) < _MIN_LAPS_SECTOR:
        return None, None
    best_s = [
        min(l.s1_ms for l in valid),
        min(l.s2_ms for l in valid),
        min(l.s3_ms for l in valid),
    ]
    recent = valid[-5:]
    avg_s = [
        sum(l.s1_ms for l in recent) // len(recent),
        sum(l.s2_ms for l in recent) // len(recent),
        sum(l.s3_ms for l in recent) // len(recent),
    ]
    losses = [avg_s[i] - best_s[i] for i in range(3)]
    max_loss = max(losses)
    if max_loss < _WEAK_SECTOR_MIN_LOSS_MS:
        return None, None
    sector_num = losses.index(max_loss) + 1
    return sector_num, max_loss


def _consistency(laps: list[LapData]) -> float:
    valid = [l.lap_time_ms for l in laps if l.lap_time_ms > 0]
    if len(valid) < 3:
        return 1.0
    mean = sum(valid) / len(valid)
    variance = sum((t - mean) ** 2 for t in valid) / len(valid)
    stddev = variance ** 0.5
    cv = stddev / mean
    return max(0.0, min(1.0, 1.0 - cv / _CONSISTENCY_MAX_CV))


def _pace_delta(laps: list[LapData]) -> int | None:
    valid = [l.lap_time_ms for l in laps if l.lap_time_ms > 0]
    if len(valid) < 2:
        return None
    best = min(valid)
    recent = valid[-3:]
    recent_avg = sum(recent) // len(recent)
    return recent_avg - best


def _tyre_advice(laps: list[LapData]) -> str:
    if len(laps) < 3:
        return "ok"
    recent = [l for l in laps[-3:] if l.lap_time_ms > 0]
    if len(recent) < 3:
        return "ok"
    d1 = recent[1].lap_time_ms - recent[0].lap_time_ms
    d2 = recent[2].lap_time_ms - recent[1].lap_time_ms
    thr = _TYRE_ADVICE_THRESHOLD_MS
    if d1 > thr and d2 > thr:
        age = recent[-1].tyre_age
        if age is not None and age >= _CLIFF_MIN_TYRE_AGE:
            return "cliff"
        return "save"
    if d1 < -200 and d2 < -200:
        return "push"
    return "ok"


def _build_advice(
    tyre: str,
    weak_sector: int | None,
    lost_ms: int | None,
    consistency: float,
) -> str | None:
    if tyre in _ADVICE:
        return _ADVICE[tyre]
    if weak_sector and lost_ms and lost_ms > 200:
        name = _SECTOR_RU.get(weak_sector, str(weak_sector))
        return f"Теряешь больше всего в {name} секторе."
    if consistency < 0.5:
        return "Темп нестабильный — работай над консистентностью."
    return None
```

- [ ] **Step 3: Run analyzer tests**

```
py -3.12 -m pytest tests/test_coach_ai.py -v
```
Expected: **17 passed**.

- [ ] **Step 4: Run full suite — no regressions**

```
py -3.12 -m pytest tests/ --ignore=tests/test_gpt.py -q
```
Expected: **296 passed** (279 + 17).

---

## Task 3: Engine Integration

**Files:**
- Modify: `core/engine.py`

- [ ] **Step 1: Add import at top of `core/engine.py`**

Find the imports section (around line 45, after `from core.strategy_ai.strategy import StrategyAnalyzer`). Add:

```python
from core.coach_ai import DriverCoach
```

- [ ] **Step 2: Instantiate `DriverCoach` in `Engine.__init__`**

Find `self.strategy_analyzer = StrategyAnalyzer()` (around line 112). Add immediately after:

```python
        self.driver_coach = DriverCoach()
```

- [ ] **Step 3: Add `coach_ai` to initial state dict**

Find `"strategy_ai": { ... }` in `self.state` (around line 154). Add after the `strategy_ai` block:

```python
            "coach_ai": {
                "weak_sector": None,
                "lost_time_ms": None,
                "consistency_score": 1.0,
                "pace_delta_ms": None,
                "tyre_advice": "ok",
                "lap_count": 0,
                "advice": None,
            },
```

- [ ] **Step 4: Feed lap data to coach on lap completion**

Find the lap-completion block (around line 596–603):
```python
                    if cur > self._prev_lap and self._prev_lap > 0 and lms > 0:
                        self.recorder.on_lap_complete(
                            lap_num=self._prev_lap,
                            last_lap_ms=lms,
                            s1_ms=pl.get("s1_ms", 0),
                            s2_ms=pl.get("s2_ms", 0),
                            s3_ms=pl.get("s3_ms", 0),
                        )
```

Add the coach call immediately after `self.recorder.on_lap_complete(...)`:

```python
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
```

- [ ] **Step 5: Update `state["coach_ai"]` in `_maybe_snapshot()`**

Find `self.state["strategy_ai"] = self.strategy_analyzer.get_state()` (around line 715). Add immediately after:

```python
            self.state["coach_ai"] = self.driver_coach.get_state()
```

- [ ] **Step 6: Add `get_coach_ai_state()` method**

Find `def get_strategy_ai_state(self)` (around line 980). Add after it:

```python
    def get_coach_ai_state(self) -> dict:
        with self.state_lock:
            return dict(self.state.get("coach_ai", {}))
```

- [ ] **Step 7: Run full test suite**

```
py -3.12 -m pytest tests/ --ignore=tests/test_gpt.py -q
```
Expected: **296 passed**.

---

## Task 4: API endpoint + UI panel

**Files:**
- Modify: `web_server.py`
- Modify: `NewSpotterUI/lib/api.ts`
- Modify: `NewSpotterUI/components/spotter/views/dashboard.tsx`

- [ ] **Step 1: Add `/api/coach-ai` endpoint to `web_server.py`**

Find `GET /api/strategy-ai` endpoint. Add a similar one right after it:

```python
@app.route("/api/coach-ai")
def api_coach_ai():
    return _json(engine.get_coach_ai_state())
```

- [ ] **Step 2: Add `CoachAIState` type to `NewSpotterUI/lib/api.ts`**

After the `StrategyAIState` type, add:

```typescript
export type CoachAIState = {
  weak_sector: number | null
  lost_time_ms: number | null
  consistency_score: number
  pace_delta_ms: number | null
  tyre_advice: string
  lap_count: number
  advice: string | null
}
```

Then add `coach_ai?: CoachAIState` to `SpotterState` after `strategy_ai?: StrategyAIState`:

```typescript
  strategy_ai?: StrategyAIState
  coach_ai?: CoachAIState
  yandex_ok?: boolean
```

- [ ] **Step 3: Add Coach panel to `dashboard.tsx`**

In `dashboard.tsx`, find where `trackAi` and `strategyAi` are destructured (around line 40):

```tsx
  const trackAi = state?.track_ai
  const strategyAi = state?.strategy_ai
```

Add:
```tsx
  const coachAi = state?.coach_ai
```

Then add labels map and panel. Find the Strategy panel block (the `<Panel label="Стратегия"...>` block) and add after it, before `<Panel label="Live Events"`:

```tsx
        <Panel label="Коуч" action={
          <span className="label-mono text-[10px] text-muted-foreground">
            {coachAi?.lap_count ? `${coachAi.lap_count} кр.` : "—"}
          </span>
        }>
          <div className="grid grid-cols-2 gap-5">
            <Readout
              label="КОНСИСТ."
              value={coachAi?.consistency_score != null
                ? `${Math.round(coachAi.consistency_score * 100)}%`
                : "—"}
            />
            <Readout
              label="ДЕЛЬТА"
              value={coachAi?.pace_delta_ms != null
                ? (coachAi.pace_delta_ms >= 0
                    ? `+${(coachAi.pace_delta_ms / 1000).toFixed(2)}с`
                    : `${(coachAi.pace_delta_ms / 1000).toFixed(2)}с`)
                : "—"}
            />
            <Readout
              label="СЛАБ. СЕК."
              value={coachAi?.weak_sector != null ? `S${coachAi.weak_sector}` : "—"}
            />
            <Readout
              label="ШИНЫ"
              value={coachAi?.tyre_advice?.toUpperCase() ?? "—"}
            />
          </div>
          {coachAi?.advice && (
            <p className="mt-3 text-xs text-muted-foreground leading-relaxed">
              {coachAi.advice}
            </p>
          )}
        </Panel>
```

- [ ] **Step 4: Build frontend**

```
pnpm -C NewSpotterUI build
```
Expected: exit 0.

- [ ] **Step 5: Run final test suite**

```
py -3.12 -m pytest tests/ --ignore=tests/test_gpt.py -q
```
Expected: **296 passed**.

---

## Self-Review Checklist

**Spec coverage:**
- ✅ braking analysis → covered via sector weakness (S1 typically contains heavy braking zones)
- ✅ corner loss → `weak_sector` detection at sector granularity (finest available without per-frame throttle/brake data)
- ✅ consistency → `consistency_score` via coefficient of variation
- ✅ pace delta → `pace_delta_ms` (recent avg vs. session best)
- ✅ `DriverReport` output with all required fields
- ✅ Tests required → 17 tests in `test_coach_ai.py`
- ✅ No LLM in calculations
- ✅ Integrates through existing events/state

**Note on braking/corner granularity:** Throttle/brake per-corner data is not currently parsed from UDP (CAR_TELEMETRY packet fields exist but are unused in engine.py). Sector-level analysis is the maximum granularity available without extending the telemetry parser — which task2.md explicitly prohibits ("DO NOT rewrite telemetry parser").
