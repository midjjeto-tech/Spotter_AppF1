"""
commentator/story.py
====================
Post-Race Story Mode: превращает факт-блок гонки (core/race_story.py) в короткий
итог-репортаж (3–5 предложений) голосом текущей персоны.

LLM-путь через AIProvider; при недоступном LLM — детерминированный офлайн-фолбэк
из тех же фактов (приложение всегда что-то выдаёт). Имена склоняются через
core/ru_names.py: в промпт кладём шпаргалку, чтобы модель не коверкала фамилии.
"""
from __future__ import annotations

from core.broadcast.styles import get_style
from core.ru_names import glossary

_SESSION_LABEL = {"race": "гонки", "qualifying": "квалификации", "practice": "практики"}
_SESSION_DONE = {"race": "Гонка завершена.", "qualifying": "Квалификация завершена.",
                 "practice": "Практика завершена."}


def _fmt_lap(ms: int | None) -> str:
    if not ms or ms <= 0:
        return ""
    total = ms / 1000.0
    m = int(total // 60)
    s = total - m * 60
    return f"{m}:{s:06.3f}" if m else f"{s:.1f}с"


def _names_in_facts(facts: dict) -> list[str]:
    names: list[str] = []
    for o in facts.get("overtakes", []):
        if o.get("target"):
            names.append(o["target"])
    for i in facts.get("incidents", []):
        if i.get("driver"):
            names.append(i["driver"])
    if facts.get("leader"):
        names.append(facts["leader"])
    return names


def _format_facts(facts: dict) -> str:
    L: list[str] = []
    sp, fp = facts.get("start_position"), facts.get("final_position")
    if sp:
        L.append(f"- Старт: позиция {sp}")
    if fp:
        L.append(f"- Финиш: позиция {fp}")
    g = facts.get("positions_gained")
    if g:
        L.append(f"- {'Отыграно' if g > 0 else 'Потеряно'} позиций: {abs(g)}")
    if facts.get("total_laps"):
        L.append(f"- Всего кругов: {facts['total_laps']}")
    lap = _fmt_lap(facts.get("best_lap_ms"))
    if lap:
        bl = facts.get("best_lap_number")
        L.append(f"- Лучший круг: {lap}" + (f" (круг {bl})" if bl else ""))
    for o in facts.get("overtakes", []):
        L.append(f"- Обгон: прошёл {o['target']}"
                 + (f" на круге {o['lap']}" if o.get("lap") else ""))
    for i in facts.get("incidents", []):
        label = "штраф" if i["code"] == "PENA" else "сход"
        L.append(f"- {label.capitalize()}"
                 + (f" на круге {i['lap']}" if i.get("lap") else ""))
    if facts.get("fastest_lap_flag"):
        L.append("- Был быстрейший круг гонки")
    if facts.get("weak_sector"):
        L.append(f"- Слабый сектор: S{facts['weak_sector']}")
    if facts.get("weak_sector_vs_f1"):
        L.append(f"- Слабее эталона F1 в секторе: S{facts['weak_sector_vs_f1']}")
    vlv = facts.get("vs_last_visit")
    if vlv:
        date = (vlv.get("last_visit_date") or "").split("T")[0]
        dt_ms = vlv["laptime_delta_ms"]
        pd = vlv["position_delta"]
        speed = (f"быстрее на {abs(dt_ms) / 1000.0:.1f}с" if dt_ms < 0
                else f"медленнее на {abs(dt_ms) / 1000.0:.1f}с")
        if pd > 0:
            pos = f"финиш выше на {pd}"
        elif pd < 0:
            pos = f"финиш ниже на {abs(pd)}"
        else:
            pos = "та же позиция на финише"
        suffix = f" ({date})" if date else ""
        L.append(f"- С прошлого визита сюда{suffix}: {speed}, {pos}")
    tm = facts.get("teammate_result")
    if tm:
        L.append(f"- Напарник по команде: {tm}")
    cs = facts.get("career_stats")
    if cs:
        L.append(f"- Карьера: гонка №{cs['total_races']}, побед {cs['wins']}, "
                 f"подиумов {cs['podiums']}, средняя позиция {cs['avg_position']:.1f}")
    c = facts.get("consistency")
    if c is not None:
        L.append(f"- Консистентность: {int(c * 100)}%")
    return "\n".join(L) if L else "- мало данных"


def build_prompt(facts: dict, persona: str, gp_context: str | None = None,
                  session_type: str = "race") -> str:
    """Структурный fact-only промпт для итог-репортажа."""
    label = _SESSION_LABEL.get(session_type, _SESSION_LABEL["race"])
    parts = [
        get_style(persona),
        f"\nТы подводишь ИТОГ уже ЗАВЕРШЁННОЙ {label} игрока — как спортивный "
        "журналист. Ретроспектива, прошедшее время.",
        f"\nФАКТЫ {label.upper()} (опирайся ТОЛЬКО на них, ничего не выдумывай):\n"
        + _format_facts(facts),
    ]
    if gp_context:
        parts.append("\nСверка с реальным Гран-при:\n" + gp_context)
    gloss = glossary(_names_in_facts(facts))
    if gloss:
        parts.append("\nСКЛОНЕНИЕ ИМЁН (бери фамилии ТОЛЬКО в этих формах):\n" + gloss)
    parts.append(
        "\nНАПИШИ итог: 3–5 предложений, ОДИН абзац, русский, без markdown, "
        "кавычек и эмодзи. Числа — словами. Если фактов мало — короткий честный итог."
    )
    return "\n".join(parts)


def render_fallback(facts: dict, persona: str = "tv", session_type: str = "race") -> str:
    """Детерминированный офлайн-итог из фактов (без LLM)."""
    parts: list[str] = []
    sp, fp = facts.get("start_position"), facts.get("final_position")
    if fp and sp:
        parts.append(f"Финиш на позиции {fp} со старта {sp}.")
    elif fp:
        parts.append(f"Финиш на позиции {fp}.")
    lap = _fmt_lap(facts.get("best_lap_ms"))
    if lap:
        bl = facts.get("best_lap_number")
        parts.append(f"Лучший круг — {lap}" + (f" на {bl}-м." if bl else "."))
    n = len(facts.get("overtakes", []))
    if n:
        parts.append(f"Обгонов: {n}.")
    if facts.get("weak_sector"):
        parts.append(f"Слабый сектор — S{facts['weak_sector']}.")
    return " ".join(parts) or _SESSION_DONE.get(session_type, _SESSION_DONE["race"])


def generate_with_source(facts: dict, ai, persona: str,
                         gp_context: str | None = None,
                         session_type: str = "race") -> tuple[str, str]:
    """История плюс её происхождение: "llm" или "fallback". Тот же приём, что
    у `core/racefeed/generators.py::render_with_source` — тексты выглядят
    одинаково, и без этой пометки шаблонный итог невозможно отличить от
    написанного моделью (экран «Разбор» показывает её пользователю)."""
    if ai is not None and getattr(ai, "available", False):
        text = ai.generate(build_prompt(facts, persona, gp_context, session_type), persona)
        if text and text.strip():
            return text.strip(), "llm"
    return render_fallback(facts, persona, session_type), "fallback"


def generate(facts: dict, ai, persona: str, gp_context: str | None = None,
             session_type: str = "race") -> str:
    """Сгенерировать историю: LLM, при недоступности — офлайн-фолбэк."""
    return generate_with_source(facts, ai, persona, gp_context, session_type)[0]
