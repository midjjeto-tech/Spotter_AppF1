"""
core/race_ai/analyzer.py
=========================
RaceAnalyzer: orchestrates threat, battle, intensity, and decision logic.
Called once per telemetry snapshot (~1 s). Must complete in <5 ms.
No I/O, no network, no LLM.
"""
from __future__ import annotations

from core.race_ai.models import RaceEvent, RaceAIState
from core.race_ai.threat import detect_threat
from core.race_ai.intensity import calculate_intensity, get_mode
from core.race_ai.battles import BattleDetector
from core.race_ai.decisions import make_decision

TYRE_AGE_WARN = 30    # laps
TYRE_WEAR_WARN = 60.0 # percent


class RaceAnalyzer:
    """Single-instance, stateful race intelligence engine."""

    def __init__(self):
        self.battle_detector = BattleDetector()
        self._state = RaceAIState(
            intensity=0, mode="CALM", current_event=None,
            threat=None, advice=None)
        self._prev_gap_behind: int | None = None
        # Реальное состояние battle.active — RaceEvent-возврат update() может
        # МАСКИРОВАТЬ battle.active тем же тиком, если is_threat тоже сработал
        # (if/elif ниже отдаёт приоритет "attack") — внешним потребителям
        # (defense-tracker) нужен настоящий сигнал, не то, что "победило" в
        # выборе типа события. См. docs/superpowers/plans/2026-07-20-defense-
        # event-damage-phrase-variety.md.
        self.last_battle_active: bool = False

    def reset_transient(self) -> None:
        """Сбросить транзитное состояние близости/угрозы (флэшбек/новая сессия).

        Чистит историю боёв и тренд отрыва, чтобы после перемотки не тянулся
        ложный «догоняет/борьба» из до-флэшбекового момента. Лап-уровневую
        статистику (она тут не хранится) не трогаем."""
        self.battle_detector = BattleDetector()
        self._prev_gap_behind = None
        self.last_battle_active = False
        self._state = RaceAIState(
            intensity=0, mode="CALM", current_event=None,
            threat=None, advice=None)

    def update(self, snapshot: dict) -> RaceEvent | None:
        """Analyse one telemetry snapshot. Returns RaceEvent or None.

        snapshot keys (all optional — missing values handled gracefully):
            gap_behind_ms, gap_front_ms, drs_active, player_pos, player_lap,
            total_laps, driver_behind, tyre_age, tyre_wear
        """
        gap_behind    = snapshot.get("gap_behind_ms")
        gap_front     = snapshot.get("gap_front_ms")
        drs_active    = bool(snapshot.get("drs_active", False))
        player_lap    = snapshot.get("player_lap")
        total_laps    = snapshot.get("total_laps")
        driver_behind = snapshot.get("driver_behind") or "оппонент"
        tyre_age      = snapshot.get("tyre_age")
        tyre_wear     = snapshot.get("tyre_wear")
        session_type  = snapshot.get("session_type")

        gap_closing = (
            self._prev_gap_behind is not None
            and gap_behind is not None
            and gap_behind < self._prev_gap_behind)
        self._prev_gap_behind = gap_behind

        # "Laps remaining" only makes sense in a RACE. Practice/qualifying report a
        # total_laps too (e.g. a 20-lap practice programme), but reaching its end is
        # NOT a final lap — so we suppress the whole final-lap concept (event, the
        # intensity boost, and the threat boost) off-race by zeroing laps_remaining.
        # session_type is None in unit snapshots → treat as race-permissive.
        laps_remaining = None
        if player_lap and total_laps and session_type in (None, "race"):
            laps_remaining = total_laps - player_lap

        is_threat, confidence = detect_threat(
            gap_behind, drs_active, gap_closing, laps_remaining)

        battle = self.battle_detector.update(gap_behind, driver_behind, "player")
        self.last_battle_active = battle.active

        intensity = calculate_intensity(
            gap_behind, drs_active, battle.active, laps_remaining, total_laps)
        mode = get_mode(intensity)

        event: RaceEvent | None = None

        if is_threat:
            event = RaceEvent(
                type="attack",
                priority="high" if confidence > 0.7 else "medium",
                confidence=confidence,
                driver=driver_behind,
                target="player",
                data={
                    "gap": round(gap_behind / 1000.0, 2) if gap_behind else None,
                    "drs": drs_active,
                    "closing": gap_closing,
                    "intensity": intensity,
                },
            )
        elif battle.active:
            event = RaceEvent(
                type="battle",
                priority="medium",
                confidence=0.7,
                driver=driver_behind,
                target="player",
                data={"intensity": battle.intensity,
                      "gap": round(gap_behind / 1000.0, 2) if gap_behind else None},
            )
        elif laps_remaining is not None and laps_remaining <= 3:
            event = RaceEvent(
                type="final_lap",
                priority="medium",
                confidence=1.0,
                driver="player",
                target="",
                data={"laps_remaining": laps_remaining},
            )
        elif (tyre_age is not None and tyre_age > TYRE_AGE_WARN
              and tyre_wear is not None and tyre_wear > TYRE_WEAR_WARN):
            event = RaceEvent(
                type="tyre_warning",
                priority="medium",
                confidence=0.85,
                driver="player",
                target="",
                data={"age": tyre_age, "wear": tyre_wear},
            )

        threat_text: str | None = None
        advice_text: str | None = None

        if event:
            decision = make_decision(event, gap_front, gap_closing)
            advice_text = decision.get("advice")

        if is_threat and gap_behind:
            threat_text = f"{driver_behind} атакует ({gap_behind / 1000:.1f}с)"

        self._state = RaceAIState(
            intensity=intensity,
            mode=mode,
            current_event=event,
            threat=threat_text,
            advice=advice_text,
        )
        return event

    def get_state(self) -> dict:
        """Return serialisable dict for API / engine state."""
        s = self._state
        event_dict = None
        if s.current_event:
            e = s.current_event
            event_dict = {
                "type": e.type, "priority": e.priority,
                "confidence": e.confidence, "driver": e.driver,
                "target": e.target, "data": e.data,
            }
        return {
            "intensity": s.intensity,
            "mode": s.mode,
            "current_event": event_dict,
            "threat": s.threat,
            "advice": s.advice,
        }
