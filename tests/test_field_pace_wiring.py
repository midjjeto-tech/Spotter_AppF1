"""Проводка положения в поле: Session History -> раскладка -> реплика и экран.

Главный тест здесь — что реплика звучит в КВАЛИФИКАЦИИ. Сводка по разрывам
заперта в гонку (`session_type != "race"` → выход), и раскладка по секторам,
унаследовав тот же гейт, оказалась бы бесполезной ровно там, где она нужнее
всего: в квалификации пилот весь заезд занят поиском своего медленного сектора.
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


def _history(player_s1: int = 30000, player_s2: int = 32000,
             player_s3: int = 29000) -> dict[int, dict]:
    """Игрок (0) заметно медленнее поля во ВТОРОМ секторе."""
    return {
        0: {"best_sector_ms": {1: player_s1, 2: player_s2, 3: player_s3},
            "best_lap_ms": 91000},
        1: {"best_sector_ms": {1: 29900, 2: 30800, 3: 29100},
            "best_lap_ms": 89800},
        2: {"best_sector_ms": {1: 29950, 2: 30900, 3: 28950},
            "best_lap_ms": 89900},
        3: {"best_sector_ms": {1: 30050, 2: 31000, 3: 29050},
            "best_lap_ms": 90100},
    }


def _capture(engine, monkeypatch):
    drafts, calls = [], []
    monkeypatch.setattr(engine._commentary_events, "publish", drafts.append)
    monkeypatch.setattr(
        engine, "_render_engineer_phrase",
        lambda draft, code, fields=None, *a, **kw: (
            calls.append((code, dict(fields or {}))), "фраза")[1])
    return drafts, calls


def _drive(engine, laps: range) -> None:
    for lap in laps:
        engine._field_pace_tick(lap)


# ── Эфир ─────────────────────────────────────────────────────────────────────

def test_weak_sector_is_reported_with_place_and_gap(engine, monkeypatch):
    engine._session_history = _history()
    engine._player_car_index = 0
    drafts, calls = _capture(engine, monkeypatch)

    _drive(engine, range(1, 4))

    assert [code for code, _ in calls] == ["field.sector_weak"]
    fields = calls[0][1]
    assert fields["sector_no"] == "втором"
    assert fields["rank"] == "четвёртый"
    assert fields["loss"] == "1,2 секунды"
    assert drafts[0]["event_code"] == "FIELD_SECTOR"
    assert drafts[0]["speaker"] == eng_mod.SPEAKER_ENGINEER


def test_it_speaks_in_qualifying_unlike_the_gap_digest(engine, monkeypatch):
    """Сводка по разрывам в квалификации молчит по построению. Эта раскладка —
    наоборот: именно там она и нужна."""
    engine._session_type = "qualifying"
    engine._session_history = _history()
    engine._player_car_index = 0
    drafts, _ = _capture(engine, monkeypatch)

    _drive(engine, range(1, 4))

    assert len(drafts) == 1


def test_it_speaks_in_practice_too(engine, monkeypatch):
    engine._session_type = "practice"
    engine._session_history = _history()
    engine._player_car_index = 0
    drafts, _ = _capture(engine, monkeypatch)

    _drive(engine, range(1, 4))

    assert len(drafts) == 1


def test_a_single_lap_never_speaks(engine, monkeypatch):
    engine._session_history = _history()
    engine._player_car_index = 0
    drafts, _ = _capture(engine, monkeypatch)

    engine._field_pace_tick(1)

    assert drafts == []


def test_leading_every_sector_earns_praise_not_a_warning(engine, monkeypatch):
    engine._session_history = _history(player_s1=29000, player_s2=30000,
                                       player_s3=28000)
    engine._player_car_index = 0
    _, calls = _capture(engine, monkeypatch)

    _drive(engine, range(1, 4))

    assert [code for code, _ in calls] == ["field.sector_strong"]
    assert "loss" not in calls[0][1]


def test_a_middling_field_position_is_not_praised(engine, monkeypatch):
    """«Ты четвёртый в секторе, и это твоя сильная сторона» — это утешение.

    Отрывы здесь всюду ниже произносимого, поэтому слабого сектора нет, а
    сильный есть — но игрок в нём не первый, и хвалить не за что."""
    history = _history(player_s1=29980, player_s2=30870, player_s3=29010)
    engine._session_history = history
    engine._player_car_index = 0
    drafts, _ = _capture(engine, monkeypatch)

    _drive(engine, range(1, 8))

    assert drafts == []


def test_chatter_toggle_silences_the_air_but_not_the_screen(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = False
    engine._session_history = _history()
    engine._player_car_index = 0
    drafts, _ = _capture(engine, monkeypatch)

    _drive(engine, range(1, 4))

    assert drafts == []
    assert engine._field_pace is not None
    assert engine._field_pace.weakest.sector == 2


def test_the_same_topic_is_not_repeated_every_lap(engine, monkeypatch):
    engine._session_history = _history()
    engine._player_car_index = 0
    drafts, _ = _capture(engine, monkeypatch)

    _drive(engine, range(1, 12))

    assert len(drafts) <= 2


def test_a_thin_field_stays_silent(engine, monkeypatch):
    engine._session_history = {
        0: {"best_sector_ms": {1: 30000, 2: 32000}, "best_lap_ms": 91000},
        1: {"best_sector_ms": {1: 29900, 2: 30800}, "best_lap_ms": 89800},
    }
    engine._player_car_index = 0
    drafts, _ = _capture(engine, monkeypatch)

    _drive(engine, range(1, 6))

    assert drafts == []
    assert engine._field_pace is None


def test_empty_history_costs_nothing(engine, monkeypatch):
    engine._session_history = {}
    engine._player_car_index = 0
    drafts, _ = _capture(engine, monkeypatch)

    _drive(engine, range(1, 6))

    assert drafts == []


# ── Экран ────────────────────────────────────────────────────────────────────

def test_standing_reaches_the_ui_state(engine, monkeypatch):
    engine._session_history = _history()
    engine._player_car_index = 0
    _capture(engine, monkeypatch)
    _drive(engine, range(1, 4))

    engine._ui_state.set_analysis(
        race_ai={}, strategy_ai={}, coach_ai={}, rivals={}, track_ai=None,
        track_name="Test", field_pace=engine._field_pace.to_dict())

    section = engine._ui_state.section("field_pace")
    assert section["weakest"]["sector"] == 2
    assert section["weakest"]["rank"] == 4
    assert section["lap_rank"] == 4
    assert len(section["sectors"]) == 3


def test_a_snapshot_without_a_recount_does_not_wipe_the_screen(engine):
    """Раскладка обновляется раз в круг, а проекция пересобирается на каждом
    снимке телеметрии — None не должен затирать уже посчитанное."""
    engine._ui_state.set_analysis(
        race_ai={}, strategy_ai={}, coach_ai={}, rivals={}, track_ai=None,
        track_name="Test", field_pace={"sectors": [], "weakest": None})
    engine._ui_state.set_analysis(
        race_ai={}, strategy_ai={}, coach_ai={}, rivals={}, track_ai=None,
        track_name="Test", field_pace=None)

    assert engine._ui_state.section("field_pace") is not None


# ── Границы сессии ───────────────────────────────────────────────────────────

def test_session_restart_forgets_the_field(engine):
    """Секторы практики в квалификации означали бы не тот темп."""
    from tests.telemetry import consume_f1_event_packet
    from core.packets import HEADER_SIZE

    engine._session_history = _history()
    engine._player_car_index = 0
    _drive(engine, range(1, 4))
    assert engine._field_pace is not None

    buf = bytearray(HEADER_SIZE + 4)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = b"SSTA"
    consume_f1_event_packet(engine, bytes(buf))

    assert engine._field_pace is None


def test_track_change_forgets_the_field(engine, monkeypatch):
    from core.coach_ai.reference_store import TrackHistory
    monkeypatch.setattr(eng_mod, "load_track_history", lambda tid: TrackHistory())

    engine._session_history = _history()
    engine._player_car_index = 0
    _drive(engine, range(1, 4))
    assert engine._field_pace is not None

    engine._consume_telemetry_delta(TelemetryDelta("session", {
        "track_id": 17, "weather": 0, "track_temp": 30, "air_temp": 20,
    }, 0, 2025))

    assert engine._field_pace is None
