import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from commentator.channel_router import route_event, CHANNEL_COMMENTARY
from tests.telemetry import consume_f1_event_packet


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


class _FakeCareer:
    ready = True

    def __init__(self, sectors=None):
        self._sectors = sectors

    def compare(self, laps):
        return {"gap_ms": -500, "player_best_ms": 79500, "best_ever_ms": 80000,
                "best_ever_date": "2026-01-01", "sectors": self._sectors}

    def context_line(self, cmp):
        return "личный рекорд трассы — контекст"

    def pb_line(self, cmp):
        return "Новый личный рекорд трассы! Быстрее прежнего на 0.5 секунды!"

    def sector_pb_line(self, n, s):
        return f"Сектор {n} — новый личный рекорд трассы!"


def _drain(engine):
    events = []
    while not engine._commentary_events.empty():
        events.append(engine._commentary_events.get_nowait())
    return events


def _event_buf(code: str) -> bytes:
    from core.packets import HEADER_SIZE
    buf = bytearray(HEADER_SIZE + 4)
    buf[HEADER_SIZE:HEADER_SIZE + 4] = code.encode("ascii")
    return bytes(buf)


def test_career_pb_event_routes_to_commentary():
    assert route_event({"event_code": "CAREER_PB"}, "race") == CHANNEL_COMMENTARY


def test_career_sector_pb_event_routes_to_commentary():
    assert route_event({"event_code": "CAREER_SECTOR_PB"}, "race") == CHANNEL_COMMENTARY


def test_update_sets_hud_and_pb_event(engine):
    engine.career_memory = _FakeCareer()
    engine._career_comparison_progress.best_lap_ms = None
    engine._career_comparison_progress.best_sector_ms = {}
    _drain(engine)
    engine._update_career_memory()
    hud = engine.get_state().get("career_memory")
    assert hud is not None and hud["gap_ms"] == -500
    assert hud["sectors"] is None
    evt = engine._commentary_events.get_nowait()
    assert evt["event_code"] == "CAREER_PB" and evt["phrase"]


def test_no_double_pb_when_not_improved(engine):
    engine.career_memory = _FakeCareer()
    engine._career_comparison_progress.best_lap_ms = 79500
    engine._career_comparison_progress.best_sector_ms = {}
    _drain(engine)
    engine._update_career_memory()
    assert engine._commentary_events.empty()


def test_update_noop_when_not_ready(engine):
    class _NotReady:
        ready = False
    engine.career_memory = _NotReady()
    _drain(engine)
    engine._update_career_memory()
    assert engine._commentary_events.empty()


def test_sector_pb_fires_on_first_improvement(engine):
    sectors = {1: {"player_ms": 26400, "gap_ms": -100}, 2: {"player_ms": 27400, "gap_ms": -100},
               3: {"player_ms": 25700, "gap_ms": -300}}
    engine.career_memory = _FakeCareer(sectors=sectors)
    engine._career_comparison_progress.best_lap_ms = None
    engine._career_comparison_progress.best_sector_ms = {}
    _drain(engine)
    engine._update_career_memory()
    events = _drain(engine)
    sector_events = [e for e in events if e["event_code"] == "CAREER_SECTOR_PB"]
    assert len(sector_events) == 1
    assert engine._career_comparison_progress.best_sector_ms == {1: 26400, 2: 27400, 3: 25700}


def test_sector_pb_picks_smallest_gap_when_multiple_improve(engine):
    sectors = {1: {"player_ms": 26400, "gap_ms": 500}, 2: {"player_ms": 27400, "gap_ms": -300},
               3: {"player_ms": 25700, "gap_ms": 200}}
    engine.career_memory = _FakeCareer(sectors=sectors)
    engine._career_comparison_progress.best_lap_ms = None
    engine._career_comparison_progress.best_sector_ms = {}
    _drain(engine)
    engine._update_career_memory()
    events = _drain(engine)
    sector_events = [e for e in events if e["event_code"] == "CAREER_SECTOR_PB"]
    assert len(sector_events) == 1
    assert "Сектор 2" in sector_events[0]["phrase"]


def test_sector_pb_silent_when_not_improved(engine):
    sectors = {1: {"player_ms": 26400, "gap_ms": 500}, 2: {"player_ms": 27400, "gap_ms": -300},
               3: {"player_ms": 25700, "gap_ms": 200}}
    engine.career_memory = _FakeCareer(sectors=sectors)
    engine._career_comparison_progress.best_lap_ms = 79500
    engine._career_comparison_progress.best_sector_ms = {1: 26400, 2: 27400, 3: 25700}
    _drain(engine)
    engine._update_career_memory()
    assert engine._commentary_events.empty()


def test_sector_pb_absent_when_sectors_none(engine):
    engine.career_memory = _FakeCareer(sectors=None)
    engine._career_comparison_progress.best_lap_ms = None
    engine._career_comparison_progress.best_sector_ms = {}
    _drain(engine)
    engine._update_career_memory()
    events = _drain(engine)
    assert all(e["event_code"] != "CAREER_SECTOR_PB" for e in events)


def test_update_sets_analytics_context(engine):
    engine._f1_context_line = None    # изолируемся от состояния других тестов модуля
    engine._career_context_line = None
    engine.career_memory = _FakeCareer()
    engine._career_comparison_progress.best_lap_ms = None
    engine._career_comparison_progress.best_sector_ms = {}
    _drain(engine)
    engine._update_career_memory()
    assert engine.commentator.analytics_context == engine.career_memory.context_line(
        engine.career_memory.compare([]))


def test_analytics_context_combines_f1_and_career_without_clobbering(engine):
    """Регрессия: до фикса Career Memory затирала F1 Benchmark в analytics_context,
    т.к. обе фичи вызывали set_analytics_context() напрямую с перезаписью. Обе части
    должны присутствовать ОДНОВРЕМЕННО."""
    engine._f1_context_line = "F1-КОНТЕКСТ-МАРКЕР"
    engine._career_context_line = None
    engine._refresh_analytics_context()
    engine.career_memory = _FakeCareer()
    engine._career_comparison_progress.best_lap_ms = None
    engine._career_comparison_progress.best_sector_ms = {}
    _drain(engine)
    engine._update_career_memory()
    assert "F1-КОНТЕКСТ-МАРКЕР" in engine.commentator.analytics_context
    assert engine.career_memory.context_line(
        engine.career_memory.compare([])) in engine.commentator.analytics_context


def test_reset_clears_both_context_lines_and_analytics_context(engine):
    engine._f1_context_line = "старый F1 контекст"
    engine._career_context_line = "старый career контекст"
    engine._refresh_analytics_context()
    assert engine.commentator.analytics_context
    engine._f1_context_line = None
    engine._career_context_line = None
    engine._refresh_analytics_context()
    assert engine.commentator.analytics_context is None


def test_pb_event_carries_vehicle_idx_and_raw_comparison_fields(engine):
    engine.career_memory = _FakeCareer()
    engine._career_comparison_progress.best_lap_ms = None
    engine._career_comparison_progress.best_sector_ms = {}
    _drain(engine)
    engine._update_career_memory()
    evt = engine._commentary_events.get_nowait()
    assert evt["vehicle_idx"] == engine._player_car_index
    assert evt["gap_ms"] == -500
    assert evt["player_best_ms"] == 79500
    assert evt["best_ever_ms"] == 80000
    assert evt["best_ever_date"] == "2026-01-01"


def test_sector_pb_event_carries_vehicle_idx(engine):
    sectors = {1: {"player_ms": 26400, "gap_ms": -100}, 2: {"player_ms": 27400, "gap_ms": -100},
               3: {"player_ms": 25700, "gap_ms": -300}}
    engine.career_memory = _FakeCareer(sectors=sectors)
    engine._career_comparison_progress.best_lap_ms = None
    engine._career_comparison_progress.best_sector_ms = {}
    _drain(engine)
    engine._update_career_memory()
    events = _drain(engine)
    sector_events = [e for e in events if e["event_code"] == "CAREER_SECTOR_PB"]
    assert len(sector_events) == 1
    assert sector_events[0]["vehicle_idx"] == engine._player_car_index
    fired_sector = sector_events[0]["sector"]
    assert sector_events[0]["sector_player_ms"] == sectors[fired_sector]["player_ms"]


def test_lap_pb_sets_career_pb_this_race_flag(engine):
    engine.career_memory = _FakeCareer()
    engine._career_comparison_progress.best_lap_ms = None
    engine._career_comparison_progress.best_sector_ms = {}
    engine._career_pb_this_race = False
    _drain(engine)
    engine._update_career_memory()
    assert engine._career_pb_this_race is True


def test_sector_pb_sets_career_pb_this_race_flag(engine):
    sectors = {1: {"player_ms": 26400, "gap_ms": -100}, 2: {"player_ms": 27400, "gap_ms": -100},
               3: {"player_ms": 25700, "gap_ms": -300}}
    engine.career_memory = _FakeCareer(sectors=sectors)
    engine._career_comparison_progress.best_lap_ms = None
    engine._career_comparison_progress.best_sector_ms = {}
    engine._career_pb_this_race = False
    _drain(engine)
    engine._update_career_memory()
    assert engine._career_pb_this_race is True


def test_no_pb_does_not_set_career_pb_this_race_flag(engine):
    engine.career_memory = _FakeCareer()
    engine._career_comparison_progress.best_lap_ms = 79500
    engine._career_comparison_progress.best_sector_ms = {1: 26400, 2: 27400, 3: 25700}
    engine._career_pb_this_race = False
    _drain(engine)
    engine._update_career_memory()
    assert engine._career_pb_this_race is False


def test_ssta_resets_career_pb_this_race_flag(engine):
    engine._career_pb_this_race = True
    consume_f1_event_packet(engine, _event_buf("SSTA"))
    assert engine._career_pb_this_race is False


def test_career_recap_podium_gets_high_importance(engine):
    engine._career_pb_this_race = False
    _drain(engine)
    engine._publish_career_recap(
        vs_last_visit={"laptime_delta_ms": 500, "position_delta": -2, "last_visit_date": "2026-01-01"},
        career_stats={"total_races": 10, "wins": 1, "podiums": 3, "avg_position": 5.0},
        final_pos=2,
    )
    evt = engine._commentary_events.get_nowait()
    assert evt["event_code"] == "CAREER_RECAP"
    assert evt["importance"] == 90
    assert evt["vehicle_idx"] == engine._player_car_index


def test_career_recap_improved_position_gets_medium_importance(engine):
    engine._career_pb_this_race = False
    _drain(engine)
    engine._publish_career_recap(
        vs_last_visit={"laptime_delta_ms": 500, "position_delta": 3, "last_visit_date": "2026-01-01"},
        career_stats={"total_races": 10, "wins": 0, "podiums": 0, "avg_position": 8.0},
        final_pos=7,
    )
    evt = engine._commentary_events.get_nowait()
    assert evt["importance"] == 70


def test_career_recap_faster_lap_gets_medium_importance(engine):
    engine._career_pb_this_race = False
    _drain(engine)
    engine._publish_career_recap(
        vs_last_visit={"laptime_delta_ms": -250, "position_delta": -1, "last_visit_date": "2026-01-01"},
        career_stats={"total_races": 10, "wins": 0, "podiums": 0, "avg_position": 8.0},
        final_pos=9,
    )
    evt = engine._commentary_events.get_nowait()
    assert evt["importance"] == 70


def test_career_recap_pb_this_race_gets_medium_importance_even_if_vs_last_visit_none(engine):
    engine._career_pb_this_race = True
    _drain(engine)
    engine._publish_career_recap(
        vs_last_visit=None,
        career_stats={"total_races": 1, "wins": 0, "podiums": 0, "avg_position": 9.0},
        final_pos=9,
    )
    evt = engine._commentary_events.get_nowait()
    assert evt["importance"] == 70


def test_career_recap_routine_finish_gets_low_importance(engine):
    engine._career_pb_this_race = False
    _drain(engine)
    engine._publish_career_recap(
        vs_last_visit={"laptime_delta_ms": 300, "position_delta": -1, "last_visit_date": "2026-01-01"},
        career_stats={"total_races": 10, "wins": 0, "podiums": 0, "avg_position": 8.0},
        final_pos=9,
    )
    evt = engine._commentary_events.get_nowait()
    assert evt["importance"] == 40


def test_career_recap_handles_none_vs_last_visit_without_crashing(engine):
    engine._career_pb_this_race = False
    _drain(engine)
    engine._publish_career_recap(
        vs_last_visit=None,
        career_stats={"total_races": 1, "wins": 0, "podiums": 0, "avg_position": 9.0},
        final_pos=9,
    )
    evt = engine._commentary_events.get_nowait()
    assert evt["importance"] == 40


def test_career_recap_carries_facts_for_racefeed(engine):
    vs_last_visit = {"laptime_delta_ms": 500, "position_delta": -2, "last_visit_date": "2026-01-01"}
    career_stats = {"total_races": 10, "wins": 1, "podiums": 3, "avg_position": 5.0}
    engine._career_pb_this_race = False
    _drain(engine)
    engine._publish_career_recap(vs_last_visit=vs_last_visit, career_stats=career_stats, final_pos=2)
    evt = engine._commentary_events.get_nowait()
    assert evt["vs_last_visit"] == vs_last_visit
    assert evt["career_stats"] == career_stats


def test_career_recap_final_pos_3_is_still_podium(engine):
    engine._career_pb_this_race = False
    _drain(engine)
    engine._publish_career_recap(vs_last_visit=None, career_stats={}, final_pos=3)
    evt = engine._commentary_events.get_nowait()
    assert evt["importance"] == 90


def test_career_recap_final_pos_none_is_not_podium(engine):
    engine._career_pb_this_race = False
    _drain(engine)
    engine._publish_career_recap(
        vs_last_visit={"laptime_delta_ms": 300, "position_delta": -1, "last_visit_date": "2026-01-01"},
        career_stats={}, final_pos=None,
    )
    evt = engine._commentary_events.get_nowait()
    assert evt["importance"] == 40
