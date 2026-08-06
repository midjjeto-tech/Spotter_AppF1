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
    try:
        typ = raw["type"]
        frac = float(raw["fraction"])
        direction = raw["direction"]
    except KeyError as exc:
        raise ValueError(f"Corner {idx} missing required field {exc}") from exc
    if typ not in _PRE:
        raise ValueError(f"Corner {idx} unknown type {typ!r}. Valid: {sorted(_PRE)}")
    pre = _PRE[typ]
    post = _POST[typ]
    atk, dfn = _SIDES[typ]
    return Corner(
        id=cid,
        name=name,
        start=max(0.0, frac - pre),
        end=min(1.0, frac + post),
        type=typ,
        direction=direction,
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
        corners = [_corner_from_dict(c, i) for i, c in enumerate(raw.get("corners", []))]
    except (OSError, json.JSONDecodeError, ValueError, KeyError):
        return None
    return TrackInfo(
        name=raw["name"],
        length_m=float(raw["length_m"]),
        corners=corners,
    )
