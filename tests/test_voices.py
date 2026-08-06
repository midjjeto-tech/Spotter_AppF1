from yandex_ai import voices


def test_resolve_default_tv():
    # 2026-07-01: tv пересажен с legacy filipp («робот») на премиальный alexander
    assert voices.resolve("tv") == {"voice": "alexander", "emotion": "neutral", "speed": 1.05}


def test_resolve_unknown_persona_falls_back_to_tv():
    assert voices.resolve("nope")["voice"] == "alexander"


def test_no_persona_uses_legacy_robotic_voices_by_default():
    """Регресс-гард жалобы «звучит как робот»: legacy-голоса filipp/ermil/zahar
    не должны возвращаться в дефолты персон (остаются доступными как оверрайды)."""
    for persona, spec in voices.DEFAULT_PERSONA_VOICE.items():
        assert spec["voice"] not in ("filipp", "ermil", "zahar"), persona


def test_resolve_applies_partial_override():
    out = voices.resolve("tv", {"tv": {"voice": "jane"}})
    assert out["voice"] == "jane"
    assert out["emotion"] == "neutral"  # не затёрто


def test_resolve_ignores_unknown_keys():
    out = voices.resolve("tv", {"tv": {"bogus": 1}})
    assert "bogus" not in out


def test_catalog_has_default_voices():
    for spec in voices.DEFAULT_PERSONA_VOICE.values():
        assert spec["voice"] in voices.AVAILABLE_VOICES


def test_default_emotions_supported_by_their_voice():
    """Регресс-гард: дефолтная эмоция персоны ДОЛЖНА поддерживаться её голосом.

    Иначе SpeechKit вернёт 400 'Unknown role' и персона молча уйдёт на Piper
    (баг zahar+evil, 2026-06-24). Проба подтвердила: zahar не умеет evil."""
    for persona, spec in voices.DEFAULT_PERSONA_VOICE.items():
        supported = voices.AVAILABLE_VOICES.get(spec["voice"], [])
        assert spec["emotion"] in supported, (
            f"{persona}: эмоция '{spec['emotion']}' не поддержана голосом "
            f"'{spec['voice']}' (доступно: {supported})")
