"""
core/radio/policy.py
======================
Чистые таблицы решений для радиообмена: КТО говорит (канал), НАСКОЛЬКО срочно,
СКОЛЬКО живёт сообщение и КАК оно ведёт себя относительно уже звучащей фразы.

Без I/O, без состояния, без импорта engine — полностью юнит-тестируемо.

Три правила, которые нельзя нарушать при правках таблиц ниже.

1. **Канал ортогонален `commentator/channel_router.py`.** Тот отвечает на
   вопрос «как доставить» (озвучить длинно / коротко / только в ленту), этот —
   на вопрос «кто говорит». Оба нужны, они не взаимозаменяемы.

2. **`critical` выдаётся только явно.** Либо `priority == "critical"` в
   событии, либо код в `_URGENCY_BY_CODE`. Через importance до critical не
   дотянуться (см. `urgency_for`): сегодня importance 90 получают SC, RTMT,
   COLL, PENA, RCWN, CHQF и целая пачка синтетики — если позволить числу
   выдавать critical, право прерывать звучащую фразу получит половина гонки, и
   спотер (единственный, кому это право нужно по смыслу) утонет в общем потоке.

3. **TTL отсчитывается от момента события, не от попадания в TTS** (ТЗ §7).
   Здесь только величина окна; отсчёт — в `message.py` по `created_at`.
"""
from __future__ import annotations

from collections.abc import Mapping

# ── Каналы: кто говорит ──────────────────────────────────────────────────────
CHANNEL_SPOTTER = "spotter"
CHANNEL_ENGINEER = "engineer"
CHANNEL_COMMENTATOR = "commentator"

# ── Срочность ────────────────────────────────────────────────────────────────
URGENCY_CRITICAL = "critical"
URGENCY_HIGH = "high"
URGENCY_NORMAL = "normal"
URGENCY_LOW = "low"

# ── Политика относительно уже звучащей фразы ─────────────────────────────────
POLICY_INTERRUPT = "interrupt"          # прервать текущую, играть первой
POLICY_NEXT = "next"                    # встать в очередь перед normal/low
POLICY_REPLACE = "replace"              # вытеснить прежнее сообщение той же категории
POLICY_DROP_IF_BUSY = "drop_if_busy"    # играть только на свободном радио

_SPEAKER_LABEL: dict[str, str] = {
    CHANNEL_SPOTTER: "Споттер",
    CHANNEL_ENGINEER: "Инженер",
    CHANNEL_COMMENTATOR: "Комментатор",
}

# Слот голоса по каналу. Раньше здесь стояла персона комментатора "calm" — и
# это был источник главной поломки: при выбранной пользователем персоне "calm"
# все три канала звучали ОДНИМ голосом (marina), то есть разделение каналов
# существовало на бумаге и не существовало на слух. Теперь у ролей свои слоты
# (core/radio/voice_cast.py), а None у комментатора по-прежнему значит
# «говорить персоной, которую выбрал пользователь».
_VOICE_PERSONA: dict[str, str | None] = {
    CHANNEL_SPOTTER: "spotter",
    CHANNEL_ENGINEER: "engineer",
    CHANNEL_COMMENTATOR: None,
}

# Маркер event["speaker"], которым все инженерские трекеры уже помечают свои
# реплики. Дублируем строку, а не импортируем core.engine.SPEAKER_ENGINEER:
# policy не должен зависеть от движка (иначе тесты policy тянут весь engine).
_SPEAKER_ENGINEER_MARKER = "engineer"

_SPOTTER_CODES: frozenset[str] = frozenset({
    "SPOTTER_CAR_LEFT", "SPOTTER_CAR_RIGHT", "SPOTTER_CAR_BOTH", "SPOTTER_CLEAR",
})

# Инженерные коды — полный список из аудита §2. Новый код инженера, забытый
# здесь, всё равно попадёт в канал engineer через маркер speaker (см.
# channel_for), но лучше вносить явно: от категории зависят TTL и phrase bank.
_ENGINEER_CODES: frozenset[str] = frozenset({
    # боксы и стратегия
    "STRAT_BOX_CALL_1", "STRAT_BOX_CALL_2", "STRAT_BOX_CALL_3",
    "PIT_CALL_NOTICE", "PIT_WINDOW_APPROACH", "PIT_EXIT",
    # Реплика инженера на выезде из боксов, рядом с трансляционной PIT_EXIT
    # комментатора. Отдельный код, потому что канал у них разный.
    "PIT_EXIT_ENGINEER",
    "STRAT_PIT", "STRAT_UNDERCUT", "STRAT_OVERCUT", "STRAT_SAVE", "STRAT_PUSH",
    "STRAT_FUEL", "STRAT_ERS_SAVE", "STRAT_ERS_OVERTAKE",
    # сводки и advisory
    "ENGINEER_GAP_DIGEST", "ENGINEER_RAIN_ADVISORY",
    "ENGINEER_TRACK_LIMITS_WARNING", "ENGINEER_PENA_TRACK_LIMITS",
    # DRS
    "DRS_PROXIMITY_ENTER", "DRS_PROXIMITY_EXIT", "DRS_ALLOWED_ON",
    "DRS_ALLOWED_OFF", "DRS_PROXIMITY_ENTER_AND_ALLOWED", "DRSE", "DRSD",
    # позиция и оборона
    "POSITION_CALL", "POSITION_CALL_OWN_PIT", "LEADER_CHANGE", "DEFENSE",
    # состояние машины
    "DAMAGE_WING", "DAMAGE_FLOOR", "DAMAGE_GEARBOX", "DAMAGE_ENGINE",
    "TYRE_WARN",
    # официальные решения и флаги
    "PENA", "RDFL",
    "SAFETY_CAR_DEPLOYED", "SAFETY_CAR_ENDING", "SAFETY_CAR_CLEAR",
    # одобрение
    "PRAISE_OVERTAKE", "PRAISE_FASTEST_LAP",
    # Личные рекорды пилота — свой архив трассы (CAREER_*) и поле этой сессии
    # (F1_*). Тексты у них на «ты»: «Сектор 2 — твой лучший в сессии». Пока их
    # тут не было, они уходили комментатору по умолчанию, и при персоне `calm`
    # личную реплику произносил женский голос, хотя инженером выбран Волков
    # (живой заезд 2026-08-09). Категория и TTL у них при этом свои,
    # аналитические, и канал их не трогает.
    "CAREER_PB", "CAREER_SECTOR_PB", "F1_BENCH", "F1_SECTOR_BENCH",
    # разведданные о сопернике впереди
    "ENGINEER_RIVAL_INTEL",
    # инженер спрашивает пилота (единственная реплика, которая ждёт ответа)
    "ENGINEER_ASKS_DRIVER",
    # ритуалы сессии
    "SESSION_RADIO_CHECK", "SESSION_RESULT",
    # диалог с пилотом
    "USER_Q", "PRE_RACE_PEP_TALK",
    # Ответы на ДЕЙСТВЕННЫЕ вопросы пилота. Отдельные коды, потому что от кода
    # зависит категория, а от неё — TTL и guard'ы актуальности. «Данных нет» и
    # «износ 48%» могут прозвучать с опозданием без вреда, а «да, заезжай» через
    # 15 секунд, когда игрок уже в пит-лейне, — вредная неправда.
    "USER_Q_PIT", "USER_Q_GAP", "USER_Q_SAFETY_CAR",
})

#: Коды ответов инженера на запрос пилота. Перечислены явно, а не найдены по
#: префиксу `USER_Q`: связывание вопроса с ответом в истории радио
#: (`RadioSession`) не должно молча подхватить будущий код вроде `USER_QUEUE_*`.
PTT_ANSWER_CODES: frozenset[str] = frozenset({
    "USER_Q", "USER_Q_PIT", "USER_Q_GAP", "USER_Q_SAFETY_CAR",
})

# ── Категории: группировка для TTL и phrase bank ─────────────────────────────
_CATEGORY_BY_CODE: dict[str, str] = {
    "SPOTTER_CAR_LEFT": "spotter_side",
    "SPOTTER_CAR_RIGHT": "spotter_side",
    "SPOTTER_CAR_BOTH": "spotter_side",
    "SPOTTER_CLEAR": "spotter_clear",

    "STRAT_BOX_CALL_1": "box_call",
    "STRAT_BOX_CALL_2": "box_call",
    "STRAT_BOX_CALL_3": "box_call",
    "PIT_CALL_NOTICE": "box_call",
    "PIT_WINDOW_APPROACH": "pit_window",
    "PIT_EXIT": "pit_window",
    "PIT_EXIT_ENGINEER": "pit_window",

    "STRAT_PIT": "strategy",
    "STRAT_UNDERCUT": "strategy",
    "STRAT_OVERCUT": "strategy",
    "STRAT_SAVE": "strategy",
    "STRAT_PUSH": "strategy",
    "STRAT_FUEL": "fuel",
    "STRAT_ERS_SAVE": "ers",
    "STRAT_ERS_OVERTAKE": "ers",

    "ENGINEER_GAP_DIGEST": "gap_digest",
    "ENGINEER_RAIN_ADVISORY": "weather",
    "ENGINEER_TRACK_LIMITS_WARNING": "track_limits",
    "ENGINEER_PENA_TRACK_LIMITS": "penalty",
    "PENA": "penalty",
    "RDFL": "red_flag",

    "DRS_PROXIMITY_ENTER": "drs",
    "DRS_PROXIMITY_EXIT": "drs",
    "DRS_ALLOWED_ON": "drs",
    "DRS_ALLOWED_OFF": "drs",
    "DRS_PROXIMITY_ENTER_AND_ALLOWED": "drs",
    "DRSE": "drs",
    "DRSD": "drs",

    "POSITION_CALL": "position",
    "POSITION_CALL_OWN_PIT": "position",
    "LEADER_CHANGE": "position",
    "DEFENSE": "defense",

    "DAMAGE_WING": "damage",
    "DAMAGE_FLOOR": "damage",
    "DAMAGE_GEARBOX": "damage",
    "DAMAGE_ENGINE": "damage",
    "TYRE_WARN": "tyres",

    "SAFETY_CAR_DEPLOYED": "safety_car",
    "SAFETY_CAR_ENDING": "safety_car",
    "SAFETY_CAR_CLEAR": "safety_car",

    "PRAISE_OVERTAKE": "praise",
    "PRAISE_FASTEST_LAP": "praise",

    "ENGINEER_RIVAL_INTEL": "rival_intel",
    "ENGINEER_ASKS_DRIVER": "driver_query",

    "SESSION_RADIO_CHECK": "session",
    "SESSION_RESULT": "session",

    # Справочный ответ пилоту — без TTL: он спросил сам, опоздавший ответ лучше
    # молчания.
    "USER_Q": "ptt_answer",
    # Действенные ответы наследуют категорию соответствующей автоматической
    # реплики — вместе с её TTL и её guard'ами. Отвечать «заезжай» после заезда
    # в боксы или называть разрыв до пилота, которого уже обогнали, нельзя
    # независимо от того, кто начал разговор.
    "USER_Q_PIT": "box_call",
    "USER_Q_GAP": "gap_digest",
    "USER_Q_SAFETY_CAR": "safety_car",
    "PRE_RACE_PEP_TALK": "pep_talk",
    "AMBIENT": "ambient",

    "BATTLE": "battle",
    "ATTACK": "battle",
    "ATTACK_ZONE": "battle",
    "OVTK": "battle",

    "F1_SECTOR_BENCH": "secondary_analytics",
    "CAREER_SECTOR_PB": "secondary_analytics",
}
DEFAULT_CATEGORY = "commentary"

# ── Темы: О ЧЁМ новость, независимо от кода ──────────────────────────────────
# Категория отвечает на вопрос «какое у реплики окно жизни», тема — на другой:
# «про что она». Это разные вопросы, и склеивать их нельзя: `drs` и `gap_digest`
# живут по разным TTL, но сообщают ОДНО И ТО ЖЕ — «ты вплотную к машине
# впереди». Именно на этом инженер повторялся: два трекера, два кода, разные
# слова, одна новость (`core/situation_dedup.py::EngineerTopicDedup`).
#
# Второе число — РАНГ ДЕЙСТВЕННОСТИ внутри темы. Уровней ровно ДВА:
#
#   0 — факт: реплика сообщает положение дел («Отрыв впереди 0,9», «Ты в зоне
#       DRS»). Сказанное дважды разными словами, это и есть повтор.
#   1 — действие: реплика говорит пилоту, что ДЕЛАТЬ прямо сейчас («DRS
#       открыта, атакуй»). Такую душить фактом нельзя, она пробивает окно.
#
# Ургентность для этого не годится: у всех кодов ниже она одинаковая
# (`normal`), и без ранга выбор решался бы тем, чей пакет телеметрии пришёл
# первым, то есть случайно.
#
# Шкалу намеренно НЕ дробим тоньше. С тремя и более уровнями почти каждая
# реплика оказывается «чуть действеннее» предыдущей и пробивает окно — дедуп
# перестаёт что-либо дедуплицировать. Проверено: с рангами 0/1/2 сводку по
# разрывам пробивал даже обычный вход в зону DRS.
#
# Таблица — БЕЛЫЙ СПИСОК: кода здесь нет — реплика не дедупится вовсе. Так и
# задумано. Молчание опаснее повтора, и безопасные коды (споттер, боксы, флаги,
# повреждения, штрафы) сюда не попадают НИКОГДА.
TOPIC_CAR_AHEAD = "car_ahead"
#: Состояние соперника — ОТДЕЛЬНАЯ тема от дистанции до него, и намеренно.
#: «Отрыв впереди 0,9» и «у него шины на восемь кругов старше» дополняют друг
#: друга: одно про то, где он, другое — про то, кто он. Душить второе первым
#: значило бы выбросить как раз ту разведку, ради которой всё писалось. А вот
#: три реплики подряд про одного и того же соперника — это уже поток, и от него
#: тема защищает.
TOPIC_RIVAL_STATE = "rival_state"

_TOPIC_BY_CODE: dict[str, tuple[str, int]] = {
    # Факты о дистанции до машины впереди. Вход в зону DRS сюда же: без
    # разрешения им ещё нельзя воспользоваться, это сообщение, а не команда.
    "ENGINEER_GAP_DIGEST": (TOPIC_CAR_AHEAD, 0),
    "DRS_PROXIMITY_ENTER": (TOPIC_CAR_AHEAD, 0),
    # Зона и разрешение сразу — прямое руководство к действию.
    "DRS_PROXIMITY_ENTER_AND_ALLOWED": (TOPIC_CAR_AHEAD, 1),
    # Разведка — всегда факт о сопернике. Ранг 0: она не говорит, что делать
    # прямо сейчас, и заглушать ею команду к действию нельзя.
    "ENGINEER_RIVAL_INTEL": (TOPIC_RIVAL_STATE, 0),
}


#: Реплики инженера, на которые уместно спросить согласия пилота.
#:
#: Чего здесь НЕТ и не будет: `STRAT_BOX_CALL_*`. «Бокс, бокс» — команда, а не
#: тема для обсуждения; спрашивать на неё согласия значит превратить безопасную
#: команду в переговоры и потерять секунды там, где их нет. То же правило, что
#: держит боевые команды вне характера и вне дедупа.
_PROPOSAL_CODES: frozenset[str] = frozenset({
    "STRAT_UNDERCUT", "STRAT_OVERCUT", "STRAT_PIT",
    "PIT_CALL_NOTICE", "STRAT_SAVE", "STRAT_PUSH",
})


def is_proposal(code: str) -> bool:
    """Можно ли по этой реплике ждать «да» или «нет» от пилота."""
    return code in _PROPOSAL_CODES


def topic_for(code: str) -> tuple[str, int] | None:
    """(тема, ранг действенности) для кода, либо None если код вне тем."""
    return _TOPIC_BY_CODE.get(code)


def topics() -> frozenset[str]:
    return frozenset(topic for topic, _rank in _TOPIC_BY_CODE.values())

# ── TTL по категориям (окна из ТЗ §7) ────────────────────────────────────────
# None = не устаревает. Так помечены только сообщения, требующие ДЕЙСТВИЯ или
# запрошенные пилотом явно: промолчать про штраф или не ответить на вопрос
# хуже, чем ответить с задержкой.
_TTL_BY_CATEGORY: dict[str, float | None] = {
    "spotter_side": 2.0,
    "spotter_clear": 3.0,
    "box_call": 10.0,
    "pit_window": 15.0,
    "strategy": 15.0,
    "damage": 15.0,
    "tyres": 15.0,
    "weather": 30.0,
    "gap_digest": 12.0,
    "position": 12.0,
    # Похвала уместна по горячим следам, а не через полминуты: одобрение
    # опоздавшее на круг звучит как реакция на что-то другое.
    "praise": 12.0,
    # Разведка про соперника впереди устаревает вместе с обстановкой: он мог
    # уже уехать, заехать в боксы или быть обогнанным.
    "rival_intel": 15.0,
    # Вопрос, прозвучавший с опозданием, застанет пилота уже в другой
    # обстановке — и окно ответа к тому моменту закроется.
    "driver_query": 10.0,
    "battle": 10.0,
    "defense": 8.0,
    "drs": 5.0,
    "ers": 5.0,
    "fuel": 12.0,
    "track_limits": 15.0,
    "safety_car": 20.0,
    "ambient": 15.0,
    "secondary_analytics": 15.0,
    "pep_talk": 30.0,
    # Ритуалы начала и конца заезда — то же окно, что у соседнего напутствия.
    # Бессрочными их сделать нельзя (см. never_expiring_categories): TTL=None
    # даётся только тому, что требует ДЕЙСТВИЯ или запрошено пилотом. Итог
    # заезда как факт не устаревает, но проверка радио через минуту после
    # старта — уже нелепость, а категория у них одна.
    "session": 30.0,
    DEFAULT_CATEGORY: 15.0,
    "penalty": None,
    "red_flag": None,
    "ptt_answer": None,
}

# ── Срочность по коду ────────────────────────────────────────────────────────
# Только те случаи, которые ТЗ §6 называет прямо. Всё остальное — по importance
# (см. правило 2 в шапке модуля).
#
# Таблица ОБЯЗАНА перебивать `priority="critical"`, а не наоборот. Причина —
# `core/packets.py::CRITICAL_EVENTS = {PENA, RTMT, CHQF, RCWN, COLL, SCAR,
# RDFL}`: этим набором сырые события помечаются как critical с самого начала
# проекта, и в нём лежат финиш (CHQF) и определение победителя (RCWN). Это
# крупные новости, а не срочные команды — прерывать ими звучащую фразу нет
# причин. То есть существующий `priority` — это двухуровневое «важно / обычно»,
# а не «требует реакции сейчас / потом»; ТЗ §6 просит четыре уровня с другим
# смыслом. Поэтому для перечисленных здесь кодов авторитет у таблицы, а
# `priority="critical"` остаётся авторитетом для всех остальных.
#
# Старый `priority` при этом НЕ трогаем: его четыре гарантии (флор importance,
# обход cooldown, обход дедупа, прерывание) продолжают работать как раньше.
_URGENCY_BY_CODE: dict[str, str] = {
    # critical: безопасность рядом с машиной
    "SPOTTER_CAR_LEFT": URGENCY_CRITICAL,
    "SPOTTER_CAR_RIGHT": URGENCY_CRITICAL,
    "SPOTTER_CAR_BOTH": URGENCY_CRITICAL,
    # «Чисто» — тоже critical: это СНЯТИЕ предупреждения. Опоздавшее «чисто»
    # оставляет пилота в уверенности, что машина ещё рядом, — то есть вредит
    # ровно так же, как опоздавшее «слева».
    "SPOTTER_CLEAR": URGENCY_CRITICAL,
    # critical: обязательное действие прямо сейчас
    "STRAT_BOX_CALL_1": URGENCY_CRITICAL,
    "STRAT_BOX_CALL_2": URGENCY_CRITICAL,
    "STRAT_BOX_CALL_3": URGENCY_CRITICAL,
    "RDFL": URGENCY_CRITICAL,
    "PENA": URGENCY_CRITICAL,
    "ENGINEER_PENA_TRACK_LIMITS": URGENCY_CRITICAL,

    # high: меняет ход гонки, но не требует реакции в эту же секунду
    "SAFETY_CAR_DEPLOYED": URGENCY_HIGH,
    "SAFETY_CAR_ENDING": URGENCY_HIGH,
    "SAFETY_CAR_CLEAR": URGENCY_HIGH,
    "ENGINEER_RAIN_ADVISORY": URGENCY_HIGH,
    "PIT_WINDOW_APPROACH": URGENCY_HIGH,
    "STRAT_FUEL": URGENCY_HIGH,
    # Остаток legacy-набора CRITICAL_EVENTS. Все четыре — крупные новости, а не
    # команды: сход соперника, контакт, финиш и победитель ничего не требуют от
    # пилота ПРЯМО СЕЙЧАС, поэтому встают в очередь, а не рвут звучащую фразу.
    # «Опасность после контакта» — работа споттера (SPOTTER_*, ТЗ §4.1), не
    # COLL: COLL знает только, что контакт был, а не где сейчас чужая машина.
    "RTMT": URGENCY_HIGH,
    # Три градации контакта (core/engine.py::_grade_contact). Даже авария
    # остаётся high, а не critical: это по-прежнему НОВОСТЬ, а не команда — от
    # пилота она ничего не требует в эту же секунду, и рвать ради неё звучащую
    # фразу споттера нельзя. Притирка уходит в low: упомянуть можно, перебивать
    # ею что-либо — нет.
    "COLL_HEAVY": URGENCY_HIGH,
    "COLL": URGENCY_HIGH,
    "COLL_LIGHT": URGENCY_LOW,
    "CHQF": URGENCY_HIGH,
    "RCWN": URGENCY_HIGH,

    # low: атмосфера и вторичная аналитика
    "AMBIENT": URGENCY_LOW,
    "SEND": URGENCY_LOW,
    "FLBK": URGENCY_LOW,
    "F1_SECTOR_BENCH": URGENCY_LOW,
    "CAREER_SECTOR_PB": URGENCY_LOW,
}

# Повреждение: ТЗ §6 различает «существенное» (high) и «критическое»
# (critical). Порог заметности (20%) живёт в core/engine.py; здесь — вторая,
# более высокая планка «это уже опасно».
CRITICAL_DAMAGE_SEVERITY = 70

# Пороги отката по importance. До critical отсюда не дотянуться намеренно.
_IMPORTANCE_HIGH = 80
_IMPORTANCE_NORMAL = 50

# Категории, где новое сообщение вытесняет прежнее вместо того, чтобы встать за
# ним в очередь: периодические сводки о медленно меняющемся состоянии. Две
# сводки о гэпе подряд — это не диалог, это устаревшая и свежая версия одного
# и того же факта.
_REPLACEABLE_CATEGORIES: frozenset[str] = frozenset({
    "gap_digest", "position", "ers", "fuel", "tyres", "drs", "defense",
})

# Человеческие названия для UI. Критерий готовности №11: пользователь не должен
# видеть сырые коды. Ключ — КАТЕГОРИЯ, а не код: 7 DRS-кодов не нуждаются в 7
# разных заголовках.
_UI_TITLE_BY_CATEGORY: dict[str, str] = {
    "spotter_side": "Машина рядом",
    "spotter_clear": "Чисто",
    "box_call": "Команда в боксы",
    "pit_window": "Окно пит-стопа",
    "strategy": "Стратегия",
    "damage": "Повреждение",
    "tyres": "Резина",
    "weather": "Погода",
    "gap_digest": "Разрывы",
    "position": "Позиция",
    "battle": "Борьба",
    "defense": "Оборона",
    "drs": "DRS",
    "ers": "ERS",
    "fuel": "Топливо",
    "track_limits": "Пределы трассы",
    "penalty": "Штраф",
    "red_flag": "Красный флаг",
    "safety_car": "Safety Car",
    "ambient": "Обстановка",
    "secondary_analytics": "Аналитика",
    "ptt_answer": "Ответ инженера",
    "pep_talk": "Перед стартом",
    DEFAULT_CATEGORY: "Сообщение",
}


def channel_for(event: Mapping[str, object]) -> str:
    """Кто говорит: spotter / engineer / commentator.

    Порядок: явный список споттера → явный список инженера → маркер
    `speaker="engineer"` (страховка для кода, забытого в таблице) → комментатор
    по умолчанию.
    """
    code = str(event.get("event_code") or "")
    if code in _SPOTTER_CODES:
        return CHANNEL_SPOTTER
    if code in _ENGINEER_CODES:
        return CHANNEL_ENGINEER
    if event.get("speaker") == _SPEAKER_ENGINEER_MARKER:
        return CHANNEL_ENGINEER
    return CHANNEL_COMMENTATOR


def speaker_label_for(channel: str) -> str:
    return _SPEAKER_LABEL.get(channel, _SPEAKER_LABEL[CHANNEL_COMMENTATOR])


def voice_persona_for(channel: str) -> str | None:
    """Персона TTS. None = текущая персона пользователя (комментатор)."""
    return _VOICE_PERSONA.get(channel)


def category_for(code: str) -> str:
    return _CATEGORY_BY_CODE.get(code, DEFAULT_CATEGORY)


def urgency_for(event: Mapping[str, object]) -> str:
    """critical / high / normal / low.

    Порядок разрешения:
      1. severity повреждения — единственный числовой критерий, который ТЗ §6
         просит различать внутри одной категории («существенное» vs
         «критическое»);
      2. таблица кодов — авторитет для всего, что в ней названо. Перебивает и
         importance (SC приходит с 90, но прерывать спотера не должен), и
         legacy-`priority` (см. комментарий над `_URGENCY_BY_CODE`);
      3. `priority == "critical"` — для кодов вне таблицы: воля публикующего
         кода остаётся в силе там, где таблица молчит;
      4. importance — для всего остального.
    """
    code = str(event.get("event_code") or "")

    if category_for(code) == "damage":
        severity = event.get("damage_severity")
        if isinstance(severity, (int, float)) and severity >= CRITICAL_DAMAGE_SEVERITY:
            return URGENCY_CRITICAL
        return URGENCY_HIGH

    listed = _URGENCY_BY_CODE.get(code)
    if listed is not None:
        return listed

    if event.get("priority") == "critical":
        return URGENCY_CRITICAL

    importance = event.get("importance", _IMPORTANCE_NORMAL)
    try:
        importance = int(importance)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        importance = _IMPORTANCE_NORMAL
    if importance >= _IMPORTANCE_HIGH:
        return URGENCY_HIGH
    if importance >= _IMPORTANCE_NORMAL:
        return URGENCY_NORMAL
    return URGENCY_LOW


def ttl_for(code: str) -> float | None:
    """Окно жизни сообщения в секундах, либо None если оно не устаревает."""
    return _TTL_BY_CATEGORY.get(category_for(code), _TTL_BY_CATEGORY[DEFAULT_CATEGORY])


def expires_at_for(code: str, created_at: float) -> float | None:
    """Абсолютный дедлайн, отсчитанный ОТ МОМЕНТА СОБЫТИЯ (ТЗ §7)."""
    ttl = ttl_for(code)
    return None if ttl is None else created_at + ttl


def interrupt_policy_for(urgency: str, category: str) -> str:
    if urgency == URGENCY_CRITICAL:
        return POLICY_INTERRUPT
    if urgency == URGENCY_HIGH:
        return POLICY_NEXT
    if urgency == URGENCY_LOW:
        return POLICY_DROP_IF_BUSY
    if category in _REPLACEABLE_CATEGORIES:
        return POLICY_REPLACE
    return POLICY_NEXT


def ui_title_for(code: str) -> str:
    """Человеческое название сообщения для UI (критерий готовности №11)."""
    return _UI_TITLE_BY_CATEGORY.get(
        category_for(code), _UI_TITLE_BY_CATEGORY[DEFAULT_CATEGORY])


def known_codes() -> frozenset[str]:
    """Все коды, о которых policy что-то знает. Для тестов на связность таблиц."""
    return frozenset(
        _SPOTTER_CODES | _ENGINEER_CODES
        | frozenset(_CATEGORY_BY_CODE) | frozenset(_URGENCY_BY_CODE)
    )


def ttl_categories() -> frozenset[str]:
    """Категории, для которых задан TTL. Для тестов на связность таблиц."""
    return frozenset(_TTL_BY_CATEGORY)


def never_expiring_categories() -> frozenset[str]:
    """Категории без срока жизни.

    Список закрыт и зафиксирован тестом: бессрочность — не «на всякий случай», а
    обоснованное исключение. Обоснование сегодня одно из двух — либо сообщение
    требует ДЕЙСТВИЯ (штраф, красный флаг), либо пилот запросил его САМ
    (ответ на PTT). Промолчать в этих случаях хуже, чем ответить с опозданием.
    Добавление четвёртой категории должно требовать правки теста, а не проходить
    незаметно."""
    return frozenset(
        category for category, ttl in _TTL_BY_CATEGORY.items() if ttl is None)
