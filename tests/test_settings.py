"""Tests for core/settings — load/save/reset with isolated tmp_path."""
from __future__ import annotations

import json
import pytest


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    import core.settings as s
    monkeypatch.setattr(s, "_PATH", tmp_path / "settings.json")


def test_load_returns_defaults_when_no_file():
    from core.settings import load, DEFAULTS
    assert load() == DEFAULTS


def test_save_and_load_roundtrip():
    from core.settings import load, save, DEFAULTS
    save({"persona": "hype", "radio_fx": False})
    result = load()
    assert result["persona"] == "hype"
    assert result["radio_fx"] is False
    assert result["commentary_enabled"] == DEFAULTS["commentary_enabled"]


def test_reset_restores_defaults():
    from core.settings import save, reset, load, DEFAULTS
    save({"persona": "toxic", "broadcast_mode_enabled": True})
    assert reset() == DEFAULTS
    assert load() == DEFAULTS


def test_load_ignores_unknown_keys():
    import core.settings as s
    s._PATH.write_text(json.dumps({"unknown": 42, "persona": "calm"}), encoding="utf-8")
    from core.settings import load
    result = load()
    assert "unknown" not in result
    assert result["persona"] == "calm"


def test_load_handles_corrupt_json():
    import core.settings as s
    s._PATH.write_text("NOT JSON {{{", encoding="utf-8")
    from core.settings import load, DEFAULTS
    assert load() == DEFAULTS


def test_save_ignores_unknown_keys():
    from core.settings import save, load
    save({"persona": "tv", "ghost_key": "x"})
    assert "ghost_key" not in load()


def test_partial_save_fills_missing_from_defaults():
    from core.settings import save, load, DEFAULTS
    save({"persona": "calm"})
    result = load()
    assert result["persona"] == "calm"
    for k, v in DEFAULTS.items():
        if k != "persona":
            assert result[k] == v


def test_defaults_include_commentary_mode():
    from core.settings import DEFAULTS
    assert DEFAULTS["commentary_mode"] == "live"


def test_save_and_load_roundtrip_commentary_mode():
    from core.settings import load, save
    save({"commentary_mode": "story"})
    assert load()["commentary_mode"] == "story"


def test_defaults_include_mic_device():
    from core.settings import DEFAULTS
    assert DEFAULTS["mic_device"] is None


def test_racefeed_enabled_defaults_to_false():
    from core.settings import DEFAULTS
    assert DEFAULTS["racefeed_enabled"] is False


def test_overlay_theme_defaults_to_broadcast():
    """Обновление не должно перекрашивать HUD пользователю без спроса."""
    from core.settings import DEFAULTS
    assert DEFAULTS["overlay_theme"] == "broadcast"


@pytest.mark.parametrize("theme", ["broadcast", "cockpit", "radio"])
def test_overlay_theme_roundtrip(theme):
    from core.settings import load, save
    save({"overlay_theme": theme})
    assert load()["overlay_theme"] == theme


def test_unknown_overlay_theme_falls_back_to_default():
    """Восемь окон читают ключ независимо: неизвестная тема должна откатывать
    HUD на привычный вид, а не оставлять его без стилей."""
    import core.settings as s
    s._PATH.write_text(json.dumps({"overlay_theme": "ludicrous"}), encoding="utf-8")
    from core.settings import load
    assert load()["overlay_theme"] == "broadcast"
