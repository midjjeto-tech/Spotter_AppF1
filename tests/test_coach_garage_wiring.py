"""Проводка фазы 3: пакет 5 и износ доезжают до отчёта «Гараж».

Фаза 3 намеренно НЕ публикует событий: сетап посреди заезда не меняется, а про
резину в эфире уже говорит strategy_ai. Тест на молчание стоит здесь же —
иначе первая же правка вернёт лишнюю реплику незаметно.
"""
import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.telemetry_adapters import TelemetryDelta


@pytest.fixture
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def test_car_setup_delta_is_stored(engine):
    engine._consume_telemetry_delta(
        TelemetryDelta("car_setup", {"brake_bias": 54, "diff_on_throttle": 75}, 0, 25))

    assert engine._player_setup["brake_bias"] == 54


def test_empty_setup_payload_does_not_wipe_a_known_setup(engine):
    """Пакет приходит редко; пустой ответ парсера не должен стирать то, что
    уже знаем."""
    engine._consume_telemetry_delta(
        TelemetryDelta("car_setup", {"brake_bias": 54}, 0, 25))
    engine._consume_telemetry_delta(TelemetryDelta("car_setup", {}, 0, 25))

    assert engine._player_setup["brake_bias"] == 54


def test_car_setup_publishes_nothing(engine, monkeypatch):
    drafts = []
    monkeypatch.setattr(engine._commentary_events, "publish", drafts.append)

    engine._consume_telemetry_delta(
        TelemetryDelta("car_setup", {"brake_bias": 54}, 0, 25))

    assert drafts == []


def test_garage_report_combines_tyre_load_and_hints(engine):
    engine._player_setup = {"brake_bias": 54, "diff_on_throttle": 75}
    engine.tyre_load.observe(
        wear={"rl": 10.0, "rr": 10.0, "fl": 40.0, "fr": 20.0},
        surface_temp={"rl": 88, "rr": 90, "fl": 128, "fr": 92})
    for _ in range(8):
        engine.coach_log.add(_lockup())

    report = engine._garage_report()

    assert report["tyre_load"]["worst_wheel"] == "fl"
    assert report["setup"]["brake_bias"] == 54
    assert [h["parameter"] for h in report["hints"]] == ["brake_bias"]


def test_garage_report_without_setup_has_no_hints(engine):
    engine._player_setup = {}
    for _ in range(8):
        engine.coach_log.add(_lockup())

    report = engine._garage_report()

    assert report["hints"] == []


def test_tyre_load_is_fed_from_car_damage(engine):
    engine._consume_telemetry_delta(TelemetryDelta("car_damage", {
        "player": {"tyre_wear_per_wheel": {"rl": 10.0, "rr": 10.0,
                                           "fl": 40.0, "fr": 20.0}},
        "all": {},
    }, 0, 25))

    assert engine.tyre_load.report().worst_wheel == "fl"


def _lockup():
    from core.coach_ai.models import CornerMistake
    _lockup.lap = getattr(_lockup, "lap", 0) + 1
    return CornerMistake(kind="lockup", wheel="fl", corner_id=3,
                         corner_name="Turn 3", phase="braking", lap=_lockup.lap,
                         peak=0.5, duration_s=0.3, speed_kmh=180)


# ── Подпись баланса (тип поворота -> механика или аэродинамика) ──────────────

def test_balance_signature_reaches_the_garage_report(engine, monkeypatch):
    """Разметка типов лежала в tracks/*.json с самого начала и работала только
    на споттера. Проверяем, что теперь она доезжает до гаража."""
    from core.track_ai.models import Corner

    corners = [
        Corner(id=i, name=f"Turn {i}",
               start=0.1 * i, end=0.1 * i + 0.05,
               type="slow" if i <= 4 else "fast",
               direction="left", attack_side="inside", defense_side="inside")
        for i in range(1, 9)
    ]
    monkeypatch.setattr(engine, "_track_manager",
                        type("TM", (), {"corners": lambda self: corners})())
    monkeypatch.setattr(engine.coach_log, "map_rows", lambda: [
        {"corner_id": c, "kind": "understeer", "lap": 1} for c in (1, 2, 3)
    ])

    balance = engine._garage_report()["balance"]

    assert balance is not None
    assert balance["domain"] == "mechanical"
    assert "3 из 4" in balance["evidence"]


def test_no_track_map_means_no_balance_verdict(engine, monkeypatch):
    """Без разметки типов сказать «во всех медленных» нечем."""
    monkeypatch.setattr(engine, "_track_manager", None)
    monkeypatch.setattr(engine.coach_log, "map_rows", lambda: [
        {"corner_id": c, "kind": "understeer", "lap": 1} for c in (1, 2, 3)
    ])

    assert engine._garage_report()["balance"] is None
