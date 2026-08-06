from core.strategy_ai.models import StrategyDecision, StrategyEvent
from core.strategy_ai.module import StrategyModule, StrategySnapshot


def _snapshot(**overrides):
    values = {
        "player_lap": 10,
        "total_laps": 50,
        "player_pos": 5,
        "gap_front_ms": 2000,
        "gap_behind_ms": 3000,
        "gap_leader_ms": 12000,
        "tyre_compound": "MEDIUM",
        "tyre_age": 5,
        "tyre_wear": 10.0,
        "last_lap_ms": 90_000,
        "fuel": 35.0,
        "ers_percent": 60.0,
        "ers_deploy_mode": 1,
        "session_type": "race",
        "pit_status": 0,
    }
    values.update(overrides)
    return StrategySnapshot(**values)


class _Analyzer:
    def __init__(self, event=None):
        self.event = event
        self.inputs = []
        self.reset_calls = 0

    def update(self, snapshot):
        self.inputs.append(snapshot)
        return self.event

    def get_state(self):
        return {"action": self.event.decision.action if self.event else "hold"}

    def reset(self):
        self.reset_calls += 1
        self.event = None


def _event(*, action="pit", confidence=0.9, type_="pit_window"):
    decision = StrategyDecision(action=action, confidence=confidence, reason="test")
    return StrategyEvent(
        type=type_, priority="high", confidence=confidence,
        decision=decision, data={"source": "test"})


def test_decisive_tick_returns_box_call_then_notice_and_suppresses_advisory():
    module = StrategyModule(analyzer=_Analyzer(_event()))

    result = module.tick(_snapshot(), 100.0, engineer_chatter_enabled=True)

    assert [event["event_code"] for event in result.events] == [
        "STRAT_BOX_CALL_1", "PIT_CALL_NOTICE"]
    assert result.state == {"action": "pit"}


def test_non_decisive_tick_maps_strategy_event_and_honours_cooldown():
    module = StrategyModule(
        analyzer=_Analyzer(_event(action="save", confidence=0.7, type_="fuel_save")))

    first = module.tick(_snapshot(), 100.0, engineer_chatter_enabled=True)
    second = module.tick(_snapshot(), 119.9, engineer_chatter_enabled=True)

    assert [event["event_code"] for event in first.events] == ["STRAT_FUEL"]
    assert second.events == ()


def test_missing_decision_resets_box_call_escalation():
    analyzer = _Analyzer(_event())
    module = StrategyModule(analyzer=analyzer)
    assert module.tick(_snapshot(), 100.0, engineer_chatter_enabled=True).events[0][
        "event_code"] == "STRAT_BOX_CALL_1"

    analyzer.event = None
    module.tick(_snapshot(), 101.0, engineer_chatter_enabled=True)
    analyzer.event = _event()

    assert module.tick(_snapshot(), 102.0, engineer_chatter_enabled=True).events[0][
        "event_code"] == "STRAT_BOX_CALL_1"


def test_session_reset_rearms_pit_window_approach_and_resets_analyzer_state():
    analyzer = _Analyzer(None)
    module = StrategyModule(analyzer=analyzer)
    close_to_window = _snapshot(tyre_age=25, tyre_wear=20.0)

    first = module.tick(close_to_window, 100.0, engineer_chatter_enabled=True)
    second = module.tick(close_to_window, 101.0, engineer_chatter_enabled=True)
    module.reset("session_started")
    third = module.tick(close_to_window, 102.0, engineer_chatter_enabled=True)

    assert [e["event_code"] for e in first.events] == ["PIT_WINDOW_APPROACH"]
    assert second.events == ()
    assert [e["event_code"] for e in third.events] == ["PIT_WINDOW_APPROACH"]
    assert len(analyzer.inputs) == 3
    assert analyzer.reset_calls == 1


def test_flashback_reset_preserves_lap_level_analyzer_history():
    analyzer = _Analyzer(None)
    module = StrategyModule(analyzer=analyzer)

    module.reset("flashback")

    assert analyzer.reset_calls == 0


def test_reset_clears_strategy_cooldown():
    analyzer = _Analyzer(_event(action="save", confidence=0.7, type_="fuel_save"))
    module = StrategyModule(analyzer=analyzer)
    module.last_advisory_at = 500.0

    module.reset("session_started")

    assert module.last_advisory_at == 0.0
