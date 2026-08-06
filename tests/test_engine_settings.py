import core.engine as eng_mod
from core.engine import F1Engine
from core.radio import voice_cast
from core.settings import DEFAULTS


def test_engineer_chatter_enabled_defaults_to_true():
    assert DEFAULTS["engineer_chatter_enabled"] is True


def test_engine_template_mode_without_creds(monkeypatch):
    # нет сохранённых креденшелов -> AIProvider недоступен, llm_engine = Шаблоны
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    assert e.ai.available is False
    assert e.get_state()["llm_engine"] == "Шаблоны"


def test_apply_settings_recomputes_the_voice_cast(monkeypatch):
    """Раньше здесь проверялся ключ `persona_voice` — прямой оверрайд голоса
    персоны. Его больше нет: пользователь выбирает ПЕРСОНАЖА инженера, а голоса
    раздаёт `core/radio/voice_cast.py`, потому что прямой оверрайд позволял
    выставить инженеру голос комментатора и сломать главный инвариант.

    Проверяем новый контракт: смена персонажа пересчитывает каст и уезжает в
    озвучку целиком, с обоими слотами."""
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({"persona": "calm", "engineer_character": "volkov"})
    captured = {}
    monkeypatch.setattr(e.voice, "set_voice_overrides", lambda ov: captured.update(ov))

    e.apply_settings({"engineer_character": "grom"})

    assert set(captured) == {voice_cast.SLOT_ENGINEER, voice_cast.SLOT_SPOTTER}
    # persona=calm занимает marina, значит Гром получает свой первый голос.
    assert captured[voice_cast.SLOT_ENGINEER]["voice"] == "anton"


def test_apply_settings_persona_change_also_recomputes_the_cast(monkeypatch):
    """Голос инженера зависит не только от персонажа: смена персоны
    комментатора может отобрать у инженера его предпочтительный голос."""
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({"persona": "calm", "engineer_character": "volkov"})
    captured = {}
    monkeypatch.setattr(e.voice, "set_voice_overrides", lambda ov: captured.update(ov))

    # tv занимает alexander — первый голос Волкова, он обязан уступить.
    e.apply_settings({"persona": "tv"})

    assert captured[voice_cast.SLOT_ENGINEER]["voice"] == "kirill"


def test_engine_init_applies_saved_mic_device(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({"mic_device": "Saved Mic"})
    assert e._voice_listener._device == "Saved Mic"


def test_apply_settings_mic_device_calls_set_device(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = F1Engine({})
    captured = {}
    monkeypatch.setattr(e._voice_listener, "set_device", lambda d: captured.update(device=d))
    e.apply_settings({"mic_device": "USB Mic"})
    assert captured == {"device": "USB Mic"}
