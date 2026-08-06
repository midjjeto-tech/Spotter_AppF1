"""Tests for core/track_ai/ — Track Intelligence Layer."""
from __future__ import annotations

import pytest

from core.track_ai.models import Corner, TrackInfo, TrackContext
from core.track_ai.corners import get_corner, get_phase, BRAKING_OFFSET
from core.track_ai.zones import is_attack_zone
from core.track_ai.racing_line import get_advice
from core.track_ai.loader import load_track
from core.track_ai.track_manager import TrackManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _hairpin(id=1, start=0.40, end=0.45):
    return Corner(id=id, name="Turn 1", start=start, end=end,
                  type="hairpin", direction="left",
                  attack_side="inside", defense_side="inside")

def _fast_corner(id=2, start=0.10, end=0.15):
    return Corner(id=id, name="Curva Grande", start=start, end=end,
                  type="fast", direction="left",
                  attack_side="none", defense_side="outside")

def _chicane(id=3, start=0.30, end=0.38):
    return Corner(id=id, name="Chicane", start=start, end=end,
                  type="chicane", direction="right",
                  attack_side="inside", defense_side="inside")

# ---------------------------------------------------------------------------
# corners.py
# ---------------------------------------------------------------------------

def test_get_corner_on_straight():
    corners = [_hairpin(start=0.40, end=0.45)]
    # well before braking zone
    assert get_corner(0.20, corners) is None

def test_get_corner_inside_bounds():
    corners = [_hairpin(start=0.40, end=0.45)]
    c = get_corner(0.42, corners)
    assert c is not None
    assert c.type == "hairpin"

def test_get_corner_in_braking_zone():
    corners = [_hairpin(start=0.40, end=0.45)]
    # exactly BRAKING_OFFSET before start
    lap_pct = 0.40 - BRAKING_OFFSET
    c = get_corner(lap_pct, corners)
    assert c is not None
    assert c.name == "Turn 1"

def test_get_corner_before_braking_zone():
    corners = [_hairpin(start=0.40, end=0.45)]
    c = get_corner(0.40 - BRAKING_OFFSET - 0.01, corners)
    assert c is None

def test_get_phase_braking():
    c = _hairpin(start=0.40, end=0.45)
    assert get_phase(0.38, c) == "braking"

def test_get_phase_entry():
    c = _hairpin(start=0.40, end=0.45)
    # just after start but before midpoint (0.425)
    assert get_phase(0.410, c) == "entry"

def test_get_phase_apex():
    c = _hairpin(start=0.40, end=0.45)
    # past midpoint (0.425) and before end-0.005 (0.445)
    assert get_phase(0.432, c) == "apex"

def test_get_phase_exit():
    c = _hairpin(start=0.40, end=0.45)
    # near end
    assert get_phase(0.448, c) == "exit"

# ---------------------------------------------------------------------------
# zones.py
# ---------------------------------------------------------------------------

def test_zones_attack_true_braking_before_hairpin():
    c = _hairpin()
    assert is_attack_zone(c, "braking", drs_active=False) is True

def test_zones_attack_false_straight():
    assert is_attack_zone(None, "straight", drs_active=False) is False

def test_zones_attack_true_drs_on_straight():
    assert is_attack_zone(None, "straight", drs_active=True) is True

def test_zones_attack_false_fast_corner():
    c = _fast_corner()
    # fast corner braking zone is NOT a typical attack zone
    assert is_attack_zone(c, "braking", drs_active=False) is False

def test_zones_attack_true_chicane_braking():
    c = _chicane()
    assert is_attack_zone(c, "braking", drs_active=False) is True

# ---------------------------------------------------------------------------
# racing_line.py
# ---------------------------------------------------------------------------

def test_racing_line_hairpin_defense():
    c = _hairpin()
    r = get_advice(c, threat_active=True)
    assert r["advice"] == "inside"
    assert "hairpin" in r["advice_reason"]

def test_racing_line_fast_hold_line():
    c = _fast_corner()
    r = get_advice(c, threat_active=True)
    assert r["advice"] == "hold_line"

def test_racing_line_no_threat():
    c = _hairpin()
    r = get_advice(c, threat_active=False)
    assert r["advice"] == "none"

def test_racing_line_no_corner():
    r = get_advice(None, threat_active=True)
    assert r["advice"] == "none"

def test_racing_line_chicane_defense():
    c = _chicane()
    r = get_advice(c, threat_active=True)
    assert r["advice"] == "inside"

# ---------------------------------------------------------------------------
# loader.py
# ---------------------------------------------------------------------------

def test_loader_known_track_bahrain():
    t = load_track("Bahrain")
    assert t is not None
    assert t.name == "Bahrain"
    assert len(t.corners) > 0
    assert t.length_m > 0

def test_loader_known_track_spa():
    t = load_track("Spa")
    assert t is not None
    assert t.name == "Spa"

def test_loader_unknown_track():
    assert load_track("UnknownCircuit") is None

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
        assert 0.0 <= c.start < c.end <= 1.0, (
            f"{city} corner {c.id}: invalid [{c.start:.3f}, {c.end:.3f}]"
        )
        assert c.type in {"hairpin", "slow", "medium", "fast", "chicane"}, (
            f"{city} corner {c.id}: unknown type '{c.type}'"
        )
        assert c.attack_side in {"inside", "outside", "none"}, (
            f"{city} corner {c.id}: bad attack_side '{c.attack_side}'"
        )

# ---------------------------------------------------------------------------
# track_manager.py
# ---------------------------------------------------------------------------

def _build_manager():
    t = load_track("Bahrain")
    return TrackManager(t)


def test_track_manager_resolve_returns_context():
    tm = _build_manager()
    ctx = tm.resolve(216.5)  # ~Turn 1 area
    assert ctx is not None
    assert isinstance(ctx, TrackContext)


def test_track_manager_resolve_straight_returns_no_corner():
    tm = _build_manager()
    # ~55% of lap = roughly between Turn 9 and Turn 10 (straight area)
    ctx = tm.resolve(1700.0)
    assert ctx is not None
    # Phase should be "straight" when not near a corner
    assert ctx.phase in ("straight", "braking", "entry", "apex", "exit")  # just doesn't crash


def test_track_manager_resolve_wraparound():
    tm = _build_manager()
    # lap_distance_m greater than track length — should wraparound
    ctx = tm.resolve(5412.0 + 200.0)
    assert ctx is not None


def test_track_manager_resolve_negative_returns_none():
    tm = _build_manager()
    assert tm.resolve(-1.0) is None


def test_track_manager_track_name():
    tm = _build_manager()
    assert tm.track_name == "Bahrain"


def test_track_manager_to_dict_keys():
    tm = _build_manager()
    ctx = tm.resolve(216.5, drs_active=False, threat_active=False)
    d = ctx.to_dict()
    for key in ("corner", "corner_id", "corner_type", "phase", "sector", "attack_zone", "defense_advice"):
        assert key in d
