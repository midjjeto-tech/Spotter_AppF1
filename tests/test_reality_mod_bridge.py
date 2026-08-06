import json

from core import reality_mod_bridge as bridge


def test_auto_mode_enabled_is_opt_in(tmp_path):
    assert bridge.auto_mode_enabled(tmp_path) is False
    (tmp_path / "auto_state.json").write_text(
        json.dumps({"enabled": True}), encoding="utf-8"
    )
    assert bridge.auto_mode_enabled(tmp_path) is True


def test_result_payload_preserves_full_classification():
    grid = [{"vehicle_idx": 4, "position": 2, "team": "Ferrari"}]
    payload = bridge.build_result_payload(grid, track_id=10, game_year=2026)
    assert payload["schema_version"] == 1
    assert payload["track_id"] == 10
    assert payload["game_year"] == 2026
    assert payload["classification"] == grid
