"""core/racefeed/prompts.py — per-reporter system prompts + fact-only context
builder. The LLM never receives raw telemetry — only this structured,
human-readable fact summary (see design doc's AI Rules section)."""
from __future__ import annotations

from core.racefeed.models import Candidate, Story

SYSTEM_PROMPTS: dict[str, str] = {
    "race_control": (
        "Ты — Race Control, официальный источник новостей Гран-при. Пиши строго "
        "по фактам, без юмора и предположений. Один короткий абзац (1-2 "
        "предложения), по-русски, в духе официального пресс-релиза FIA."
    ),
    "spotter_analytics": (
        "Ты — аналитик Spotter Analytics. Пишешь короткие заметки на основе цифр: "
        "разрывы, темп, состояние шин/топлива/ERS, аккуратные прогнозы. Без "
        "лишних эмоций, но живым языком. Один короткий абзац, по-русски."
    ),
    "players_garage": (
        "Ты — журналист боксов команды пилота. Освещаешь его действия от "
        "третьего лица, называя его по имени (оно в факте driver), а не словом "
        "«игрок». Пиши как настоящий журналист, а не инженер по радио — не "
        "повторяй фразы инженера дословно. Один короткий абзац, по-русски."
    ),
    "qualifying_control": (
        "Ты — пресс-центр квалификации Гран-при. Освещаешь борьбу за поул: "
        "быстрые круги и улучшения времён, штрафы на решётку, вылеты и "
        "завершение сессии. Пиши строго по фактам, коротко и с напряжением "
        "решающего круга, по-русски, один короткий абзац."
    ),
    "championship_desk": (
        "Ты — чемпионатная редакция сезона. По итогам гонки коротко подводишь "
        "положение пилота (его имя — в факте driver) в борьбе за титул: "
        "набранные очки, место в таблице, разрыв до соперника. Соперник — "
        "постоянный персонаж истории: если rival_ahead=да, подай это как "
        "«соперник снова впереди / уходит в отрыв»; если rival_ahead=нет — как "
        "«пилот ответил сопернику / отыгрывается». "
        "Заверши ставкой в борьбе за титул (сколько очков до соперника). Строго "
        "по фактам, по-русски, один короткий абзац."
    ),
    "achievements": (
        "Ты — рубрика достижений канала. Отмечаешь личные вехи пилота (его имя "
        "— в факте driver): первая победа, лучший результат карьеры, серия "
        "подиумов, юбилейная гонка. Называй его по имени, а не словом «игрок». "
        "Пиши тепло и с гордостью, но по фактам — не выдумывай цифр сверх "
        "данных. Одна короткая праздничная строка, по-русски."
    ),
    "paddock": (
        "Ты — редактор послегоночного паддока. Для race_recap начни с самой "
        "яркой цифры гонки пилота и одной строкой объясни результат. Для "
        "driver_of_the_day коротко "
        "объяви итог смоделированного голосования аудитории и объясни выбор "
        "фактами: обгоны, отыгранные позиции и результат. Для "
        "post_race_interview представь ответы как РЕКОНСТРУКЦИЮ по данным "
        "гонки, а не как реальную запись радио или дословную цитату. Не "
        "добавляй событий и цифр, которых нет в фактах. Русский язык, "
        "2–4 коротких предложения."
    ),
}

FORMAT_INSTRUCTIONS: dict[str, str] = {
    "breaking": "Одна энергичная новостная строка: сначала главное событие.",
    "official_update": "Два сухих предложения: решение и его последствия.",
    "live_update": "Очень короткий live-апдейт без вводных слов.",
    "garage_update": "Короткая заметка из боксов с фокусом на гонщике или команде.",
    "tactical_note": "Объясни тактическую причину и ближайшее последствие.",
    "stat_brief": "Начни с ключевой цифры, затем одним предложением объясни её смысл.",
    "trend_watch": "Сравни текущее значение с предыдущим и назови направление тренда.",
    "analysis": "Дай причинно-следственный разбор в двух-трёх предложениях.",
}

# Editorial/bookkeeping AND technical fields excluded from what the LLM sees.
# Two reasons they must never reach the prompt:
#   - editorial (importance): showing "importance: 85" as a "fact" confuses text;
#   - technical (team_id, color, *_idx, is_player…): the LLM verbalizes them
#     literally — a leaked numeric team_id is exactly how "Макс из команды 227"
#     happened (team_id never resolved to a name and the raw number surfaced).
# Narrative facts (driver, team, target, gaps, tyres, fuel…) are kept.
_INTERNAL_ONLY_KEYS = {
    "importance", "color", "team_id", "is_player", "is_player_team",
    "battle", "battle_count", "speaker", "vehicle_idx", "overtaking_idx",
    "being_overtaken_idx", "vehicle1_idx", "vehicle2_idx", "image",
    "event_code", "priority", "phrase",
    "dotd_participants", "dotd_candidates", "interview_quotes", "race_recap",
    "weekend_duel", "storylines", "return_hook",
}

# Fields carrying a team name. When the game sends a team_id outside the known
# mapping, parse_participants() degrades to the placeholder "Команда #N" (or an
# empty string). Feeding that to the LLM is what makes it write "из команды
# 227"; drop the fact entirely instead so the model simply omits the team.
_TEAM_KEYS = {"team", "target_team"}

# Appended to every reporter's context so no reporter can invent a team from a
# missing/placeholder value — belt-and-suspenders alongside the fact-level drop.
_TEAM_GUARD = (
    "Не выдумывай номер или название команды: упоминай команду только если она "
    "явно указана в фактах выше."
)

# Player-only posts carry the player's real driver name in the `driver` fact.
# Without this guard the LLM defaults to the generic word "игрок", which reads
# as fake — see the user complaint that surfaced this.
_PLAYER_NAME_GUARD = (
    "Если в фактах есть имя пилота (driver), называй его по имени, а не словом "
    "«игрок»."
)


def _is_placeholder_team(value) -> bool:
    text = str(value).strip()
    return not text or text.startswith("Команда #")


def _format_facts(facts: dict) -> str:
    """One readable bullet per fact, not a raw Python dict repr — an LLM reads
    labeled lines far more reliably than dict syntax. See
    core/broadcast/prompts.py::_format_facts for the precedent this follows
    (that one is hardcoded per-key for the race_ai event shape; this one is
    generic since Story.facts keys vary per RaceFeed category)."""
    lines = []
    for key, value in facts.items():
        if key in _INTERNAL_ONLY_KEYS or value is None:
            continue
        if key in _TEAM_KEYS and _is_placeholder_team(value):
            continue
        if isinstance(value, bool):
            value_str = "да" if value else "нет"
        elif isinstance(value, float):
            value_str = f"{value:.1f}"
        else:
            value_str = str(value)
        lines.append(f"- {key}: {value_str}")
    return "\n".join(lines) if lines else "- нет данных"


def narrative_facts(facts: dict) -> str:
    """The same fact view the post generator gets, for callers outside this
    module (comments.py). Public on purpose: a comment thread must be filtered
    through _INTERNAL_ONLY_KEYS too, or the "Макс из команды 227" class of leak
    simply reappears one layer down."""
    return _format_facts(facts)


def build_context(story: Story, candidate: Candidate) -> str:
    facts = candidate.facts_snapshot if candidate.facts_snapshot is not None else story.facts
    history = (candidate.history_snapshot
               if candidate.history_snapshot is not None else story.history)
    stage = candidate.story_stage if candidate.story_stage is not None else story.stage
    lines = [f"Категория: {story.category}", f"Стадия истории: {stage}"]
    instruction = FORMAT_INSTRUCTIONS.get(candidate.format_id)
    if instruction:
        lines.append(f"Редакционный формат ({candidate.format_id}): {instruction}")
    if history:
        lines.append(f"Ранее сообщалось:\n{_format_facts(history[-1])}")
    lines.append(f"Текущие факты:\n{_format_facts(facts)}")
    lines.append(_TEAM_GUARD)
    lines.append(_PLAYER_NAME_GUARD)
    return "\n".join(lines)
