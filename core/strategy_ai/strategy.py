"""
core/strategy_ai/strategy.py
==============================
StrategyAnalyzer: orchestrates tyre, pit-window and pace logic.
Called once per telemetry snapshot (~1 s). Must complete in <5 ms.
No I/O, no network, no LLM.
"""
from __future__ import annotations

from core.strategy_ai.analysis import (
    FuelTracker,
    LapRecord,
    PaceTracker,
    ers_overtake_recommended,
    ers_save_recommended,
    fuel_save_recommended,
    pace_mode,
)
from core.strategy_ai.models import StrategyAIState, StrategyDecision, StrategyEvent
from core.strategy_ai.opponents import OpponentPitDetector
from core.strategy_ai.pit_window import (
    detect_overcut,
    detect_pit_window,
    detect_undercut,
)
from core.strategy_ai.tyres import tyre_status

MIN_CONFIDENCE_EMIT = 0.55

_ADVICE_RU: dict[str, str] = {
    "cover_opponent":     "Соперник в боксах! Прикрой — пора в пит-стоп.",
    "undercut_available": "Андеркат возможен — готовься к пит-стопу.",
    "overcut_available":  "Оверкат: держись на трассе, соперник в боксах.",
    "pit_window_open":    "Окно пит-стопа открыто.",
    "tyre_degradation":   "Береги шины, темп шин растёт.",
    "push_pace":          "Можно давить — шины держат.",
    "fuel_save":          "Экономь топливо до финиша.",
    "ers_overtake":       "Есть заряд — атакуй, режим овертейк.",
    "ers_save":           "Береги заряд батареи.",
    "hold_pace":          "Держи стабильный темп.",
}


class StrategyAnalyzer:
    """Single-instance, stateful race strategy engine."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Forget every observation from the previous race timeline."""
        self._prev_player_lap: int | None = None
        self._pace_tracker = PaceTracker()
        self._fuel_tracker = FuelTracker()
        self._pit_detector = OpponentPitDetector()
        self._state = StrategyAIState(
            action="hold",
            confidence=0.0,
            reason="hold_pace",
            advice=None,
            mode="HOLD",
            tyre_status="unknown",
            current_event=None,
        )

    def update(self, snapshot: dict) -> StrategyEvent | None:
        """Analyse one telemetry snapshot. Returns StrategyEvent or None.

        snapshot keys (all optional):
            player_lap, total_laps, player_pos,
            gap_front_ms, gap_behind_ms, gap_leader_ms,
            tyre_compound, tyre_age, tyre_wear,
            last_lap_ms, fuel
        """
        player_lap = snapshot.get("player_lap")
        total_laps = snapshot.get("total_laps")
        gap_front = snapshot.get("gap_front_ms")
        gap_behind = snapshot.get("gap_behind_ms")
        compound = snapshot.get("tyre_compound")
        tyre_age = snapshot.get("tyre_age")
        tyre_wear = snapshot.get("tyre_wear")
        last_lap = snapshot.get("last_lap_ms")
        fuel = snapshot.get("fuel")
        ers_percent = snapshot.get("ers_percent")
        ers_deploy_mode = snapshot.get("ers_deploy_mode")

        laps_remaining = None
        if player_lap is not None and total_laps:
            laps_remaining = total_laps - player_lap

        t_status = tyre_status(tyre_age, tyre_wear, compound)

        # Push to pace tracker on new lap
        if (
            player_lap is not None
            and player_lap != self._prev_player_lap
            and last_lap is not None
        ):
            self._pace_tracker.push(LapRecord(
                lap_number=player_lap,
                lap_time_ms=last_lap,
                tyre_compound=compound,
                tyre_age=tyre_age,
            ))
            self._prev_player_lap = player_lap

        # Push fuel reading
        if fuel is not None and player_lap is not None:
            self._fuel_tracker.push(player_lap, fuel)

        # Update opponent pit detector
        self._pit_detector.update(gap_front)

        # --- Decision tree ---
        event: StrategyEvent | None = None
        decision = StrategyDecision(action="hold", confidence=0.4, reason="hold_pace")

        # Priority 1: Cover opponent pit
        cover_ok, cover_conf = self._pit_detector.should_cover(t_status)
        if cover_ok:
            decision = StrategyDecision(
                action="pit",
                confidence=cover_conf,
                reason="cover_opponent",
                data={
                    "gap_front_s": round(gap_front / 1000.0, 2) if gap_front else None,
                    "tyre_age": tyre_age,
                    "tyre_status": t_status,
                },
            )
            event = StrategyEvent(
                type="cover_opponent",
                priority="high",
                confidence=cover_conf,
                decision=decision,
                data=dict(decision.data),
            )

        # Priority 2: Undercut
        if not event:
            ok, conf = detect_undercut(
                gap_front, tyre_age, tyre_wear, laps_remaining, compound)
            if ok:
                decision = StrategyDecision(
                    action="pit",
                    confidence=conf,
                    reason="undercut_available",
                    data={
                        "gap_front_s": round(gap_front / 1000.0, 2) if gap_front else None,
                        "laps_remaining": laps_remaining,
                        "tyre_age": tyre_age,
                        "tyre_wear": tyre_wear,
                    },
                )
                event = StrategyEvent(
                    type="undercut",
                    priority="high" if conf > 0.75 else "medium",
                    confidence=conf,
                    decision=decision,
                    data=dict(decision.data),
                )

        # Priority 3: Pit window
        if not event:
            open_win, conf, laps_to_pit = detect_pit_window(
                tyre_age, tyre_wear, laps_remaining, compound)
            if open_win:
                decision = StrategyDecision(
                    action="pit",
                    confidence=conf,
                    reason="pit_window_open",
                    data={
                        "laps_to_pit": laps_to_pit,
                        "laps_remaining": laps_remaining,
                        "tyre_age": tyre_age,
                        "tyre_wear": tyre_wear,
                    },
                )
                event = StrategyEvent(
                    type="pit_window",
                    priority="high" if conf > 0.8 else "medium",
                    confidence=conf,
                    decision=decision,
                    data=dict(decision.data),
                )

        # Priority 4: Overcut
        if not event:
            ok, conf = detect_overcut(
                gap_front, tyre_age, tyre_wear, laps_remaining, compound)
            if ok:
                decision = StrategyDecision(
                    action="hold",
                    confidence=conf,
                    reason="overcut_available",
                    data={
                        "gap_front_s": round(gap_front / 1000.0, 2) if gap_front else None,
                        "laps_remaining": laps_remaining,
                    },
                )
                event = StrategyEvent(
                    type="overcut",
                    priority="medium",
                    confidence=conf,
                    decision=decision,
                    data=dict(decision.data),
                )

        # Priority 5: Fuel save
        if not event:
            fuel_ok, fuel_conf = fuel_save_recommended(fuel, laps_remaining)
            if fuel_ok:
                decision = StrategyDecision(
                    action="save",
                    confidence=fuel_conf,
                    reason="fuel_save",
                    data={"fuel": fuel, "laps_remaining": laps_remaining},
                )
                event = StrategyEvent(
                    type="fuel_save",
                    priority="medium",
                    confidence=fuel_conf,
                    decision=decision,
                    data=dict(decision.data),
                )

        # Priority 5a: ERS overtake (близкий соперник + есть заряд)
        if not event:
            ok, conf = ers_overtake_recommended(ers_percent, ers_deploy_mode, gap_front)
            if ok:
                decision = StrategyDecision(
                    action="push",
                    confidence=conf,
                    reason="ers_overtake",
                    data={"ers_percent": ers_percent,
                          "gap_front_s": round(gap_front / 1000.0, 2) if gap_front else None},
                )
                event = StrategyEvent(
                    type="ers_overtake",
                    priority="medium",
                    confidence=conf,
                    decision=decision,
                    data=dict(decision.data),
                )

        # Priority 5b: ERS save (низкий заряд)
        if not event:
            ok, conf = ers_save_recommended(ers_percent)
            if ok:
                decision = StrategyDecision(
                    action="save",
                    confidence=conf,
                    reason="ers_save",
                    data={"ers_percent": ers_percent},
                )
                event = StrategyEvent(
                    type="ers_save",
                    priority="low",
                    confidence=conf,
                    decision=decision,
                    data=dict(decision.data),
                )

        # Priority 6: Pace mode
        if not event:
            mode, mode_conf = pace_mode(
                last_lap, self._pace_tracker.prev_lap_ms(), gap_front, gap_behind,
                tyre_age, tyre_wear, compound)
            if mode == "save":
                decision = StrategyDecision(
                    action="save",
                    confidence=mode_conf,
                    reason="tyre_degradation",
                    data={
                        "tyre_age": tyre_age,
                        "tyre_wear": tyre_wear,
                        "laps_remaining": laps_remaining,
                    },
                )
                event = StrategyEvent(
                    type="tyre_save",
                    priority="low",
                    confidence=mode_conf,
                    decision=decision,
                    data=dict(decision.data),
                )
            elif mode == "push":
                decision = StrategyDecision(
                    action="push",
                    confidence=mode_conf,
                    reason="push_pace",
                    data={
                        "gap_front_s": round(gap_front / 1000.0, 2) if gap_front else None,
                    },
                )
                event = StrategyEvent(
                    type="push_pace",
                    priority="low",
                    confidence=mode_conf,
                    decision=decision,
                    data=dict(decision.data),
                )

        # Confidence filter: drop low-confidence events
        if event is not None and event.confidence < MIN_CONFIDENCE_EMIT:
            event = None
            decision = StrategyDecision(action="hold", confidence=0.4, reason="hold_pace")

        # Build advice string
        mode_map = {"pit": "PIT", "push": "PUSH", "save": "SAVE", "hold": "HOLD"}
        advice = _ADVICE_RU.get(decision.reason)
        if event and event.type == "pit_window" and decision.data.get("laps_to_pit") is not None:
            n = int(decision.data["laps_to_pit"])
            if n % 10 == 1 and n % 100 != 11:
                advice = f"Пит через {n} круг."
            elif 2 <= n % 10 <= 4 and n % 100 not in (12, 13, 14):
                advice = f"Пит через {n} круга."
            else:
                advice = f"Пит через {n} кругов."

        self._state = StrategyAIState(
            action=decision.action,
            confidence=decision.confidence,
            reason=decision.reason,
            advice=advice,
            mode=mode_map.get(decision.action, "HOLD"),
            tyre_status=t_status,
            current_event=event,
        )
        return event

    def get_state(self) -> dict:
        """Return serialisable dict for API / engine state."""
        s = self._state
        event_dict = None
        if s.current_event:
            e = s.current_event
            event_dict = {
                "type": e.type,
                "priority": e.priority,
                "confidence": e.confidence,
                "action": e.decision.action,
                "reason": e.decision.reason,
                "data": e.data,
            }
        lr = s.current_event.data.get("laps_remaining") if s.current_event else None
        return {
            "action": s.action,
            "confidence": s.confidence,
            "reason": s.reason,
            "advice": s.advice,
            "mode": s.mode,
            "tyre_status": s.tyre_status,
            "current_event": event_dict,
            "fuel_mode": self._fuel_tracker.fuel_mode(lr),
            "pace_trend": self._pace_tracker.trend(),
        }
