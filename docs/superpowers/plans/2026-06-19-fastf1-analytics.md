# FastF1 Analytics Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record player lap data during F1 25 gameplay and compare it with real FastF1 data after the race.

**Architecture:** New `analytics/` package (loader→normalizer→comparator→context); `core/session_recorder.py` captures UDP lap data; three new endpoints in `web_server.py`; new "Архив" tab in `index.html`. No existing core logic removed — only additive hooks in `engine.py` and `packets.py`.

**Tech Stack:** fastf1==3.8.3, Python 3.12, bottle, existing pywebview stack

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `analytics/__init__.py` | Create | Package marker |
| `analytics/archive.py` | Create | Atomic JSON read/write |
| `analytics/normalizer.py` | Create | FastF1 Session → plain dict |
| `analytics/loader.py` | Create | TRACK_ID_TO_GP + session loading |
| `analytics/comparator.py` | Create | Best-lap comparison |
| `analytics/context.py` | Create | Qwen context string |
| `core/session_recorder.py` | Create | Records player laps |
| `core/packets.py` | Modify | Extend parse_player_lap + parse_session |
| `core/engine.py` | Modify | Wire up SessionRecorder |
| `commentator/brain.py` | Modify | Accept analytics_context |
| `web_server.py` | Modify | 3 new endpoints |
| `index.html` | Modify | "Архив" tab |

---

### Task 1: analytics/archive.py

**Files:**
- Create: `analytics/__init__.py`
- Create: `analytics/archive.py`

- [ ] **Step 1: Create package marker**

Create `analytics/__init__.py` — empty file.

- [ ] **Step 2: Write test script `test_archive.py`**

```python
import sys, json; sys.path.insert(0, '.')
from analytics.archive import (save_game_session, load_game_session,
    list_game_sessions, save_f1, load_f1, save_compare, load_compare)

gs = {"timestamp": "2026-06-19T15:30:00", "track_id": 3,
      "track_name": "Bahrain", "session_type": "R",
      "total_laps_completed": 2, "final_position": 5,
      "player_laps": [{"lap": 2, "last_lap_ms": 93200,
                       "s1_ms": 27900, "s2_ms": 35400, "s3_ms": 29900}],
      "events": ["OVTK"]}
path = save_game_session(gs)
loaded = load_game_session(path)
assert loaded["track_name"] == "Bahrain"
assert loaded["player_laps"][0]["last_lap_ms"] == 93200

sessions = list_game_sessions()
assert any(s["track_name"] == "Bahrain" for s in sessions)

f1 = {"event": "Bahrain Grand Prix", "year": 2025, "session": "Race"}
save_f1(3, 2025, "R", f1)
assert load_f1(3, 2025, "R")["event"] == "Bahrain Grand Prix"
assert load_f1(99, 2025, "R") is None

cpath = save_compare(path, 3, 2025, "R", {"gap_ms": 1400, "partial": False})
assert load_compare(cpath)["gap_ms"] == 1400

path.unlink(missing_ok=True)
print("ALL ARCHIVE TESTS PASSED")
```

- [ ] **Step 3: Run — expect ImportError**

```
python test_archive.py
```

- [ ] **Step 4: Implement `analytics/archive.py`**

```python
from __future__ import annotations
import json, os, tempfile
from datetime import datetime
from pathlib import Path
import config

_GAME_DIR = Path(config.DATA_DIR) / "game_sessions"
_ARCHIVE_DIR = Path(config.DATA_DIR) / "race_archive"

def _ensure_dirs():
    _GAME_DIR.mkdir(parents=True, exist_ok=True)
    _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".tmp", dir=path.parent, delete=False, encoding="utf-8")
    try:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp.flush(); tmp.close()
        os.replace(tmp.name, path)
    except Exception:
        tmp.close()
        try: os.unlink(tmp.name)
        except OSError: pass
        raise

def save_game_session(data: dict) -> Path:
    _ensure_dirs()
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = _GAME_DIR / f"{ts}.json"
    _atomic_write(path, data)
    return path

def load_game_session(path: str | Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

def list_game_sessions() -> list[dict]:
    _ensure_dirs()
    result = []
    for p in sorted(_GAME_DIR.glob("*.json"), reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            result.append({"path": str(p), "track_name": d.get("track_name", "?"),
                           "timestamp": d.get("timestamp", p.stem),
                           "final_position": d.get("final_position")})
        except (OSError, json.JSONDecodeError):
            continue
    return result

def save_f1(track_id: int, year: int, stype: str, data: dict) -> Path:
    _ensure_dirs()
    path = _ARCHIVE_DIR / f"{year}_{track_id}_{stype}_f1.json"
    _atomic_write(path, data)
    return path

def load_f1(track_id: int, year: int, stype: str) -> dict | None:
    path = _ARCHIVE_DIR / f"{year}_{track_id}_{stype}_f1.json"
    if not path.exists(): return None
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return None

def save_compare(game_path: str | Path, track_id: int, year: int,
                 stype: str, data: dict) -> Path:
    _ensure_dirs()
    stem = Path(game_path).stem
    path = _ARCHIVE_DIR / f"{stem}_{track_id}_{year}_{stype}_compare.json"
    _atomic_write(path, data)
    return path

def load_compare(compare_path: str | Path) -> dict | None:
    try: return json.loads(Path(compare_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return None
```

- [ ] **Step 5: Run — expect PASS**

```
python test_archive.py
```

- [ ] **Step 6: Delete `test_archive.py`, commit**

```
git add analytics/__init__.py analytics/archive.py
git commit -m "feat: add analytics/archive.py - atomic JSON read/write"
```

---

### Task 2: analytics/normalizer.py

**Files:**
- Create: `analytics/normalizer.py`

- [ ] **Step 1: Write `test_normalizer.py`**

```python
import sys; sys.path.insert(0, '.')
import fastf1
from pathlib import Path
Path("fastf1_cache").mkdir(exist_ok=True)
fastf1.Cache.enable_cache("fastf1_cache")
print("Loading Bahrain 2025 R (~30s first time)...")
session = fastf1.get_session(2025, "Bahrain", "R")
session.load(laps=True, telemetry=False, weather=True, messages=True)

from analytics.normalizer import normalize
data = normalize(session)

required = ["event","year","session","weather","total_results_count",
            "results_top10","results","fastest_lap","best_sectors",
            "safety_cars","penalties"]
for k in required:
    assert k in data, f"Missing: {k}"
assert isinstance(data["safety_cars"], int)
assert isinstance(data["total_results_count"], int)
assert len(data["results_top10"]) <= 10
fl = data["fastest_lap"]
for f in ["driver","lap","time_ms","s1_ms","s2_ms","s3_ms"]:
    assert f in fl, f"fastest_lap missing: {f}"
if data["results_top10"]:
    for f in ["pos","driver","team","gap_s","fastest_lap_ms"]:
        assert f in data["results_top10"][0]
print("winner:", data["results_top10"][0]["driver"] if data["results_top10"] else "N/A")
print("fastest_lap:", data["fastest_lap"])
print("ALL NORMALIZER TESTS PASSED")
```

- [ ] **Step 2: Run — expect ImportError**

```
python test_normalizer.py
```

- [ ] **Step 3: Implement `analytics/normalizer.py`**

```python
from __future__ import annotations
import math

def _td_to_ms(td) -> int | None:
    try:
        if td is None: return None
        if hasattr(td, 'isnull') and td.isnull(): return None
        total = td.total_seconds()
        return None if math.isnan(total) else int(total * 1000)
    except Exception: return None

def _safe_int(v) -> int | None:
    try:
        f = float(v)
        return None if math.isnan(f) else int(f)
    except Exception: return None

def _safe_float(v) -> float | None:
    try:
        f = float(v)
        return None if math.isnan(f) else round(f, 3)
    except Exception: return None

def _weather(session) -> dict:
    out = {"air_temp": None, "track_temp": None, "rainfall": None}
    try:
        w = session.weather_data
        if w is not None and not w.empty:
            row = w.iloc[len(w) // 2]
            out["air_temp"] = _safe_float(row.get("AirTemp"))
            out["track_temp"] = _safe_float(row.get("TrackTemp"))
            out["rainfall"] = bool(row.get("Rainfall", False))
    except Exception: pass
    return out

def _results(session) -> list[dict]:
    out = []
    try:
        res = session.results
        if res is None or res.empty: return out
        for _, row in res.iterrows():
            pos = _safe_int(row.get("Position"))
            if pos is None: continue
            gap = None
            try:
                t = row.get("Time")
                if pos > 1 and t is not None and hasattr(t, "total_seconds"):
                    gap = round(t.total_seconds(), 3)
            except Exception: pass
            out.append({"pos": pos,
                        "driver": str(row.get("Abbreviation", "?")),
                        "team": str(row.get("TeamName", "?")),
                        "gap_s": gap,
                        "fastest_lap_ms": _td_to_ms(row.get("FastestLapTime"))})
        out.sort(key=lambda r: r["pos"])
    except Exception: pass
    return out

def _fastest_lap(session) -> dict:
    out = {"driver": None, "lap": None, "time_ms": None,
           "s1_ms": None, "s2_ms": None, "s3_ms": None}
    try:
        laps = session.laps
        if laps is None or laps.empty: return out
        fl = laps.pick_fastest()
        if fl is None or (hasattr(fl, 'empty') and fl.empty): return out
        out.update({"driver": str(fl.get("Driver", "?")),
                    "lap": _safe_int(fl.get("LapNumber")),
                    "time_ms": _td_to_ms(fl.get("LapTime")),
                    "s1_ms": _td_to_ms(fl.get("Sector1Time")),
                    "s2_ms": _td_to_ms(fl.get("Sector2Time")),
                    "s3_ms": _td_to_ms(fl.get("Sector3Time"))})
    except Exception: pass
    return out

def _best_sectors(session) -> dict:
    out = {"s1_ms": None, "s2_ms": None, "s3_ms": None}
    try:
        laps = session.laps
        if laps is None or laps.empty: return out
        for col, key in [("Sector1Time","s1_ms"),("Sector2Time","s2_ms"),("Sector3Time","s3_ms")]:
            valid = laps[col].dropna()
            if not valid.empty: out[key] = _td_to_ms(valid.min())
    except Exception: pass
    return out

def _safety_cars(session) -> int:
    try:
        msgs = session.race_control_messages
        if msgs is None or msgs.empty: return 0
        sc = msgs[msgs["Message"].str.contains("SAFETY CAR", na=False, case=False)]
        dep = sc[sc["Message"].str.contains("DEPLOYED", na=False, case=False)]
        return len(dep) if not dep.empty else (1 if not sc.empty else 0)
    except Exception: return 0

def _penalties(session) -> int:
    try:
        msgs = session.race_control_messages
        if msgs is None or msgs.empty: return 0
        pen = msgs[msgs["Message"].str.contains(
            r"PENALTY|TIME PENALTY|DRIVE THROUGH|STOP AND GO", na=False, case=False)]
        return len(pen)
    except Exception: return 0

def normalize(session) -> dict:
    """FastF1 Session → plain dict. Never raises."""
    try:
        event = str(session.event.get("EventName", None))
        year = _safe_int(session.event.year)
        sname = str(session.name)
    except Exception:
        event = year = sname = None
    results = _results(session)
    return {
        "event": event, "year": year, "session": sname,
        "weather": _weather(session),
        "total_results_count": len(results),
        "results_top10": results[:10],
        "results": results,
        "fastest_lap": _fastest_lap(session),
        "best_sectors": _best_sectors(session),
        "safety_cars": _safety_cars(session),
        "penalties": _penalties(session),
    }
```

- [ ] **Step 4: Run — expect PASS**

```
python test_normalizer.py
```

- [ ] **Step 5: Delete `test_normalizer.py`, commit**

```
git add analytics/normalizer.py
git commit -m "feat: add analytics/normalizer.py - FastF1 Session to plain dict"
```

---

### Task 3: analytics/loader.py

**Files:**
- Create: `analytics/loader.py`

- [ ] **Step 1: Write `test_loader.py`**

```python
import sys; sys.path.insert(0, '.')
from analytics.loader import load_f1_session, TRACK_ID_TO_GP

assert len(TRACK_ID_TO_GP) == 24, f"Expected 24, got {len(TRACK_ID_TO_GP)}"
session, err = load_f1_session(99)
assert session is None and err == "no_fastf1_data"

print("Loading Bahrain 2025 (~30s first run)...")
session, err = load_f1_session(3, 2025, "R")
assert err is None, f"Error: {err}"
assert session is not None
print("Loaded:", session.event["EventName"])
print("ALL LOADER TESTS PASSED")
```

- [ ] **Step 2: Run — expect ImportError**

```
python test_loader.py
```

- [ ] **Step 3: Implement `analytics/loader.py`**

```python
from __future__ import annotations
from pathlib import Path
import fastf1
import fastf1.exceptions
import config

# ⚠️ EXPECTED ORDER — NOT VERIFIED on live F1 25 UDP packets.
# Verify m_trackId on real packets and update ONLY this table.
TRACK_ID_TO_GP: dict[int, tuple[str, str]] = {
    0:  ("Melbourne",   "Australian Grand Prix"),
    1:  ("Shanghai",    "Chinese Grand Prix"),
    2:  ("Suzuka",      "Japanese Grand Prix"),
    3:  ("Sakhir",      "Bahrain Grand Prix"),
    4:  ("Jeddah",      "Saudi Arabian Grand Prix"),
    5:  ("Miami",       "Miami Grand Prix"),
    6:  ("Imola",       "Emilia-Romagna Grand Prix"),
    7:  ("Monaco",      "Monaco Grand Prix"),
    8:  ("Barcelona",   "Spanish Grand Prix"),
    9:  ("Montreal",    "Canadian Grand Prix"),
    10: ("Spielberg",   "Austrian Grand Prix"),
    11: ("Silverstone", "British Grand Prix"),
    12: ("Spa",         "Belgian Grand Prix"),
    13: ("Budapest",    "Hungarian Grand Prix"),
    14: ("Zandvoort",   "Dutch Grand Prix"),
    15: ("Monza",       "Italian Grand Prix"),
    16: ("Baku",        "Azerbaijan Grand Prix"),
    17: ("Singapore",   "Singapore Grand Prix"),
    18: ("Austin",      "United States Grand Prix"),
    19: ("Mexico City", "Mexico City Grand Prix"),
    20: ("São Paulo",   "São Paulo Grand Prix"),
    21: ("Las Vegas",   "Las Vegas Grand Prix"),
    22: ("Lusail",      "Qatar Grand Prix"),
    23: ("Abu Dhabi",   "Abu Dhabi Grand Prix"),
}

_CACHE = Path(config.DATA_DIR) / "fastf1_cache"
_CACHE.mkdir(parents=True, exist_ok=True)
fastf1.Cache.enable_cache(str(_CACHE))


def load_f1_session(track_id: int, year: int = 2025,
                    session_type: str = "R") -> tuple[object | None, str | None]:
    """Returns (session, error). session=None on failure."""
    entry = TRACK_ID_TO_GP.get(track_id)
    if entry is None:
        return None, "no_fastf1_data"
    gp_name, _ = entry
    try:
        session = fastf1.get_session(year, gp_name, session_type)
    except Exception as exc:
        return None, f"session_not_found: {exc}"
    try:
        session.load(laps=True, telemetry=False, weather=True, messages=True)
    except fastf1.exceptions.RateLimitExceededError:
        return None, "rate_limit"
    except Exception as exc:
        return None, f"load_error: {exc}"
    return session, None
```

- [ ] **Step 4: Run — expect PASS**

```
python test_loader.py
```

- [ ] **Step 5: Delete `test_loader.py`, commit**

```
git add analytics/loader.py
git commit -m "feat: add analytics/loader.py - FastF1 loader with TRACK_ID_TO_GP"
```

---

### Task 4: analytics/context.py + analytics/comparator.py

**Files:**
- Create: `analytics/context.py`
- Create: `analytics/comparator.py`

context.py must exist before comparator.py (comparator imports it).

- [ ] **Step 1: Implement `analytics/context.py`**

```python
from __future__ import annotations

def _fmt(ms: int | None) -> str:
    if not ms: return "?"
    m = int(ms // 60000)
    s = (ms % 60000) / 1000
    return f"{m}:{s:06.3f}"

def build_qwen_context(compare: dict, f1_meta: dict) -> str:
    """≤ 250-char Russian string. Never raises."""
    try:
        return _build(compare, f1_meta)
    except Exception:
        return "Данные для сравнения недоступны."

def _build(compare: dict, f1_meta: dict) -> str:
    cov = compare.get("source_coverage", {})
    if cov.get("f1") == "none":
        return "Данные реального GP для этой трассы недоступны."

    event = f1_meta.get("event") or "GP"
    year = f1_meta.get("year") or ""
    top = f1_meta.get("results_top10") or []
    winner = top[0]["driver"] if top else "?"
    fl_driver = compare.get("f1_best_lap_driver") or "?"
    fl_time = _fmt(compare.get("f1_fastest_ms"))
    fl_lap = (f1_meta.get("fastest_lap") or {}).get("lap")

    header = f"{event} {year}: победил {winner}."
    fl = f" Быстрейший круг {fl_driver} {fl_time}"
    fl += f" (круг {fl_lap})." if fl_lap else "."

    if cov.get("player") == "none":
        return (header + fl + " Игровые данные не записаны.")[:250]

    pt = _fmt(compare.get("player_best_lap_ms"))
    pl = compare.get("player_best_lap_lap_number")
    gms = compare.get("gap_ms")
    gs = f"{gms/1000:.1f}" if gms is not None else "?"
    player = f" Твой лучший — {pt}"
    player += f" (круг {pl})" if pl else ""
    player += f", отставание {gs}с."

    if compare.get("partial") or "sectors" not in compare:
        return (header + fl + player)[:250]

    secs = compare["sectors"]
    worst_k, worst_v = max(secs.items(), key=lambda kv: kv[1]["gap_ms"])
    sg = f"{worst_v['gap_ms']/1000:.1f}"
    sector = f" Теряешь в {worst_k.upper()} (+{sg}с)."
    result = header + fl + player + sector
    return result[:250] if len(result) <= 250 else (header + fl + player)[:250]
```

- [ ] **Step 2: Write `test_comparator.py`**

```python
import sys; sys.path.insert(0, '.')
from analytics.comparator import compare

game = {"player_laps": [
    {"lap": 1, "last_lap_ms": 0, "s1_ms": 0, "s2_ms": 0, "s3_ms": 0},
    {"lap": 2, "last_lap_ms": 93200, "s1_ms": 27900, "s2_ms": 35400, "s3_ms": 29900},
    {"lap": 3, "last_lap_ms": 92800, "s1_ms": 27700, "s2_ms": 34800, "s3_ms": 30300},
]}
f1 = {"fastest_lap": {"driver": "NOR", "lap": 35, "time_ms": 91401,
                       "s1_ms": 27200, "s2_ms": 33900, "s3_ms": 30301}}

r = compare(game, f1)
for k in ["comparison_basis","source_coverage","player_best_lap_ms",
          "player_best_lap_lap_number","f1_fastest_ms","f1_best_lap_driver",
          "gap_ms","partial","qwen_context"]:
    assert k in r, f"Missing: {k}"
assert r["comparison_basis"] == "best_lap"
assert r["player_best_lap_ms"] == 92800
assert r["player_best_lap_lap_number"] == 3
assert r["gap_ms"] == 1399
assert r["partial"] == False
assert "sectors" in r
assert r["sectors"]["s2"]["gap_ms"] == 900

# Partial: no player sectors
r2 = compare({"player_laps": [{"lap":2,"last_lap_ms":93000,"s1_ms":0,"s2_ms":0,"s3_ms":0}]}, f1)
assert r2["partial"] == True and "sectors" not in r2 and r2["gap_ms"] == 1599

# No valid laps
r3 = compare({"player_laps": [{"lap":1,"last_lap_ms":0,"s1_ms":0,"s2_ms":0,"s3_ms":0}]}, f1)
assert r3["source_coverage"]["player"] == "none" and r3["gap_ms"] is None

# No F1 data
r4 = compare(game, {"fastest_lap": {"driver":None,"lap":None,"time_ms":None,"s1_ms":None,"s2_ms":None,"s3_ms":None}})
assert r4["source_coverage"]["f1"] == "none" and r4["gap_ms"] is None

assert all(len(x["qwen_context"]) <= 250 for x in [r,r2,r3,r4])
print("ALL COMPARATOR TESTS PASSED")
```

- [ ] **Step 3: Run — expect ImportError on comparator**

```
python test_comparator.py
```

- [ ] **Step 4: Implement `analytics/comparator.py`**

```python
from __future__ import annotations

def compare(game: dict, f1: dict) -> dict:
    """Best-lap comparison. All output fields always present."""
    valid = [l for l in game.get("player_laps", []) if l.get("last_lap_ms", 0) > 0]
    best = min(valid, key=lambda l: l["last_lap_ms"]) if valid else None

    f1fl = f1.get("fastest_lap") or {}
    f1_time = f1fl.get("time_ms")
    f1_driver = f1fl.get("driver")

    if best is None:
        pcov = "none"
    elif all(best.get(k, 0) > 0 for k in ("s1_ms", "s2_ms", "s3_ms")):
        pcov = "full"
    else:
        pcov = "partial"

    if f1_time is None:
        fcov = "none"
    elif all(f1fl.get(k) and f1fl[k] > 0 for k in ("s1_ms", "s2_ms", "s3_ms")):
        fcov = "full"
    else:
        fcov = "partial"

    gap_ms = (best["last_lap_ms"] - f1_time) if (best and f1_time) else None

    sectors = None
    if pcov == "full" and fcov == "full":
        sectors = {s: {"player_ms": best[f"{s}_ms"], "f1_ms": f1fl[f"{s}_ms"],
                       "gap_ms": best[f"{s}_ms"] - f1fl[f"{s}_ms"]}
                   for s in ("s1", "s2", "s3")}

    partial = pcov != "full" or fcov != "full"

    from analytics.context import build_qwen_context
    proto = {"source_coverage": {"player": pcov, "f1": fcov},
             "player_best_lap_ms": best["last_lap_ms"] if best else None,
             "player_best_lap_lap_number": best["lap"] if best else None,
             "f1_fastest_ms": f1_time, "f1_best_lap_driver": f1_driver,
             "gap_ms": gap_ms, "sectors": sectors, "partial": partial}
    qwen = build_qwen_context(proto, f1)

    result = {"comparison_basis": "best_lap",
              "source_coverage": {"player": pcov, "f1": fcov},
              "player_best_lap_ms": proto["player_best_lap_ms"],
              "player_best_lap_lap_number": proto["player_best_lap_lap_number"],
              "f1_fastest_ms": f1_time, "f1_best_lap_driver": f1_driver,
              "gap_ms": gap_ms, "partial": partial, "qwen_context": qwen}
    if sectors:
        result["sectors"] = sectors
    return result
```

- [ ] **Step 5: Run — expect PASS**

```
python test_comparator.py
```

- [ ] **Step 6: Delete `test_comparator.py`, commit**

```
git add analytics/context.py analytics/comparator.py
git commit -m "feat: add analytics/comparator.py + context.py - best-lap comparison and Qwen string"
```

---

### Task 5: core/session_recorder.py

**Files:**
- Create: `core/session_recorder.py`

- [ ] **Step 1: Write `test_recorder.py`**

```python
import sys, json; sys.path.insert(0, '.')
from core.session_recorder import SessionRecorder

r = SessionRecorder()
r.on_lap_complete(2, 93200, 27900, 35400, 29900)
r.on_lap_complete(3, 92800, 27700, 34800, 30300)

path = r.finalize(3, "Bahrain", "R", 5, ["OVTK"])
assert path and path.exists()
d = json.loads(path.read_text())
assert d["track_id"] == 3 and d["final_position"] == 5
assert len(d["player_laps"]) == 2
assert d["player_laps"][0]["last_lap_ms"] == 93200

# reset clears
r.reset()
assert r.finalize(3, "Bahrain", "R", None, []) is None

# double finalize without reset → None
r.on_lap_complete(2, 91000, 0, 0, 0)
p2 = r.finalize(3, "Bahrain", "R", 1, [])
assert p2 is not None
assert r.finalize(3, "Bahrain", "R", 1, []) is None

path.unlink(missing_ok=True)
p2.unlink(missing_ok=True)
print("ALL RECORDER TESTS PASSED")
```

- [ ] **Step 2: Run — expect ImportError**

```
python test_recorder.py
```

- [ ] **Step 3: Implement `core/session_recorder.py`**

```python
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from analytics import archive

class SessionRecorder:
    def __init__(self):
        self._laps: list[dict] = []
        self._done = False

    def reset(self) -> None:
        self._laps = []
        self._done = False

    def on_lap_complete(self, lap_num: int, last_lap_ms: int,
                        s1_ms: int, s2_ms: int, s3_ms: int) -> None:
        self._laps.append({"lap": lap_num, "last_lap_ms": last_lap_ms,
                           "s1_ms": s1_ms, "s2_ms": s2_ms, "s3_ms": s3_ms})

    def finalize(self, track_id: int, track_name: str, session_type: str,
                 final_position: int | None, events: list[str]) -> Path | None:
        if self._done or not self._laps:
            return None
        self._done = True
        data = {"timestamp": datetime.now().isoformat(timespec="seconds"),
                "track_id": track_id, "track_name": track_name,
                "session_type": session_type,
                "total_laps_completed": len(self._laps),
                "final_position": final_position,
                "player_laps": list(self._laps),
                "events": list(events)}
        try:
            return archive.save_game_session(data)
        except Exception:
            return None
```

- [ ] **Step 4: Run — expect PASS**

```
python test_recorder.py
```

- [ ] **Step 5: Delete `test_recorder.py`, commit**

```
git add core/session_recorder.py
git commit -m "feat: add core/session_recorder.py - records player laps for post-race compare"
```

---

### Task 6: Extend core/packets.py

**Files:**
- Modify: `core/packets.py`

- [ ] **Step 1: Add diagnostic script `diag_lap_offsets.py` — run during F1 25 race**

```python
"""Run during F1 25 race to find sector time byte offsets. Ctrl+C to stop."""
import socket, struct

HEADER_FORMAT = "<HBBBBBQfIIBB"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
LAP_DATA_SIZE = 57

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", 20777))
print("Listening on port 20777...")
while True:
    data, _ = sock.recvfrom(4096)
    hdr = struct.unpack_from(HEADER_FORMAT, data)
    if hdr[5] != 2: continue  # PACKET_LAP_DATA
    pidx = hdr[10]
    base = HEADER_SIZE + pidx * LAP_DATA_SIZE
    if base + LAP_DATA_SIZE > len(data): continue
    last_ms = struct.unpack_from("<I", data, base)[0]
    if last_ms == 0: continue
    print(f"\nlast_lap_ms={last_ms} ({last_ms/1000:.3f}s)  lap={data[base+33]}")
    # Candidate uint16 values — find two that sum close to last_ms
    for off in [8, 10, 12, 14, 16, 18, 20, 22]:
        v = struct.unpack_from("<H", data, base + off)[0]
        print(f"  offset {off:2d}: {v:6d}ms = {v/1000:.3f}s")
```

Run: `python diag_lap_offsets.py` while racing. Identify offsets where two values sum ≈ `last_ms`. Those are S1 and S2 (derive S3 = last - S1 - S2).

- [ ] **Step 2: Update `parse_player_lap` in `core/packets.py`**

Replace existing `parse_player_lap`:

```python
def parse_player_lap(data: bytes, player_idx: int) -> dict:
    base = HEADER_SIZE + player_idx * LAP_DATA_SIZE
    if base + 34 > len(data):
        return {}

    last_lap_ms = struct.unpack_from("<I", data, base + 0)[0]

    # Sector times: F1 25 format (verify offsets with diag_lap_offsets.py)
    # S1 = minutes*60000 + ms_part; S3 derived from total - S1 - S2
    s1_ms_part = struct.unpack_from("<H", data, base + 8)[0]
    s1_minutes  = data[base + 10]
    s2_ms_part = struct.unpack_from("<H", data, base + 11)[0]
    s2_minutes  = data[base + 13]
    s1_ms = s1_minutes * 60000 + s1_ms_part
    s2_ms = s2_minutes * 60000 + s2_ms_part
    s3_ms = (last_lap_ms - s1_ms - s2_ms
             if last_lap_ms > 0 and s1_ms > 0 and s2_ms > 0 else 0)

    return {
        "position": data[base + 32],
        "current_lap": data[base + 33],
        "last_lap_ms": last_lap_ms,
        "s1_ms": s1_ms,
        "s2_ms": s2_ms,
        "s3_ms": s3_ms,
    }
```

- [ ] **Step 3: Update `parse_session` to return `track_id`**

Replace existing `parse_session`:

```python
def parse_session(data: bytes) -> dict:
    """total_laps and track_id from Session Data (packet 1)."""
    if len(data) < HEADER_SIZE + 8:
        return {}
    track_id = struct.unpack_from("<b", data, HEADER_SIZE + 7)[0]  # int8, signed; -1 = unknown
    return {"total_laps": data[HEADER_SIZE + 3], "track_id": int(track_id)}
```

- [ ] **Step 4: Smoke test**

```
python -c "
from core.packets import parse_player_lap, parse_session, HEADER_SIZE, LAP_DATA_SIZE
import struct
fake = bytes(HEADER_SIZE + 22 * LAP_DATA_SIZE)
r = parse_player_lap(fake, 0)
assert 'last_lap_ms' in r and 's1_ms' in r
fake_s = bytes(HEADER_SIZE + 10)
ps = parse_session(fake_s)
assert 'track_id' in ps
print('packets.py smoke test OK')
"
```

- [ ] **Step 5: Delete `diag_lap_offsets.py`, commit**

```
git add core/packets.py
git commit -m "feat: extend parse_player_lap with sector times; parse_session adds track_id"
```

---

### Task 7: Wire SessionRecorder into core/engine.py

**Files:**
- Modify: `core/engine.py`

Read `core/engine.py` in full before editing to locate exact line numbers.

- [ ] **Step 1: Add imports and instance vars to `__init__`**

At top of `engine.py` add to imports:
```python
from core.session_recorder import SessionRecorder
from analytics.loader import TRACK_ID_TO_GP
```

In `Engine.__init__`, after existing instance vars:
```python
self.recorder = SessionRecorder()
self._track_id: int = -1
self._prev_lap: int = 0
self._session_events: list[str] = []
```

- [ ] **Step 2: Track lap changes in `_update_telemetry`**

In `_update_telemetry`, find where `parse_player_lap` is called. After it, add:

```python
if player_lap_data:
    cur = player_lap_data.get("current_lap", 0)
    lms = player_lap_data.get("last_lap_ms", 0)
    if cur > self._prev_lap and self._prev_lap > 0 and lms > 0:
        self.recorder.on_lap_complete(
            lap_num=self._prev_lap,
            last_lap_ms=lms,
            s1_ms=player_lap_data.get("s1_ms", 0),
            s2_ms=player_lap_data.get("s2_ms", 0),
            s3_ms=player_lap_data.get("s3_ms", 0),
        )
    if cur > 0:
        self._prev_lap = cur
```

- [ ] **Step 3: Update Session packet handling for track_id**

Find `PACKET_SESSION` handling in `_update_telemetry`. After `parse_session(data)`:
```python
session_info = parse_session(data)
if session_info.get("track_id", -1) >= 0:
    self._track_id = session_info["track_id"]
```

- [ ] **Step 4: Add SSTA/CHQF hooks in event loop**

In the event handling block (after `event = parse_event(data)`), before the existing guard checks:

```python
code = event.get("event_code")
if code == "SSTA":
    self.recorder.reset()
    self._session_events = []
    self._prev_lap = 0
elif code in ("CHQF", "SEND"):
    self._session_events.append(code)
    track_name = TRACK_ID_TO_GP.get(self._track_id, ("Unknown", "Unknown"))[0]
    with self.state_lock:
        grid = self.state.get("race", {}).get("grid", [])
        pidx = header.get("player_car_index")
        pos = next((e.get("position") for e in grid
                    if e.get("vehicle_idx") == pidx), None)
    self.recorder.finalize(
        track_id=self._track_id, track_name=track_name,
        session_type="R", final_position=pos,
        events=list(self._session_events),
    )
else:
    self._session_events.append(code)
```

- [ ] **Step 5: Add `set_analytics_context` public method**

```python
def set_analytics_context(self, context: str | None) -> None:
    if hasattr(self, 'brain'):
        self.brain.analytics_context = context
```

- [ ] **Step 6: Smoke test import**

```
python -c "from core.engine import Engine; print('engine OK')"
```

- [ ] **Step 7: Commit**

```
git add core/engine.py
git commit -m "feat: wire SessionRecorder into engine.py - lap recording + SSTA/CHQF hooks"
```

---

### Task 8: commentator/brain.py — accept analytics_context

**Files:**
- Modify: `commentator/brain.py`

- [ ] **Step 1: Read brain.py to find __init__ and prompt-building method**

Locate: `__init__` signature, the method that constructs an LLM prompt string.

- [ ] **Step 2: Add `analytics_context` field to `__init__`**

In `Brain.__init__`, add:
```python
self.analytics_context: str | None = None
```

- [ ] **Step 3: Inject into prompt**

In the method that builds the LLM prompt (search for where a string prompt is assembled), prepend:
```python
if self.analytics_context:
    prompt = f"[Контекст реального GP: {self.analytics_context}]\n" + prompt
```

- [ ] **Step 4: Smoke test**

```
python -c "
from commentator.brain import Brain
b = Brain('tv')
b.analytics_context = 'тест'
assert b.analytics_context == 'тест'
print('brain OK')
"
```

- [ ] **Step 5: Commit**

```
git add commentator/brain.py
git commit -m "feat: add analytics_context to Brain for Qwen GP context injection"
```

---

### Task 9: web_server.py — three new endpoints

**Files:**
- Modify: `web_server.py`

- [ ] **Step 1: Read web_server.py to find engine reference and route patterns**

Note the variable name used for the `Engine` instance (likely `engine` or `_engine`).

- [ ] **Step 2: Add imports**

After existing imports in `web_server.py`:
```python
import json as _json
from analytics import archive as _archive
from analytics.loader import load_f1_session, TRACK_ID_TO_GP
from analytics.normalizer import normalize as _normalize
from analytics.comparator import compare as _compare
```

- [ ] **Step 3: Add `/api/sessions`**

```python
@app.route("/api/sessions", method="GET")
def api_sessions():
    response.content_type = "application/json"
    return _json.dumps(_archive.list_game_sessions(), ensure_ascii=False)
```

- [ ] **Step 4: Add `/api/load_f1`**

```python
@app.route("/api/load_f1", method="POST")
def api_load_f1():
    response.content_type = "application/json"
    try:
        body = _json.loads(request.body.read().decode("utf-8"))
        year = int(body.get("year", 2025))
        stype = str(body.get("stype", "R"))
        game_path = body.get("game_session_path", "")
    except Exception as exc:
        response.status = 400
        return _json.dumps({"error": f"bad_request: {exc}"})

    game = _archive.load_game_session(game_path) or {"player_laps": [], "events": []}
    track_id = int(game.get("track_id", -1))

    session, err = load_f1_session(track_id, year, stype)
    if err:
        return _json.dumps({"error": err})

    f1_data = _normalize(session)
    entry = TRACK_ID_TO_GP.get(track_id)
    if entry:
        f1_data["event"] = entry[1]
    _archive.save_f1(track_id, year, stype, f1_data)

    compare_result = _compare(game, f1_data)
    from pathlib import Path
    cpath = _archive.save_compare(game_path or "no_game", track_id, year, stype, compare_result)

    # Inject Qwen context into engine
    # (replace `engine` with actual variable name found in Step 1)
    try:
        engine.set_analytics_context(compare_result.get("qwen_context"))
    except Exception:
        pass

    return _json.dumps({
        "f1_meta": f1_data,
        "game_meta": {"track_name": game.get("track_name", "?"),
                      "timestamp": game.get("timestamp", ""),
                      "final_position": game.get("final_position"),
                      "total_laps": game.get("total_laps_completed", 0)},
        "compare": compare_result,
        "compare_id": Path(cpath).name,
    }, ensure_ascii=False)
```

- [ ] **Step 5: Add `/api/archive/<compare_id>`**

```python
@app.route("/api/archive/<compare_id>", method="GET")
def api_archive(compare_id):
    response.content_type = "application/json"
    from pathlib import Path
    import config as _cfg
    cpath = Path(_cfg.DATA_DIR) / "race_archive" / compare_id
    data = _archive.load_compare(cpath)
    if data is None:
        response.status = 404
        return _json.dumps({"error": "not_found"})
    return _json.dumps(data, ensure_ascii=False)
```

- [ ] **Step 6: Start app and test `/api/sessions`**

```
python app.pyw
```
In browser or curl: `http://localhost:8765/api/sessions`
Expected: `[]` or list of sessions.

- [ ] **Step 7: Commit**

```
git add web_server.py
git commit -m "feat: add /api/sessions /api/load_f1 /api/archive endpoints"
```

---

### Task 10: index.html — "Архив" tab

**Files:**
- Modify: `index.html`

- [ ] **Step 1: Add nav item** — find `.nav-item` block, append:

```html
<div class="nav-item" data-section="archive" onclick="showSection('archive')">
  <span class="nav-icon">📁</span>
  <span class="nav-label">Архив</span>
</div>
```

- [ ] **Step 2: Add section HTML** — after last `<section>`, add:

```html
<section id="section-archive" class="section" style="display:none">
  <div class="section-header"><h2 class="section-title">АРХИВ ГОНОК</h2></div>
  <div class="card" style="margin-bottom:12px">
    <div class="card-label">ИГРОВАЯ СЕССИЯ</div>
    <select id="arc-session" style="width:100%;margin-bottom:8px">
      <option value="">— выберите сессию —</option>
    </select>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <input type="number" id="arc-year" value="2025" min="2024" max="2025" style="width:72px">
      <select id="arc-stype">
        <option value="R">Гонка</option>
        <option value="Q">Квалификация</option>
        <option value="FP1">Практика 1</option>
      </select>
      <button class="btn-primary" onclick="arcLoad()">Загрузить FastF1</button>
    </div>
    <div id="arc-status" style="margin-top:8px;font-size:12px;color:var(--text-sub)"></div>
  </div>
  <div id="arc-results" style="display:none">
    <div class="card" style="margin-bottom:12px">
      <div class="card-label">РЕАЛЬНЫЙ GP</div>
      <div id="arc-event" style="font-size:14px;font-weight:700;margin-bottom:8px"></div>
      <table style="width:100%;font-size:12px;border-collapse:collapse">
        <thead><tr style="color:var(--text-sub)">
          <th style="text-align:left;padding:4px">P</th>
          <th style="text-align:left;padding:4px">Пилот</th>
          <th style="text-align:left;padding:4px">Команда</th>
          <th style="text-align:right;padding:4px">Разрыв</th>
        </tr></thead>
        <tbody id="arc-f1-rows"></tbody>
      </table>
    </div>
    <div class="card" style="margin-bottom:12px">
      <div class="card-label">СРАВНЕНИЕ — ЛУЧШИЙ КРУГ</div>
      <div id="arc-partial" style="display:none;font-size:12px;color:var(--text-sub);padding:6px;background:rgba(255,255,255,.04);border-radius:4px;margin-bottom:8px">
        ⚠ Неполные данные — секторное сравнение недоступно
      </div>
      <div id="arc-compare"></div>
    </div>
    <div class="card">
      <div class="card-label">КОНТЕКСТ КОММЕНТАТОРА</div>
      <div id="arc-qwen" style="font-size:13px;font-style:italic;padding:8px;background:rgba(255,255,255,.04);border-radius:4px"></div>
    </div>
  </div>
</section>
```

- [ ] **Step 3: Add JS** — inside `<script>` tag:

```javascript
function arcFmtMs(ms) {
  if (!ms) return '?';
  const m = Math.floor(ms / 60000);
  const s = ((ms % 60000) / 1000).toFixed(3).padStart(6, '0');
  return `${m}:${s}`;
}

async function arcLoadSessions() {
  try {
    const r = await fetch('/api/sessions');
    const sessions = await r.json();
    const sel = document.getElementById('arc-session');
    sel.innerHTML = '<option value="">— выберите сессию —</option>';
    sessions.forEach(s => {
      const o = document.createElement('option');
      o.value = s.path;
      o.textContent = `${s.track_name} ${s.timestamp}${s.final_position ? ' P'+s.final_position : ''}`;
      sel.appendChild(o);
    });
  } catch(e) { console.error(e); }
}

async function arcLoad() {
  const path = document.getElementById('arc-session').value;
  const year = document.getElementById('arc-year').value;
  const stype = document.getElementById('arc-stype').value;
  const status = document.getElementById('arc-status');
  if (!path) { status.textContent = 'Выберите сессию'; return; }
  status.textContent = 'Загрузка FastF1… (~30с при первом запросе)';
  try {
    const r = await fetch('/api/load_f1', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({year: parseInt(year), stype, game_session_path: path})
    });
    const data = await r.json();
    if (data.error) { status.textContent = 'Ошибка: ' + data.error; return; }
    status.textContent = 'Загружено ✓';
    arcRender(data);
  } catch(e) { status.textContent = 'Ошибка: ' + e.message; }
}

function arcRender({f1_meta, compare}) {
  document.getElementById('arc-results').style.display = 'block';
  document.getElementById('arc-event').textContent = `${f1_meta.event||'?'} ${f1_meta.year||''}`;

  const tbody = document.getElementById('arc-f1-rows');
  tbody.innerHTML = '';
  (f1_meta.results_top10||[]).forEach(r => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td style="padding:4px;font-weight:${r.pos===1?700:400}">${r.pos}</td>
      <td style="padding:4px">${r.driver}</td>
      <td style="padding:4px;color:var(--text-sub)">${r.team}</td>
      <td style="padding:4px;text-align:right">${r.gap_s!=null?'+'+r.gap_s+'s':'—'}</td>`;
    tbody.appendChild(tr);
  });

  document.getElementById('arc-partial').style.display = compare.partial ? 'block' : 'none';

  let html = `<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">
    <div><div style="font-size:10px;color:var(--text-sub);letter-spacing:1px">ТВОЙ ЛУЧШИЙ</div>
      <div style="font-size:20px;font-weight:700;font-family:monospace">${arcFmtMs(compare.player_best_lap_ms)}</div>
      <div style="font-size:11px;color:var(--text-sub)">круг ${compare.player_best_lap_lap_number||'?'}</div></div>
    <div><div style="font-size:10px;color:var(--text-sub);letter-spacing:1px">F1 БЫСТРЕЙШИЙ</div>
      <div style="font-size:20px;font-weight:700;font-family:monospace;color:var(--accent)">${arcFmtMs(compare.f1_fastest_ms)}</div>
      <div style="font-size:11px;color:var(--text-sub)">${compare.f1_best_lap_driver||'?'}</div></div>
  </div>
  <div style="font-size:13px;margin-bottom:8px">Отставание: <strong>${compare.gap_ms!=null?(compare.gap_ms/1000).toFixed(3)+'с':'—'}</strong></div>`;
  if (compare.sectors) {
    ['s1','s2','s3'].forEach(s => {
      const sec = compare.sectors[s];
      const hot = sec.gap_ms > 500 ? 'color:var(--accent)' : '';
      html += `<div style="display:flex;justify-content:space-between;font-size:12px;padding:3px 0;border-top:1px solid rgba(255,255,255,.06)">
        <span>${s.toUpperCase()}</span>
        <span style="font-family:monospace">${arcFmtMs(sec.player_ms)}</span>
        <span style="color:var(--text-sub)">${arcFmtMs(sec.f1_ms)}</span>
        <span style="${hot}">+${(sec.gap_ms/1000).toFixed(3)}с</span></div>`;
    });
  }
  document.getElementById('arc-compare').innerHTML = html;
  document.getElementById('arc-qwen').textContent = compare.qwen_context || '';
}

// Load sessions when Archive tab opens
document.addEventListener('DOMContentLoaded', () => {
  document.querySelector('[data-section="archive"]')
    ?.addEventListener('click', arcLoadSessions);
});
```

- [ ] **Step 4: Open app, click "Архив", verify tab renders**

- [ ] **Step 5: Commit**

```
git add index.html
git commit -m "feat: add Archive tab to index.html - session picker, F1 results, lap comparison"
```

---

## Self-Review

| Requirement | Task |
|-------------|------|
| archive atomic writes (same drive) | Task 1 |
| normalizer fixed fields + results_top10 | Task 2 |
| loader TRACK_ID_TO_GP 24 entries + warning | Task 3 |
| best-lap comparison only | Task 4 |
| partial=True rules, gap_ms always present | Task 4 |
| qwen_context always ≤ 250 chars | Task 4 |
| fallback templates (4 cases) | Task 4 |
| session_recorder records laps | Task 5 |
| parse_player_lap sector times | Task 6 |
| parse_session returns track_id | Task 6 |
| engine lap-change detection | Task 7 |
| SSTA reset / CHQF finalize | Task 7 |
| brain.analytics_context | Task 8 |
| /api/sessions /api/load_f1 /api/archive | Task 9 |
| /api/load_f1 returns f1_meta+game_meta+compare+compare_id | Task 9 |
| "Архив" tab UI | Task 10 |
| partial notice in UI | Task 10 |
| graceful fallback unknown track | Tasks 3+4 |

All spec requirements covered. ✓
