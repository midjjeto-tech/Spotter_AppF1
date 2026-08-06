"""
core/session_guard.py
======================
Session-aware per-event cooldown and spam prevention.

Practice sessions use strict cooldowns and suppress race-only events.
Qualifying uses moderate sector-driven cooldowns.
Race uses the most permissive cooldowns.
Critical events always bypass all cooldowns.
"""
from __future__ import annotations

import time


class SessionGuard:
    """Per-session and per-event spam prevention.

    Call set_session_type() whenever the session packet arrives.
    Call should_emit(event) before queuing commentary — returns False to suppress.
    """

    # Events that only make sense in a race context — silence in practice
    _PRACTICE_SUPPRESS: frozenset[str] = frozenset({
        "STRAT_PUSH", "STRAT_SAVE", "STRAT_FUEL", "STRAT_PIT",
        "STRAT_UNDERCUT", "STRAT_OVERCUT",
        "STRAT_ERS_SAVE", "STRAT_ERS_OVERTAKE",
        "FINAL_LAP",
    })

    # Per-event cooldowns (seconds) by session type.
    # "default" applies to any code not explicitly listed.
    _COOLDOWNS: dict[str, dict[str, float]] = {
        "practice": {
            "FTLP": 60.0,
            "OVTK": 25.0,
            "DRSE": 45.0,
            "DRSD": 45.0,
            "TMPT": 90.0,
            "SPTP": 90.0,
            "STLG": 300.0,
            "ATTACK": 60.0,
            "BATTLE": 40.0,
            "AMBIENT": 60.0,
            "PIT_CALL_NOTICE": 120.0,
            "default": 20.0,
        },
        "qualifying": {
            "FTLP": 12.0,
            "OVTK": 10.0,
            "DRSE": 20.0,
            "DRSD": 20.0,
            "TMPT": 30.0,
            "ATTACK": 20.0,
            "BATTLE": 15.0,
            "PIT_CALL_NOTICE": 60.0,
            "default": 10.0,
        },
        "race": {
            "DRSE": 8.0,
            "DRSD": 8.0,
            "SPTP": 30.0,
            "TMPT": 30.0,
            # Затяжная борьба/погоня: коротких кодов недостаточно для нарратива —
            # одна и та же ситуация повторялась каждые 4 с (см. core/situation_dedup).
            "OVTK": 12.0,
            "ATTACK": 12.0,
            "BATTLE": 15.0,
            "ATTACK_ZONE": 15.0,
            # Дребезг уверенности вокруг DECISIVE_CONFIDENCE (core/strategy_ai/
            # box_call.py) может сбросить и заново взвести BoxCallTracker на
            # tier 1 несколько раз за одно и то же решительное окно — команда
            # инженера (critical) обходит cooldown осознанно (см. should_emit),
            # но реплика комментатора рядом с ней не должна повторяться так же
            # часто, как дефолтный cooldown (4с) позволил бы.
            "PIT_CALL_NOTICE": 60.0,
            "default": 4.0,
        },
        "unknown": {
            "default": 4.0,
        },
    }

    def __init__(self) -> None:
        self._session_type: str = "unknown"
        self._last: dict[str, float] = {}

    def set_session_type(self, session_type: str) -> None:
        """Update session type; resets all per-event cooldown state."""
        if session_type != self._session_type:
            self._session_type = session_type
            self._last.clear()

    def should_emit(self, event: dict) -> bool:
        """Return True if this event should be sent to commentary.

        False = suppress (cooldown active or race-only event in practice).
        Critical events always bypass all cooldowns.
        """
        if event.get("priority") == "critical":
            return True

        code: str = event.get("event_code", "")
        st = self._session_type

        if st == "practice" and code in self._PRACTICE_SUPPRESS:
            return False

        cooldowns = self._COOLDOWNS.get(st, self._COOLDOWNS["unknown"])
        cooldown = cooldowns.get(code, cooldowns["default"])

        now = time.time()
        last = self._last.get(code, 0.0)
        if now - last < cooldown:
            return False

        self._last[code] = now
        return True
