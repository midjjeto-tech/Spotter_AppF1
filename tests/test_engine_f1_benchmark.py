import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from commentator.channel_router import route_event, CHANNEL_COMMENTARY


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


class _FakeBench:
    ready = True

    def __init__(self, sectors=None):
        self._sectors = sectors

    def compare(self, laps):
        return {"gap_ms": 1500, "player_best_ms": 81346, "player_best_lap": 5,
                "f1_time_ms": 79846, "f1_driver": "Ферстаппен",
                "event": "Italian Grand Prix", "year": 2025, "source": "fastest_lap",
                "sectors": self._sectors,
                "sectors_source": "api" if self._sectors else None,
                "sectors_blocked": False,
                "interpretation": "Игровое время на 1.500 с больше реального ориентира.",
                "comparison_disclaimer": "Условия игры и реального GP не сопоставимы."}

    def context_line(self, cmp, player_name=None):
        return "Эталон трассы — быстрейший круг Ферстаппена 1:19.846."

    def pb_line(self, cmp, player_name=None):
        return "Личный рекорд круга! Отставание полторы секунды от быстрейшего круга Ферстаппена."

    def sector_pb_line(self, n, s):
        return f"Сектор {n} — твой лучший в сессии."


def _drain(engine):
    events = []
    while not engine._commentary_events.empty():
        events.append(engine._commentary_events.get_nowait())
    return events


def test_f1_bench_event_routes_to_commentary():
    assert route_event({"event_code": "F1_BENCH"}, "race") == CHANNEL_COMMENTARY


def test_f1_sector_bench_event_routes_to_commentary():
    assert route_event({"event_code": "F1_SECTOR_BENCH"}, "race") == CHANNEL_COMMENTARY


def test_update_sets_hud_context_and_pb_event(engine):
    engine.f1_benchmark = _FakeBench()
    engine._f1_comparison_progress.best_lap_ms = None
    engine._f1_comparison_progress.best_sector_ms = {}
    _drain(engine)
    engine._update_f1_benchmark()
    hud = engine.get_state().get("f1_benchmark")
    assert hud is not None and hud["gap_ms"] == 1500 and hud["f1_driver"] == "Ферстаппен"
    assert hud["sectors"] is None                            # без секторов в этой фикстуре
    assert engine.commentator.analytics_context              # контекст обновлён
    evt = engine._commentary_events.get_nowait()                    # PB-событие (полный круг)
    assert evt["event_code"] == "F1_BENCH" and evt["phrase"]


def test_no_double_pb_when_not_improved(engine):
    engine.f1_benchmark = _FakeBench()
    engine._f1_comparison_progress.best_lap_ms = 81346                                # тот же best уже зафиксирован
    engine._f1_comparison_progress.best_sector_ms = {}
    _drain(engine)
    engine._update_f1_benchmark()
    assert engine._commentary_events.empty()                        # не улучшил → без озвучки


def test_update_noop_when_not_ready(engine):
    class _NotReady:
        ready = False
    engine.f1_benchmark = _NotReady()
    _drain(engine)
    engine._update_f1_benchmark()                            # без исключений, без событий
    assert engine._commentary_events.empty()


def test_sector_pb_fires_on_first_improvement(engine):
    """Холодный старт: первый круг сессии — все секторы считаются PB."""
    sectors = {1: {"player_ms": 27000, "gap_ms": -200}, 2: {"player_ms": 38000, "gap_ms": 100},
               3: {"player_ms": 26000, "gap_ms": 50}}
    engine.f1_benchmark = _FakeBench(sectors=sectors)
    engine._f1_comparison_progress.best_lap_ms = None
    engine._f1_comparison_progress.best_sector_ms = {}
    _drain(engine)
    engine._update_f1_benchmark()
    events = _drain(engine)
    sector_events = [e for e in events if e["event_code"] == "F1_SECTOR_BENCH"]
    assert len(sector_events) == 1
    assert engine._f1_comparison_progress.best_sector_ms == {1: 27000, 2: 38000, 3: 26000}


def test_sector_pb_picks_smallest_gap_when_multiple_improve(engine):
    """Несколько PB-секторов в одном круге -> ОДНА реплика, про наименьший gap_ms
    (ближе всего к/лучше реального F1 — самое впечатляющее достижение)."""
    sectors = {1: {"player_ms": 27000, "gap_ms": 500}, 2: {"player_ms": 38000, "gap_ms": -300},
               3: {"player_ms": 26000, "gap_ms": 200}}
    engine.f1_benchmark = _FakeBench(sectors=sectors)
    engine._f1_comparison_progress.best_lap_ms = None
    engine._f1_comparison_progress.best_sector_ms = {}
    _drain(engine)
    engine._update_f1_benchmark()
    events = _drain(engine)
    sector_events = [e for e in events if e["event_code"] == "F1_SECTOR_BENCH"]
    assert len(sector_events) == 1
    assert "Сектор 2" in sector_events[0]["phrase"]        # наименьший gap_ms (-300)


def test_sector_pb_silent_when_not_improved(engine):
    sectors = {1: {"player_ms": 27000, "gap_ms": 500}, 2: {"player_ms": 38000, "gap_ms": -300},
               3: {"player_ms": 26000, "gap_ms": 200}}
    engine.f1_benchmark = _FakeBench(sectors=sectors)
    engine._f1_comparison_progress.best_lap_ms = 81346
    engine._f1_comparison_progress.best_sector_ms = {1: 27000, 2: 38000, 3: 26000}   # уже лучшие — не улучшены
    _drain(engine)
    engine._update_f1_benchmark()
    assert engine._commentary_events.empty()


def test_sector_pb_absent_when_sectors_none(engine):
    """compare()["sectors"] is None -> без секторной реплики, полный бенчмарк не трогаем."""
    engine.f1_benchmark = _FakeBench(sectors=None)
    engine._f1_comparison_progress.best_lap_ms = None
    engine._f1_comparison_progress.best_sector_ms = {}
    _drain(engine)
    engine._update_f1_benchmark()
    events = _drain(engine)
    assert all(e["event_code"] != "F1_SECTOR_BENCH" for e in events)
