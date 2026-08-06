"""
commentator/radio_answer.py
=============================
Voice Q&A "инженерское радио" — закрытый набор тем (погода/гэп/шины/позиция/
штрафы/повреждения/топливо/ERS/круги до финиша/окно пит-стопа), keyword-
классификация без LLM, детерминированные ответы из данных телеметрии (тот же
паттерн, что commentator/radio.py, core/strategy_ai/weather_advisory.py,
core/strategy_ai/gap_digest.py). См. docs/superpowers/specs/2026-07-12-voice-radio-mode-design.md
и docs/superpowers/plans/2026-07-19-voice-qa-expansion.md (8 тем + голосовые
команды поверх существующих хоткеев).

Заменяет commentator/query.py (свободный LLM-ответ) целиком.
"""
from __future__ import annotations

import re

from core.num_to_words import ru_plural
from core.packets import WEATHER_LABEL
from core.strategy_ai.pit_window import detect_pit_window

OFF_TOPIC_ANSWER = "Возьми фокус на гонку, пока не можем ответить."

_TOPIC_STEMS: dict[str, tuple[str, ...]] = {
    # Напарник — единственный соперник на заведомо равной машине; в реальной F1
    # это главная точка отсчёта пилота. Стоит ПЕРВЫМ осознанно: «какая позиция
    # у напарника» иначе поймалось бы стемом "позици" темы position и вернуло
    # бы позицию самого игрока. Порядок словаря = приоритет (см. classify_topic).
    # Стем "команд" не берём — он ловит вопросы про стратегию команды вообще.
    "teammate": ("напарник", "тиммейт", "партнёр", "второй пилот"),
    # Порядок = приоритет. Более узкие темы стоят ДО общих, иначе общий стем
    # съедает их: «кто впереди» ушло бы в gap (стем "впереди") и вернуло бы
    # цифру вместо имени, а «стоит ли заезжать» — в pit_window вместо решения.
    # «кто впереди» / «кто сзади» СОЗНАТЕЛЬНО не здесь: эти формулировки уже
    # закреплены за темой gap (тесты test_gap_answer_behind_only и соседние), и
    # там ответ называет и имя, и цифру. Переносить их сюда значило бы поменять
    # работающий контракт ради формально более буквального разбора.
    "rival": ("кто рядом", "с кем борюсь", "кто передо мной", "кто за мной",
              "с кем я борюсь"),
    # Только решение-образные формулировки. «пора в боксы» остаётся у
    # pit_window: там про окно, и это тоже закреплено тестом.
    "should_pit": ("стоит ли заезжать", "мне заезжать", "заезжать сейчас",
                   "надо заезжать", "заезжаем"),
    "front_wing": ("переднее крыло", "крыло"),
    "car_state": ("состояние машины", "как машина", "машина цела",
                  "что с машиной"),
    "strategy": ("стратеги", "план"),
    "safety_car": ("сейфти", "safety", "машина безопасности", "вск", "vsc"),
    # Стемы — ПОДСТРОКИ реальных вопросов, а не именительный падеж: «какое время
    # последнего круга» не содержит «последний круг».
    "last_lap": ("время последнего", "последнего круга", "время круга",
                 "время на круге", "мой круг", "сектор"),
    "gap_ahead": ("сколько до впереди", "отрыв впереди", "гэп впереди"),
    "gap_behind": ("сколько сзади", "отрыв сзади", "гэп сзади"),
    "weather": ("погод", "дожд", "сухо", "мокро"),
    "gap": ("гэп", "отрыв", "разрыв", "впереди", "сзади", "соперник", "лидер"),
    "tyres": ("шин", "резин", "износ", "покрышк"),
    "position": ("позици", "мест"),
    "penalties": ("штраф",),
    "damage": ("повреждени", "ущерб"),
    "fuel": ("топлив", "бензин", "горюч"),
    "ers": ("ers", "эрс", "батаре", "заряд"),
    "laps_remaining": ("сколько кругов", "кругов остал", "до финиша"),
    # "-" вырезается _normalize() до сравнения — "пит-стоп" и "питстоп"
    # неотличимы после нормализации, стем всегда без дефиса.
    "pit_window": ("питы", "питстоп", "боксы"),
    "tyre_sets": ("комплект",),
}

# Голосовые команды поверх уже существующих хоткеев (core/hotkeys.py) —
# отдельный словарь, не тема Q&A: не несут данных, исполняют действие.
_COMMAND_STEMS: dict[str, tuple[str, ...]] = {
    # «Повтори» стоит ПЕРВОЙ: она обязана сработать даже если пилот сказал
    # «повтори про шины» — иначе стем "шин" увёл бы это в тему tyres и выдал
    # свежий ответ вместо повтора того, что пилот не расслышал.
    "repeat": ("повтори", "ещё раз", "не расслышал", "не понял", "что ты сказал"),
    "toggle_commentary": ("замолч", "тише", "помолчи", "хватит болтать", "заткнись"),
    "talk_more": ("говори чаще", "больше информации", "подробнее",
                  "чаще докладывай", "рассказывай больше"),
    "next_persona": ("смени персону", "смени голос", "другой голос", "поменяй голос"),
}

_DAMAGE_NOTICEABLE_THRESHOLD = 20   # тот же порог, что core/engine.py::_DAMAGE_NOTICEABLE_THRESHOLD
_DAMAGE_LABELS: tuple[tuple[str, str], ...] = (
    ("wing_damage", "крыло"),
    ("floor_damage", "пол"),
    ("gearbox_damage", "коробка передач"),
    ("engine_damage", "двигатель"),
)

_ERS_MODE_RU = {0: "не используется", 1: "средний", 2: "обгон", 3: "быстрый круг"}

# Действия Strategy AI по-русски. Ключи — те же, что отдаёт
# core/strategy_ai/module.py; переводим здесь, а не в UI, потому что это уходит
# в РЕЧЬ.
_STRATEGY_ACTION_RU: dict[str, str] = {
    "hold": "Остаёмся на плане",
    "pit": "План — заезд в боксы",
    "push": "План — атаковать",
    "save": "План — берегём резину",
    "undercut": "План — андеркат",
    "overcut": "План — оверкат",
}

# m_safetyCarStatus из PACKET_SESSION.
_SAFETY_CAR_RU: dict[int, str] = {
    0: "Трасса чистая, зелёный флаг.",
    1: "На трассе Safety Car.",
    2: "Виртуальный Safety Car.",
    3: "Формейшн-лэп за машиной безопасности.",
}


def _no_data() -> str:
    """Короткий честный отказ (ТЗ §12): длинный универсальный звучит хуже.

    Берётся из общего банка, чтобы вариант не был один и тот же каждый раз."""
    from core.radio.phrases import no_data
    return no_data()

# Компаунды в фиксированном порядке (сухая -> мокрая) — та же терминология,
# что уже установлена в commentator/personas.py (софт/медиум/хард/
# интермедиэйт/дождевые), не придумываем новую.
_TYRE_COMPOUND_ORDER = ("S", "M", "H", "I", "W")
_TYRE_COMPOUND_RU = {
    "S": "софт", "M": "медиум", "H": "хард",
    "I": "интермедиэйт", "W": "дождевые",
}


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", (text or "").lower())


def classify_topic(question: str) -> str | None:
    """Первая совпавшая тема по стему подстроки (без учёта порядка слов).
    Порядок словаря = приоритет при совпадении нескольких тем сразу."""
    normalized = _normalize(question)
    if not normalized:
        return None
    for topic, stems in _TOPIC_STEMS.items():
        if any(stem in normalized for stem in stems):
            return topic
    return None


def classify_command(question: str) -> str | None:
    """Голосовая команда ("замолчи"/"смени персону") вместо вопроса про
    данные — исполняет действие, не несёт ответа-факта. Отдельно от
    classify_topic(), проверяется первым в core/engine.py::_run_voice_question."""
    normalized = _normalize(question)
    if not normalized:
        return None
    for command, stems in _COMMAND_STEMS.items():
        if any(stem in normalized for stem in stems):
            return command
    return None


#: Согласие и отказ на ПРЕДЛОЖЕНИЕ инженера. Живут отдельно от `_COMMAND_STEMS`
#: намеренно: команды проверяются раньше тем и для любой реплики подряд, а «да»
#: с «нет» в таком положении перехватывали бы обычную речь пилота. Эти стемы
#: спрашиваются только тогда, когда предложение реально висит
#: (`core/strategy_ai/agreement.py`), поэтому и разбор отдельный.
_DECISION_STEMS: dict[str, tuple[str, ...]] = {
    # Отказ проверяется ПЕРВЫМ: «не надо» содержит «на», а «нет» — подстрока
    # многих слов, поэтому порядок здесь несёт смысл, как и в `_COMMAND_STEMS`.
    "decline": ("нет", "не надо", "не сейчас", "отставить", "остаёмся",
                "остаемся", "рано", "отмена", "не буду"),
    "accept": ("да", "давай", "согласен", "подтверждаю", "поехали",
               "делаем", "принято", "хорошо", "идёт", "идет"),
}


def classify_decision(text: str) -> str | None:
    """"accept" / "decline" / None — решение пилота по предложению инженера.

    Отдельно от `classify_command`, и вызывать это можно ТОЛЬКО когда
    предложение висит: иначе любое «да» посреди гонки стало бы согласием
    неизвестно на что.
    """
    normalized = _normalize(text)
    if not normalized:
        return None
    words = set(normalized.split())
    for decision, stems in _DECISION_STEMS.items():
        for stem in stems:
            # Короткие слова сверяем ЦЕЛИКОМ: подстрока «да» живёт в «дальше»,
            # «когда», «данные», и без этого согласием оказывалась бы половина
            # обычных реплик.
            if len(stem) <= 3:
                if stem in words:
                    return decision
            elif stem in normalized:
                return decision
    return None


def _weather_answer(weather: dict | None, rain_forecast: dict | None) -> str:
    if weather is None:
        return "Данные о погоде пока недоступны."
    label = WEATHER_LABEL.get(weather["weather"], "неизвестно")
    base = f"{label.capitalize()}, {weather['track_temp']}° на трассе."
    if rain_forecast is not None:
        minutes = rain_forecast["minutes"]
        pct = rain_forecast["rain_pct"]
        min_word = ru_plural(minutes, "минуту", "минуты", "минут")
        return f"{base} Дождь через {minutes} {min_word}, вероятность {pct}%."
    return f"{base} Дождя не ожидается."


def _gap_answer(gap_front_ms: int | None, gap_behind_ms: int | None,
                 ahead_name: str | None = None, behind_name: str | None = None) -> str:
    if not gap_front_ms and not gap_behind_ms:
        return "Вы лидируете."
    parts = []
    if gap_front_ms:
        # «Отрыв» — преимущество, которое пилот держит; до машины ВПЕРЕДИ у
        # него отставание. Та же терминология, что в банке фраз.
        clause = f"До машины впереди {gap_front_ms / 1000:.1f}"
        clause += f" — это {ahead_name}." if ahead_name else "."
        parts.append(clause)
    if gap_behind_ms:
        clause = f"Отрыв сзади {gap_behind_ms / 1000:.1f}"
        clause += f" — это {behind_name}." if behind_name else "."
        parts.append(clause)
    return " ".join(parts)


def _tyres_answer(tyre_wear: float | None) -> str:
    if tyre_wear is None:
        return "Данные по износу пока недоступны."
    return f"Износ шин {round(tyre_wear)}%."


def _position_answer(position: int | None) -> str:
    if position is None:
        return "Позиция пока не определена."
    return f"Ты на {position}-м месте из 22."


def _penalties_answer(penalty_count: int, penalty_seconds: int) -> str:
    if not penalty_count:
        return "Штрафов пока нет."
    count_word = ru_plural(penalty_count, "штраф", "штрафа", "штрафов")
    sec_word = ru_plural(penalty_seconds, "секунда", "секунды", "секунд")
    return f"У тебя {penalty_count} {count_word}, {penalty_seconds} {sec_word}."


def _damage_answer(damage: dict | None) -> str:
    if not damage:
        return "Машина цела, серьёзных повреждений нет."
    parts = [f"{label} {damage[key]}%" for key, label in _DAMAGE_LABELS
             if damage.get(key, 0) >= _DAMAGE_NOTICEABLE_THRESHOLD]
    if not parts:
        return "Машина цела, серьёзных повреждений нет."
    return f"Повреждено: {', '.join(parts)}."


def _fuel_answer(fuel_kg: float | None) -> str:
    if fuel_kg is None:
        return "Данные о топливе пока недоступны."
    return f"Топлива {round(fuel_kg, 1)} кг."


def _ers_answer(ers_percent: float | None, ers_deploy_mode: int | None) -> str:
    if ers_percent is None:
        return "Данные по ERS пока недоступны."
    label = _ERS_MODE_RU.get(ers_deploy_mode, "неизвестно")
    return f"Заряд ERS {round(ers_percent)}%, режим — {label}."


def _laps_remaining_answer(laps_remaining: int | None) -> str:
    if laps_remaining is None:
        return "Пока не известно, сколько кругов осталось."
    if laps_remaining <= 0:
        return "Это последний круг."
    word = ru_plural(laps_remaining, "круг", "круга", "кругов")
    return f"Осталось {laps_remaining} {word}."


def _pit_window_answer(tyre_age: int | None, tyre_wear: float | None,
                        laps_remaining: int | None, tyre_compound: str | None) -> str:
    open_, _conf, laps_left = detect_pit_window(
        tyre_age, tyre_wear, laps_remaining, tyre_compound)
    if open_:
        return "Окно пит-стопа открыто — заезжай в этом круге."
    if laps_left is not None:
        word = ru_plural(laps_left, "круг", "круга", "кругов")
        return f"Ещё примерно {laps_left} {word} до пит-стопа."
    return "Пока рано думать про пит-стоп."


def _tyre_sets_answer(available: dict[str, int] | None) -> str:
    """available — {"S": n, "M": n, ...} только доступных (m_available==1)
    комплектов, из core/engine.py::_player_tyre_sets_available. None —
    пакет ещё не пришёл; пустой/все нули — реально не осталось свободных
    комплектов (разные состояния, разные ответы)."""
    if available is None:
        return "Данные о комплектах пока недоступны."
    parts = [f"{available[c]} {_TYRE_COMPOUND_RU[c]}" for c in _TYRE_COMPOUND_ORDER
             if available.get(c)]
    if not parts:
        return "Свободных комплектов не осталось."
    return f"Доступно: {', '.join(parts)}."


def _rival_answer(ahead_name: str | None, behind_name: str | None,
                  gap_front_ms: int | None, gap_behind_ms: int | None) -> str:
    """Кто рядом — ИМЕНАМИ, не цифрами (для цифр есть тема gap)."""
    parts = []
    if ahead_name:
        parts.append(f"Впереди {ahead_name}")
        if gap_front_ms:
            parts[-1] += f", {gap_front_ms / 1000:.1f}"
    if behind_name:
        parts.append(f"сзади {behind_name}")
        if gap_behind_ms:
            parts[-1] += f", {gap_behind_ms / 1000:.1f}"
    if not parts:
        # Имён нет, но цифры могут быть — отдать их лучше, чем отказать.
        if gap_front_ms or gap_behind_ms:
            return _gap_answer(gap_front_ms, gap_behind_ms)
        return _no_data()
    return ", ".join(parts) + "."


def _gap_ahead_answer(gap_front_ms: int | None, ahead_name: str | None) -> str:
    if not gap_front_ms:
        return "Впереди никого, ты лидируешь."
    tail = f" — это {ahead_name}." if ahead_name else "."
    return f"До машины впереди {gap_front_ms / 1000:.1f}{tail}"


def _gap_behind_answer(gap_behind_ms: int | None, behind_name: str | None) -> str:
    if not gap_behind_ms:
        return "Сзади чисто."
    tail = f" — это {behind_name}." if behind_name else "."
    return f"Отрыв сзади {gap_behind_ms / 1000:.1f}{tail}"


def _front_wing_answer(damage: dict | None) -> str:
    """Отдельная тема: переднее крыло — то, про что пилот спрашивает чаще
    всего после контакта, и общий ответ про «повреждения» на этот вопрос не
    отвечает."""
    if not damage:
        return _no_data()
    value = damage.get("wing_damage")
    if value is None:
        return _no_data()
    if value < _DAMAGE_NOTICEABLE_THRESHOLD:
        return "Переднее крыло в порядке."
    return f"Переднее крыло повреждено на {int(value)}%."


def _car_state_answer(damage: dict | None, tyre_wear: float | None,
                      fuel_kg: float | None) -> str:
    """Состояние машины целиком — одной короткой сводкой."""
    if damage is None and tyre_wear is None and fuel_kg is None:
        return _no_data()
    broken = [label for key, label in _DAMAGE_LABELS
              if (damage or {}).get(key, 0) >= _DAMAGE_NOTICEABLE_THRESHOLD]
    if broken:
        return f"Повреждения: {', '.join(broken)}."
    if tyre_wear is not None and tyre_wear >= 60:
        return f"Машина цела, но резина изношена на {round(tyre_wear)}%."
    return "Машина цела, всё в норме."


def _strategy_answer(strategy: dict | None) -> str:
    """Активная стратегия — из уже существующего состояния Strategy AI, без
    собственных решений."""
    if not strategy:
        return _no_data()
    action = strategy.get("action")
    advice = strategy.get("advice")
    label = _STRATEGY_ACTION_RU.get(action)
    if label is None and not advice:
        return _no_data()
    if advice:
        return f"{label}. {advice}" if label else str(advice)
    return f"{label}."


def _safety_car_answer(status: int | None) -> str:
    if status is None:
        return _no_data()
    label = _SAFETY_CAR_RU.get(int(status))
    if label is None:
        return _no_data()
    return label


def _last_lap_answer(last_lap_ms: int | None) -> str:
    if not last_lap_ms:
        return _no_data()
    total = last_lap_ms / 1000.0
    minutes = int(total // 60)
    seconds = total - minutes * 60
    if minutes:
        return f"Последний круг {minutes}:{seconds:04.1f}."
    return f"Последний круг {seconds:.1f}."


def _should_pit_answer(tyre_age: int | None, tyre_wear: float | None,
                       laps_remaining: int | None,
                       tyre_compound: str | None) -> str:
    """Решение, а не описание окна: пилот спрашивает «заезжать?», а не «открыто
    ли окно»."""
    open_, _conf, laps_left = detect_pit_window(
        tyre_age, tyre_wear, laps_remaining, tyre_compound)
    if open_:
        return "Да, окно открыто. Заезжай."
    if laps_left is not None:
        word = ru_plural(laps_left, "круг", "круга", "кругов")
        return f"Нет, оставайся на трассе. Ещё {laps_left} {word}."
    return "Нет, оставайся на трассе."


def answer_radio_question(question: str, *, weather: dict | None,
                           rain_forecast: dict | None,
                           gap_front_ms: int | None, gap_behind_ms: int | None,
                           tyre_wear: float | None,
                           ahead_name: str | None = None, behind_name: str | None = None,
                           position: int | None = None,
                           penalty_count: int = 0, penalty_seconds: int = 0,
                           damage: dict | None = None,
                           fuel_kg: float | None = None,
                           ers_percent: float | None = None, ers_deploy_mode: int | None = None,
                           laps_remaining: int | None = None,
                           tyre_age: int | None = None, tyre_compound: str | None = None,
                           tyre_sets_available: dict[str, int] | None = None,
                           teammate_report: str | None = None,
                           strategy: dict | None = None,
                           safety_car_status: int | None = None,
                           last_lap_ms: int | None = None) -> str:
    """Всегда возвращает непустую строку. Пустой/нераспознанный вопрос -> OFF_TOPIC_ANSWER."""
    topic = classify_topic(question)
    if topic == "teammate":
        # Отчёт собирает core/strategy_ai/teammate.py на стороне движка: ему
        # нужен весь грид и история кругов, а не отдельные скалярные поля —
        # тащить их сюда по одному значило бы дублировать поиск напарника.
        return teammate_report or "Напарника на трассе не вижу."
    if topic == "weather":
        return _weather_answer(weather, rain_forecast)
    if topic == "gap":
        return _gap_answer(gap_front_ms, gap_behind_ms, ahead_name, behind_name)
    if topic == "tyres":
        return _tyres_answer(tyre_wear)
    if topic == "position":
        return _position_answer(position)
    if topic == "penalties":
        return _penalties_answer(penalty_count, penalty_seconds)
    if topic == "damage":
        return _damage_answer(damage)
    if topic == "fuel":
        return _fuel_answer(fuel_kg)
    if topic == "ers":
        return _ers_answer(ers_percent, ers_deploy_mode)
    if topic == "laps_remaining":
        return _laps_remaining_answer(laps_remaining)
    if topic == "pit_window":
        return _pit_window_answer(tyre_age, tyre_wear, laps_remaining, tyre_compound)
    if topic == "tyre_sets":
        return _tyre_sets_answer(tyre_sets_available)
    if topic == "rival":
        return _rival_answer(ahead_name, behind_name, gap_front_ms, gap_behind_ms)
    if topic == "gap_ahead":
        return _gap_ahead_answer(gap_front_ms, ahead_name)
    if topic == "gap_behind":
        return _gap_behind_answer(gap_behind_ms, behind_name)
    if topic == "front_wing":
        return _front_wing_answer(damage)
    if topic == "car_state":
        return _car_state_answer(damage, tyre_wear, fuel_kg)
    if topic == "strategy":
        return _strategy_answer(strategy)
    if topic == "safety_car":
        return _safety_car_answer(safety_car_status)
    if topic == "last_lap":
        return _last_lap_answer(last_lap_ms)
    if topic == "should_pit":
        return _should_pit_answer(tyre_age, tyre_wear, laps_remaining,
                                  tyre_compound)
    return OFF_TOPIC_ANSWER
