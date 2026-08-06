"""
commentator/channel_router.py
==============================
Routes an event to the correct output channel.

Channels:
  CHANNEL_COMMENTARY — full spoken narration (LLM or template)
  CHANNEL_RADIO      — short cockpit dialogue (commentator/radio.py templates)
  CHANNEL_OVERLAY    — silent feed entry only (no voice)

Routing rules:
  - Major lifecycle events (SSTA/CHQF/RCWN/RTMT/PENA/OVTK/FTLP,
    SAFETY_CAR_DEPLOYED/ENDING/CLEAR/RDFL) → commentary
  - Cockpit telemetry events (DRSE/DRSD) in race → radio; in practice → overlay
  - Strategy advice (STRAT_*) → radio
  - Race AI tactical (ATTACK/BATTLE/TYRE_WARN) → radio for TYRE_WARN; commentary for ATTACK/BATTLE
  - AMBIENT/FINAL_LAP → commentary
  - RaceFeed-only synthetic events (CAREER_RECAP) → overlay (silent), regardless of session type
  - Everything else → commentary (safe default)
"""
from __future__ import annotations

CHANNEL_COMMENTARY = "commentary"
CHANNEL_RADIO      = "radio"
CHANNEL_OVERLAY    = "overlay"

# Events that always route to commentary regardless of session type
_ALWAYS_COMMENTARY: frozenset[str] = frozenset({
    "SSTA", "CHQF", "RCWN", "RTMT", "PENA",
    "OVTK", "FTLP", "AMBIENT", "FINAL_LAP",
    "ATTACK", "BATTLE",
    # Phase B (Safety Car/VSC/красный флаг) — same tier as PENA/RTMT.
    "SAFETY_CAR_DEPLOYED", "SAFETY_CAR_ENDING", "SAFETY_CAR_CLEAR", "RDFL",
})

# Events routed to radio in a race context
_RADIO_IN_RACE: frozenset[str] = frozenset({
    "DRSE", "DRSD",
    "STRAT_PIT", "STRAT_UNDERCUT", "STRAT_OVERCUT",
    "STRAT_SAVE", "STRAT_PUSH", "STRAT_FUEL",
    "TYRE_WARN",
})

# Events silenced to overlay-only in practice (no voice at all)
_PRACTICE_OVERLAY: frozenset[str] = frozenset({
    "DRSE", "DRSD", "SPTP", "STLG", "FLBK", "TMPT",
})

# Events that are RaceFeed-only and must never be voiced, in any session type
# (unlike _PRACTICE_OVERLAY, which only silences in practice — these are
# silent everywhere, since they exist purely to feed core/racefeed/, not to
# be spoken; see core/engine.py::_publish_career_recap's docstring).
_ALWAYS_OVERLAY: frozenset[str] = frozenset({
    "CAREER_RECAP",
    "RACEFEED_DOTD",
    "POST_RACE_INTERVIEW",
    "RACE_RECAP",
})


def route_event(event: dict, session_type: str = "race") -> str:
    """Return the output channel for this event and session type.

    Parameters
    ----------
    event : dict
        Event dict (must have "event_code").
    session_type : str
        "race", "qualifying", "practice", or "unknown".

    Returns
    -------
    str
        One of CHANNEL_COMMENTARY, CHANNEL_RADIO, CHANNEL_OVERLAY.
    """
    code: str = event.get("event_code", "")

    if code in _ALWAYS_COMMENTARY:
        return CHANNEL_COMMENTARY

    if session_type == "practice" and code in _PRACTICE_OVERLAY:
        return CHANNEL_OVERLAY

    if code in _RADIO_IN_RACE:
        return CHANNEL_RADIO

    if code in _ALWAYS_OVERLAY:
        return CHANNEL_OVERLAY

    return CHANNEL_COMMENTARY
