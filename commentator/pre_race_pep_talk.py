"""
commentator/pre_race_pep_talk.py
==================================
Пред-гоночная реплика инженера: превращает тир последней гонки карьеры
(core/pre_race_pep_talk.py) в короткую фразу (1 предложение) голосом
инженера ("calm"). LLM-путь через AIProvider; фолбэк — захардкоженная
фраза на тир (приложение всегда что-то выдаёт).
"""
from __future__ import annotations

from core.broadcast.styles import get_style

_TIER_LABEL = {
    "podium": "подиум",
    "points": "очковая зона",
    "struggled": "провальная, за пределами очков или сход",
}

_FALLBACK = {
    "podium": "Прошлая гонка — подиум, отличный темп. Повторим результат.",
    "points": "В прошлой гонке набрал очки. Сегодня попробуем прибавить.",
    "struggled": "Прошлая гонка не задалась. Сегодня — реванш.",
}


def build_prompt(facts: dict, persona: str) -> str:
    tier_label = _TIER_LABEL[facts["tier"]]
    position = facts["position"] if facts["position"] is not None else "не финишировал"
    track = facts.get("track") or "неизвестна"
    return "\n".join([
        get_style(persona),
        "\nТы — гоночный ИНЖЕНЕР игрока, говоришь ПЕРЕД стартом новой гонки "
        "(экран выбора стратегии, до светофора). Обращение на «ты».",
        f"\nФАКТ: в прошлой гонке карьеры (трасса: {track}) игрок финишировал "
        f"на позиции {position} ({tier_label}).",
        "\nНАПИШИ короткую пред-гоночную реплику: ОДНО предложение, русский, "
        "без markdown/кавычек/эмодзи. Если тир 'podium' — похвали темп и "
        "предложи повторить. Если 'points' — отметь, что неплохо, но есть "
        "куда расти. Если 'struggled' — коротко подбодри, без разбора причин.",
    ])


def render_fallback(facts: dict) -> str:
    return _FALLBACK[facts["tier"]]


def generate(facts: dict, ai, persona: str) -> str:
    """LLM, при недоступности — офлайн-фолбэк. persona влияет только на
    ТОН промпта (через get_style) — итоговый ГОЛОС всегда "calm" (инженер),
    выбирается вызывающим кодом (core/engine.py), не этим модулем."""
    if ai is not None and getattr(ai, "available", False):
        text = ai.generate(build_prompt(facts, persona), persona)
        if text and text.strip():
            return text.strip()
    return render_fallback(facts)
