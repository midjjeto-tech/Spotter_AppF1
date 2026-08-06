"""tests/test_rivals.py — Rival Intelligence unit tests."""
from core.rivals.models import RivalSnapshot, RivalProfile


def test_rival_snapshot_fields():
    snap = RivalSnapshot(
        vehicle_idx=3,
        driver="Carlos Sainz",
        team="Ferrari",
        position=5,
        lap=20,
    )
    assert snap.vehicle_idx == 3
    assert snap.driver == "Carlos Sainz"
    assert snap.position == 5


def test_rival_profile_fields():
    profile = RivalProfile(
        vehicle_idx=3,
        driver="Carlos Sainz",
        team="Ferrari",
        pit_count=1,
        lap_count=20,
        current_position=5,
        style="consistent",
        nearby=True,
    )
    assert profile.pit_count == 1
    assert profile.style == "consistent"
    assert profile.nearby is True


def test_rival_profile_new_fields_default():
    profile = RivalProfile(
        vehicle_idx=3, driver="Carlos Sainz", team="Ferrari",
        pit_count=0, lap_count=1, current_position=5,
        style="consistent", nearby=False,
    )
    assert profile.tyre_age is None
    assert profile.body_damage == 0.0
    assert profile.pit_status == 0
    assert profile.mistake_at is None


from core.rivals.tracker import RivalTracker


def _grid(*entries) -> list[dict]:
    """Build a grid list from (vehicle_idx, position, lap, driver) or
    (vehicle_idx, position, lap, driver, pit_status) tuples. pit_status
    defaults to 0 (not in the pit lane) when omitted."""
    out = []
    for e in entries:
        vi, pos, lap, drv = e[:4]
        pit_status = e[4] if len(e) > 4 else 0
        out.append({"vehicle_idx": vi, "position": pos, "lap": lap,
                     "driver": drv, "team": "Team", "color": "#fff",
                     "pit_status": pit_status})
    return out


# --- basic update ---

def test_tracker_registers_rivals():
    t = RivalTracker()
    grid = _grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz"), (2, 3, 1, "Leclerc"))
    t.update(grid, player_vehicle_idx=0)
    state = t.get_state()
    assert state["rival_count"] == 2
    names = [r["driver"] for r in state["rivals"]]
    assert "Sainz" in names
    assert "Leclerc" in names


def test_tracker_player_excluded():
    t = RivalTracker()
    grid = _grid((0, 1, 1, "Player"), (1, 3, 1, "Sainz"))
    t.update(grid, player_vehicle_idx=0)
    state = t.get_state()
    assert all(r["driver"] != "Player" for r in state["rivals"])


def test_tracker_nearby_flag():
    t = RivalTracker()
    grid = _grid((0, 5, 3, "Player"), (1, 4, 3, "Sainz"), (2, 10, 3, "Leclerc"))
    t.update(grid, player_vehicle_idx=0)
    state = t.get_state()
    sainz = next(r for r in state["rivals"] if r["driver"] == "Sainz")
    leclerc = next(r for r in state["rivals"] if r["driver"] == "Leclerc")
    assert sainz["nearby"] is True
    assert leclerc["nearby"] is False


def test_nearby_count():
    t = RivalTracker()
    grid = _grid(
        (0, 5, 3, "Player"),
        (1, 4, 3, "A"),
        (2, 6, 3, "B"),
        (3, 3, 3, "C"),
        (4, 10, 3, "D"),
    )
    t.update(grid, player_vehicle_idx=0)
    state = t.get_state()
    assert state["nearby_count"] == 3


# --- pit detection (real pit_status, not position-jump heuristic) ---

def test_pit_detected_on_real_pit_status_transition():
    t = RivalTracker()
    t.update(_grid((0, 1, 5, "Player"), (1, 3, 5, "Sainz", 0)), player_vehicle_idx=0, now=1.0)
    t.update(_grid((0, 1, 6, "Player"), (1, 18, 6, "Sainz", 1)), player_vehicle_idx=0, now=2.0)
    state = t.get_state()
    sainz = next(r for r in state["rivals"] if r["driver"] == "Sainz")
    assert sainz["pit_count"] == 1


def test_pit_not_counted_from_position_jump_without_pit_status():
    """Раньше pit_count считался эвристикой по размеру скачка позиции — теперь
    только по реальному pit_status. Большой скачок БЕЗ пита — сигнал "ошибка",
    не пит (см. test_mistake_detected_on_large_position_loss_without_pit,
    добавляется отдельной задачей позже)."""
    t = RivalTracker()
    t.update(_grid((0, 1, 5, "Player"), (1, 3, 5, "Sainz", 0)), player_vehicle_idx=0, now=1.0)
    t.update(_grid((0, 1, 6, "Player"), (1, 18, 6, "Sainz", 0)), player_vehicle_idx=0, now=2.0)
    state = t.get_state()
    sainz = next(r for r in state["rivals"] if r["driver"] == "Sainz")
    assert sainz["pit_count"] == 0


def test_pit_not_detected_on_small_position_change():
    t = RivalTracker()
    t.update(_grid((0, 1, 5, "Player"), (1, 3, 5, "Sainz", 0)), player_vehicle_idx=0, now=1.0)
    t.update(_grid((0, 1, 6, "Player"), (1, 5, 6, "Sainz", 0)), player_vehicle_idx=0, now=2.0)
    state = t.get_state()
    sainz = next(r for r in state["rivals"] if r["driver"] == "Sainz")
    assert sainz["pit_count"] == 0


def test_pit_count_increments_on_each_real_pit_entry():
    t = RivalTracker()
    for g in [
        _grid((0, 1, 5, "Player"), (1, 3, 5, "Sainz", 0)),
        _grid((0, 1, 6, "Player"), (1, 18, 6, "Sainz", 1)),   # заезд 1
        _grid((0, 1, 6, "Player"), (1, 8, 7, "Sainz", 0)),    # выехал
        _grid((0, 1, 7, "Player"), (1, 3, 7, "Sainz", 0)),
        _grid((0, 1, 8, "Player"), (1, 19, 8, "Sainz", 1)),   # заезд 2
    ]:
        t.update(g, player_vehicle_idx=0, now=1.0)
    sainz = next(r for r in t.get_state()["rivals"] if r["driver"] == "Sainz")
    assert sainz["pit_count"] == 2


# --- style classification ---

def test_style_consistent_on_stable_positions():
    t = RivalTracker()
    for lap in range(1, 8):
        t.update(_grid((0, 5, lap, "Player"), (1, 3, lap, "Sainz")), player_vehicle_idx=0)
    sainz = next(r for r in t.get_state()["rivals"] if r["driver"] == "Sainz")
    assert sainz["style"] == "consistent"


def test_style_charging_when_position_improves():
    t = RivalTracker()
    for i, pos in enumerate([15, 13, 11, 9, 7, 5]):
        t.update(_grid((0, 1, i + 1, "Player"), (1, pos, i + 1, "Sainz")), player_vehicle_idx=0)
    sainz = next(r for r in t.get_state()["rivals"] if r["driver"] == "Sainz")
    assert sainz["style"] in ("charging", "aggressive")


def test_style_fading_when_position_worsens():
    t = RivalTracker()
    for i, pos in enumerate([3, 5, 7, 9, 11, 13]):
        t.update(_grid((0, 1, i + 1, "Player"), (1, pos, i + 1, "Sainz")), player_vehicle_idx=0)
    sainz = next(r for r in t.get_state()["rivals"] if r["driver"] == "Sainz")
    assert sainz["style"] in ("fading", "aggressive")


# --- get_state contract ---

def test_get_state_has_all_keys():
    t = RivalTracker()
    t.update(_grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz")), player_vehicle_idx=0)
    state = t.get_state()
    for key in ("rivals", "rival_count", "nearby_count"):
        assert key in state


def test_rival_entry_has_all_fields():
    t = RivalTracker()
    t.update(_grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz")), player_vehicle_idx=0)
    rival = t.get_state()["rivals"][0]
    for key in ("driver", "team", "position", "lap", "pit_count", "style", "nearby"):
        assert key in rival


# --- get_style accessor ---

def test_get_style_returns_known_rival_style():
    t = RivalTracker()
    grid = _grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz"))
    t.update(grid, player_vehicle_idx=0)
    assert t.get_style(1) == "consistent"     # дефолт при малой истории (см. _classify_style)


def test_get_style_returns_none_for_unknown_vehicle():
    t = RivalTracker()
    grid = _grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz"))
    t.update(grid, player_vehicle_idx=0)
    assert t.get_style(99) is None


def test_get_style_returns_none_for_player():
    """RivalTracker никогда не профилирует игрока (update() пропускает его
    целиком) — get_style() для игрока всегда None, без специальной проверки."""
    t = RivalTracker()
    grid = _grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz"))
    t.update(grid, player_vehicle_idx=0)
    assert t.get_style(0) is None


def test_get_style_returns_none_for_none_vehicle_idx():
    t = RivalTracker()
    assert t.get_style(None) is None


# --- mistake detection ---

def test_mistake_timestamp_set_on_large_position_loss_without_pit():
    t = RivalTracker()
    t.update(_grid((0, 1, 5, "Player"), (1, 3, 5, "Sainz", 0)), player_vehicle_idx=0, now=1.0)
    t.update(_grid((0, 1, 6, "Player"), (1, 18, 6, "Sainz", 0)), player_vehicle_idx=0, now=42.0)
    assert t._profiles[1].mistake_at == 42.0


def test_mistake_timestamp_not_set_on_real_pit_transition():
    t = RivalTracker()
    t.update(_grid((0, 1, 5, "Player"), (1, 3, 5, "Sainz", 0)), player_vehicle_idx=0, now=1.0)
    t.update(_grid((0, 1, 6, "Player"), (1, 18, 6, "Sainz", 1)), player_vehicle_idx=0, now=42.0)
    assert t._profiles[1].mistake_at is None


# --- tyre age accessors ---

def test_update_tyre_sets_age_for_known_rival():
    t = RivalTracker()
    t.update(_grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz")), player_vehicle_idx=0, now=1.0)
    t.update_tyre(1, 12)
    assert t.get_tyre_age(1) == 12


def test_update_tyre_noop_for_unknown_rival():
    t = RivalTracker()
    t.update_tyre(99, 5)          # no profile yet — must not raise
    assert t.get_tyre_age(99) is None


def test_get_tyre_age_returns_none_for_none_vehicle_idx():
    t = RivalTracker()
    assert t.get_tyre_age(None) is None


# --- damage-based mistake detection ---

def test_update_damage_sets_mistake_on_threshold_cross():
    t = RivalTracker()
    t.update(_grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz")), player_vehicle_idx=0, now=1.0)
    t.update_damage(1, body_damage=45, threshold=20, now=5.0)
    assert t.get_recent_mistake(1, now=5.0) is True


def test_update_damage_no_mistake_below_threshold():
    t = RivalTracker()
    t.update(_grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz")), player_vehicle_idx=0, now=1.0)
    t.update_damage(1, body_damage=10, threshold=20, now=5.0)
    assert t.get_recent_mistake(1, now=5.0) is False


def test_update_damage_only_flags_on_threshold_cross_not_every_tick():
    t = RivalTracker()
    t.update(_grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz")), player_vehicle_idx=0, now=1.0)
    t.update_damage(1, body_damage=45, threshold=20, now=5.0)
    t.update_damage(1, body_damage=46, threshold=20, now=50.0)   # already above, no re-trigger
    assert t._profiles[1].mistake_at == 5.0


def test_update_damage_noop_for_unknown_rival():
    t = RivalTracker()
    t.update_damage(99, body_damage=90, threshold=20, now=1.0)   # must not raise
    assert t.get_recent_mistake(99, now=1.0) is False


def test_get_recent_mistake_expires_after_window():
    t = RivalTracker()
    t.update(_grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz")), player_vehicle_idx=0, now=1.0)
    t.update_damage(1, body_damage=45, threshold=20, now=5.0)
    assert t.get_recent_mistake(1, now=5.0 + 60.0) is True     # exactly at window edge
    assert t.get_recent_mistake(1, now=5.0 + 61.0) is False    # past the window


def test_get_recent_mistake_false_when_never_set():
    t = RivalTracker()
    t.update(_grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz")), player_vehicle_idx=0, now=1.0)
    assert t.get_recent_mistake(1, now=1.0) is False


def test_get_recent_mistake_false_for_none_vehicle_idx():
    t = RivalTracker()
    assert t.get_recent_mistake(None, now=1.0) is False


def test_get_state_rival_entry_has_tyre_age_and_recent_mistake():
    t = RivalTracker()
    t.update(_grid((0, 1, 1, "Player"), (1, 2, 1, "Sainz")), player_vehicle_idx=0, now=1.0)
    t.update_tyre(1, 8)
    t.update_damage(1, body_damage=50, threshold=20, now=1.0)
    rival = t.get_state(now=1.0)["rivals"][0]
    assert rival["tyre_age"] == 8
    assert rival["recent_mistake"] is True
