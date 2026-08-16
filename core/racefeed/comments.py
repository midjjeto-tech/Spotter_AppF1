"""Compact AI expert notes for RaceFeed posts.

The LLM is asked for one or two useful analytical notes. A deterministic
persona-based fallback keeps those notes available when the provider is
offline or returns malformed output. The resulting Comment objects are
persisted with the post, so reads never trigger regeneration.

Two inputs keep a thread on the subject of its post: the session phase
(live/finished — a thread under the chequered flag must not wonder about the
next pit stop) and the event's narrative facts, filtered through the same
_INTERNAL_ONLY_KEYS view the post generator uses so no team_id or importance
score can leak into a comment.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import time
import uuid
from typing import Protocol

from core.racefeed.models import Comment, Post
from core.racefeed.prompts import narrative_facts
from core.ru_names import decline


class _AIProviderLike(Protocol):
    available: bool
    def generate_with_system(self, system: str, user: str) -> str | None: ...


_PERSONAS = (
    ("apex_nerd", "ApexData", "AD", "аналитик"),
    ("sector_times", "SectorTimes", "ST", "тайминг"),
    ("grandstand", "Grandstand_44", "G4", "болельщик"),
    ("pitwall", "PitWallRumours", "PW", "инсайдер"),
    ("late_braker", "LateBraker", "LB", "провокатор"),
    ("tyre_whisperer", "TyreWhisperer", "TW", "стратег"),
)

_AUTOMATIC_EXPERTS = {
    "apex_nerd", "sector_times", "pitwall", "tyre_whisperer",
}

_SYSTEM = """Ты создаёшь короткие AI-разборы под постом локального гоночного
канала. Верни ТОЛЬКО JSON-массив из 1-2 объектов вида
{"persona":"apex_nerd","text":"...","reply_to":null}. Доступные persona:
apex_nerd, sector_times, pitwall, tyre_whisperer. Каждый объект должен добавлять
новую пользу: объяснение данных, стратегическое последствие или осторожный
вывод. Не изображай толпу болельщиков, спор ради спора или социальную активность.

ГЛАВНОЕ: комментарии обсуждают КОНКРЕТНОЕ событие из поста и фактов ниже. Не
пиши реплики, которые подошли бы к любому посту. Не придумывай круги, позиции,
времена, штрафы, пит-стопы и результаты, которых нет в фактах и тексте поста.

reply_to всегда null. Русский язык, 1–2 коротких предложения."""

_PHASE_INSTRUCTION = {
    "finished": ("Фаза: гонка уже завершена, результат окончательный. Не "
                 "рассуждай о будущих кругах, пит-стопах, обгонах или ещё не "
                 "определившемся исходе — только об итогах и последствиях."),
    "live": ("Фаза: гонка продолжается, исход ещё не решён. Уместны прогнозы "
             "и осторожность."),
}

# Экспертная заметка нужна только там, где есть решение, последствие или итог.
# Для новых категорий правило fail-closed: сначала явно определить пользу,
# затем включать дополнительный LLM-вызов.
_EXPERT_NOTE_CATEGORIES = {
    "incident", "penalty", "retirement", "safety_car", "flag",
    "player_overtake", "player_pit_stop", "player_fastest_lap",
    "player_progression", "championship", "milestone",
    "driver_of_the_day", "post_race_interview", "race_recap",
}


def comments_enabled_for(post: Post) -> bool:
    """Стоит ли вообще генерировать комментарии под этим постом. Вынесено из
    generate_comments() отдельной функцией, чтобы правило было тестируемым в
    изоляции от LLM-заглушек."""
    return post.category in _EXPERT_NOTE_CATEGORIES


def _phase_of(post: Post) -> str:
    """Post-race categories are published after the flag by construction, so
    they stay "finished" even if an older Post (before session_phase existed)
    is passed in."""
    if post.category in {"driver_of_the_day", "post_race_interview", "race_recap"}:
        return "finished"
    return "finished" if post.session_phase == "finished" else "live"


def generate_comments(post: Post, ai_provider: _AIProviderLike,
                      facts: dict | None = None) -> list[Comment]:
    if not comments_enabled_for(post):
        return []
    phase = _phase_of(post)
    raw_items: list[dict] | None = None
    if ai_provider.available:
        lines = [
            f"Автор поста: {post.reporter_id}",
            f"Категория: {post.category}",
            _PHASE_INSTRUCTION[phase],
        ]
        if facts:
            lines.append(f"Факты события:\n{narrative_facts(facts)}")
        lines.append(f"Текст поста: {post.text}")
        try:
            raw_items = _parse(
                ai_provider.generate_with_system(_SYSTEM, "\n".join(lines))
            )
        except Exception:
            raw_items = None
    if not raw_items:
        raw_items = _fallback(post, phase, facts or {})
    return _materialize(post, raw_items)


def _parse(raw: str | None, minimum: int = 1) -> list[dict] | None:
    if not raw:
        return None
    match = re.search(r"\[[\s\S]*\]", raw)
    if match is None:
        return None
    try:
        value = json.loads(match.group(0))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(value, list):
        return None
    cleaned = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        persona = str(item.get("persona", ""))
        text = str(item.get("text", "")).strip()
        if persona not in _AUTOMATIC_EXPERTS or persona in seen or not text:
            continue
        seen.add(persona)
        cleaned.append({"persona": persona, "text": text[:360], "reply_to": None})
        if len(cleaned) == 2:
            break
    return cleaned if len(cleaned) >= minimum else None


# Offline threads are built from two pools: what actually happened (the family
# pool, one line per persona, facts interpolated) and how the paddock feels
# about it given the session phase. Mixing 3 + 2 keeps a thread specific to its
# event without losing the live tension / post-race finality that made the old
# single generic pool readable in the first place.
_FAMILY_BY_CATEGORY = {
    "incident": "contact",
    "penalty": "penalty",
    "retirement": "retirement",
    "safety_car": "neutralised",
    # "flag" is resolved per event code in _family_of — a chequered flag and a
    # red flag are not the same conversation.
    "player_overtake": "overtake",
    "player_pit_stop": "pit_stop",
    "player_fastest_lap": "fastest_lap",
    "player_progression": "progression",
    "championship": "standings",
    "milestone": "standings",
    "driver_of_the_day": "paddock",
    "post_race_interview": "paddock",
    "race_recap": "paddock",
}


def _text(value) -> str:
    return str(value or "").strip()


def _forms(name: str) -> dict[str, str]:
    """Surname in every case via core/ru_names.py — the same declension table
    the voice pipeline uses. Without it a thread reads «Сход Норрис» / «Дуэль с
    Ферстаппен», which is exactly the kind of detail that makes the fake
    community look fake."""
    return {case: decline(name, case) for case in ("nom", "gen", "dat", "acc", "ins")}


def _contact_lines(d: dict, o: dict, facts: dict) -> list[tuple[str, str]]:
    return [
        ("apex_nerd", f"Точка контакта решает всё: кто был впереди в момент касания — {d['nom']} или {o['nom']}."),
        ("sector_times", f"На повторе видно, что {d['nom']} уже был на уровне зеркал. Это меняет трактовку эпизода."),
        ("grandstand", f"Ну и рубка! {d['nom']} и {o['nom']} не уступают друг другу ни метра 😳"),
        ("late_braker", f"Спорный момент. По мне, {d['nom']} заехал в поворот слишком глубоко и сам создал контакт."),
        ("pitwall", "На пит-уолле смотрят повтор кадр за кадром и готовят аргументы для стюардов."),
        ("tyre_whisperer", "После такого касания надо смотреть на состояние машины: такие удары редко проходят бесследно."),
    ]


def _penalty_lines(d: dict, o: dict, facts: dict) -> list[tuple[str, str]]:
    seconds = facts.get("time_seconds")
    penalty = (f"{int(seconds)} с" if isinstance(seconds, (int, float)) and seconds
               else "Штраф")
    return [
        ("apex_nerd", f"{penalty} — стандартное решение для такого эпизода, стюарды тут предсказуемы."),
        ("sector_times", f"Для {d['gen']} это ощутимо: столько на дистанции обратно не отыгрывается."),
        ("grandstand", f"Жёстко по отношению к {d['dat']}. Хотя, если честно, там было за что 🤷"),
        ("late_braker", "Не согласен со стюардами. За тот же манёвр в прошлой гонке никого не тронули."),
        ("pitwall", f"В команде {d['gen']} наверняка будут просить пересмотр — им это решение невыгодно."),
        ("tyre_whisperer", "Такой штраф ломает всю расчётную стратегию отрезка, не только позицию."),
    ]


def _retirement_lines(d: dict, o: dict, facts: dict) -> list[tuple[str, str]]:
    return [
        ("apex_nerd", f"Сход {d['gen']} — это не только его результат, это сдвиг всей классификации позади."),
        ("sector_times", f"Судя по последним кругам, у {d['gen']} темп сыпался ещё до остановки."),
        ("grandstand", f"Обидно за {d['acc']}. Столько работы — и всё заканчивается вот так 😔"),
        ("late_braker", "Машину надо было тащить до финиша, даже медленно. Иногда очки приезжают сами."),
        ("pitwall", "Похоже на техническую проблему, а не на ошибку пилота — но команда подробностей не даст."),
        ("tyre_whisperer", "Если это перегрев, то остальным стоит внимательнее смотреть на температуры."),
    ]


def _finish_lines(d: dict, o: dict, facts: dict) -> list[tuple[str, str]]:
    return [
        ("apex_nerd", "Итог сложился из десятка мелких решений по ходу дистанции, а не из одного эпизода."),
        ("sector_times", "Теперь видно полную картину по кругам, а не обрывки по ходу трансляции."),
        ("grandstand", "Отличная гонка! Спасибо всем, кто дотерпел до клетчатого 👏"),
        ("late_braker", "Результат результатом, но пара решений по ходу дистанции ещё долго будет обсуждаться."),
        ("pitwall", "В боксах выдыхают: дистанция пройдена, дальше только разбор."),
        ("tyre_whisperer", "Доехать до финиша на этой резине было отдельным испытанием."),
    ]


def _neutralised_lines(d: dict, o: dict, facts: dict) -> list[tuple[str, str]]:
    return [
        ("apex_nerd", "Нейтрализация обнуляет накопленные разрывы — вся дистанция впереди пересчитывается заново."),
        ("sector_times", "Отрывы, которые строились кругами, исчезают за один сектор. Всегда больно смотреть."),
        ("grandstand", "Ну вот, только гонка разошлась 😩"),
        ("late_braker", "Кому-то это подарок, кому-то приговор. Как всегда, повезёт тем, кто ещё не питовался."),
        ("pitwall", "Дежурный вопрос на пит-уолле: заезжать сейчас или держать позицию."),
        ("tyre_whisperer", "Резина остынет, и первые круги после рестарта будут самыми скользкими."),
    ]


def _overtake_lines(d: dict, o: dict, facts: dict) -> list[tuple[str, str]]:
    return [
        ("apex_nerd", f"Обгон {o['gen']} готовился заранее: {d['nom']} несколько кругов держался в зоне досягаемости."),
        ("sector_times", f"Решающим стал выход из предыдущего поворота — там {d['nom']} и получил преимущество над {o['ins']}."),
        ("grandstand", f"Вот это манёвр! {d['nom']} прошёл {o['acc']} чисто и без нервов 🔥"),
        ("late_braker", f"Красиво, но {o['nom']} почти не сопротивлялся. Ждал большего от защиты."),
        ("pitwall", f"Теперь у {d['gen']} чистый воздух впереди — это сразу плюс к темпу."),
        ("tyre_whisperer", "Атака стоила резины. Вопрос, во что это выльется в конце отрезка."),
    ]


def _pit_stop_lines(d: dict, o: dict, facts: dict) -> list[tuple[str, str]]:
    compound = _text(facts.get("tyre_compound"))
    compound_line = (f"Состав {compound} под текущие условия — вполне рабочий выбор."
                     if compound else "Выбор состава здесь важнее, чем секунды на пит-лейне.")
    return [
        ("apex_nerd", f"Главное сейчас — куда {d['nom']} вернулся в трафике, а не сколько простоял."),
        ("sector_times", "Потеря на пит-лейне окупается за несколько кругов, если резина работает."),
        ("grandstand", f"Ну давай, {d['nom']}, теперь отыгрывайся 💪"),
        ("late_braker", "Рано заехали, на мой взгляд. Можно было потерпеть ещё пару кругов."),
        ("pitwall", "Такой заезд обычно означает, что команда увидела окно и решила его закрыть."),
        ("tyre_whisperer", compound_line),
    ]


def _fastest_lap_lines(d: dict, o: dict, facts: dict) -> list[tuple[str, str]]:
    return [
        ("apex_nerd", f"Быстрый круг {d['gen']} говорит о том, что запас темпа у машины ещё есть."),
        ("sector_times", "Интересно, в каком секторе набрано время — от этого зависит, повторяемо ли оно."),
        ("grandstand", f"{d['nom']} сегодня в ударе! 🔥"),
        ("late_braker", "Быстрый круг на пустой трассе и быстрый круг в борьбе — разные вещи."),
        ("pitwall", "Такие круги обычно едут на свежей резине сразу после заезда в боксы."),
        ("tyre_whisperer", "Один круг — недорого. Вопрос, чем за него заплатили в деградации."),
    ]


def _progression_lines(d: dict, o: dict, facts: dict) -> list[tuple[str, str]]:
    return [
        ("apex_nerd", f"Прогресс {d['gen']} на этой трассе виден именно в стабильности, а не в одном круге."),
        ("sector_times", "Улучшение по секторам — самый честный показатель роста пилота."),
        ("grandstand", f"Приятно смотреть, как {d['nom']} прибавляет от гонки к гонке 👏"),
        ("late_braker", "Прогресс есть, но проверять его надо в плотной борьбе, а не в чистом воздухе."),
        ("pitwall", "Такие цифры в команде отслеживают внимательнее, чем итоговую позицию."),
        ("tyre_whisperer", "Ровный темп обычно означает, что пилот наконец понял, как беречь резину."),
    ]


def _standings_lines(d: dict, o: dict, facts: dict) -> list[tuple[str, str]]:
    rival_line = (f"Дуэль с {o['ins']} — главный сюжет этого сезона."
                  if _text(facts.get("rival"))
                  else "Борьба в таблице ещё далека от развязки.")
    return [
        ("apex_nerd", f"В таблице это заметно меняет расклад вокруг {d['gen']}."),
        ("sector_times", "Очки набираются стабильностью, и текущая динамика это подтверждает."),
        ("grandstand", f"Заслуженно! {d['nom']} идёт к этому весь сезон 🏆"),
        ("late_braker", "Радоваться рано: пара неудачных уик-эндов — и всё выглядит иначе."),
        ("pitwall", rival_line),
        ("tyre_whisperer", "Такие результаты редко берутся одним фактором — тут сложилось всё сразу."),
    ]


def _paddock_lines(d: dict, o: dict, facts: dict) -> list[tuple[str, str]]:
    return [
        ("apex_nerd", f"Выбор {d['gen']} выглядит логично: здесь ценится вся гонка, а не один яркий круг."),
        ("sector_times", "Итог совпадает с цифрами: темп и продвижение по пелотону были заметными."),
        ("grandstand", f"{d['nom']} сегодня действительно дал шоу. Мой голос туда же 👏"),
        ("late_braker", "Я бы всё равно поставил выше стабильность на дистанции, а не число атак."),
        ("pitwall", "В командах уже разбирают те эпизоды, о которых пилоты сказали после финиша."),
        ("tyre_whisperer", "Работа с резиной тоже часть этого результата, даже если она не видна одной цифрой."),
    ]


def _generic_lines(d: dict, o: dict, facts: dict) -> list[tuple[str, str]]:
    return [
        ("apex_nerd", f"Здесь важнее не сам эпизод, а темп после него. Смотрим следующие круги {d['gen']}."),
        ("sector_times", "По секторам картина подтверждается: это не один случайный поворот."),
        ("grandstand", f"Вот за такие моменты и смотрим гонки. {d['nom']} сегодня не отступает 🔥"),
        ("late_braker", "Не спешил бы с выводами по одному эпизоду."),
        ("pitwall", "На пит-уолле это уже наверняка считают отдельным сценарием."),
        ("tyre_whisperer", "Резина в такие моменты решает больше, чем кажется со стороны."),
    ]


_FAMILY_POOLS = {
    "contact": _contact_lines,
    "penalty": _penalty_lines,
    "retirement": _retirement_lines,
    "finish": _finish_lines,
    "neutralised": _neutralised_lines,
    "overtake": _overtake_lines,
    "pit_stop": _pit_stop_lines,
    "fastest_lap": _fastest_lap_lines,
    "progression": _progression_lines,
    "standings": _standings_lines,
    "paddock": _paddock_lines,
    "generic": _generic_lines,
}

# Phase flavour. The "live" pool keeps the uncertainty that made threads feel
# alive; the "finished" pool must never speculate about laps, pit stops or an
# undecided result — that is the bug this split exists for.
_PHASE_POOLS = {
    "live": [
        ("apex_nerd", "До конца ещё далеко, и по такой дистанции всё может перевернуться."),
        ("sector_times", "Следующие круги покажут, разовый это эпизод или тенденция."),
        ("grandstand", "Как же нервно смотреть, когда исход ещё не решён 😬"),
        ("late_braker", "Все празднуют, а гонка не закончена. Один неудачный пит — и картина другая."),
        ("pitwall", "В боксах сейчас пересчитывают окно. Решать надо в ближайшие круги."),
        ("tyre_whisperer", "Деградация ближе к концу отрезка добавит драмы."),
    ],
    "finished": [
        ("apex_nerd", "Задним числом видно, насколько это повлияло на итог."),
        ("sector_times", "Финальные цифры расставили всё по местам."),
        ("grandstand", "Отличная гонка. Уже жду следующую 👏"),
        ("late_braker", "Результат результатом, но осадок от пары решений остался."),
        ("pitwall", "В паддоке этот уик-энд будут разбирать ещё долго."),
        ("tyre_whisperer", "Задним числом видно, что резина решила здесь больше всего."),
    ],
}

_FAMILY_LINES_PER_THREAD = 2
_MIN_THREAD_SIZE = 1
_MAX_THREAD_SIZE = 2


def _family_of(post: Post, facts: dict, phase: str) -> str:
    """Category → conversation family. "flag" covers everything from the start
    of the session to the chequered flag, so it is resolved by event code: a
    thread under the finish must not ask whether to pit under the safety car."""
    if post.category == "flag":
        code = _text(facts.get("event_code"))
        if code in {"CHQF", "SEND"} or (not code and phase == "finished"):
            return "finish"
        if code == "RDFL":
            return "neutralised"
        return "generic"
    return _FAMILY_BY_CATEGORY.get(post.category, "generic")


def _fallback(post: Post, phase: str, facts: dict) -> list[dict]:
    driver = _forms(_text(facts.get("driver")) or _text(post.driver) or "пилот")
    other = _forms(_text(facts.get("target")) or _text(facts.get("rival"))
                   or "соперник")
    family = _family_of(post, facts, phase)
    event_lines = _FAMILY_POOLS[family](driver, other, facts)
    phase_lines = list(_PHASE_POOLS[phase])

    seed = int(hashlib.sha256(post.id.encode("utf-8")).hexdigest()[:8], 16)
    rng = random.Random(seed)
    rng.shuffle(event_lines)
    rng.shuffle(phase_lines)
    # Only a few family lines make the thread, so the ones naming a concrete
    # fact (the other driver, the rival, the compound) go first — otherwise the
    # shuffle can drop exactly the line that ties the thread to this event.
    # Stable sort keeps the shuffled order inside each group.
    # Match on the declined stem, not the raw fact: facts carry «Макс
    # Ферстаппен», the line carries «Ферстаппеном».
    anchors = [_text(facts.get("tyre_compound"))]
    if _text(facts.get("target")) or _text(facts.get("rival")):
        anchors.append(other["nom"])
    anchors = [value for value in anchors if value]
    if anchors:
        event_lines.sort(
            key=lambda item: 0 if any(a in item[1] for a in anchors) else 1
        )
    ordered = [
        item for item in event_lines
        if item[0] in _AUTOMATIC_EXPERTS
    ][:_FAMILY_LINES_PER_THREAD] + [
        item for item in phase_lines
        if item[0] in _AUTOMATIC_EXPERTS
    ]

    size = rng.randint(_MIN_THREAD_SIZE, _MAX_THREAD_SIZE)
    # keep at most one line per persona so a thread doesn't feel like one bot
    picked: list[tuple[str, str]] = []
    used: set[str] = set()
    for persona, text in ordered:
        if persona in used:
            continue
        used.add(persona)
        picked.append((persona, text))
        if len(picked) == size:
            break
    result = [{"persona": p, "text": text, "reply_to": None}
              for p, text in picked]
    return result


def _reveal_schedule(post: Post, count: int) -> list[float]:
    """Absolute created_at for each comment, spread over minutes with growing,
    jittered gaps so a thread keeps "докапываясь" long after the post lands
    (the UI reveals each comment when its time passes) instead of dumping the
    whole batch in the first minute. Deterministic per post so re-reads and the
    volatile/SQLite paths agree on identical timestamps."""
    seed = int(hashlib.sha256((post.id + ":reveal").encode("utf-8")).hexdigest()[:8], 16)
    rng = random.Random(seed)
    schedule: list[float] = []
    # Первый разбор появляется быстро, второй — после небольшой паузы. UI не
    # изображает typing: заметка просто становится доступной по расписанию.
    cursor = post.published_at + rng.uniform(8.0, 20.0)
    for index in range(count):
        schedule.append(cursor)
        gap = rng.uniform(18.0, 40.0) + index * 14.0
        cursor += gap
    return schedule


def _materialize(post: Post, raw_items: list[dict]) -> list[Comment]:
    persona_map = {item[0]: item for item in _PERSONAS}
    ids = [uuid.uuid4().hex for _ in raw_items]
    schedule = _reveal_schedule(post, len(raw_items))
    comments = []
    for index, item in enumerate(raw_items):
        persona = persona_map[item["persona"]]
        reply_index = item.get("reply_to")
        parent_id = (
            ids[reply_index]
            if isinstance(reply_index, int) and 0 <= reply_index < index
            else None
        )
        comments.append(Comment(
            id=ids[index], post_id=post.id, parent_id=parent_id,
            author_id=persona[0], author_name=persona[1], avatar=persona[2],
            author_badge=persona[3], text=item["text"],
            created_at=schedule[index], likes=0,
        ))
    return comments


# --- ответы AI-экспертов на реплику читателя --------------------------------

_REPLY_SYSTEM = """Ты — AI-эксперты локального гоночного канала. Читатель
оставил реплику под постом. Ответь ему от лица 1-2 экспертов.

Верни ТОЛЬКО JSON-массив из 1-2 объектов вида
{"persona":"apex_nerd","text":"..."}. Доступные persona: apex_nerd,
sector_times, pitwall, tyre_whisperer.

Отвечай ПО СУЩЕСТВУ реплики читателя: объясни данные, последствие или границу
доступных фактов. Опирайся только на то, что уже сказано в посте и в треде: не
придумывай новых кругов, позиций, времён и результатов. К читателю обращайся на
«ты». Русский язык, 1-2 коротких предложения."""

_REPLY_FALLBACK = (
    ("apex_nerd", "Резонно. По тому, что видно в этом эпизоде, спорить особо не с чем."),
    ("sector_times", "Проверил бы это по секторам, но в целом читается так же."),
    ("pitwall", "На пит-уолле, думаю, оценили бы примерно так же."),
    ("tyre_whisperer", "Всё так, только резина в этой истории решала не меньше."),
)

_REPLY_MIN_DELAY_S = 10.0
_REPLY_MAX_DELAY_S = 40.0


def _reply_prompt(post_text: str, thread: list[dict], player_text: str) -> str:
    recent = [
        f"- {item.get('author_name') or item.get('author_id')}: {item.get('text', '')}"
        for item in thread[-6:]
        if item.get("text")
    ]
    lines = [f"Пост: {post_text}"]
    if recent:
        lines.append("Тред:\n" + "\n".join(recent))
    lines.append(f"Реплика читателя: {player_text}")
    return "\n".join(lines)


def generate_replies(post_id: str, parent_id: str, post_text: str,
                     thread: list[dict], player_text: str,
                     ai_provider: _AIProviderLike,
                     parent_created_at: float | None = None) -> list[Comment]:
    """1-2 ответа AI-экспертов на реплику читателя, связанные parent_id.

    Появляются с короткой задержкой и затем раскрываются тем же UI-механизмом,
    что автоматические заметки."""
    raw_items: list[dict] | None = None
    if ai_provider.available:
        try:
            raw_items = _parse(
                ai_provider.generate_with_system(
                    _REPLY_SYSTEM, _reply_prompt(post_text, thread, player_text)
                ),
                minimum=1,
            )
        except Exception:
            raw_items = None
    seed = int(hashlib.sha256((parent_id + ":replies").encode("utf-8")).hexdigest()[:8], 16)
    rng = random.Random(seed)
    if not raw_items:
        # Без провайдера остаётся честный короткий экспертный fallback.
        pool = list(_REPLY_FALLBACK)
        rng.shuffle(pool)
        raw_items = [{"persona": persona, "text": text}
                     for persona, text in pool[:rng.randint(1, 2)]]

    persona_map = {item[0]: item for item in _PERSONAS}
    base = parent_created_at if parent_created_at is not None else time.time()
    replies: list[Comment] = []
    used: set[str] = set()
    for item in raw_items[:2]:
        persona = persona_map.get(item["persona"])
        if persona is None or persona[0] in used:
            continue
        used.add(persona[0])
        base += rng.uniform(_REPLY_MIN_DELAY_S, _REPLY_MAX_DELAY_S)
        replies.append(Comment(
            id=uuid.uuid4().hex, post_id=post_id, parent_id=parent_id,
            author_id=persona[0], author_name=persona[1], avatar=persona[2],
            author_badge=persona[3], text=item["text"], created_at=base,
            likes=0,
        ))
    return replies
