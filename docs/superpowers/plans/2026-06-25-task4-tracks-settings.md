# Task 4 + All F1 25 Tracks — Settings Persistence & Complete Track Database

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two independent features: (A) add all 24 F1 25 circuits to track intelligence; (B) persist all app settings across restarts with a Reset button.

**Architecture:**
- (A) Simplified corner schema: `{id, fraction, type, direction}` — loader computes `start`/`end`/`attack_side`/`defense_side` from type. Migrate existing 5 tracks. Create 19 new tracks. All 24 pass a single parametric test.
- (B) New `core/settings.py` with `load/save/reset`; `app.pyw` loads on start; `web_server.py` persists on every POST; new `POST /api/settings/reset`; Reset button in `settings.tsx`.

**Tech Stack:** Python 3.12, pathlib, json; Next.js 16 + TypeScript + Tailwind; pytest monkeypatch.

---

## Section A — All 24 F1 25 Circuits

### Task 1: Update `core/track_ai/loader.py` — fraction-based corner schema

**Files:**
- Modify: `core/track_ai/loader.py`

Corner JSON schema changes from 8 fields to 4:
```json
{"id": 1, "fraction": 0.055, "type": "slow", "direction": "left"}
```
`name` is optional (defaults to `"Turn N"`). `start`, `end`, `attack_side`, `defense_side` are computed by the loader from `type`.

- [ ] **Step 1: Replace `core/track_ai/loader.py` entirely**

```python
"""core/track_ai/loader.py — load track JSON from the tracks/ database.

Corner JSON schema (new, compact):
    {"id": 1, "fraction": 0.055, "type": "slow", "direction": "left"}
    optional: "name" (defaults to "Turn N")

Loader computes start/end and attack_side/defense_side from type.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.track_ai.models import Corner, TrackInfo

_TRACKS_DIR = Path(__file__).parent.parent.parent / "tracks"

# Half-widths before/after the apex fraction, by corner type.
# start = fraction - _PRE, end = fraction + _POST
_PRE: dict[str, float] = {
    "hairpin": 0.025, "slow": 0.020, "medium": 0.015,
    "fast": 0.012, "chicane": 0.018,
}
_POST: dict[str, float] = {
    "hairpin": 0.025, "slow": 0.018, "medium": 0.013,
    "fast": 0.012, "chicane": 0.018,
}

# Derived attack/defense sides by type (no overtaking on fast corners).
_SIDES: dict[str, tuple[str, str]] = {
    "hairpin": ("inside", "inside"),
    "slow":    ("inside", "inside"),
    "medium":  ("inside", "inside"),
    "fast":    ("none",   "outside"),
    "chicane": ("inside", "inside"),
}

_TRACK_FILES: dict[str, str] = {
    # original 5
    "Bahrain":     "bahrain",
    "Sakhir":      "bahrain",
    "Monza":       "monza",
    "Spa":         "spa",
    "Silverstone": "silverstone",
    "Monaco":      "monaco",
    # all remaining F1 25 circuits
    "Melbourne":   "melbourne",
    "Shanghai":    "shanghai",
    "Suzuka":      "suzuka",
    "Jeddah":      "jeddah",
    "Miami":       "miami",
    "Imola":       "imola",
    "Barcelona":   "barcelona",
    "Montreal":    "montreal",
    "Spielberg":   "spielberg",
    "Budapest":    "budapest",
    "Zandvoort":   "zandvoort",
    "Baku":        "baku",
    "Singapore":   "singapore",
    "Austin":      "austin",
    "Mexico City": "mexico_city",
    "São Paulo":   "sao_paulo",
    "Las Vegas":   "las_vegas",
    "Lusail":      "lusail",
    "Abu Dhabi":   "abu_dhabi",
}


def _corner_from_dict(raw: dict, idx: int) -> Corner:
    """Parse one corner dict. Supports compact fraction schema only."""
    cid = raw.get("id", idx + 1)
    name = raw.get("name", f"Turn {cid}")
    typ = raw["type"]
    frac = float(raw["fraction"])
    pre = _PRE.get(typ, 0.015)
    post = _POST.get(typ, 0.013)
    atk, dfn = _SIDES.get(typ, ("inside", "inside"))
    return Corner(
        id=cid,
        name=name,
        start=max(0.0, frac - pre),
        end=min(1.0, frac + post),
        type=typ,
        direction=raw["direction"],
        attack_side=atk,
        defense_side=dfn,
    )


def load_track(city: str) -> TrackInfo | None:
    """Load TrackInfo for city name; return None if unknown or file missing."""
    stem = _TRACK_FILES.get(city)
    if stem is None:
        return None

    path = _TRACKS_DIR / f"{stem}.json"
    if not path.exists():
        return None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    corners = [_corner_from_dict(c, i) for i, c in enumerate(raw.get("corners", []))]
    return TrackInfo(
        name=raw["name"],
        length_m=float(raw["length_m"]),
        corners=corners,
    )
```

- [ ] **Step 2: Verify import + smoke-load**

```powershell
py -3.12 -c "
from core.track_ai.loader import load_track
t = load_track('Bahrain')
print(t.name, t.length_m, 'corners:', len(t.corners))
print('T1 start:', round(t.corners[0].start,3), 'end:', round(t.corners[0].end,3))
"
```

Expected (after Bahrain migration in Task 2):
```
Bahrain 5412.0 corners: 15
T1 start: 0.035 end: 0.075
```
(start = 0.055 - 0.020 = 0.035, end = 0.055 + 0.020 = 0.075 — same as old file)

---

### Task 2: Migrate existing 5 tracks to fraction schema

**Files:**
- Overwrite: `tracks/bahrain.json`
- Overwrite: `tracks/monza.json`
- Overwrite: `tracks/spa.json`
- Overwrite: `tracks/silverstone.json`
- Overwrite: `tracks/monaco.json`

Fractions are midpoints of original `start`/`end` ranges. Named corners preserve their names.

- [ ] **Step 1: Overwrite `tracks/bahrain.json`**

```json
{
  "name": "Bahrain",
  "length_m": 5412,
  "corners": [
    {"id":1,  "name":"Turn 1",  "fraction":0.055,"type":"slow",   "direction":"left"},
    {"id":2,  "name":"Turn 2",  "fraction":0.094,"type":"fast",   "direction":"right"},
    {"id":3,  "name":"Turn 3",  "fraction":0.119,"type":"medium", "direction":"left"},
    {"id":4,  "name":"Turn 4",  "fraction":0.145,"type":"medium", "direction":"right"},
    {"id":5,  "name":"Turn 5",  "fraction":0.170,"type":"slow",   "direction":"right"},
    {"id":6,  "name":"Turn 6",  "fraction":0.195,"type":"medium", "direction":"left"},
    {"id":7,  "name":"Turn 7",  "fraction":0.227,"type":"fast",   "direction":"right"},
    {"id":8,  "name":"Turn 8",  "fraction":0.424,"type":"hairpin","direction":"left"},
    {"id":9,  "name":"Turn 9",  "fraction":0.467,"type":"medium", "direction":"right"},
    {"id":10, "name":"Turn 10", "fraction":0.557,"type":"slow",   "direction":"right"},
    {"id":11, "name":"Turn 11", "fraction":0.584,"type":"slow",   "direction":"left"},
    {"id":12, "name":"Turn 12", "fraction":0.645,"type":"fast",   "direction":"left"},
    {"id":13, "name":"Turn 13", "fraction":0.765,"type":"hairpin","direction":"right"},
    {"id":14, "name":"Turn 14", "fraction":0.803,"type":"medium", "direction":"left"},
    {"id":15, "name":"Turn 15", "fraction":0.886,"type":"slow",   "direction":"right"}
  ]
}
```

- [ ] **Step 2: Overwrite `tracks/monza.json`**

```json
{
  "name": "Monza",
  "length_m": 5793,
  "corners": [
    {"id":1,"name":"Variante del Rettifilo","fraction":0.117,"type":"chicane","direction":"right"},
    {"id":2,"name":"Curva Grande",          "fraction":0.205,"type":"fast",   "direction":"left"},
    {"id":3,"name":"Variante della Roggia", "fraction":0.363,"type":"chicane","direction":"right"},
    {"id":4,"name":"Lesmo 1",               "fraction":0.470,"type":"medium", "direction":"right"},
    {"id":5,"name":"Lesmo 2",               "fraction":0.552,"type":"medium", "direction":"right"},
    {"id":6,"name":"Variante Ascari",       "fraction":0.708,"type":"chicane","direction":"right"},
    {"id":7,"name":"Curva Parabolica",      "fraction":0.877,"type":"medium", "direction":"right"}
  ]
}
```

- [ ] **Step 3: Overwrite `tracks/spa.json`**

```json
{
  "name": "Spa",
  "length_m": 7004,
  "corners": [
    {"id":1, "name":"La Source",  "fraction":0.051,"type":"hairpin","direction":"right"},
    {"id":2, "name":"Eau Rouge",  "fraction":0.123,"type":"fast",   "direction":"left"},
    {"id":3, "name":"Les Combes", "fraction":0.295,"type":"chicane","direction":"right"},
    {"id":4, "name":"Rivage",     "fraction":0.375,"type":"slow",   "direction":"right"},
    {"id":5, "name":"Pouhon",     "fraction":0.469,"type":"fast",   "direction":"left"},
    {"id":6, "name":"Fagnes",     "fraction":0.544,"type":"chicane","direction":"right"},
    {"id":7, "name":"Stavelot",   "fraction":0.613,"type":"medium", "direction":"right"},
    {"id":8, "name":"Paul Frere", "fraction":0.666,"type":"fast",   "direction":"right"},
    {"id":9, "name":"Blanchimont","fraction":0.770,"type":"fast",   "direction":"left"},
    {"id":10,"name":"Bus Stop",   "fraction":0.865,"type":"chicane","direction":"right"}
  ]
}
```

- [ ] **Step 4: Overwrite `tracks/silverstone.json`**

```json
{
  "name": "Silverstone",
  "length_m": 5891,
  "corners": [
    {"id":1, "name":"Abbey",    "fraction":0.080,"type":"medium", "direction":"right"},
    {"id":2, "name":"Farm",     "fraction":0.130,"type":"medium", "direction":"left"},
    {"id":3, "name":"Village",  "fraction":0.190,"type":"slow",   "direction":"right"},
    {"id":4, "name":"The Loop", "fraction":0.258,"type":"hairpin","direction":"right"},
    {"id":5, "name":"Aintree",  "fraction":0.334,"type":"medium", "direction":"right"},
    {"id":6, "name":"Wellington","fraction":0.390,"type":"medium","direction":"left"},
    {"id":7, "name":"Brooklands","fraction":0.454,"type":"medium","direction":"right"},
    {"id":8, "name":"Luffield", "fraction":0.530,"type":"slow",   "direction":"left"},
    {"id":9, "name":"Woodcote", "fraction":0.645,"type":"fast",   "direction":"right"},
    {"id":10,"name":"Copse",    "fraction":0.702,"type":"fast",   "direction":"right"},
    {"id":11,"name":"Becketts", "fraction":0.780,"type":"fast",   "direction":"right"},
    {"id":12,"name":"Chapel",   "fraction":0.845,"type":"fast",   "direction":"left"},
    {"id":13,"name":"Stowe",    "fraction":0.903,"type":"medium", "direction":"right"},
    {"id":14,"name":"Vale",     "fraction":0.956,"type":"slow",   "direction":"right"}
  ]
}
```

- [ ] **Step 5: Overwrite `tracks/monaco.json`**

```json
{
  "name": "Monaco",
  "length_m": 3337,
  "corners": [
    {"id":1, "name":"Sainte Devote",      "fraction":0.065,"type":"medium", "direction":"right"},
    {"id":2, "name":"Massenet",           "fraction":0.164,"type":"fast",   "direction":"left"},
    {"id":3, "name":"Casino",             "fraction":0.248,"type":"slow",   "direction":"right"},
    {"id":4, "name":"Mirabeau",           "fraction":0.340,"type":"medium", "direction":"right"},
    {"id":5, "name":"Grand Hotel Hairpin","fraction":0.425,"type":"hairpin","direction":"left"},
    {"id":6, "name":"Mirabeau Bas",       "fraction":0.523,"type":"medium", "direction":"right"},
    {"id":7, "name":"Portier",            "fraction":0.614,"type":"medium", "direction":"right"},
    {"id":8, "name":"Nouvelle Chicane",   "fraction":0.780,"type":"chicane","direction":"right"},
    {"id":9, "name":"Tabac",              "fraction":0.855,"type":"medium", "direction":"right"},
    {"id":10,"name":"Piscine",            "fraction":0.910,"type":"chicane","direction":"right"},
    {"id":11,"name":"La Rascasse",        "fraction":0.956,"type":"hairpin","direction":"right"},
    {"id":12,"name":"Anthony Noghes",     "fraction":0.985,"type":"medium", "direction":"left"}
  ]
}
```

- [ ] **Step 6: Run existing track tests (must still pass)**

```powershell
py -3.12 -m pytest tests/test_track_ai.py -v -k "loader or track_manager"
```

Expected: all existing loader/manager tests pass.

---

### Task 3: Create 19 new track JSON files

**Files:** Create `tracks/melbourne.json` through `tracks/abu_dhabi.json`

All files use the same compact schema: `{id, fraction, type, direction}` with optional `name`.

- [ ] **Step 1: Create `tracks/melbourne.json`** — Albert Park, 5278 m

```json
{
  "name": "Melbourne",
  "length_m": 5278,
  "corners": [
    {"id":1, "fraction":0.045,"type":"slow",   "direction":"right"},
    {"id":2, "fraction":0.080,"type":"medium", "direction":"left"},
    {"id":3, "fraction":0.133,"type":"slow",   "direction":"right"},
    {"id":4, "fraction":0.165,"type":"medium", "direction":"left"},
    {"id":5, "fraction":0.204,"type":"fast",   "direction":"right"},
    {"id":6, "fraction":0.257,"type":"medium", "direction":"left"},
    {"id":7, "fraction":0.291,"type":"medium", "direction":"right"},
    {"id":8, "fraction":0.395,"type":"hairpin","direction":"left"},
    {"id":9, "fraction":0.524,"type":"medium", "direction":"right"},
    {"id":10,"fraction":0.554,"type":"slow",   "direction":"left"},
    {"id":11,"fraction":0.635,"type":"chicane","direction":"right"},
    {"id":12,"fraction":0.658,"type":"chicane","direction":"left"},
    {"id":13,"fraction":0.774,"type":"medium", "direction":"right"},
    {"id":14,"fraction":0.811,"type":"medium", "direction":"left"},
    {"id":15,"fraction":0.890,"type":"chicane","direction":"right"},
    {"id":16,"fraction":0.914,"type":"chicane","direction":"left"}
  ]
}
```

- [ ] **Step 2: Create `tracks/shanghai.json`** — Shanghai International Circuit, 5451 m

```json
{
  "name": "Shanghai",
  "length_m": 5451,
  "corners": [
    {"id":1, "fraction":0.039,"type":"fast",   "direction":"left"},
    {"id":2, "fraction":0.078,"type":"hairpin","direction":"left"},
    {"id":3, "fraction":0.110,"type":"fast",   "direction":"right"},
    {"id":4, "fraction":0.138,"type":"fast",   "direction":"left"},
    {"id":5, "fraction":0.165,"type":"fast",   "direction":"right"},
    {"id":6, "fraction":0.347,"type":"hairpin","direction":"right"},
    {"id":7, "fraction":0.387,"type":"medium", "direction":"left"},
    {"id":8, "fraction":0.415,"type":"medium", "direction":"right"},
    {"id":9, "fraction":0.442,"type":"medium", "direction":"left"},
    {"id":10,"fraction":0.493,"type":"slow",   "direction":"left"},
    {"id":11,"fraction":0.588,"type":"fast",   "direction":"right"},
    {"id":12,"fraction":0.623,"type":"fast",   "direction":"left"},
    {"id":13,"fraction":0.657,"type":"fast",   "direction":"right"},
    {"id":14,"fraction":0.727,"type":"medium", "direction":"left"},
    {"id":15,"fraction":0.758,"type":"medium", "direction":"right"},
    {"id":16,"fraction":0.845,"type":"hairpin","direction":"right"}
  ]
}
```

- [ ] **Step 3: Create `tracks/suzuka.json`** — Suzuka Circuit, 5807 m

```json
{
  "name": "Suzuka",
  "length_m": 5807,
  "corners": [
    {"id":1, "name":"First Curve",    "fraction":0.045,"type":"fast",   "direction":"right"},
    {"id":2, "name":"First Curve 2",  "fraction":0.073,"type":"fast",   "direction":"left"},
    {"id":3, "name":"S Curve 1",      "fraction":0.096,"type":"chicane","direction":"right"},
    {"id":4, "name":"S Curve 2",      "fraction":0.116,"type":"chicane","direction":"left"},
    {"id":5, "name":"S Curve 3",      "fraction":0.136,"type":"chicane","direction":"right"},
    {"id":6, "name":"Dunlop",         "fraction":0.168,"type":"medium", "direction":"right"},
    {"id":7, "name":"Degner 1",       "fraction":0.203,"type":"medium", "direction":"right"},
    {"id":8, "name":"Degner 2",       "fraction":0.228,"type":"medium", "direction":"left"},
    {"id":9, "name":"Hairpin",        "fraction":0.297,"type":"hairpin","direction":"left"},
    {"id":10,"name":"Spoon 1",        "fraction":0.440,"type":"fast",   "direction":"left"},
    {"id":11,"name":"Spoon 2",        "fraction":0.468,"type":"medium", "direction":"left"},
    {"id":12,"name":"130R",           "fraction":0.600,"type":"fast",   "direction":"left"},
    {"id":13,"name":"Casio Chicane 1","fraction":0.651,"type":"chicane","direction":"right"},
    {"id":14,"name":"Casio Chicane 2","fraction":0.671,"type":"chicane","direction":"left"}
  ]
}
```

- [ ] **Step 4: Create `tracks/jeddah.json`** — Jeddah Corniche Circuit, 6174 m

```json
{
  "name": "Jeddah",
  "length_m": 6174,
  "corners": [
    {"id":1,  "fraction":0.024,"type":"slow",   "direction":"right"},
    {"id":4,  "fraction":0.099,"type":"medium", "direction":"left"},
    {"id":7,  "fraction":0.185,"type":"fast",   "direction":"left"},
    {"id":10, "fraction":0.278,"type":"medium", "direction":"right"},
    {"id":12, "fraction":0.330,"type":"slow",   "direction":"right"},
    {"id":13, "fraction":0.360,"type":"medium", "direction":"left"},
    {"id":17, "fraction":0.490,"type":"fast",   "direction":"right"},
    {"id":20, "fraction":0.568,"type":"medium", "direction":"left"},
    {"id":22, "fraction":0.640,"type":"slow",   "direction":"right"},
    {"id":23, "fraction":0.671,"type":"medium", "direction":"left"},
    {"id":25, "fraction":0.738,"type":"fast",   "direction":"right"},
    {"id":27, "fraction":0.803,"type":"medium", "direction":"left"}
  ]
}
```

- [ ] **Step 5: Create `tracks/miami.json`** — Miami International Autodrome, 5412 m

```json
{
  "name": "Miami",
  "length_m": 5412,
  "corners": [
    {"id":1,  "fraction":0.032,"type":"slow",   "direction":"right"},
    {"id":2,  "fraction":0.062,"type":"medium", "direction":"left"},
    {"id":3,  "fraction":0.090,"type":"medium", "direction":"right"},
    {"id":5,  "fraction":0.142,"type":"fast",   "direction":"left"},
    {"id":6,  "fraction":0.169,"type":"chicane","direction":"right"},
    {"id":7,  "fraction":0.189,"type":"chicane","direction":"left"},
    {"id":11, "fraction":0.373,"type":"medium", "direction":"left"},
    {"id":12, "fraction":0.401,"type":"medium", "direction":"right"},
    {"id":14, "fraction":0.485,"type":"hairpin","direction":"left"},
    {"id":15, "fraction":0.518,"type":"medium", "direction":"right"},
    {"id":17, "fraction":0.622,"type":"chicane","direction":"left"},
    {"id":18, "fraction":0.645,"type":"chicane","direction":"right"},
    {"id":19, "fraction":0.735,"type":"slow",   "direction":"left"}
  ]
}
```

- [ ] **Step 6: Create `tracks/imola.json`** — Autodromo Enzo e Dino Ferrari, 4909 m

```json
{
  "name": "Imola",
  "length_m": 4909,
  "corners": [
    {"id":1, "name":"Tamburello 1",    "fraction":0.045,"type":"chicane","direction":"right"},
    {"id":2, "name":"Tamburello 2",    "fraction":0.066,"type":"chicane","direction":"left"},
    {"id":3, "name":"Villeneuve",      "fraction":0.134,"type":"medium", "direction":"right"},
    {"id":4, "name":"Tosa",            "fraction":0.230,"type":"hairpin","direction":"left"},
    {"id":5, "name":"Piratella",       "fraction":0.376,"type":"medium", "direction":"left"},
    {"id":6, "name":"Acque Minerali 1","fraction":0.437,"type":"medium", "direction":"right"},
    {"id":7, "name":"Acque Minerali 2","fraction":0.464,"type":"medium", "direction":"left"},
    {"id":8, "name":"Variante Alta 1", "fraction":0.568,"type":"chicane","direction":"right"},
    {"id":9, "name":"Variante Alta 2", "fraction":0.590,"type":"chicane","direction":"left"},
    {"id":10,"name":"Rivazza 1",       "fraction":0.755,"type":"hairpin","direction":"right"},
    {"id":11,"name":"Rivazza 2",       "fraction":0.789,"type":"medium", "direction":"left"}
  ]
}
```

- [ ] **Step 7: Create `tracks/barcelona.json`** — Circuit de Barcelona-Catalunya, 4657 m

```json
{
  "name": "Barcelona",
  "length_m": 4657,
  "corners": [
    {"id":1,  "fraction":0.040,"type":"slow",   "direction":"right"},
    {"id":2,  "fraction":0.079,"type":"medium", "direction":"left"},
    {"id":3,  "fraction":0.108,"type":"medium", "direction":"right"},
    {"id":4,  "fraction":0.141,"type":"medium", "direction":"left"},
    {"id":5,  "fraction":0.202,"type":"slow",   "direction":"left"},
    {"id":6,  "fraction":0.245,"type":"medium", "direction":"right"},
    {"id":7,  "fraction":0.275,"type":"medium", "direction":"left"},
    {"id":8,  "fraction":0.312,"type":"fast",   "direction":"right"},
    {"id":9,  "fraction":0.493,"type":"slow",   "direction":"left"},
    {"id":10, "fraction":0.565,"type":"medium", "direction":"right"},
    {"id":11, "fraction":0.626,"type":"fast",   "direction":"left"},
    {"id":12, "fraction":0.695,"type":"fast",   "direction":"right"},
    {"id":13, "fraction":0.754,"type":"fast",   "direction":"right"},
    {"id":14, "fraction":0.823,"type":"medium", "direction":"left"}
  ]
}
```

- [ ] **Step 8: Create `tracks/montreal.json`** — Circuit Gilles Villeneuve, 4361 m

```json
{
  "name": "Montreal",
  "length_m": 4361,
  "corners": [
    {"id":1,  "fraction":0.033,"type":"medium", "direction":"right"},
    {"id":2,  "fraction":0.062,"type":"medium", "direction":"left"},
    {"id":3,  "fraction":0.092,"type":"medium", "direction":"right"},
    {"id":4,  "fraction":0.173,"type":"medium", "direction":"left"},
    {"id":5,  "name":"Casino 1",        "fraction":0.281,"type":"chicane","direction":"right"},
    {"id":6,  "name":"Casino 2",        "fraction":0.305,"type":"chicane","direction":"left"},
    {"id":7,  "fraction":0.372,"type":"medium", "direction":"right"},
    {"id":8,  "name":"Senna's Hairpin", "fraction":0.440,"type":"hairpin","direction":"left"},
    {"id":9,  "fraction":0.478,"type":"medium", "direction":"right"},
    {"id":10, "fraction":0.614,"type":"medium", "direction":"left"},
    {"id":11, "fraction":0.663,"type":"medium", "direction":"right"},
    {"id":12, "fraction":0.754,"type":"medium", "direction":"left"},
    {"id":13, "name":"Wall of Champs 1","fraction":0.838,"type":"chicane","direction":"right"},
    {"id":14, "name":"Wall of Champs 2","fraction":0.867,"type":"chicane","direction":"left"}
  ]
}
```

- [ ] **Step 9: Create `tracks/spielberg.json`** — Red Bull Ring, 4318 m

```json
{
  "name": "Spielberg",
  "length_m": 4318,
  "corners": [
    {"id":1,  "fraction":0.038,"type":"slow",   "direction":"right"},
    {"id":2,  "fraction":0.163,"type":"medium", "direction":"right"},
    {"id":3,  "fraction":0.252,"type":"slow",   "direction":"left"},
    {"id":4,  "fraction":0.303,"type":"medium", "direction":"left"},
    {"id":5,  "fraction":0.417,"type":"fast",   "direction":"right"},
    {"id":6,  "fraction":0.448,"type":"medium", "direction":"left"},
    {"id":7,  "fraction":0.533,"type":"medium", "direction":"right"},
    {"id":8,  "fraction":0.649,"type":"medium", "direction":"right"},
    {"id":9,  "fraction":0.755,"type":"slow",   "direction":"left"},
    {"id":10, "fraction":0.859,"type":"medium", "direction":"right"}
  ]
}
```

- [ ] **Step 10: Create `tracks/budapest.json`** — Hungaroring, 4381 m

```json
{
  "name": "Budapest",
  "length_m": 4381,
  "corners": [
    {"id":1,  "fraction":0.033,"type":"medium", "direction":"right"},
    {"id":2,  "fraction":0.065,"type":"medium", "direction":"left"},
    {"id":3,  "fraction":0.099,"type":"medium", "direction":"right"},
    {"id":4,  "fraction":0.158,"type":"hairpin","direction":"left"},
    {"id":5,  "fraction":0.192,"type":"medium", "direction":"right"},
    {"id":6,  "fraction":0.255,"type":"medium", "direction":"left"},
    {"id":7,  "fraction":0.294,"type":"medium", "direction":"right"},
    {"id":8,  "fraction":0.370,"type":"medium", "direction":"left"},
    {"id":9,  "fraction":0.450,"type":"medium", "direction":"right"},
    {"id":10, "fraction":0.500,"type":"medium", "direction":"left"},
    {"id":11, "fraction":0.569,"type":"hairpin","direction":"right"},
    {"id":12, "fraction":0.610,"type":"medium", "direction":"left"},
    {"id":13, "fraction":0.685,"type":"medium", "direction":"right"},
    {"id":14, "fraction":0.773,"type":"medium", "direction":"left"}
  ]
}
```

- [ ] **Step 11: Create `tracks/zandvoort.json`** — Circuit Zandvoort, 4259 m

```json
{
  "name": "Zandvoort",
  "length_m": 4259,
  "corners": [
    {"id":1,  "name":"Tarzanbocht",   "fraction":0.034,"type":"hairpin","direction":"right"},
    {"id":2,  "fraction":0.080,"type":"medium", "direction":"left"},
    {"id":3,  "name":"Hugenholtz",    "fraction":0.148,"type":"fast",   "direction":"right"},
    {"id":4,  "fraction":0.187,"type":"medium", "direction":"left"},
    {"id":5,  "fraction":0.238,"type":"medium", "direction":"right"},
    {"id":6,  "name":"Hunzerug",      "fraction":0.323,"type":"slow",   "direction":"left"},
    {"id":7,  "fraction":0.364,"type":"medium", "direction":"right"},
    {"id":8,  "name":"Audi S",        "fraction":0.448,"type":"medium", "direction":"left"},
    {"id":9,  "fraction":0.477,"type":"medium", "direction":"right"},
    {"id":10, "fraction":0.550,"type":"medium", "direction":"left"},
    {"id":11, "fraction":0.620,"type":"medium", "direction":"right"},
    {"id":12, "fraction":0.657,"type":"medium", "direction":"left"},
    {"id":13, "name":"Scheivlak",     "fraction":0.732,"type":"fast",   "direction":"right"},
    {"id":14, "name":"Arie Luyendyk", "fraction":0.837,"type":"fast",   "direction":"right"}
  ]
}
```

- [ ] **Step 12: Create `tracks/baku.json`** — Baku City Circuit, 6003 m

```json
{
  "name": "Baku",
  "length_m": 6003,
  "corners": [
    {"id":1,  "fraction":0.025,"type":"medium", "direction":"right"},
    {"id":2,  "fraction":0.054,"type":"medium", "direction":"left"},
    {"id":3,  "fraction":0.111,"type":"slow",   "direction":"left"},
    {"id":4,  "fraction":0.138,"type":"slow",   "direction":"right"},
    {"id":5,  "fraction":0.162,"type":"slow",   "direction":"left"},
    {"id":6,  "fraction":0.186,"type":"slow",   "direction":"right"},
    {"id":7,  "fraction":0.208,"type":"slow",   "direction":"left"},
    {"id":8,  "fraction":0.237,"type":"slow",   "direction":"right"},
    {"id":10, "fraction":0.364,"type":"medium", "direction":"right"},
    {"id":11, "fraction":0.397,"type":"medium", "direction":"left"},
    {"id":15, "name":"Turn 15","fraction":0.565,"type":"hairpin","direction":"right"},
    {"id":16, "fraction":0.604,"type":"medium", "direction":"left"},
    {"id":20, "name":"Turn 20","fraction":0.914,"type":"slow",   "direction":"left"}
  ]
}
```

- [ ] **Step 13: Create `tracks/singapore.json`** — Marina Bay Street Circuit, 4940 m

```json
{
  "name": "Singapore",
  "length_m": 4940,
  "corners": [
    {"id":1,  "fraction":0.025,"type":"slow",   "direction":"right"},
    {"id":2,  "fraction":0.054,"type":"medium", "direction":"right"},
    {"id":3,  "fraction":0.099,"type":"medium", "direction":"left"},
    {"id":5,  "fraction":0.159,"type":"slow",   "direction":"right"},
    {"id":7,  "fraction":0.229,"type":"hairpin","direction":"left"},
    {"id":8,  "fraction":0.267,"type":"medium", "direction":"right"},
    {"id":10, "fraction":0.355,"type":"medium", "direction":"right"},
    {"id":11, "fraction":0.387,"type":"medium", "direction":"left"},
    {"id":13, "fraction":0.460,"type":"medium", "direction":"left"},
    {"id":14, "fraction":0.490,"type":"medium", "direction":"right"},
    {"id":16, "fraction":0.592,"type":"slow",   "direction":"left"},
    {"id":18, "fraction":0.679,"type":"medium", "direction":"right"},
    {"id":20, "fraction":0.750,"type":"slow",   "direction":"left"},
    {"id":22, "fraction":0.822,"type":"slow",   "direction":"right"},
    {"id":23, "fraction":0.903,"type":"medium", "direction":"left"}
  ]
}
```

- [ ] **Step 14: Create `tracks/austin.json`** — Circuit of the Americas, 5513 m

```json
{
  "name": "Austin",
  "length_m": 5513,
  "corners": [
    {"id":1,  "fraction":0.034,"type":"slow",   "direction":"left"},
    {"id":2,  "fraction":0.072,"type":"medium", "direction":"right"},
    {"id":3,  "fraction":0.102,"type":"medium", "direction":"left"},
    {"id":4,  "fraction":0.134,"type":"medium", "direction":"right"},
    {"id":6,  "fraction":0.207,"type":"fast",   "direction":"right"},
    {"id":7,  "fraction":0.237,"type":"fast",   "direction":"left"},
    {"id":8,  "fraction":0.272,"type":"fast",   "direction":"right"},
    {"id":9,  "fraction":0.295,"type":"fast",   "direction":"left"},
    {"id":10, "fraction":0.318,"type":"fast",   "direction":"right"},
    {"id":11, "fraction":0.387,"type":"hairpin","direction":"right"},
    {"id":12, "fraction":0.428,"type":"medium", "direction":"left"},
    {"id":15, "fraction":0.568,"type":"medium", "direction":"right"},
    {"id":16, "fraction":0.600,"type":"medium", "direction":"left"},
    {"id":18, "fraction":0.697,"type":"medium", "direction":"left"},
    {"id":19, "fraction":0.757,"type":"chicane","direction":"right"},
    {"id":20, "fraction":0.787,"type":"chicane","direction":"left"}
  ]
}
```

- [ ] **Step 15: Create `tracks/mexico_city.json`** — Autodromo Hermanos Rodriguez, 4304 m

```json
{
  "name": "Mexico City",
  "length_m": 4304,
  "corners": [
    {"id":1,  "fraction":0.029,"type":"medium", "direction":"right"},
    {"id":2,  "fraction":0.059,"type":"medium", "direction":"left"},
    {"id":3,  "fraction":0.085,"type":"medium", "direction":"right"},
    {"id":4,  "fraction":0.130,"type":"slow",   "direction":"left"},
    {"id":5,  "fraction":0.158,"type":"slow",   "direction":"right"},
    {"id":6,  "name":"Esses 1",   "fraction":0.208,"type":"fast","direction":"left"},
    {"id":7,  "name":"Esses 2",   "fraction":0.232,"type":"fast","direction":"right"},
    {"id":8,  "name":"Esses 3",   "fraction":0.258,"type":"fast","direction":"left"},
    {"id":11, "fraction":0.432,"type":"medium", "direction":"right"},
    {"id":12, "fraction":0.465,"type":"medium", "direction":"left"},
    {"id":14, "fraction":0.570,"type":"slow",   "direction":"left"},
    {"id":15, "fraction":0.617,"type":"medium", "direction":"right"},
    {"id":16, "name":"Foro Sol",  "fraction":0.679,"type":"fast","direction":"right"},
    {"id":17, "name":"Peraltada", "fraction":0.753,"type":"fast","direction":"right"}
  ]
}
```

- [ ] **Step 16: Create `tracks/sao_paulo.json`** — Autodromo Jose Carlos Pace (Interlagos), 4309 m

```json
{
  "name": "São Paulo",
  "length_m": 4309,
  "corners": [
    {"id":1,  "name":"Curva 1",          "fraction":0.043,"type":"slow",   "direction":"right"},
    {"id":2,  "fraction":0.074,"type":"medium", "direction":"left"},
    {"id":3,  "fraction":0.107,"type":"medium", "direction":"right"},
    {"id":4,  "name":"S da Senna 1",     "fraction":0.192,"type":"chicane","direction":"right"},
    {"id":5,  "name":"S da Senna 2",     "fraction":0.220,"type":"chicane","direction":"left"},
    {"id":6,  "name":"Descida do Lago",  "fraction":0.272,"type":"medium", "direction":"right"},
    {"id":7,  "fraction":0.343,"type":"medium", "direction":"left"},
    {"id":8,  "name":"Ferradura",        "fraction":0.434,"type":"hairpin","direction":"right"},
    {"id":9,  "fraction":0.475,"type":"medium", "direction":"left"},
    {"id":10, "fraction":0.532,"type":"medium", "direction":"right"},
    {"id":11, "name":"Juncao",           "fraction":0.630,"type":"medium", "direction":"right"},
    {"id":12, "fraction":0.665,"type":"medium", "direction":"left"},
    {"id":14, "name":"Mergulho",         "fraction":0.797,"type":"fast",   "direction":"left"},
    {"id":15, "name":"Subida dos Boxes", "fraction":0.863,"type":"slow",   "direction":"right"}
  ]
}
```

- [ ] **Step 17: Create `tracks/las_vegas.json`** — Las Vegas Strip Circuit, 6201 m

```json
{
  "name": "Las Vegas",
  "length_m": 6201,
  "corners": [
    {"id":1,  "fraction":0.020,"type":"slow",   "direction":"right"},
    {"id":2,  "fraction":0.040,"type":"slow",   "direction":"left"},
    {"id":3,  "fraction":0.092,"type":"medium", "direction":"right"},
    {"id":4,  "fraction":0.158,"type":"slow",   "direction":"right"},
    {"id":5,  "fraction":0.179,"type":"slow",   "direction":"left"},
    {"id":6,  "fraction":0.232,"type":"medium", "direction":"right"},
    {"id":7,  "fraction":0.299,"type":"medium", "direction":"left"},
    {"id":8,  "fraction":0.368,"type":"medium", "direction":"right"},
    {"id":10, "fraction":0.461,"type":"slow",   "direction":"left"},
    {"id":11, "fraction":0.490,"type":"medium", "direction":"right"},
    {"id":12, "fraction":0.559,"type":"hairpin","direction":"left"},
    {"id":13, "fraction":0.603,"type":"medium", "direction":"right"},
    {"id":14, "fraction":0.664,"type":"slow",   "direction":"left"},
    {"id":15, "fraction":0.692,"type":"slow",   "direction":"right"},
    {"id":16, "fraction":0.761,"type":"medium", "direction":"left"},
    {"id":17, "fraction":0.825,"type":"slow",   "direction":"right"}
  ]
}
```

- [ ] **Step 18: Create `tracks/lusail.json`** — Lusail International Circuit, 5380 m

```json
{
  "name": "Lusail",
  "length_m": 5380,
  "corners": [
    {"id":1,  "fraction":0.030,"type":"slow",   "direction":"left"},
    {"id":2,  "fraction":0.067,"type":"fast",   "direction":"right"},
    {"id":3,  "fraction":0.100,"type":"fast",   "direction":"left"},
    {"id":4,  "fraction":0.140,"type":"fast",   "direction":"right"},
    {"id":5,  "fraction":0.174,"type":"fast",   "direction":"left"},
    {"id":6,  "fraction":0.225,"type":"medium", "direction":"right"},
    {"id":7,  "fraction":0.268,"type":"medium", "direction":"left"},
    {"id":8,  "fraction":0.326,"type":"medium", "direction":"right"},
    {"id":9,  "fraction":0.382,"type":"medium", "direction":"left"},
    {"id":10, "fraction":0.442,"type":"medium", "direction":"right"},
    {"id":11, "fraction":0.525,"type":"hairpin","direction":"left"},
    {"id":12, "fraction":0.567,"type":"medium", "direction":"right"},
    {"id":13, "fraction":0.632,"type":"fast",   "direction":"left"},
    {"id":14, "fraction":0.672,"type":"fast",   "direction":"right"},
    {"id":15, "fraction":0.732,"type":"medium", "direction":"right"},
    {"id":16, "fraction":0.793,"type":"slow",   "direction":"left"}
  ]
}
```

- [ ] **Step 19: Create `tracks/abu_dhabi.json`** — Yas Marina Circuit, 5281 m

```json
{
  "name": "Abu Dhabi",
  "length_m": 5281,
  "corners": [
    {"id":1,  "fraction":0.027,"type":"slow",   "direction":"right"},
    {"id":2,  "fraction":0.058,"type":"medium", "direction":"left"},
    {"id":3,  "fraction":0.100,"type":"medium", "direction":"right"},
    {"id":4,  "fraction":0.157,"type":"medium", "direction":"left"},
    {"id":5,  "fraction":0.190,"type":"medium", "direction":"right"},
    {"id":6,  "fraction":0.228,"type":"slow",   "direction":"left"},
    {"id":7,  "fraction":0.260,"type":"slow",   "direction":"right"},
    {"id":8,  "fraction":0.300,"type":"hairpin","direction":"left"},
    {"id":9,  "fraction":0.337,"type":"medium", "direction":"right"},
    {"id":11, "fraction":0.432,"type":"medium", "direction":"left"},
    {"id":12, "fraction":0.468,"type":"medium", "direction":"right"},
    {"id":14, "fraction":0.572,"type":"fast",   "direction":"left"},
    {"id":15, "fraction":0.612,"type":"fast",   "direction":"right"},
    {"id":16, "fraction":0.664,"type":"medium", "direction":"left"},
    {"id":17, "fraction":0.704,"type":"medium", "direction":"right"}
  ]
}
```

- [ ] **Step 20: Verify all 24 JSON files parse cleanly**

```powershell
py -3.12 -c "
import json, pathlib
files = list(pathlib.Path('tracks').glob('*.json'))
for f in sorted(files):
    d = json.loads(f.read_text())
    for c in d['corners']:
        assert 'fraction' in c, f'{f.name}: corner missing fraction'
        assert c['type'] in {'hairpin','slow','medium','fast','chicane'}, f'{f.name}: bad type'
        assert 0.0 < c['fraction'] < 1.0, f'{f.name}: fraction out of range'
print(f'All {len(files)} JSON files valid')
"
```

Expected: `All 24 JSON files valid`

---

### Task 4: Parametric tests for all 24 tracks

**Files:**
- Modify: `tests/test_track_ai.py`

- [ ] **Step 1: Replace `test_loader_all_supported_tracks` with full parametric test**

Find the function `test_loader_all_supported_tracks` and replace it with:

```python
_ALL_F1_25_CITIES = [
    "Bahrain", "Sakhir", "Monza", "Spa", "Silverstone", "Monaco",
    "Melbourne", "Shanghai", "Suzuka", "Jeddah", "Miami", "Imola",
    "Barcelona", "Montreal", "Spielberg", "Budapest", "Zandvoort",
    "Baku", "Singapore", "Austin", "Mexico City", "São Paulo",
    "Las Vegas", "Lusail", "Abu Dhabi",
]

@pytest.mark.parametrize("city", _ALL_F1_25_CITIES)
def test_loader_all_f1_25_tracks(city: str):
    t = load_track(city)
    assert t is not None, f"load_track('{city}') returned None"
    assert len(t.corners) >= 6, f"{city}: only {len(t.corners)} corners"
    assert 3000 < t.length_m < 9000, f"{city}: length {t.length_m} out of range"
    for c in t.corners:
        assert 0.0 < c.start < c.end < 1.0, (
            f"{city} corner {c.id}: invalid [{c.start:.3f}, {c.end:.3f}]"
        )
        assert c.type in {"hairpin", "slow", "medium", "fast", "chicane"}, (
            f"{city} corner {c.id}: unknown type '{c.type}'"
        )
        assert c.attack_side in {"inside", "outside", "none"}, (
            f"{city} corner {c.id}: bad attack_side '{c.attack_side}'"
        )
```

- [ ] **Step 2: Run the parametric test**

```powershell
py -3.12 -m pytest tests/test_track_ai.py::test_loader_all_f1_25_tracks -v 2>&1 | tail -30
```

Expected: 25 PASSED (24 unique cities + Sakhir alias).

- [ ] **Step 3: Run full test suite**

```powershell
py -3.12 -m pytest -q
```

Expected: all previously-passing tests still pass + 25 new parametric cases. Record final count.

---

## Section B — Persist All Settings

### Task 5: Create `core/settings.py`

**Files:**
- Create: `core/settings.py`

- [ ] **Step 1: Write `core/settings.py`**

```python
"""core/settings.py — persistent JSON settings store.

Three functions: load / save / reset. No class.

Future additions (volume, cooldown, persona_voices) belong in DEFAULTS here.
Boot errors (corrupt JSON, permissions) silently return DEFAULTS — the app
must always start.
"""
from __future__ import annotations

import json
from pathlib import Path

import config

DEFAULTS: dict = {
    "commentary_enabled":      True,
    "autovoice_enabled":       True,
    "critical_events_enabled": True,
    "ambient_enabled":         True,
    "radio_fx":                True,
    "commentator_position":    "auto",
    "persona":                 config.PERSONA,
    "min_comment_gap":         config.MIN_COMMENT_GAP,
    "broadcast_mode_enabled":  False,
}

_PATH = Path(config.DATA_DIR) / "settings.json"


def load() -> dict:
    """Return settings dict. Missing keys filled from DEFAULTS; unknown keys dropped."""
    result = dict(DEFAULTS)
    try:
        if _PATH.exists():
            saved = json.loads(_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                result.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except Exception:  # noqa: BLE001
        pass
    return result


def save(settings: dict) -> None:
    """Persist only known keys. Silently ignores I/O errors."""
    try:
        _PATH.write_text(
            json.dumps(
                {k: settings[k] for k in DEFAULTS if k in settings},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass


def reset() -> dict:
    """Overwrite disk with DEFAULTS, return a copy."""
    save(DEFAULTS)
    return dict(DEFAULTS)
```

- [ ] **Step 2: Verify import**

```powershell
py -3.12 -c "from core.settings import load, save, reset, DEFAULTS; print(list(DEFAULTS))"
```

Expected: 9 keys printed, no error.

---

### Task 6: Tests for `core/settings.py`

**Files:**
- Create: `tests/test_settings.py`

- [ ] **Step 1: Write `tests/test_settings.py`**

```python
"""Tests for core/settings — load/save/reset with isolated tmp_path."""
from __future__ import annotations

import json
import pytest


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    import core.settings as s
    monkeypatch.setattr(s, "_PATH", tmp_path / "settings.json")


def test_load_returns_defaults_when_no_file():
    from core.settings import load, DEFAULTS
    assert load() == DEFAULTS


def test_save_and_load_roundtrip():
    from core.settings import load, save, DEFAULTS
    save({"persona": "hype", "radio_fx": False})
    result = load()
    assert result["persona"] == "hype"
    assert result["radio_fx"] is False
    assert result["commentary_enabled"] == DEFAULTS["commentary_enabled"]


def test_reset_restores_defaults():
    from core.settings import save, reset, load, DEFAULTS
    save({"persona": "toxic", "broadcast_mode_enabled": True})
    assert reset() == DEFAULTS
    assert load() == DEFAULTS


def test_load_ignores_unknown_keys():
    import core.settings as s
    s._PATH.write_text(json.dumps({"unknown": 42, "persona": "calm"}), encoding="utf-8")
    from core.settings import load
    result = load()
    assert "unknown" not in result
    assert result["persona"] == "calm"


def test_load_handles_corrupt_json():
    import core.settings as s
    s._PATH.write_text("NOT JSON {{{", encoding="utf-8")
    from core.settings import load, DEFAULTS
    assert load() == DEFAULTS


def test_save_ignores_unknown_keys():
    from core.settings import save, load
    save({"persona": "tv", "ghost_key": "x"})
    assert "ghost_key" not in load()


def test_partial_save_fills_missing_from_defaults():
    from core.settings import save, load, DEFAULTS
    save({"persona": "calm"})
    result = load()
    assert result["persona"] == "calm"
    for k, v in DEFAULTS.items():
        if k != "persona":
            assert result[k] == v
```

- [ ] **Step 2: Run settings tests**

```powershell
py -3.12 -m pytest tests/test_settings.py -v
```

Expected: 7 tests PASSED.

---

### Task 7: Update `app.pyw` — load settings at startup

**Files:**
- Modify: `app.pyw`

- [ ] **Step 1: Add import; replace hardcoded `_settings` block**

In `app.pyw`, add after the existing imports block:

```python
import core.settings as _settings_store
```

Replace the entire `_settings = { ... }` dict literal (the 11-line block starting at `_settings = {`) with:

```python
_settings = _settings_store.load()
```

- [ ] **Step 2: Verify syntax**

```powershell
py -3.12 -m py_compile app.pyw && echo "OK"
```

Expected: `OK`

---

### Task 8: Update `web_server.py` — persist + reset endpoint

**Files:**
- Modify: `web_server.py`

- [ ] **Step 1: Add `import core.settings as _ss` inside `start_api_server`**

At the top of the `start_api_server` function body (before the first `@app.route`), add:

```python
import core.settings as _ss
```

- [ ] **Step 2: Update `POST /api/settings` to call `_ss.save()`**

Find the `api_settings` function and change the body so after `settings.update(body)` it calls:

```python
@app.route("/api/settings", method="POST")
def api_settings():
    body = request.json or {}
    if body:
        engine.apply_settings(body)
        settings.update(body)
        _ss.save(settings)
    return _json({"ok": True})
```

- [ ] **Step 3: Add `POST /api/settings/reset` immediately after**

```python
@app.route("/api/settings/reset", method="POST")
def api_settings_reset():
    defaults = _ss.reset()
    engine.apply_settings(defaults)
    settings.update(defaults)
    return _json({"ok": True, "settings": defaults})
```

- [ ] **Step 4: Verify syntax**

```powershell
py -3.12 -m py_compile web_server.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 5: Run full test suite**

```powershell
py -3.12 -m pytest -q
```

Expected: all tests pass (including 7 new settings tests + 25 new track tests).

---

### Task 9: Update `settings.tsx` + rebuild webui

**Files:**
- Modify: `NewSpotterUI/lib/api.ts`
- Modify: `NewSpotterUI/components/spotter/views/settings.tsx`

- [ ] **Step 1: Add `resetSettings` to `NewSpotterUI/lib/api.ts`**

After the `saveSettings` export, add:

```typescript
export const resetSettings = (): Promise<{ ok: boolean; settings: SettingsState }> =>
  fetch("/api/settings/reset", { method: "POST" }).then((r) => r.json())
```

- [ ] **Step 2: Update `settings.tsx` — add import, state, handler, button**

Add `resetSettings` to the import from `@/lib/api`:

```typescript
import { getYandexStatus, resetSettings, saveSettings, saveYandex, type SpotterState, type YandexStatus } from "@/lib/api"
```

Add `resetting` state and handler after `const [ySaving, setYSaving] = useState(false)`:

```typescript
const [resetting, setResetting] = useState(false)

const handleReset = async () => {
  if (!confirm("Сбросить все настройки к значениям по умолчанию?")) return
  setResetting(true)
  try {
    await resetSettings()
    window.location.reload()
  } finally {
    setResetting(false)
  }
}
```

Inside the `<Panel label="Комментатор">` section, add a reset row after the existing fields (before the closing `</Panel>`):

```tsx
<div className="flex justify-end border-t border-border pt-4">
  <Button
    onClick={handleReset}
    disabled={resetting}
    className="bg-secondary text-muted-foreground hover:bg-elevated hover:text-foreground"
  >
    {resetting ? "Сбрасываю…" : "Сбросить к дефолтам"}
  </Button>
</div>
```

- [ ] **Step 3: TypeScript check**

```powershell
pnpm -C NewSpotterUI exec tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Build and sync**

```powershell
pnpm -C NewSpotterUI build
robocopy NewSpotterUI\out webui /MIR /NJH /NJS
```

Expected: build succeeds; `webui/` updated.

- [ ] **Step 5: Final full test suite**

```powershell
py -3.12 -m pytest -q
```

Expected: all tests pass. Note the total count.

---

## Self-Review

**Spec coverage:**
- ✅ 19 new track JSONs — Tasks 3 (Steps 1-19)
- ✅ 5 existing tracks migrated to compact fraction format — Task 2
- ✅ Loader computes `start`/`end`/`attack_side`/`defense_side` from type — Task 1
- ✅ All 24 F1 25 city names mapped in `_TRACK_FILES` — Task 1 (loader replacement)
- ✅ Parametric test for all 24 cities — Task 4
- ✅ `core/settings.py` with `load/save/reset` — Task 5
- ✅ Graceful on corrupt JSON — Task 6 (`test_load_handles_corrupt_json`)
- ✅ Автозагрузка при старте — Task 7 (`_settings = _settings_store.load()`)
- ✅ Автосохранение при изменении — Task 8 (`_ss.save(settings)` in `api_settings`)
- ✅ Кнопка «Сбросить к дефолтам» — Task 9
- ✅ `persona_voices`/`volume` not yet in DEFAULTS — noted in `settings.py` comment as future additions

**Backward compatibility:** `test_track_manager_resolve_returns_context` uses `load_track("Bahrain")` at `216.5m`. With new format: T1 fraction=0.055, type=slow, pre=0.020 → start=0.035. `216.5/5412≈0.040`. Detection range: `[0.035-0.018, 0.075)` = `[0.017, 0.075)`. lap_pct=0.040 is inside → returns T1 → test still passes. ✅
