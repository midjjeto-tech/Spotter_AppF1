"""
commentator/planner.py
========================
Планировщик реплики: Python оценивает ВАЖНОСТЬ события (0-100) и решает, О ЧЁМ
и КАК говорить (focus/reaction/length/emotion) — LLM формулирует текст СТРОГО по
этой директиве, а не выбирает тему сам. Чинит корневую причину рассинхрона
триггер↔фраза (LLM пересказывает доминантную драму таймлайна на любой триггер),
задокументированную в CONTEXT.md.

Чистые функции без I/O и без сети — полностью юнит-тестируемы отдельно от engine.
См. docs/superpowers/specs/2026-07-05-comment-planner-importance-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanContext:
    """Срез состояния гонки, нужный только для оценки важности. F1Engine строит
    это по значению (см. _plan_context()) — planner в state/lock'и НЕ лезет."""
    player_involved: bool = False
    battle: bool = False
    laps_remaining: int | None = None
    session_type: str = "race"


@dataclass(frozen=True)
class CommentPlan:
    """Директива для LLM: ЧТО комментировать и КАК. Собирается build_plan()
    ПОСЛЕ entity resolution — driver/target в event должны быть настоящими
    именами, не '#N'/'гонщик'."""
    focus: str
    reaction: str
    length: str
    emotion: str
    importance: int
    must_mention: tuple[str, ...] = ()
    narrative: bool = False


# Базовый балл по event_code — см. design spec §"score_importance — базовая таблица".
# Если добавляешь новый event_code сюда — проверь заодно _REACTION_BY_CODE ниже
# (и _NON_RACE_PENALIZED_CODES, если код относится к OVTK/FTLP-подобным).
_BASE_IMPORTANCE: dict[str, int] = {
    # Контакт градуирован по последствию (core/engine.py::_grade_contact):
    # игра шлёт один и тот же COLL и на притирку, и на аварию, а тяжести в
    # пакете нет. Прежняя единая цифра 90 давала «ХАОС НА ТРАССЕ» на каждое
    # касание. COLL_LIGHT ниже _DEFAULT_IMPORTANCE, но одной цифрой тишина не
    # обеспечивается: порога озвучки по важности в проекте нет вовсе, и низкий
    # балл лишь отодвигает реплику. Молчание задаёт `_should_commentate`
    # (core/engine.py) — там притирка отправляется в ленту как `muted`.
    "COLL_HEAVY": 90, "COLL": 65, "COLL_LIGHT": 25,
    "RTMT": 90,
    "PENA": 88, "RCWN": 88, "CHQF": 88,
    "OVTK": 60,
    "FTLP": 55,
    "DAMAGE_WING": 65, "DAMAGE_FLOOR": 65, "DAMAGE_GEARBOX": 65, "DAMAGE_ENGINE": 65,
    "F1_BENCH": 55, "CAREER_PB": 55,
    "F1_SECTOR_BENCH": 45, "CAREER_SECTOR_PB": 45,
    "SSTA": 70, "STLG": 70,
    "SEND": 40,
    "TMPT": 30, "SPTP": 30, "DRSE": 30, "DRSD": 30,
    "FLBK": 25,
    "AMBIENT": 20,
    "PIT_EXIT": 65,
    "DRS_PROXIMITY_ENTER": 30, "DRS_PROXIMITY_EXIT": 30,
    "DRS_ALLOWED_ON": 30, "DRS_ALLOWED_OFF": 30,
    "DRS_PROXIMITY_ENTER_AND_ALLOWED": 30,
    "POSITION_CALL": 55, "POSITION_CALL_OWN_PIT": 55,
    "LEADER_CHANGE": 55,
    "PIT_WINDOW_APPROACH": 55,
    "DEFENSE": 55,
    "SPOTTER_CAR_LEFT": 70, "SPOTTER_CAR_RIGHT": 70,
    "SPOTTER_CAR_BOTH": 70, "SPOTTER_CLEAR": 70,
    # Phase B (Safety Car/VSC/красный флаг) — та же драматичность, что у
    # RTMT/COLL (90): деплой/красный флаг реально меняют ход гонки.
    "SAFETY_CAR_DEPLOYED": 90, "SAFETY_CAR_ENDING": 90,
    "SAFETY_CAR_CLEAR": 90, "RDFL": 90,
}
_DEFAULT_IMPORTANCE = 50

# Модификаторы (design spec §"score_importance"): суммируются, итог зажимается [0,100].
_PLAYER_INVOLVED_BONUS = 20
_BATTLE_BONUS = 15
_FINAL_LAPS_BONUS = 10
_FINAL_LAPS_THRESHOLD = 3
_NON_RACE_PENALTY = 10
_NON_RACE_PENALIZED_CODES = ("OVTK", "FTLP")
_CRITICAL_FLOOR = 90


def score_importance(event: dict, ctx: PlanContext) -> int:
    """Важность 0..100. Событие с priority == 'critical' всегда получает ХОТЯ БЫ
    90 — сегодняшние гарантии critical (гэп/прерывание/анти-вытеснение) сохранены."""
    code = event.get("event_code", "")
    score = _BASE_IMPORTANCE.get(code, _DEFAULT_IMPORTANCE)

    if ctx.player_involved:
        score += _PLAYER_INVOLVED_BONUS
    if ctx.battle:
        score += _BATTLE_BONUS
    if ctx.laps_remaining is not None and ctx.laps_remaining <= _FINAL_LAPS_THRESHOLD:
        score += _FINAL_LAPS_BONUS
    if ctx.session_type != "race" and code in _NON_RACE_PENALIZED_CODES:
        score -= _NON_RACE_PENALTY

    if event.get("priority") == "critical":
        score = max(score, _CRITICAL_FLOOR)

    return max(0, min(100, score))


# Тип реакции по коду события — участвует в директиве LLM (build_plan()).
_REACTION_BY_CODE: dict[str, str] = {
    # Директива задаёт ТОН всей реплики, поэтому градация обязана доезжать и
    # сюда: со словом «авария» LLM драматизирует что угодно, включая притирку.
    "COLL_HEAVY": "авария",
    "COLL": "контакт",
    "COLL_LIGHT": "лёгкое касание без последствий, упомянуть вскользь",
    "RTMT": "сход",
    "PENA": "штраф",
    "RCWN": "победитель определён",
    "CHQF": "финиш",
    "OVTK": "атака",
    "FTLP": "рекорд круга",
    "DAMAGE_WING": "разбор повреждения",
    "DAMAGE_FLOOR": "разбор повреждения",
    "DAMAGE_GEARBOX": "разбор повреждения",
    "DAMAGE_ENGINE": "разбор повреждения",
    "F1_BENCH": "рекорд", "CAREER_PB": "рекорд",
    "F1_SECTOR_BENCH": "рекорд", "CAREER_SECTOR_PB": "рекорд",
    "SSTA": "старт", "STLG": "старт",
    "SEND": "итог сессии",
    "TMPT": "предупреждение", "SPTP": "разбор",
    "DRSE": "ремарка", "DRSD": "ремарка",
    "FLBK": "ремарка",
    "AMBIENT": "разбор",
    "PIT_EXIT": "выезд из боксов",
    "PIT_CALL_NOTICE": "команда с пит-уолла: пит-стоп в этом круге",
    "SAFETY_CAR_DEPLOYED": "safety car на трассе",
    "SAFETY_CAR_ENDING": "safety car заканчивается",
    "SAFETY_CAR_CLEAR": "гонка возобновляется",
    "RDFL": "красный флаг",
}
_DEFAULT_REACTION = "ремарка"

# Стиль соперника (RivalTracker._classify_style) -> русская фраза-суффикс в
# focus. "consistent" намеренно отсутствует — незаметный дефолт, не повод для
# реплики (design spec 2026-07-05-race-memory).
_STYLE_PHRASES: dict[str, str] = {
    "aggressive": "агрессивен",
    "charging": "в ударе",
    "fading": "теряет темп",
}

_TYRE_AGE_GAP_THRESHOLD = 5   # круга разницы, чтобы факт был достоин упоминания

# Длина: только два состояния (design spec §"build_plan — маппинг важности в стиль").
_LENGTH_SHORT_THRESHOLD = 80
_LENGTH_SHORT = "короткая ударная"
_LENGTH_NORMAL = "обычная"

# Эмоция: три ступени по важности, персона сдвигает результат на одну ступень.
_EMOTION_LADDER = ["спокойно", "оживлённо", "на пределе"]
_EMOTION_TOP = _EMOTION_LADDER[-1]     # верхняя ступень — форсируется для force_urgent
_EMOTION_HIGH_THRESHOLD = 80
_EMOTION_MID_THRESHOLD = 50
_PERSONA_EMOTION_SHIFT = {"calm": -1, "hype": 1, "toxic": 1}


def _base_emotion(importance: int) -> str:
    if importance >= _EMOTION_HIGH_THRESHOLD:
        return _EMOTION_TOP
    if importance >= _EMOTION_MID_THRESHOLD:
        return _EMOTION_LADDER[1]
    return _EMOTION_LADDER[0]


def _shift_emotion(emotion: str, persona: str) -> str:
    shift = _PERSONA_EMOTION_SHIFT.get(persona, 0)
    if shift == 0:
        return emotion
    idx = _EMOTION_LADDER.index(emotion) + shift
    idx = max(0, min(len(_EMOTION_LADDER) - 1, idx))
    return _EMOTION_LADDER[idx]


def build_plan(event: dict, importance: int, persona: str, mode: str = "live") -> CommentPlan:
    """Строит директиву для LLM. Вызывать ПОСЛЕ entity resolution — driver/target
    в event должны быть уже резолвнутыми именами (см. _commentary_loop в
    core/engine.py: entity resolution идёт раньше build_plan() в пайплайне).

    Последние круги (laps_remaining <= _FINAL_LAPS_THRESHOLD, ТОТ ЖЕ порог, что
    и в score_importance — не отдельная константа) и борьба за позицию (battle)
    принудительно делают реплику короткой и эмоциональной НЕЗАВИСИМО от того,
    что дала бы числовая шкала важности — см. design spec
    2026-07-05-final-laps-attacks-pitstop.

    Race Memory (design spec 2026-07-05-race-memory): battle_count (сколько раз
    эта пара уже обгоняла друг друга) и driver_style/target_style (тренд темпа
    соперника из RivalTracker) — чисто описательные добавки в focus, НЕ новые
    модификаторы важности (score_importance() не меняется).

    Commentary Mode (design spec 2026-07-07-commentary-mode): mode="story" forces
    normal-length phrasing (never the short/punchy variant, even when force_urgent
    would otherwise pick it) and sets narrative=True — a hint consumed by
    commentator/brain.py to nudge the LLM toward connective phrasing. mode="calm"
    changes ONLY frequency (core/engine.py::_speak_threshold()) — it does not
    touch length/emotion here. Emotion is never affected by mode, only by persona."""
    code = event.get("event_code", "")
    narrative = mode == "story"
    driver = event.get("driver") or ""
    target = event.get("target") or ""
    reaction = _REACTION_BY_CODE.get(code, _DEFAULT_REACTION)
    battle = bool(event.get("battle"))
    laps_remaining = event.get("laps_remaining")
    final_laps = laps_remaining is not None and laps_remaining <= _FINAL_LAPS_THRESHOLD
    force_urgent = final_laps or battle

    # focus_reaction — ЧАСТЬ focus (описательный текст), НЕ plan.reaction
    # (короткая категория для строки "Тип реакции: ..." в brain.py._compose()).
    # markers — список фрагментов маркера фазы/истории, объединяются одной парой
    # скобок через запятую (а не (...)(...)), см. design spec.
    markers: list[str] = []
    if final_laps:
        markers.append(f"последние {laps_remaining} круга гонки")
    battle_count = event.get("battle_count", 0)
    if battle and battle_count:   # battle УЖЕ порогует по BATTLE_THRESHOLD — не дублируем здесь
        markers.append(f"{battle_count}-я попытка обгона")
    if event.get("driver_recent_mistake"):
        markers.append(f"{driver} только что ошибся")
    if event.get("target_recent_mistake"):
        markers.append(f"{target} только что ошибся")
    driver_tyre_age = event.get("driver_tyre_age")
    target_tyre_age = event.get("target_tyre_age")
    if (driver_tyre_age is not None and target_tyre_age is not None
            and abs(driver_tyre_age - target_tyre_age) >= _TYRE_AGE_GAP_THRESHOLD):
        fresher = driver if driver_tyre_age < target_tyre_age else target
        markers.append(f"{fresher} на более свежей резине")
    focus_reaction = f"{reaction} ({', '.join(markers)})" if markers else reaction

    # Суффиксы стиля соперника — привязаны к конкретному имени, не к focus_reaction.
    # "consistent" НАМЕРЕННО отсутствует в _STYLE_PHRASES — незаметный дефолт, не
    # повод для реплики (см. design spec).
    driver_style = event.get("driver_style")
    target_style = event.get("target_style")
    driver_suffix = f" ({_STYLE_PHRASES[driver_style]})" if driver_style in _STYLE_PHRASES else ""
    target_suffix = f" ({_STYLE_PHRASES[target_style]})" if target_style in _STYLE_PHRASES else ""

    # tyre_compound — только у PIT_EXIT; идёт первой веткой без риска конфликта
    # с driver/target (PIT_EXIT никогда их не несёт, событие всегда про игрока).
    tyre_compound = event.get("tyre_compound")
    if tyre_compound:
        focus = f"{focus_reaction}: свежий комплект {tyre_compound}"
    elif target:
        focus = f"{focus_reaction}: {driver}{driver_suffix} и {target}{target_suffix}".strip()
    elif driver:
        focus = f"{focus_reaction}: {driver}{driver_suffix}".strip()
    else:
        focus = focus_reaction

    if force_urgent:
        length = _LENGTH_SHORT
        emotion = _shift_emotion(_EMOTION_TOP, persona)
    else:
        length = _LENGTH_SHORT if importance >= _LENGTH_SHORT_THRESHOLD else _LENGTH_NORMAL
        emotion = _shift_emotion(_base_emotion(importance), persona)

    if narrative:
        length = _LENGTH_NORMAL   # story: связнее важнее ударнее, даже force_urgent

    must_mention = tuple(name for name in (driver, target) if name)

    return CommentPlan(
        focus=focus,
        reaction=reaction,
        length=length,
        emotion=emotion,
        importance=importance,
        must_mention=must_mention,
        narrative=narrative,
    )
