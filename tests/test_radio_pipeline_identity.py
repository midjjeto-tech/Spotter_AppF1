"""Проводка доменной модели радио через F1Engine (Task 2).

Проверяется, что события уносят с собой данные, без которых
core/radio/situations.py не может отличить одну ситуацию от другой:
`neighbour_idx`, `damage_severity`, `sc_episode`, `box_call_window`,
`rain_front_id`, `created_at`.

Слышимое поведение на этом этапе НЕ меняется — сообщение только собирается.
"""
import struct

import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.packets import HEADER_SIZE, LAP_DATA_SIZE, MOTION_SIZE, PACKET_LAP_DATA, parse_motion_all
from core.radio import plumbing, policy
from core.radio.message import build_message
from tests.telemetry import consume_f1_event_packet, consume_f1_packet


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _drain(engine):
    drained = []
    while not engine._commentary_events.empty():
        drained.append(engine._commentary_events.get_nowait())
    return drained


def _lap_buf_with_distance(distances: dict[int, float]) -> bytes:
    buf = bytearray(HEADER_SIZE + 22 * LAP_DATA_SIZE)
    for idx, dist in distances.items():
        base = HEADER_SIZE + idx * LAP_DATA_SIZE
        struct.pack_into("<f", buf, base + 20, dist)
    return bytes(buf)


def _scar_buf(safety_car_type: int, event_reason: int) -> bytes:
    buf = bytearray(HEADER_SIZE + 4 + 2)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"SCAR"
    struct.pack_into("<BB", buf, HEADER_SIZE + 4, safety_car_type, event_reason)
    return bytes(buf)


def _ssta_buf() -> bytes:
    buf = bytearray(HEADER_SIZE + 4)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"SSTA"
    return bytes(buf)


def _motion_buf(cars: dict[int, tuple[float, float, float, float]]) -> bytes:
    n = max(cars.keys()) + 1 if cars else 1
    buf = bytearray(HEADER_SIZE + n * MOTION_SIZE)
    for idx, (wx, wz, rx, rz) in cars.items():
        base = HEADER_SIZE + idx * MOTION_SIZE
        struct.pack_into("<f", buf, base + 0, wx)
        struct.pack_into("<f", buf, base + 8, wz)
        struct.pack_into("<h", buf, base + 30, int(rx * 32767))
        struct.pack_into("<h", buf, base + 34, int(rz * 32767))
    return bytes(buf)


# ── created_at ───────────────────────────────────────────────────────────────

def test_publish_stamps_created_at_alongside_enqueued_at(engine):
    _drain(engine)
    engine._commentary_events.publish({"event_code": "OVTK"})
    event = _drain(engine)[0]

    assert event["created_at"] == pytest.approx(event["enqueued_at"])
    assert isinstance(event["created_mono"], float)


def test_publisher_can_declare_an_earlier_event_time(engine):
    """TTL считается от момента ФАКТА. Если публикующий код знает, что факт
    случился раньше публикации, его время должно выжить (ТЗ §7)."""
    _drain(engine)
    engine._commentary_events.publish({
        "event_code": "OVTK", "created_at": 123.0, "created_mono": 7.0})
    event = _drain(engine)[0]

    assert event["created_at"] == 123.0
    assert event["created_mono"] == 7.0
    assert event["enqueued_at"] != 123.0


def test_monotonic_stamp_is_independent_of_the_wall_clock():
    """Отдельная инъекция часов: подтверждает, что метки берутся из ДВУХ
    источников, а не одна из другой."""
    from commentator.planner import PlanContext
    from core.commentary_events import CommentaryEvents

    events = CommentaryEvents(
        lambda _e: PlanContext(session_type="race"),
        clock=lambda: 1000.0, monotonic=lambda: 42.0)
    event = events.publish({"event_code": "OVTK"})

    assert event["created_at"] == 1000.0
    assert event["created_mono"] == 42.0


# ── Споттер: личность соседа ─────────────────────────────────────────────────

def test_spotter_event_carries_the_neighbour_index(engine):
    engine._player_car_index = 0
    engine._race_engineer.spotter_tracker.reset()
    _drain(engine)

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_LAP_DATA,
                      _lap_buf_with_distance({0: 100.0, 1: 101.0}))
    _drain(engine)

    engine._spotter_tick(parse_motion_all(
        _motion_buf({0: (0.0, 0.0, 1.0, 0.0), 1: (2.0, 0.0, 0.0, 0.0)})))
    found = [e for e in _drain(engine) if e["event_code"] == "SPOTTER_CAR_RIGHT"]

    assert len(found) == 1
    assert plumbing.field(found[0], "neighbour_idx") == 1


def test_neighbour_index_makes_two_rivals_two_situations(engine):
    """Одна и та же сторона, разные машины — разные ситуации: сменившийся сосед
    обязан снова прозвучать, а не быть проглочен как повтор."""
    right_1 = {"event_code": "SPOTTER_CAR_RIGHT", "priority": "critical",
               **plumbing.attach(neighbour_idx=1)}
    right_5 = {"event_code": "SPOTTER_CAR_RIGHT", "priority": "critical",
               **plumbing.attach(neighbour_idx=5)}

    first = build_message(right_1, phrase="Держи справа!", now=0.0)
    second = build_message(right_5, phrase="Держи справа!", now=0.0)

    assert first.situation_id != second.situation_id


def test_clear_and_both_have_no_single_neighbour(engine):
    assert engine._spotter_neighbour_idx("SPOTTER_CLEAR", []) is None
    assert engine._spotter_neighbour_idx("SPOTTER_CAR_BOTH", [
        {"vehicle_idx": 3, "side": "left", "lateral_m": 1.0, "longitudinal_m": 0.0},
    ]) is None


def test_neighbour_index_ignores_cars_outside_the_voice_window(engine):
    """Radar считается по широкому окну (25 м), голосовой споттер — по узкому
    (6 м). Личность соседа обязана брать узкое, иначе предупреждение про
    ближнюю машину приписалось бы дальней."""
    radar = [
        {"vehicle_idx": 9, "side": "right", "lateral_m": 0.5, "longitudinal_m": 20.0},
        {"vehicle_idx": 4, "side": "right", "lateral_m": 2.0, "longitudinal_m": 1.0},
    ]
    assert engine._spotter_neighbour_idx("SPOTTER_CAR_RIGHT", radar) == 4


# ── Повреждение: severity ────────────────────────────────────────────────────

def test_damage_event_carries_severity(engine):
    engine._damage_announced = {k: False for k in
                                ("wing", "floor", "gearbox", "engine")}
    _drain(engine)
    engine._update_damage({"wing_damage": 45, "floor_damage": 0,
                           "gearbox_damage": 0, "engine_damage": 0})
    found = [e for e in _drain(engine) if e["event_code"] == "DAMAGE_WING"]

    assert len(found) == 1
    assert found[0]["damage_severity"] == 45


def test_severe_damage_becomes_critical_urgency(engine):
    engine._damage_announced = {k: False for k in
                                ("wing", "floor", "gearbox", "engine")}
    _drain(engine)
    engine._update_damage({"wing_damage": 0, "floor_damage": 0,
                           "gearbox_damage": 0, "engine_damage": 95})
    found = [e for e in _drain(engine) if e["event_code"] == "DAMAGE_ENGINE"][0]

    message = build_message(found, phrase=found["phrase"], now=0.0)
    assert message.urgency == policy.URGENCY_CRITICAL


def test_light_damage_stays_high_urgency(engine):
    engine._damage_announced = {k: False for k in
                                ("wing", "floor", "gearbox", "engine")}
    _drain(engine)
    engine._update_damage({"wing_damage": 0, "floor_damage": 25,
                           "gearbox_damage": 0, "engine_damage": 0})
    found = [e for e in _drain(engine) if e["event_code"] == "DAMAGE_FLOOR"][0]

    message = build_message(found, phrase=found["phrase"], now=0.0)
    assert message.urgency == policy.URGENCY_HIGH


# ── Safety Car: одна фаза ────────────────────────────────────────────────────

def test_safety_car_stages_share_one_episode(engine):
    engine._sc_episode = 0
    _drain(engine)

    for reason in (0, 1, 3):
        consume_f1_event_packet(engine, _scar_buf(safety_car_type=1,
                                                 event_reason=reason))
    drained = [e for e in _drain(engine)
               if str(e["event_code"]).startswith("SAFETY_CAR_")]

    assert len(drained) == 3
    assert {plumbing.field(e, "sc_episode") for e in drained} == {1}

    messages = [build_message(e, phrase="x", now=0.0) for e in drained]
    assert len({m.situation_id for m in messages}) == 1
    assert len({m.dedupe_key for m in messages}) == 3


def test_a_second_deployment_opens_a_new_episode(engine):
    engine._sc_episode = 0
    _drain(engine)

    for reason in (0, 3, 0):
        consume_f1_event_packet(engine, _scar_buf(safety_car_type=1,
                                                 event_reason=reason))
    drained = [e for e in _drain(engine)
               if str(e["event_code"]) == "SAFETY_CAR_DEPLOYED"]

    assert [plumbing.field(e, "sc_episode") for e in drained] == [1, 2]


def test_safety_car_is_no_longer_urgent_enough_to_interrupt(engine):
    """Сегодня SC приходит с priority="critical" из packets.CRITICAL_EVENTS и
    потому рвёт звучащую фразу. По ТЗ §6 это high: важно, но не в эту секунду."""
    engine._sc_episode = 0
    _drain(engine)
    consume_f1_event_packet(engine, _scar_buf(safety_car_type=1, event_reason=0))
    event = next(e for e in _drain(engine)
                 if e["event_code"] == "SAFETY_CAR_DEPLOYED")

    assert event["priority"] == "critical"      # legacy-поле не тронуто
    message = build_message(event, phrase="Safety Car на трассе.", now=0.0)
    assert message.urgency == policy.URGENCY_HIGH
    assert message.interrupt_policy == policy.POLICY_NEXT


# ── Погодный фронт ───────────────────────────────────────────────────────────

def test_rain_front_id_increments_per_episode():
    from core.strategy_ai.weather_advisory import RainAdvisoryTracker

    tracker = RainAdvisoryTracker()
    assert tracker.front_id == 0

    assert tracker.check({"minutes": 5, "rain_pct": 60}) is not None
    assert tracker.front_id == 1
    # Повторный тик того же фронта не открывает новый эпизод.
    assert tracker.check({"minutes": 4, "rain_pct": 70}) is None
    assert tracker.front_id == 1

    # Дождь ушёл за горизонт и вернулся — это новый фронт.
    assert tracker.check({"minutes": 99, "rain_pct": 10}) is None
    assert tracker.check({"minutes": 3, "rain_pct": 80}) is not None
    assert tracker.front_id == 2


def test_first_weather_front_of_two_sessions_does_not_collide():
    """Погодный фронт №1 в сессии A и фронт №1 в сессии B — РАЗНЫЕ ситуации.

    Локальный счётчик трекера нумерует фронты внутри заезда и после новой
    сессии законно начинает заново. Идентичность даёт `session_id` в составе
    `situation_id`: без него дедуп счёл бы первый фронт новой гонки повтором
    уже закрытой ситуации прошлой."""
    from core.strategy_ai.weather_advisory import RainAdvisoryTracker

    def first_front_situation(session_id: str) -> str:
        tracker = RainAdvisoryTracker()
        assert tracker.check({"minutes": 5, "rain_pct": 60}) is not None
        event = {"event_code": "ENGINEER_RAIN_ADVISORY",
                 **plumbing.attach(rain_front_id=tracker.front_id)}
        return build_message(event, phrase="Дождь скоро.", now=0.0,
                             session_id=session_id).situation_id

    session_a = first_front_situation("20260730_120000")
    session_b = first_front_situation("20260730_143000")

    assert session_a != session_b
    assert session_a.endswith("weather:rain_front_1")
    assert session_b.endswith("weather:rain_front_1")


def test_repeated_packets_keep_one_situation_inside_a_session():
    """Внутри одного заезда повторная телеметрия того же фронта обязана давать
    тот же ID — иначе каждый тик открывал бы новую ситуацию."""
    from core.strategy_ai.weather_advisory import RainAdvisoryTracker

    tracker = RainAdvisoryTracker()
    tracker.check({"minutes": 5, "rain_pct": 60})

    ids = set()
    for _ in range(5):
        # Повторные пакеты того же фронта: check() возвращает None, номер не растёт.
        tracker.check({"minutes": 4, "rain_pct": 65})
        event = {"event_code": "ENGINEER_RAIN_ADVISORY",
                 **plumbing.attach(rain_front_id=tracker.front_id)}
        ids.add(build_message(event, phrase="Дождь скоро.", now=0.0,
                              session_id="20260730_120000").situation_id)

    assert len(ids) == 1


def test_engine_rotates_the_radio_session_id_on_a_new_session(engine):
    _drain(engine)
    before = engine._radio_session_id
    engine._radio_session_id = "stale_id"

    consume_f1_event_packet(engine, _ssta_buf())

    assert engine._radio_session_id != "stale_id"
    assert engine._radio_session_id
    assert isinstance(before, str) and before


def test_rain_front_id_survives_reset():
    """`reset()` зовётся на флэшбеке и не откатывает счётчик.

    От коллизий между гонками защищает `session_id` в `situation_id`, а не рост
    счётчика (см. test_first_weather_front_of_two_sessions_does_not_collide).
    Здесь фиксируется другое: после флэшбека тот же дождь объявляется заново и
    получает следующий номер — это новое ВЫСКАЗЫВАНИЕ, а не ложная новая
    ситуация: пилот перемотал момент и прошлого предупреждения не слышал."""
    from core.strategy_ai.weather_advisory import RainAdvisoryTracker

    tracker = RainAdvisoryTracker()
    tracker.check({"minutes": 5, "rain_pct": 60})
    tracker.reset()

    assert tracker.front_id == 1
    tracker.check({"minutes": 5, "rain_pct": 60})
    assert tracker.front_id == 2


# ── Box-call: одно окно, три стадии ──────────────────────────────────────────

def test_box_call_window_id_tracks_the_armed_lap():
    from core.strategy_ai.box_call import BoxCallTracker

    tracker = BoxCallTracker()
    assert tracker.window_id is None

    assert tracker.update(12, "pit", 0.9, 0) == 1
    assert tracker.window_id == 12
    assert tracker.update(13, "pit", 0.9, 0) == 2
    assert tracker.window_id == 12  # то же окно, вторая стадия

    tracker.reset()
    assert tracker.window_id is None


def test_box_call_escalation_is_one_situation_three_statements():
    events = [
        {"event_code": f"STRAT_BOX_CALL_{tier}", "priority": "critical",
         **plumbing.attach(box_call_window=12)}
        for tier in (1, 2, 3)
    ]
    messages = [build_message(e, phrase="Бокс, бокс.", now=0.0) for e in events]

    assert len({m.situation_id for m in messages}) == 1
    assert len({m.dedupe_key for m in messages}) == 3
    assert all(m.urgency == policy.URGENCY_CRITICAL for m in messages)
    assert all(m.interrupt_policy == policy.POLICY_INTERRUPT for m in messages)


# ── Снимок телеметрии ────────────────────────────────────────────────────────

def test_message_build_failure_never_kills_the_commentary_thread(engine, monkeypatch):
    """`_commentary_loop` — бесконечный поток без внешнего обработчика:
    исключение в нём убило бы озвучку до перезапуска приложения. Пока сообщение
    ничего не решает, его отказ обязан быть бесплатным."""
    import core.engine as mod

    def boom(*_args, **_kwargs):
        raise RuntimeError("сборка сломалась")

    monkeypatch.setattr(mod, "build_radio_message", boom)

    assert engine._build_radio_message({"event_code": "OVTK"}, "Текст") is None


def test_volatile_snapshot_captures_the_fast_moving_values(engine):
    engine._player_ers_percent = 62.0
    engine._player_gap_front = 1300
    engine._player_fuel = 24.5

    snapshot = engine._volatile_snapshot()

    assert snapshot["ers_percent"] == 62.0
    assert snapshot["gap_front_ms"] == 1300
    assert snapshot["fuel_kg"] == 24.5


def test_sc_episode_resets_on_a_new_session(engine):
    """Счётчик эпизодов принадлежит сессии: без сброса вторая гонка начинала бы
    нумерацию с середины и её первый SC получил бы id из прошлой гонки."""
    engine._sc_episode = 0
    _drain(engine)
    consume_f1_event_packet(engine, _scar_buf(1, 0))
    assert engine._sc_episode == 1

    _drain(engine)
    consume_f1_event_packet(engine, _ssta_buf())
    assert engine._sc_episode == 0

    _drain(engine)
    consume_f1_event_packet(engine, _scar_buf(1, 0))
    assert engine._sc_episode == 1


def test_flashback_does_not_invent_a_new_sc_episode(engine):
    """Перемотка сбрасывает трекеры, но НЕ счётчик эпизодов: тот же SC после
    флэшбека — та же ситуация, а не новая."""
    engine._sc_episode = 0
    _drain(engine)
    consume_f1_event_packet(engine, _scar_buf(1, 0))
    episode_before = engine._sc_episode

    engine._handle_flashback()

    assert engine._sc_episode == episode_before


def test_flashback_drains_the_pending_queue(engine):
    """Уже существующее поведение, зафиксировано здесь потому, что от него
    зависит отсутствие «сообщений из будущего»: события до отката не должны
    дожить до озвучки после него."""
    _drain(engine)
    engine._commentary_events.publish({"event_code": "OVTK"})
    assert not engine._commentary_events.empty()

    engine._handle_flashback()

    assert engine._commentary_events.empty()


def test_box_call_window_gets_a_new_id_after_the_window_closes():
    from core.strategy_ai.box_call import BoxCallTracker

    tracker = BoxCallTracker()
    tracker.update(12, "pit", 0.9, 0)
    first = tracker.window_id

    # Заехал в боксы -> окно закрылось.
    tracker.update(12, "pit", 0.9, 1)
    assert tracker.window_id is None

    # Новое решительное окно на другом круге — другая ситуация.
    tracker.update(28, "pit", 0.9, 0)
    assert tracker.window_id == 28
    assert tracker.window_id != first


def test_spotter_neighbour_identity_follows_the_actual_car(engine):
    """Смена соседней машины обязана менять ситуацию, иначе новое предупреждение
    про ДРУГУЮ машину подавилось бы как повтор старого."""
    radar_car_1 = [{"vehicle_idx": 1, "side": "right",
                    "lateral_m": 1.5, "longitudinal_m": 0.5}]
    radar_car_8 = [{"vehicle_idx": 8, "side": "right",
                    "lateral_m": 1.5, "longitudinal_m": 0.5}]

    first = engine._spotter_neighbour_idx("SPOTTER_CAR_RIGHT", radar_car_1)
    second = engine._spotter_neighbour_idx("SPOTTER_CAR_RIGHT", radar_car_8)

    assert (first, second) == (1, 8)


def test_snapshot_is_frozen_into_the_message(engine):
    engine._player_ers_percent = 62.0
    event = {"event_code": "ENGINEER_GAP_DIGEST", "speaker": "engineer"}
    message = build_message(event, phrase="Отрыв впереди: 1.3.", now=0.0,
                            telemetry=engine._volatile_snapshot())

    engine._player_ers_percent = 9.0

    assert message.source_snapshot["ers_percent"] == 62.0
