"""tests/test_volume.py — volume control: scaling, per-persona override, clamping."""
import pytest
from unittest.mock import patch, MagicMock


def _make_voice():
    """Instantiate Voice with all I/O patched out."""
    from voice.tts import Voice
    with (
        patch("voice.tts.TTSQueue"),
        patch("voice.tts.PiperVoiceEngine"),
        patch("voice.tts.TTSCache"),
        patch("threading.Thread"),
    ):
        v = Voice.__new__(Voice)
        v._global_vol = 80
        v._persona_vol = {}
        v._current_persona = "tv"
        return v


def test_global_volume_scale():
    v = _make_voice()
    v.set_volume(50, {})
    assert v._effective_volume() == pytest.approx(0.5)


def test_per_persona_overrides_global():
    v = _make_voice()
    v.set_volume(80, {"hype": 60})
    v._current_persona = "hype"
    assert v._effective_volume() == pytest.approx(0.6)


def test_unknown_persona_falls_back_to_global():
    v = _make_voice()
    v.set_volume(70, {"hype": 90})
    v._current_persona = "calm"
    assert v._effective_volume() == pytest.approx(0.7)


def test_volume_100_no_change():
    v = _make_voice()
    v.set_volume(100, {})
    assert v._effective_volume() == pytest.approx(1.0)


def test_volume_0_silence():
    v = _make_voice()
    v.set_volume(0, {})
    assert v._effective_volume() == pytest.approx(0.0)


def test_volume_clamps_high():
    v = _make_voice()
    v.set_volume(150, {})
    assert v._global_vol == 100


def test_volume_clamps_low():
    v = _make_voice()
    v.set_volume(-20, {"tv": -10})
    assert v._global_vol == 0
    assert v._persona_vol["tv"] == 0


def test_settings_defaults_have_volume_keys():
    from core.settings import DEFAULTS
    assert "volume" in DEFAULTS
    for p in ("tv", "hype", "calm", "toxic"):
        assert f"volume_{p}" in DEFAULTS
    assert 0 <= DEFAULTS["volume"] <= 100
    for p in ("tv", "hype", "calm", "toxic"):
        assert 0 <= DEFAULTS[f"volume_{p}"] <= 100


def test_settings_load_preserves_volume():
    import json, tempfile, pathlib
    import core.settings as s

    tmp = pathlib.Path(tempfile.mktemp(suffix=".json"))
    tmp.write_text(json.dumps({"volume": 55, "volume_hype": 95}), encoding="utf-8")
    orig_path, orig_defaults = s._PATH, s.DEFAULTS
    s._PATH = tmp
    result = s.load()
    s._PATH = orig_path
    tmp.unlink(missing_ok=True)

    assert result["volume"] == 55
    assert result["volume_hype"] == 95
    assert result["volume_tv"] == orig_defaults["volume_tv"]
