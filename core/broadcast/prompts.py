"""core/broadcast/prompts.py — structured fact-only LLM prompt builder."""
from __future__ import annotations

from core.broadcast.styles import get_style

# Human-readable labels for race_ai event types
_TYPE_LABELS: dict[str, str] = {
    "attack":       "атака соперника",
    "battle":       "борьба позиций",
    "tyre_warning": "предупреждение о шинах",
    "final_lap":    "финальные круги",
}

_CORNER_TYPE_RU: dict[str, str] = {
    "hairpin": "шпилька",
    "slow":    "медленный",
    "medium":  "средний",
    "fast":    "быстрый",
    "chicane": "шикана",
}
_PHASE_RU: dict[str, str] = {
    "braking": "торможение",
    "entry":   "вход",
    "apex":    "апекс",
    "exit":    "выход",
}
_ADVICE_RU: dict[str, str] = {
    "inside":       "закрыть изнутри",
    "cover_inside": "закрыть изнутри",
    "hold_line":    "держать линию",
    "outside":      "держать снаружи",
    "late_brake":   "поздний тормоз",
}


def _format_track_facts(track: dict) -> list[str]:
    lines: list[str] = []
    sector = track.get("sector")
    if sector:
        lines.append(f"- Сектор: {sector}")
    corner = track.get("corner")
    corner_type = track.get("corner_type")
    if corner:
        type_label = _CORNER_TYPE_RU.get(corner_type or "", "")
        lines.append(f"- Поворот: {corner}" + (f" ({type_label})" if type_label else ""))
    phase = track.get("phase", "straight")
    phase_label = _PHASE_RU.get(phase, "")
    if phase_label:
        lines.append(f"- Фаза: {phase_label}")
    defense = track.get("defense_advice", "none")
    advice_label = _ADVICE_RU.get(defense, "")
    if advice_label:
        lines.append(f"- Линия защиты: {advice_label}")
    return lines


def _format_facts(event_dict: dict) -> str:
    lines: list[str] = []

    driver = event_dict.get("driver", "")
    if driver and driver.lower() not in {"player", "оппонент", ""}:
        lines.append(f"- Пилот: {driver}")

    event_type = event_dict.get("race_ai_type", "")
    label = _TYPE_LABELS.get(event_type, event_type)
    if label:
        lines.append(f"- Событие: {label}")

    data: dict = event_dict.get("race_ai_data") or {}
    gap = data.get("gap")
    if gap is not None:
        lines.append(f"- Разрыв: {gap:.1f} с")

    drs = data.get("drs")
    if drs is True:
        lines.append("- DRS: активен")
    elif drs is False:
        lines.append("- DRS: неактивен")

    closing = data.get("closing")
    if closing is True:
        lines.append("- Разрыв сокращается")

    confidence = data.get("confidence")
    if confidence is not None:
        pct = int(confidence * 100)
        lines.append(f"- Уверенность: {pct}%")

    tyre_age = data.get("age")
    tyre_wear = data.get("wear")
    if tyre_age is not None:
        lines.append(f"- Возраст шин: {tyre_age} кругов")
    if tyre_wear is not None:
        lines.append(f"- Износ шин: {tyre_wear:.0f}%")

    laps = data.get("laps_remaining")
    if laps is not None:
        lines.append(f"- Кругов осталось: {laps}")

    track = data.get("track")
    if track:
        lines.extend(_format_track_facts(track))

    return "\n".join(lines) if lines else "- нет данных"


def build_prompt(event_dict: dict, persona: str, recent_phrases: list[str]) -> str:
    """Structured fact-only prompt. LLM must not invent beyond provided data."""
    style = get_style(persona)
    facts = _format_facts(event_dict)
    avoid_lines = "\n".join(f"- {p}" for p in recent_phrases[-5:])
    avoid = avoid_lines if avoid_lines else "нет"

    return (
        f"{style}\n\n"
        f"Факты гонки (используй ТОЛЬКО эти данные, ничего лишнего):\n{facts}\n\n"
        f"Последние фразы (не повторяй):\n{avoid}\n\n"
        "Напиши ОДНУ короткую фразу. Максимум 25 слов. Только русский. "
        "Только по фактам выше. Не повторяй не только готовую строку, но и её "
        "начало, синтаксис или ритм: меняй заход и длину относительно списка выше."
    )
