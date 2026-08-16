"""core/racefeed/generators.py — the only place RaceFeed calls the LLM, and only
for candidates the Editor has already approved for publication (see design doc:
this ordering means a cancelled/superseded candidate never pays for an LLM call).

When the provider is down, critical publications fall back to deterministic
fact-based templates instead of vanishing: a dead LLM used to take the finish,
the safety car and the championship post down with it, while the comment threads
under posts already had an offline fallback of their own (comments.py)."""
from __future__ import annotations

from typing import Protocol

from core.num_to_words import ru_plural
from core.racefeed.editorial import is_critical_story
from core.racefeed.models import Candidate, Story
from core.racefeed.prompts import SYSTEM_PROMPTS, build_context


# Protocol (not a concrete AIProvider import) so core.racefeed doesn't gain a
# dependency on commentator — this is the one spot that would otherwise need
# one; see design doc's "isolated subsystem" requirement.
class _AIProviderLike(Protocol):
    available: bool
    def generate_with_system(self, system: str, user: str) -> str | None: ...


def _paddock_fallback(story: Story) -> str | None:
    if story.category == "driver_of_the_day":
        driver = story.facts.get("dotd_driver")
        percentage = story.facts.get("dotd_pct")
        overtakes = story.facts.get("dotd_overtakes", 0)
        gained = story.facts.get("dotd_gained", 0)
        if not driver:
            return None
        return (
            f"Итоги голосования аудитории: {driver} — Пилот дня "
            f"с результатом {percentage}%. В основе выбора: {overtakes} "
            f"обгонов и {int(gained):+d} позиций относительно старта."
        )
    if story.category == "post_race_interview":
        drivers = story.facts.get("interview_drivers") or []
        if not drivers:
            return None
        return (
            "Послегоночный микрофон: реконструкция ответов по фактам гонки. "
            f"После финиша говорим с {', '.join(str(name) for name in drivers)}."
        )
    if story.category == "race_recap":
        driver = str(story.facts.get("driver") or "").strip()
        position = story.facts.get("finish_position")
        start = story.facts.get("grid_position")
        overtakes = int(story.facts.get("overtakes") or 0)
        points = int(story.facts.get("points") or 0)
        if not driver or not isinstance(position, int) or position <= 0:
            return None
        start_text = f" с P{start}" if isinstance(start, int) and start > 0 else ""
        return (
            f"Гонка в цифрах: {driver} финишировал P{position}{start_text}, "
            f"совершил {overtakes} обгонов и набрал {points} "
            f"{ru_plural(points, 'очко', 'очка', 'очков')}."
        )
    return None


def _driver(story: Story) -> str:
    """Player-only events (PIT_EXIT, CAREER_PB) are published with driver="" —
    see core/engine.py — so the fallbacks must never interpolate a bare name."""
    return str(story.facts.get("driver") or "").strip() or "пилот"


def _lap_time(value) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    return f"{int(seconds // 60)}:{seconds % 60:06.3f}"


def _flag_fallback(story: Story) -> str | None:
    code = str(story.facts.get("event_code") or "")
    if code == "CHQF":
        return "Клетчатый флаг. Гонка завершена."
    if code == "RDFL":
        return "Красный флаг. Сессия остановлена."
    if code == "SEND":
        return "Сессия завершена."
    return None


def _retirement_fallback(story: Story) -> str | None:
    return f"{_driver(story)} сходит с дистанции и завершает гонку досрочно."


def _safety_car_fallback(story: Story) -> str | None:
    code = str(story.facts.get("event_code") or "")
    label = ("Виртуальная машина безопасности"
             if "virtual" in str(story.facts.get("sc_type") or "").lower()
             else "Машина безопасности")
    if code == "SAFETY_CAR_DEPLOYED":
        return f"{label} на трассе. Пелотон собирается в единую группу."
    if code == "SAFETY_CAR_ENDING":
        return f"{label} уходит с трассы в конце круга. Гонка вот-вот возобновится."
    if code == "SAFETY_CAR_CLEAR":
        return "Трасса чиста, гонка возобновлена."
    return None


def _penalty_fallback(story: Story) -> str | None:
    seconds = story.facts.get("time_seconds")
    lap = story.facts.get("lap_num")
    text = f"{_driver(story)} получает штраф"
    if isinstance(seconds, (int, float)) and seconds > 0:
        value = int(seconds)
        text += f" {value} {ru_plural(value, 'секунда', 'секунды', 'секунд')}"
    if isinstance(lap, int) and lap > 0:
        text += f" на {lap}-м круге"
    return text + "."


def _incident_fallback(story: Story) -> str | None:
    target = str(story.facts.get("target") or "").strip()
    if target:
        return f"Контакт на трассе: {_driver(story)} и {target}."
    return f"Инцидент на трассе с участием {_driver(story)}."


def _championship_fallback(story: Story) -> str | None:
    position = story.facts.get("player_position")
    points = story.facts.get("player_points")
    if position is None or points is None:
        return None
    points = int(points)
    text = (f"{_driver(story)} идёт P{int(position)} в чемпионате — {points} "
            f"{ru_plural(points, 'очко', 'очка', 'очков')}.")
    rival = str(story.facts.get("rival") or "").strip()
    gap = story.facts.get("gap_to_rival")
    if rival and isinstance(gap, (int, float)):
        gap = int(gap)
        text += (f" Разрыв с {rival} — {gap} "
                 f"{ru_plural(gap, 'очко', 'очка', 'очков')}.")
    return text


def _milestone_fallback(story: Story) -> str | None:
    label = str(story.facts.get("label") or "").strip()
    if not label:
        return None
    position = story.facts.get("position")
    if isinstance(position, int) and position > 0:
        return f"{label} {_driver(story)} — P{position} в этой гонке."
    return f"{label} Поздравляем {_driver(story)}."


def _player_overtake_fallback(story: Story) -> str | None:
    target = str(story.facts.get("target") or "").strip()
    if target:
        return f"{_driver(story)} проходит {target} и забирает позицию."
    return f"{_driver(story)} отыгрывает позицию на трассе."


def _player_pit_stop_fallback(story: Story) -> str | None:
    compound = str(story.facts.get("tyre_compound") or "").strip()
    text = f"{_driver(story)} возвращается на трассу после пит-стопа"
    if compound:
        text += f" на составе {compound}"
    return text + "."


def _player_fastest_lap_fallback(story: Story) -> str | None:
    lap_time = _lap_time(story.facts.get("lap_time"))
    if lap_time:
        return f"Быстрейший круг гонки: {_driver(story)} — {lap_time}."
    return f"Быстрейший круг гонки показывает {_driver(story)}."


def _player_progression_fallback(story: Story) -> str | None:
    gap_ms = story.facts.get("gap_ms")
    if isinstance(gap_ms, (int, float)) and gap_ms < 0:
        return (f"Личный рекорд: {_driver(story)} улучшает свой лучший круг на "
                f"{abs(gap_ms) / 1000:.3f} с.")
    sector_gap = story.facts.get("sector_gap_ms")
    sector = story.facts.get("sector")
    if isinstance(sector_gap, (int, float)) and isinstance(sector, int):
        return (f"Лучший личный {sector + 1}-й сектор: "
                f"{abs(sector_gap) / 1000:.3f} с к прежнему результату.")
    return f"{_driver(story)} обновляет личную статистику на этой трассе."


# Only critical categories get a template — see editorial.is_critical_story.
# Analytics ticks (gap/tyre/fuel/ERS) deliberately stay LLM-only: templated
# numbers every 20 seconds would read as a robot and still burn the Editorial
# budget, and losing them costs the feed nothing.
_CRITICAL_FALLBACKS = {
    "flag": _flag_fallback,
    "retirement": _retirement_fallback,
    "safety_car": _safety_car_fallback,
    "penalty": _penalty_fallback,
    "incident": _incident_fallback,
    "championship": _championship_fallback,
    "milestone": _milestone_fallback,
    "player_overtake": _player_overtake_fallback,
    "player_pit_stop": _player_pit_stop_fallback,
    "player_fastest_lap": _player_fastest_lap_fallback,
    "player_progression": _player_progression_fallback,
    "race_recap": _paddock_fallback,
}


def _fallback(candidate: Candidate, story: Story) -> str | None:
    if candidate.reporter_id == "paddock":
        return _paddock_fallback(story)
    if not is_critical_story(story):
        return None
    builder = _CRITICAL_FALLBACKS.get(story.category)
    return builder(story) if builder is not None else None


def render_with_source(
    candidate: Candidate, story: Story, ai_provider: _AIProviderLike
) -> tuple[str | None, str]:
    """Post text plus where it came from: "llm", "fallback" or "" when nothing
    could be rendered (the caller drops the candidate silently — see design
    doc's Error handling: RaceFeed is not safety-critical, unlike voice).
    engine.py counts the sources so a race run entirely on templates is visible
    in the diagnostics panel instead of looking like a normal one."""
    if ai_provider.available:
        system_prompt = SYSTEM_PROMPTS.get(candidate.reporter_id, "")
        context = build_context(story, candidate)
        try:
            text = ai_provider.generate_with_system(system_prompt, context)
        except Exception:
            text = None
        if text:
            return text, "llm"
    text = _fallback(candidate, story)
    return (text, "fallback") if text else (None, "")


def render(candidate: Candidate, story: Story, ai_provider: _AIProviderLike) -> str | None:
    """Text-only wrapper around render_with_source, for callers that don't care
    which path produced the post."""
    return render_with_source(candidate, story, ai_provider)[0]
