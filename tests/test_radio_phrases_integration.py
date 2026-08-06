"""Банк фраз на реальных событиях, через движок.

Проверяется не реестр (это `test_radio_phrases.py`), а проводка: детектор отдаёт
семантический код → движок переводит его в `event_code` и берёт формулировку из
банка → в событии оказывается непустая фраза той спеки, которая соответствует
ситуации.
"""
import struct

import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.packets import (
    HEADER_SIZE, LAP_DATA_SIZE, MOTION_SIZE, PACKET_LAP_DATA, parse_motion_all,
)
from core.radio import phrases as radio_phrases
from tests.telemetry import consume_f1_event_packet, consume_f1_packet


@pytest.fixture
def engine():
    """Не module-scoped: эти тесты меняют состояние трекеров и круг игрока."""
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _drain(engine):
    out = []
    while not engine._commentary_events.empty():
        out.append(engine._commentary_events.get_nowait())
    return out


def _by_code(events, code):
    return [e for e in events if e["event_code"] == code]


def _scar_buf(safety_car_type: int, event_reason: int) -> bytes:
    buf = bytearray(HEADER_SIZE + 4 + 2)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"SCAR"
    struct.pack_into("<BB", buf, HEADER_SIZE + 4, safety_car_type, event_reason)
    return bytes(buf)


def _lap_buf(distances: dict[int, float]) -> bytes:
    buf = bytearray(HEADER_SIZE + 22 * LAP_DATA_SIZE)
    for idx, dist in distances.items():
        struct.pack_into("<f", buf, HEADER_SIZE + idx * LAP_DATA_SIZE + 20, dist)
    return bytes(buf)


def _motion_buf(cars: dict[int, tuple[float, float, float, float]]) -> bytes:
    n = max(cars) + 1
    buf = bytearray(HEADER_SIZE + n * MOTION_SIZE)
    for idx, (wx, wz, rx, rz) in cars.items():
        base = HEADER_SIZE + idx * MOTION_SIZE
        struct.pack_into("<f", buf, base + 0, wx)
        struct.pack_into("<f", buf, base + 8, wz)
        struct.pack_into("<h", buf, base + 30, int(rx * 32767))
        struct.pack_into("<h", buf, base + 34, int(rz * 32767))
    return bytes(buf)


def _spot(engine, cars):
    """Один тик споттера с заданной геометрией."""
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                      _lap_buf({idx: 100.0 for idx in cars}))
    _drain(engine)
    engine._spotter_tick(parse_motion_all(_motion_buf(cars)))
    return _drain(engine)


# ── Споттер: left / right / clear ────────────────────────────────────────────

def test_spotter_left_right_and_clear_take_their_own_specs(engine):
    engine._player_car_index = 0
    engine._race_engineer.spotter_tracker.reset()

    # Машина справа (игрок смотрит вдоль +Z, right = +X).
    right = _by_code(_spot(engine, {0: (0.0, 0.0, 1.0, 0.0), 1: (2.0, 0.0, 0.0, 0.0)}),
                     "SPOTTER_CAR_RIGHT")
    assert len(right) == 1
    assert right[0]["phrase"] in radio_phrases.spec_for("spotter.right").variants

    # Та же машина слева, за пределами анти-дребезга.
    engine._race_engineer.spotter_tracker.reset()
    left = _by_code(_spot(engine, {0: (0.0, 0.0, 1.0, 0.0), 1: (-2.0, 0.0, 0.0, 0.0)}),
                    "SPOTTER_CAR_LEFT")
    assert len(left) == 1
    assert left[0]["phrase"] in radio_phrases.spec_for("spotter.left").variants


def test_spotter_side_phrase_never_names_the_opposite_side(engine):
    """Главная гарантия: сторона приходит из факта, а не из выбора варианта."""
    engine._player_car_index = 0
    engine._race_engineer.spotter_tracker.reset()

    right = _by_code(_spot(engine, {0: (0.0, 0.0, 1.0, 0.0), 1: (2.0, 0.0, 0.0, 0.0)}),
                     "SPOTTER_CAR_RIGHT")[0]
    assert "слев" not in right["phrase"].lower()


def test_spotter_clear_uses_the_clear_spec(engine):
    engine._player_car_index = 0
    engine._race_engineer.spotter_tracker.reset()
    _spot(engine, {0: (0.0, 0.0, 1.0, 0.0), 1: (2.0, 0.0, 0.0, 0.0)})

    # Машина уехала за LATERAL_EXIT_M, и прошёл анти-дребезг.
    tracker = engine._race_engineer.spotter_tracker
    tracker._last_right_change_t = 0.0
    clear = _by_code(_spot(engine, {0: (0.0, 0.0, 1.0, 0.0), 1: (50.0, 0.0, 0.0, 0.0)}),
                     "SPOTTER_CLEAR")
    assert len(clear) == 1
    assert clear[0]["phrase"] in radio_phrases.spec_for("spotter.clear").variants


# ── Box-call: эскалация tier 1 → 2 → 3 ──────────────────────────────────────

def test_box_call_escalation_uses_one_spec_per_tier():
    """Три tier'а — три спеки, и все три говорят «в боксы», ни одна не
    противоречит остальным."""
    for tier in (1, 2, 3):
        spec = radio_phrases.spec_for(f"box.call_{tier}")
        assert spec.action == "pit_now"
        rendered = radio_phrases.render(spec.code, selector_key=f"window_2:{tier}")
        assert rendered in spec.variants
        lowered = rendered.lower()
        assert "бокс" in lowered or "заходим" in lowered


def test_box_call_tiers_are_distinct_phrases():
    picked = {
        radio_phrases.render(f"box.call_{tier}", selector_key="window_2")
        for tier in (1, 2, 3)
    }
    assert len(picked) == 3


# ── Safety Car: deployed / ending / clear ───────────────────────────────────

def test_safety_car_stages_have_their_own_specs():
    stages = ("flag.safety_car_deployed", "flag.safety_car_ending",
              "flag.safety_car_clear")
    rendered = {
        code: radio_phrases.render(code, selector_key="sc_episode_1")
        for code in stages
    }
    assert len(set(rendered.values())) == 3
    assert "safety car" in rendered[stages[0]].lower() \
        or "безопасност" in rendered[stages[0]].lower()
    assert "зелён" in rendered[stages[2]].lower() \
        or "возобновляется" in rendered[stages[2]].lower()


def test_safety_car_events_still_flow_through_the_engine(engine):
    """Проводка SC не тронута Task 3 — фраза по-прежнему приходит из шаблонов
    комментатора, банк её пока не подменяет. Тест сторожит отсутствие
    регрессии."""
    engine._sc_episode = 0
    _drain(engine)
    consume_f1_event_packet(engine, _scar_buf(1, 0))
    assert _by_code(_drain(engine), "SAFETY_CAR_DEPLOYED")


# ── Rain advisory ───────────────────────────────────────────────────────────

def test_rain_advisory_keeps_the_horizon_token_until_playback():
    """Горизонт дождя ВОЛАТИЛЕН: «через 5 минут» через двадцать секунд уже
    неправда, поэтому токен доживает до резолвера (ТЗ §5), а не подставляется
    здесь. Согласование числительного делает `resolver._format`."""
    rendered = radio_phrases.render("weather.rain_soon", selector_key="rain_front_1")
    assert "{minutes}" in rendered


def test_a_precomputed_horizon_is_ignored_not_baked_in():
    """Переданное волатильное значение банк ИГНОРИРУЕТ (контракт Task 3): иначе
    оно окаменело бы в тексте и резолвер уже не смог бы его обновить."""
    rendered = radio_phrases.render("weather.rain_soon", {"minutes": "5 минут"},
                                    selector_key="rain_front_1")
    assert "{minutes}" in rendered
    assert "5 минут" not in rendered


# ── Damage ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("part,damage_key,event_code", [
    ("wing", "wing_damage", "DAMAGE_WING"),
    ("floor", "floor_damage", "DAMAGE_FLOOR"),
    ("gearbox", "gearbox_damage", "DAMAGE_GEARBOX"),
    ("engine", "engine_damage", "DAMAGE_ENGINE"),
])
def test_damage_event_carries_a_phrase_from_its_spec(engine, part, damage_key,
                                                    event_code):
    engine._player_lap = 12
    engine._damage_announced = {k: False for k in
                                ("wing", "floor", "gearbox", "engine")}
    _drain(engine)
    engine._update_damage({"wing_damage": 0, "floor_damage": 0,
                           "gearbox_damage": 0, "engine_damage": 0,
                           damage_key: 45})
    event = _by_code(_drain(engine), event_code)[0]

    assert event["phrase"] in radio_phrases.spec_for(f"damage.{part}").variants


def test_critical_damage_switches_to_the_critical_spec(engine):
    engine._player_lap = 12
    engine._damage_announced = {k: False for k in
                                ("wing", "floor", "gearbox", "engine")}
    _drain(engine)
    engine._update_damage({"wing_damage": 95, "floor_damage": 0,
                           "gearbox_damage": 0, "engine_damage": 0})
    event = _by_code(_drain(engine), "DAMAGE_WING")[0]

    assert event["phrase"] in radio_phrases.spec_for("damage.wing_critical").variants
    assert event["phrase"] not in radio_phrases.spec_for("damage.wing").variants


def test_parts_without_a_critical_spec_stay_on_the_high_one(engine):
    """У днища и коробки критической спеки нет: «теряем прижим» остаётся верным
    на любой тяжести, а немедленного бокса они не требуют."""
    engine._player_lap = 12
    engine._damage_announced = {k: False for k in
                                ("wing", "floor", "gearbox", "engine")}
    _drain(engine)
    engine._update_damage({"wing_damage": 0, "floor_damage": 99,
                           "gearbox_damage": 0, "engine_damage": 0})
    event = _by_code(_drain(engine), "DAMAGE_FLOOR")[0]

    assert event["phrase"] in radio_phrases.spec_for("damage.floor").variants


# ── Gap digest и {ers_clause} ───────────────────────────────────────────────

def test_gap_digest_keeps_its_volatile_token_unresolved():
    """Task 3 не двигает точку позднего связывания: токен обязан дожить до
    Task 4."""
    rendered = radio_phrases.render("gap.digest", selector_key="digest:1")
    assert "{gap}" in rendered


def test_ers_spec_keeps_its_volatile_token_unresolved():
    rendered = radio_phrases.render("ers.level", selector_key="digest:1")
    assert "{ers}" in rendered


def test_gap_digest_tracker_returns_bank_fragment_codes():
    """Трекер отдаёт КОДЫ фрагментов; текст собирает `phrases.compose`, а число
    подставляет резолвер на пороге озвучки."""
    from core.radio import phrases
    from core.strategy_ai.gap_digest import CODE_ERS, GapDigestTracker

    codes = GapDigestTracker().build(1300, None, ers_percent=60.0)
    assert codes == ("gap.front_first", CODE_ERS)
    assert "{ers}" in phrases.compose(codes, selector_key="sit-1")


def test_pit_exit_reaches_the_engineer_channel(engine):
    """`box.exit` до этой правки была НЕДОСТИЖИМА: выезд из боксов озвучивал
    только комментатор, в третьем лице («{driver} покидает пит-лейн»). Пилот не
    слышал единственного, что ему на выезде нужно, — резина холодная."""
    from core.radio import policy

    engine._session_type = "race"
    engine.settings["engineer_chatter_enabled"] = True
    while not engine._commentary_events.empty():
        engine._commentary_events.get_nowait()

    engine._maybe_announce_pit_exit(prev_status=1, new_status=0)

    drained = []
    while not engine._commentary_events.empty():
        drained.append(engine._commentary_events.get_nowait())
    codes = [e.get("event_code") for e in drained]

    assert "PIT_EXIT" in codes, "трансляционная реплика пропала"
    engineer = [e for e in drained if e.get("event_code") == "PIT_EXIT_ENGINEER"]
    assert engineer, "инженер промолчал на выезде"
    assert engineer[0]["phrase"]
    assert policy.channel_for({"event_code": "PIT_EXIT_ENGINEER"}) == \
        policy.CHANNEL_ENGINEER
