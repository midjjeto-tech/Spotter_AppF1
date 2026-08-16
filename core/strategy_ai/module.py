"""Deep orchestration module for deterministic race strategy.

The implementation owns decision ordering, pit-window approach state,
imperative box-call escalation, advisory cooldown and commentary-event
construction.  It performs no I/O and does not know about ``F1Engine``.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging

from core.radio.plumbing import attach as radio_plumbing
from core.strategy_ai.box_call import DECISIVE_CONFIDENCE, BoxCallTracker
from core.strategy_ai.pit_window import PitWindowApproachTracker, detect_pit_window
from core.strategy_ai.strategy import StrategyAnalyzer


_log = logging.getLogger(__name__)

_EVENT_CODES = {
    "cover_opponent": "STRAT_PIT",
    "undercut": "STRAT_UNDERCUT",
    "overcut": "STRAT_OVERCUT",
    "pit_window": "STRAT_PIT",
    "tyre_save": "STRAT_SAVE",
    "push_pace": "STRAT_PUSH",
    "fuel_save": "STRAT_FUEL",
    "ers_save": "STRAT_ERS_SAVE",
    "ers_overtake": "STRAT_ERS_OVERTAKE",
}
_CHATTER_GATED_TYPES = {"ers_save", "ers_overtake"}


@dataclass(frozen=True, slots=True)
class StrategySnapshot:
    player_lap: int | None
    total_laps: int | None
    player_pos: int | None
    gap_front_ms: int | None
    gap_behind_ms: int | None
    gap_leader_ms: int | None
    tyre_compound: str | None
    tyre_age: int | None
    tyre_wear: float | None
    last_lap_ms: int | None
    fuel: float | None
    ers_percent: float | None
    ers_deploy_mode: int | None
    session_type: str
    pit_status: int | None

    def analyzer_input(self) -> dict:
        return {
            "player_lap": self.player_lap,
            "total_laps": self.total_laps,
            "player_pos": self.player_pos,
            "gap_front_ms": self.gap_front_ms,
            "gap_behind_ms": self.gap_behind_ms,
            "gap_leader_ms": self.gap_leader_ms,
            "tyre_compound": self.tyre_compound,
            "tyre_age": self.tyre_age,
            "tyre_wear": self.tyre_wear,
            "last_lap_ms": self.last_lap_ms,
            "fuel": self.fuel,
            "ers_percent": self.ers_percent,
            "ers_deploy_mode": self.ers_deploy_mode,
        }


@dataclass(frozen=True, slots=True)
class StrategyResult:
    state: dict
    events: tuple[dict, ...]


class StrategyModule:
    """Single deep interface for one strategy tick and lifecycle resets."""

    def __init__(
        self,
        analyzer: StrategyAnalyzer | None = None,
        box_call: BoxCallTracker | None = None,
        pit_window_approach: PitWindowApproachTracker | None = None,
    ) -> None:
        self.analyzer = analyzer or StrategyAnalyzer()
        self.box_call_tracker = box_call or BoxCallTracker()
        self.pit_window_approach_tracker = pit_window_approach or PitWindowApproachTracker()
        self.last_advisory_at = 0.0
        self._tick_count = 0

    def tick(
        self,
        snapshot: StrategySnapshot,
        now: float,
        *,
        engineer_chatter_enabled: bool,
        ers_hints_enabled: bool = True,
    ) -> StrategyResult:
        strategy_event = self.analyzer.update(snapshot.analyzer_input())
        events: list[dict] = []

        laps_remaining = (
            snapshot.total_laps - snapshot.player_lap
            if snapshot.total_laps and snapshot.player_lap is not None
            else None
        )
        window_open, _confidence, laps_left = detect_pit_window(
            snapshot.tyre_age,
            snapshot.tyre_wear,
            laps_remaining,
            snapshot.tyre_compound,
        )
        if snapshot.session_type == "race":
            code = self.pit_window_approach_tracker.check(window_open, laps_left)
            if code:
                _log.info(
                    "DIAG PIT_WINDOW_APPROACH firing: laps_left=%s open=%s",
                    laps_left,
                    window_open,
                )
            if code and engineer_chatter_enabled:
                events.append({
                    "event_code": "PIT_WINDOW_APPROACH",
                    "priority": "normal",
                    # Семантический код, а не строка: формулировку даёт банк, а
                    # стабильный выбор варианта требует dedupe_key, которого у
                    # этого модуля нет — рендерит движок при публикации.
                    "phrase_code": code,
                    "speaker": "engineer",
                    "driver": "",
                    "color": "#38BDF8",
                    "bypass_speak_threshold": True,
                })

        action = strategy_event.decision.action if strategy_event else "hold"
        confidence = strategy_event.confidence if strategy_event else 0.0
        self._tick_count += 1
        if self._tick_count % 10 == 0:
            _log.info(
                "DIAG strategy tick: session_type=%s action=%s confidence=%.2f "
                "strategy_type=%s gap_front=%s gap_behind=%s",
                snapshot.session_type,
                action,
                confidence,
                strategy_event.type if strategy_event else None,
                snapshot.gap_front_ms,
                snapshot.gap_behind_ms,
            )

        box_tier = self.box_call_tracker.update(
            snapshot.player_lap,
            action,
            confidence,
            snapshot.pit_status,
        )
        if box_tier is not None:
            # box_call_window — личность окна, одна на всю эскалацию 1→2→3
            # (см. BoxCallTracker.window_id). Нужна core/radio/situations.py,
            # чтобы три tier'а читались как стадии одной ситуации, а не как три
            # независимые команды.
            box_window = radio_plumbing(
                box_call_window=self.box_call_tracker.window_id)
            events.append({
                "event_code": f"STRAT_BOX_CALL_{box_tier}",
                "priority": "critical",
                "driver": "player",
                "color": "#EF4444",
                "speaker": "engineer",
                **box_window,
            })
            if box_tier == 1:
                events.append({
                    "event_code": "PIT_CALL_NOTICE",
                    "priority": "normal",
                    "driver": "",
                    "color": "#38BDF8",
                    "bypass_speak_threshold": True,
                    **box_window,
                })

        decisive = action == "pit" and confidence >= DECISIVE_CONFIDENCE
        if strategy_event is not None and not decisive:
            if now - self.last_advisory_at >= 20.0:
                # Preserve historical semantics: a gated ERS advisory still
                # consumes this strategy cooldown window.
                self.last_advisory_at = now
                # Два тумблера, и оба гасят ERS: общий (инженер молчит целиком)
                # и частный (батарея не нужна, остальное нужно). Частный
                # добавлен потому, что пороги ERS живой калибровки не проходили,
                # и снимать их отдельно — осмысленная потребность.
                chatter_gated = (
                    strategy_event.type in _CHATTER_GATED_TYPES
                    and not (engineer_chatter_enabled and ers_hints_enabled)
                )
                if not chatter_gated:
                    events.append({
                        "event_code": _EVENT_CODES.get(strategy_event.type, "STRAT_PIT"),
                        "priority": strategy_event.priority,
                        "driver": "player",
                        "speaker": "engineer",
                        "color": "#38BDF8",
                        "strategy_ai_type": strategy_event.type,
                        "strategy_ai_data": {
                            **strategy_event.data,
                            "confidence": strategy_event.confidence,
                            "action": strategy_event.decision.action,
                            "reason": strategy_event.decision.reason,
                        },
                    })

        return StrategyResult(
            state=self.analyzer.get_state(),
            events=tuple(events),
        )

    def note_pit_exit(self) -> None:
        self.pit_window_approach_tracker.reset()

    def reset(self, reason: str) -> None:
        """Reset state appropriate to a session transition or flashback.

        A new/ended session starts a new race timeline and drops analyzer
        history.  Flashback preserves lap-level strategy by design, while
        still clearing calls and cooldowns tied to the abandoned moment.
        """
        if reason in {"session_started", "session_ended"}:
            self.analyzer.reset()
        self.box_call_tracker.reset()
        self.pit_window_approach_tracker.reset()
        self.last_advisory_at = 0.0
        self._tick_count = 0
