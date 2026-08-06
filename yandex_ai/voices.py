"""Каталог голосов Yandex SpeechKit + резолвер персона -> (voice, emotion, speed).

Маппинг конфигурируемый: дефолты ниже переопределяются пользовательскими оверрайдами
(приходят через настройки UI). Матрица emotion ниже — ориентировочная, точная поддержка
подтверждается мелким TTS-пробом на этапе интеграции.
"""
from __future__ import annotations

# voice -> поддерживаемые эмоции (роли) SpeechKit v1.
# ВАЖНО: emotion должен реально поддерживаться голосом, иначе SpeechKit вернёт
# 400 "Unknown role '<emotion>' for '<voice>' voice" и персона МОЛЧА уйдёт на Piper.
# Поддержка ниже подтверждена живым TTS-пробом (2026-06-24):
#   zahar  — evil НЕ поддерживается (только neutral/good);
#   jane/omazh — evil поддерживается (женские «злые» голоса);
#   filipp — emotion игнорирует (всегда нейтрально).
#: Голоса, качество которых признано приемлемым для эфира. Каст ролей
#: (core/radio/voice_cast.py) обязан укладываться в этот набор — на это стоит
#: тест. Остальные из AVAILABLE_VOICES ниже остаются в каталоге (их всё ещё
#: можно назначить вручную и они валидны для SpeechKit), но помечены как
#: непремиальные: легаси-рендер звучит заметно «роботнее», особенно под
#: radio_fx, и именно из-за этого в проекте однажды уже меняли дефолты.
#: Расширять набор только после живого прослушивания, не по документации.
PREMIUM_VOICES: frozenset[str] = frozenset({
    "alexander", "anton", "marina", "kirill",
})

AVAILABLE_VOICES: dict[str, list[str]] = {
    "filipp":    ["neutral"],
    "ermil":     ["neutral", "good"],
    "alena":     ["neutral", "good"],
    "zahar":     ["neutral", "good"],          # evil НЕ поддерживается (проба → 400)
    "jane":      ["neutral", "good", "evil"],
    "omazh":     ["neutral", "evil"],
    "madirus":   ["neutral"],
    "dasha":     ["neutral", "good", "friendly"],
    "julia":     ["neutral"],
    "lera":      ["neutral"],
    "marina":    ["neutral", "whisper"],
    "alexander": ["neutral"],
    "kirill":    ["neutral"],
    "anton":     ["neutral"],
}

# Дефолты — ПРЕМИАЛЬНЫЕ нейроголоса (alexander/anton/marina/kirill): легаси
# filipp/ermil/zahar звучали заметно «роботнее», особенно под radio_fx. Живость
# несут сами нейроголоса + v3-рендер (см. yandex_tts_version в core/settings.py);
# legacy-эмоции (good/evil) им не нужны и не поддерживаются — только neutral.
# Токсичность/хайп несёт ТЕКСТ LLM, не тон TTS. Старая история: zahar+evil давал
# 400 → молчаливый фолбэк на Piper; «злые» legacy-роли остались у omazh/jane.
DEFAULT_PERSONA_VOICE: dict[str, dict] = {
    "tv":    {"voice": "alexander", "emotion": "neutral", "speed": 1.05},
    "hype":  {"voice": "anton",     "emotion": "neutral", "speed": 1.15},
    "calm":  {"voice": "marina",    "emotion": "neutral", "speed": 0.95},
    "toxic": {"voice": "kirill",    "emotion": "neutral", "speed": 1.05},
    # Слоты РОЛЕЙ, а не персоны комментатора. Живут в одном словаре, потому что
    # вся цепочка синтеза (resolve -> _voice_key -> кэш -> speech.py) уже
    # принимает "персону" как строковый ключ: роль подставляется туда же и
    # получает ключ кэша, зависящий от РЕАЛЬНОГО голоса, бесплатно.
    # Значения ниже — только дефолт до первого применения оверрайдов из
    # core/radio/voice_cast.py (он же гарантирует несовпадение с комментатором).
    "engineer": {"voice": "alexander", "emotion": "neutral", "speed": 1.0},
    "spotter":  {"voice": "kirill",    "emotion": "neutral", "speed": 1.1},
}

# voice id -> человекочитаемое имя для плашки спикера в UI («Яндекс: Филипп»).
DISPLAY_NAMES: dict[str, str] = {
    "filipp": "Филипп", "ermil": "Эрмил", "alena": "Алёна", "zahar": "Захар",
    "jane": "Джейн", "omazh": "Омаж", "madirus": "Мадирус", "dasha": "Даша",
    "julia": "Юлия", "lera": "Лера", "marina": "Марина", "alexander": "Александр",
    "kirill": "Кирилл", "anton": "Антон",
}

_ALLOWED_KEYS = ("voice", "emotion", "speed")


def display_name(voice_id: str) -> str:
    """Имя голоса для UI. Неизвестный id -> сам id с заглавной буквы."""
    return DISPLAY_NAMES.get(voice_id, voice_id.capitalize() if voice_id else "—")


def resolve(persona: str, overrides: dict | None = None) -> dict:
    """Вернуть {voice, emotion, speed} для персоны с учётом частичных оверрайдов.

    overrides — dict вида {"tv": {"voice": "jane"}}. Неизвестная персона -> дефолт 'tv'.
    Неизвестные ключи в оверрайде игнорируются.
    """
    base = dict(DEFAULT_PERSONA_VOICE.get(persona, DEFAULT_PERSONA_VOICE["tv"]))
    if overrides and isinstance(overrides.get(persona), dict):
        base.update({k: v for k, v in overrides[persona].items() if k in _ALLOWED_KEYS})
    return base
