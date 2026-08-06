"""Deletion tests for compatibility surfaces retired after module migration."""

import core.engine as engine_module
from core.engine import F1Engine


def test_engine_exposes_no_retired_compatibility_surface(monkeypatch):
    monkeypatch.setattr(engine_module.yc, "load", lambda: None)
    engine = F1Engine({})

    retired = {
        "state", "state_lock", "event_queue", "_enqueue_event",
        "_update_telemetry", "_iracing_telemetry_loop", "_handle_event_packet",
        "strategy_analyzer", "_box_call_tracker", "_pit_window_approach",
        "_gap_digest", "_rain_advisory", "_track_limits", "_drs_advisory",
        "_position_calls", "_leader_change", "_spotter", "_defense",
        "_recent_event_times", "_last_significant_event_t",
        "_last_ambient_llm_t", "_last_voiced_at",
        "_last_strategy_ai_event_t", "_speak_threshold",
        "_muted_by_threshold", "_is_stale_backlog_event",
        "_is_significant_event", "_note_event_activity", "_activity_count",
        "_ambient_interval", "_in_event_cooldown", "_ambient_llm_throttled",
    }

    assert not [name for name in sorted(retired) if hasattr(engine, name)]


def test_engine_module_does_not_import_raw_packet_parsers():
    retired_parser_names = {
        "parse_header", "parse_participants", "parse_event", "parse_session",
        "parse_lap_data", "parse_player_lap", "parse_player_telemetry",
        "parse_player_status", "parse_player_damage", "parse_car_status_all",
        "parse_car_damage_all", "parse_motion_all", "parse_tyre_sets",
        "parse_final_classification", "parse_session_history",
    }

    assert not [
        name for name in sorted(retired_parser_names)
        if hasattr(engine_module, name)
    ]
