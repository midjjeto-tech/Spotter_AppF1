"""Громкость ролей: у инженера и споттера свои ключи, не персона комментатора.

Раньше инженер озвучивался персоной "calm", поэтому его громкостью управлял
ключ volume_calm. После развода каналов по ролям (core/radio/voice_cast.py)
этот ключ управляет только КОММЕНТАТОРОМ, и роли остались бы на глобальной
громкости — то есть настройка пользователя молча перестала бы действовать."""
import core.engine as eng_mod
from core.engine import F1Engine
from core.radio import voice_cast
from core.settings import DEFAULTS


def test_role_volume_keys_exist_in_defaults():
    assert "volume_engineer" in DEFAULTS
    assert "volume_spotter" in DEFAULTS


def test_engine_forwards_role_volumes_to_voice(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    captured = {}
    monkeypatch.setattr(e.voice, "set_volume",
                        lambda g, per: captured.update({"global": g, "per": per}))

    e.apply_settings({"volume": 80, "volume_engineer": 47, "volume_spotter": 90})

    assert captured["per"][voice_cast.SLOT_ENGINEER] == 47
    assert captured["per"][voice_cast.SLOT_SPOTTER] == 90


def test_effective_volume_uses_the_role_key_not_the_global(monkeypatch):
    """Регрессия, ради которой всё это: без ключа роли _effective_volume молча
    возвращает глобальную громкость, и ползунок инженера перестаёт работать."""
    from voice.tts import Voice

    v = Voice.__new__(Voice)
    v._global_vol = 80
    v._current_persona = "tv"
    v._persona_vol = {"tv": 80, voice_cast.SLOT_ENGINEER: 47}

    assert v._effective_volume(voice_cast.SLOT_ENGINEER) == 0.47
    assert v._effective_volume("tv") == 0.80


def test_saved_calm_volume_migrates_to_the_engineer(tmp_path, monkeypatch):
    """Пользователь настраивал громкость инженера ползунком, писавшим в
    volume_calm. Молча сбросить её на дефолт значит испортить настройку, о
    которой он не узнает — переносим один раз при загрузке."""
    import json

    import core.settings as s

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"volume_calm": 47}), encoding="utf-8")
    monkeypatch.setattr(s, "_PATH", path)

    loaded = s.load()

    assert loaded["volume_engineer"] == 47


def test_explicit_engineer_volume_wins_over_migration(tmp_path, monkeypatch):
    """Перенос — только для настроек, где ключа роли ещё нет. Уже заданное
    значение переписывать нельзя."""
    import json

    import core.settings as s

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"volume_calm": 47, "volume_engineer": 90}),
                    encoding="utf-8")
    monkeypatch.setattr(s, "_PATH", path)

    assert s.load()["volume_engineer"] == 90
