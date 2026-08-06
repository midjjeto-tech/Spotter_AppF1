"""
core/radio/phrases.py
=======================
Центральный банк формулировок инженерского радио-канала.

Разделение ответственности, которое нельзя размывать:

    трекер (`core/strategy_ai/*`) решает, ЧТО сказать;
    этот банк           решает, КАК коротко это сказать;
    радио-конвейер      решает, КОГДА это можно озвучить.

Поэтому здесь нет ни состояния гонки, ни телеметрии, ни стратегических решений —
только реестр `PhraseSpec` и рендер. Импортов из `commentator/` тоже нет: банк
принадлежит инженерскому конвейеру `core/radio/`.

Живёт здесь, а не в `commentator/`, чтобы не появился второй параллельный банк
рядом с уже вынесенным конвейером. Что СОЗНАТЕЛЬНО не переносилось и почему —
таблица «Инвентарь источников» в
`docs/superpowers/specs/2026-07-29-f1-manager-radio-redesign.md`.

Выбор варианта детерминирован: индекс берётся из стабильного ключа (обычно
`dedupe_key` сообщения) через crc32, а не из `random.choice()`. Следствия, ради
которых это сделано: одна и та же ситуация не меняет формулировку на каждом
пакете телеметрии, тесты воспроизводимы, и `PYTHONHASHSEED` ни на что не влияет
(встроенный `hash()` для строк солится по процессу и для этого не годится).
"""
from __future__ import annotations

import re
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from core.radio import policy

# ── Ограничения длины (ТЗ §10) ───────────────────────────────────────────────
MAX_WORDS_SPOTTER = 5
MAX_WORDS_CRITICAL = 9
MAX_WORDS_HIGH = 14
MAX_WORDS_NORMAL = 18

_MAX_WORDS_BY_URGENCY: dict[str, int] = {
    policy.URGENCY_CRITICAL: MAX_WORDS_CRITICAL,
    policy.URGENCY_HIGH: MAX_WORDS_HIGH,
    policy.URGENCY_NORMAL: MAX_WORDS_NORMAL,
    policy.URGENCY_LOW: MAX_WORDS_NORMAL,
}

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_TOKEN_RE = re.compile(r"\{([^{}]*)\}")


def word_count(phrase: str) -> int:
    """Слов в фразе. Пунктуация словом не считается (ТЗ §10)."""
    return len(_WORD_RE.findall(phrase))


def tokens_in(phrase: str) -> frozenset[str]:
    return frozenset(_TOKEN_RE.findall(phrase))


class PhraseError(ValueError):
    """Ошибка рендера: неизвестный код, недостающее или лишнее поле.

    Отдельный тип, потому что это контролируемый отказ ДО постановки в TTS, а не
    неожиданный сбой: вызывающий должен уметь его поймать и промолчать, а не
    отправить пилоту строку с фигурными скобками."""


@dataclass(frozen=True, slots=True)
class PhraseSpec:
    """Одна ситуация: что говорим, как коротко, и что нельзя отдавать LLM."""

    code: str
    variants: tuple[str, ...]
    urgency: str
    #: Поля, без которых фразу нельзя собрать. Подставляются при рендере.
    required_fields: frozenset[str] = field(default_factory=frozenset)
    #: Поля позднего связывания: остаются токенами до порога озвучки (ТЗ §8).
    #: В Task 3 они НЕ разрешаются — точку подстановки переносит Task 4.
    volatile_fields: frozenset[str] = field(default_factory=frozenset)
    #: LLM может переформулировать? По умолчанию нет (ТЗ §11).
    allow_llm: bool = False
    #: Смысловое действие, одинаковое у всех вариантов. Тест сверяет, что
    #: варианты одной спеки не расходятся в действии (нельзя, чтобы один звал в
    #: боксы, а другой советовал остаться).
    action: str = ""

    @property
    def max_words(self) -> int:
        if self.code.startswith("spotter."):
            return MAX_WORDS_SPOTTER
        return _MAX_WORDS_BY_URGENCY.get(self.urgency, MAX_WORDS_NORMAL)

    @property
    def all_fields(self) -> frozenset[str]:
        return self.required_fields | self.volatile_fields


def _spec(code: str, urgency: str, variants: tuple[str, ...], **kwargs) -> PhraseSpec:
    return PhraseSpec(code=code, urgency=urgency, variants=variants, **kwargs)


_C = policy.URGENCY_CRITICAL
_H = policy.URGENCY_HIGH
_N = policy.URGENCY_NORMAL
_L = policy.URGENCY_LOW


# ── Реестр ───────────────────────────────────────────────────────────────────
# Semantic code — стабильный, читаемый, независимый от event_code игры:
# `<секция>.<ситуация>`. Секция `spotter.` держится отдельно и получает свой,
# самый жёсткий предел длины.
#
# Вариативность там, где она безопасна. Для точных safety-команд — 1–3 почти
# идентичных варианта: пилот должен узнавать команду с первого слога, а не
# разгадывать очередную формулировку.

_SPECS: tuple[PhraseSpec, ...] = (
    # ── Споттер ──────────────────────────────────────────────────────────────
    # Сторона — ОТДЕЛЬНАЯ спека, а не вариант внутри общего пула. Держи их в
    # одном пуле — и выбор варианта начнёт решать сторону: колода однажды выдаст
    # «справа» на машину слева. ТЗ §11 запрещает отдавать сторону генерации, и
    # это касается не только LLM, но и любого выбора из общего списка.
    _spec("spotter.left", _C, (
        "Слева машина!",
        "Держи слева!",
        "Машина слева!",
    ), action="warn_left"),
    _spec("spotter.right", _C, (
        "Справа машина!",
        "Держи справа!",
        "Машина справа!",
    ), action="warn_right"),
    _spec("spotter.both", _C, (
        "Машины с обеих сторон!",
        "Зажали с двух сторон!",
    ), action="warn_both"),
    _spec("spotter.clear", _C, (
        "Чисто.",
        "Свободно.",
        "По бортам чисто.",
    ), action="clear"),

    # ── Боксы ────────────────────────────────────────────────────────────────
    # Эскалация: три tier'а — три спеки. Формулировки намеренно почти
    # одинаковые и всё короче: это команда, а не сообщение.
    _spec("box.call_1", _C, (
        "Боксы в конце круга.",
        "Заходим в этом круге.",
    ), action="pit_now"),
    _spec("box.call_2", _C, (
        "Бокс, бокс.",
        "Боксы сейчас.",
    ), action="pit_now"),
    _spec("box.call_3", _C, (
        "Бокс! Бокс!",
        "Немедленно в боксы!",
    ), action="pit_now"),
    _spec("box.notice", _N, (
        "Готовим пит-стоп.",
        "Экипаж на изготовке.",
        "Ждём тебя в боксах.",
        "Заезд планируем на этот круг.",
    ), action="pit_prepare"),
    _spec("box.window_open", _H, (
        "Окно пит-стопа открылось.",
        "Мы в окне пит-стопа.",
        "Окно открыто, можно заходить.",
        "Окно открыто. Решаем по темпу.",
    ), action="pit_window_open"),
    _spec("box.window_approach", _N, (
        "Приближаемся к окну пит-стопа.",
        "До окна пара кругов.",
        "Окно подходит, держи темп.",
        "Готовься к заезду через пару кругов.",
    ), action="pit_window_soon"),
    _spec("box.exit", _N, (
        "Вышли из боксов. Разогревай шины.",
        "Аутбокс. Набирай температуру.",
        "Ты на трассе. Шины холодные.",
        "Выехали. Первый круг аккуратно.",
    ), action="pit_exit"),

    # ── Флаги и официальные решения ──────────────────────────────────────────
    _spec("flag.safety_car_deployed", _H, (
        "Safety Car. Дельта положительная.",
        "Safety Car на трассе, сбавляй.",
        "Машина безопасности. Держи дельту.",
    ), action="safety_car_deployed"),
    _spec("flag.safety_car_ending", _H, (
        "Safety Car уходит в конце круга.",
        "Машина безопасности уезжает. Готовься.",
        "Safety Car уходит. Собирайся к рестарту.",
    ), action="safety_car_ending"),
    _spec("flag.safety_car_clear", _H, (
        "Зелёный флаг. Работаем.",
        "Гонка возобновляется, трасса чистая.",
        "Зелёный. Полный темп.",
    ), action="safety_car_clear"),
    _spec("flag.red", _C, (
        "Красный флаг. В боксы.",
        "Красный флаг! Сбавляй немедленно.",
    ), action="red_flag"),
    _spec("penalty.received", _C, (
        "Есть штраф. Слушай инструкции.",
        "Получили штраф.",
    ), action="penalty"),
    # Трек-лимиты: ЖИВОЕ предупреждение до штрафа. Отдельного объявления о
    # ШТРАФЕ за трек-лимиты здесь нет и быть не должно — этим уже занимается
    # `penalty.received`, и вторая реплика про тот же инцидент спорила бы с ней
    # (см. CONTEXT.md, предупреждение пользователя 2026-07-10).
    _spec("track_limits.warning", _H, (
        "Осторожно с лимитами трассы.",
        "Следи за пределами трассы.",
        "Держись в границах трассы.",
        "Ещё одно срезание — будет штраф.",
    ), action="track_limits_warning"),

    # ── Состояние машины ─────────────────────────────────────────────────────
    _spec("damage.wing_critical", _C, (
        "Крыло разбито. Нужен бокс.",
        "Переднее крыло всё. Заходи.",
    ), action="damage_critical"),
    _spec("damage.wing", _H, (
        "Переднее крыло повреждено. Теряем прижим.",
        "Крыло задето, аккуратнее в быстрых поворотах.",
        "Переднее крыло получило повреждение.",
        "Крыло барахлит после контакта.",
    ), action="damage_wing"),
    _spec("damage.floor", _H, (
        "Днище задето, теряем прижимную силу.",
        "Пол машины повреждён.",
        "Повреждение днища. Темп упадёт.",
        "Днище пострадало.",
    ), action="damage_floor"),
    _spec("damage.gearbox", _H, (
        "Проблема с коробкой передач.",
        "Коробка передач барахлит.",
        "Есть повреждение коробки.",
        "Трансмиссия подводит.",
    ), action="damage_gearbox"),
    _spec("damage.engine", _H, (
        "Проблема с двигателем.",
        "Двигатель повреждён.",
        "Мотор барахлит.",
        "Двигатель подаёт тревожные сигналы.",
    ), action="damage_engine"),
    _spec("damage.engine_critical", _C, (
        "Двигатель критично. В боксы.",
        "Мотор на грани. Заходи.",
    ), action="damage_critical"),

    # ── Резина, топливо, ERS ─────────────────────────────────────────────────
    _spec("tyres.cliff", _H, (
        "Шины за пределом окна.",
        "Резина сдаётся, темп уходит.",
        "Износ критический. Думаем о боксе.",
        "Шины на исходе, готовь заезд.",
    ), action="tyres_cliff"),
    _spec("tyres.wear", _N, (
        "Износ {wear}.",
        "По шинам {wear}.",
        "Износ {wear}, береги резину.",
        "Шины: {wear}. Смягчи входы.",
    # `wear` ВОЛАТИЛЬНОЕ (ТЗ §5: «wear/temperature/age могут быть volatile»):
    # износ растёт, пока фраза ждёт очереди, а после пит-стопа реплика вообще
    # относится к снятому комплекту — резолвер это отменит по `tyre_set_id`.
    ), volatile_fields=frozenset({"wear"}), action="tyres_wear"),
    _spec("tyres.ok", _N, (
        "Резина в рабочем окне.",
        "Шины держатся хорошо.",
        "По шинам всё в порядке.",
        "Резина в норме, продолжай.",
    ), action="tyres_ok"),
    # ── Стратегические рекомендации ──────────────────────────────────────────
    # Пришли из `commentator/{radio,strategist}.py`, где жили ДВУМЯ пулами на
    # одни и те же коды: `get_radio_line` вызывался раньше `strategist.
    # get_message`, поэтому для STRAT_*, маршрутизируемых в канал radio, второй
    # пул был недостижим. Здесь источник один.
    _spec("strategy.undercut", _N, (
        "Андеркат возможен. Готовься к боксам.",
        "Соперник близко — пит сейчас выведет вперёд.",
        "Окно андерката. Связывайся с боксом.",
        "Можем перебить андеркатом.",
    ), action="undercut"),
    _spec("strategy.overcut", _N, (
        "Оверкат: остаёмся, соперник заедет раньше.",
        "Шины свежие — отыграем на трассе.",
        "Держим оверкат, не заезжаем.",
        "Остаёмся дольше, это наш шанс.",
    ), action="overcut"),
    _spec("strategy.pit_window", _N, (
        "Окно пит-стопа открыто. Планируй заезд.",
        "Шины на пределе — думаем о боксах.",
        "Мы в окне, решаем по темпу.",
        "Пит-окно открылось.",
    ), action="pit_window"),
    _spec("strategy.tyre_save", _N, (
        "Береги шины, температура растёт.",
        "Снизь темп — резина деградирует.",
        "Экономь резину до пит-стопа.",
        "Чуть мягче с шинами.",
    ), action="tyre_save"),
    _spec("strategy.push_pace", _N, (
        "Можно давить — шины держат.",
        "Отрыв мал, ускоряйся.",
        "Темп есть, атакуй.",
        "Прибавляй, резина позволяет.",
    ), action="push_pace"),
    _spec("strategy.ers_save", _H, (
        "Заряд на исходе — береги деплой.",
        "Мало энергии. Экономь на выходах.",
        "Батарея садится, придержи ERS.",
        "Береги заряд, деплой экономно.",
    ), action="ers_save"),
    _spec("strategy.ers_overtake", _N, (
        "Заряд есть — жми овертейк.",
        "Полная батарея, режим атаки.",
        "Энергии хватает, атакуй сейчас.",
        "Есть заряд на обгон.",
    ), action="ers_overtake"),
    _spec("strategy.stable", _L, (
        "Стратегия стабильна. Держи темп.",
        "По плану, без изменений.",
        "Идём по стратегии.",
        "Всё по плану, держи ритм.",
    ), action="strategy_stable"),

    _spec("fuel.save", _H, (
        "Топлива мало. Режим экономии.",
        "Топливо на грани, экономь.",
        "Переходи в режим экономии топлива.",
        "Смотри расход, топлива в обрез.",
    ), action="fuel_save"),
    _spec("fuel.ok", _N, (
        "Топливо в норме.",
        "По топливу запас есть.",
        "Расход по плану.",
        "Топлива хватает, работай свободно.",
    ), action="fuel_ok"),
    _spec("ers.low", _H, (
        "Батарея пуста. Береги ERS.",
        "Заряда почти нет, экономь.",
        "ERS на нуле, копим заряд.",
        "Батарея разряжена. Снизь режим.",
    ), action="ers_save"),
    # Волатильная спека: заряд успевает измениться за время очереди и синтеза,
    # поэтому число остаётся токеном до самой озвучки (ТЗ §8, Task 4).
    _spec("ers.level", _N, (
        "Батарея {ers}.",
        "Заряд {ers}, работай по плану.",
        "ERS {ers}. Держи режим.",
        "Батарея {ers}. Хватит на атаку.",
    ), volatile_fields=frozenset({"ers"}), action="ers_report"),

    # ── Погода ───────────────────────────────────────────────────────────────
    _spec("weather.rain_soon", _H, (
        "Дождь через {minutes}. Готовь интермедиэйты.",
        "Дождь через {minutes}, следим.",
        "Через {minutes} дождь. Пока остаёмся на сликах.",
        "Осадки через {minutes}. Решение по шинам скоро.",
    # `minutes` ВОЛАТИЛЬНОЕ, не required: горизонт дождя меняется, пока фраза
    # ждёт очереди, и «дождь через 5 минут» через 20 секунд уже неправда. По
    # ТЗ §5 его надо обновлять перед озвучкой; при пропаже прогноза резолвер
    # отменит реплику целиком (`_MISSING_POLICY["minutes"] = CANCEL`).
    ), volatile_fields=frozenset({"minutes"}), action="rain_soon"),
    _spec("weather.stable", _N, (
        "Погода стабильная.",
        "Дождя пока не видно.",
        "Условия без изменений.",
        "Трасса сухая, работаем как есть.",
    ), action="weather_stable"),

    # ── Темп, позиция, борьба ────────────────────────────────────────────────
    _spec("gap.digest", _N, (
        "До машины впереди {gap}.",
        "Отрыв впереди {gap}.",
        "Разрыв {gap}. Работаем по плану.",
        "Впереди {gap}, держи темп.",
    ), volatile_fields=frozenset({"gap"}), action="gap_report"),

    # ── Фрагменты сводки по разрывам ─────────────────────────────────────────
    # Сводка не ВЫБИРАЕТСЯ, а СКЛЕИВАЕТСЯ: гэп впереди + гэп сзади + тренд
    # каждого + заряд + сравнение секторов. Поэтому здесь не одна спека с
    # вариантами, а восемь фрагментов (сторона × тренд), которые собирает
    # `compose()`. Одной спекой это выразить нельзя: комбинаций 4×4, и
    # перечислять их значило бы держать шестнадцать почти одинаковых текстов.
    #
    # Сторона — ОТДЕЛЬНЫЕ спеки, не вариант внутри пула: тот же принцип, что у
    # споттера. Выбор варианта не имеет права решать, про кого реплика.
    #
    # `gap` — разрыв ВПЕРЕДИ, `gap_behind` — СЗАДИ (разные поля снимка).
    # ТЕРМИНОЛОГИЯ. «Отрыв» — это преимущество, которое пилот ДЕРЖИТ, поэтому он
    # применим только к машине СЗАДИ. Разрыв до машины ВПЕРЕДИ — это
    # ОТСТАВАНИЕ. Прежняя формулировка «отрыв впереди» называла дефицит словом
    # для преимущества и путала два противоположных понятия.
    #
    # Второе правило — фонетическое, и оно важнее грамматики: соседние фрагменты
    # НЕ должны различаться одной буквой. «Догоняем» (мы настигаем) и
    # «Догоняют» (нас настигают) означают противоположное, а через TTS звучат
    # почти одинаково; в кокпите переспросить некого. Поэтому пары
    # догоняем/догоняют и подбираемся/подбираются здесь запрещены — есть тест.
    _spec("gap.front_first", _N, (
        "До машины впереди {gap}.",
        "Отставание {gap}.",
        "Впереди {gap}.",
    ), volatile_fields=frozenset({"gap"}), action="gap_front"),
    _spec("gap.front_closing", _N, (
        "Сокращаем отставание, {gap}.",
        "Достаём машину впереди, {gap}.",
        "Отставание падает: {gap}.",
    ), volatile_fields=frozenset({"gap"}), action="gap_front_closing"),
    _spec("gap.front_growing", _N, (
        "Впереди уходят, {gap}.",
        "Отставание растёт, {gap}.",
        # НЕ «отрывается»: отличается одной буквой от «отрываемся» в
        # gap.behind_growing, а смысл противоположный.
        "Машина впереди уезжает: {gap}.",
    ), volatile_fields=frozenset({"gap"}), action="gap_front_growing"),
    _spec("gap.front_stable", _N, (
        "Отставание стабильно, {gap}.",
        "Держим {gap} до машины впереди.",
        "Впереди ровно {gap}.",
    ), volatile_fields=frozenset({"gap"}), action="gap_front_stable"),
    _spec("gap.behind_first", _N, (
        "Отрыв от преследователя {gap_behind}.",
        "Сзади {gap_behind}.",
        "Позади {gap_behind}.",
    ), volatile_fields=frozenset({"gap_behind"}), action="gap_behind"),
    _spec("gap.behind_closing", _N, (
        "Сзади подбираются, {gap_behind}.",
        "Отрыв сзади тает: {gap_behind}.",
        "Преследователь ближе, {gap_behind}.",
    ), volatile_fields=frozenset({"gap_behind"}), action="gap_behind_closing"),
    _spec("gap.behind_growing", _N, (
        "Отрываемся, сзади {gap_behind}.",
        "Отрыв сзади растёт, {gap_behind}.",
        "Преследователь отстаёт: {gap_behind}.",
    ), volatile_fields=frozenset({"gap_behind"}), action="gap_behind_growing"),
    _spec("gap.behind_stable", _N, (
        "Отрыв сзади стабилен, {gap_behind}.",
        "Сзади держится {gap_behind}.",
        "Позади ровно {gap_behind}.",
    ), volatile_fields=frozenset({"gap_behind"}), action="gap_behind_stable"),
    _spec("position.current", _N, (
        "Ты {position}.",
        "Идёшь {position}, держи позицию.",
        "Позиция {position}. Темп ровный.",
        "Сейчас {position}. Впереди чисто.",
    ), volatile_fields=frozenset({"position"}), action="position_report"),
    _spec("position.after_pit", _N, (
        "После пит-стопа ты {position}.",
        "Вышли {position}. Догоняем.",
        "После боксов {position}, работаем.",
        "Ты {position} после заезда.",
    ), volatile_fields=frozenset({"position"}), action="position_report"),
    _spec("position.leader_change", _N, (
        "Новый лидер гонки — {rival}.",
        "Впереди теперь {rival}.",
        "{rival} возглавил гонку.",
        "Лидерство у {rival}.",
    ), required_fields=frozenset({"rival"}), action="leader_change"),
    # Все варианты используют {rival}: набор обязательных полей ОБЯЗАН быть
    # одинаковым во всех вариантах спеки, иначе рендер падал бы через раз в
    # зависимости от того, какой вариант выбрал crc32.
    _spec("battle.defend", _H, (
        "{rival} атакует. Защищай позицию.",
        "{rival} рядом, закрой внутреннюю.",
        "{rival} на крыле. Держи линию.",
        "{rival} сзади. Не открывай траекторию.",
    ), required_fields=frozenset({"rival"}), action="defend"),
    _spec("battle.held", _N, (
        "Отбился. Хорошая работа.",
        "Удержал позицию.",
        "Хорошая защита, он отстал.",
        "Не пропустил. Держим гонку.",
        "Отлично защитился.",
    ), action="defence_held"),

    # ── DRS ──────────────────────────────────────────────────────────────────
    _spec("drs.in_range", _N, (
        "Ты в зоне DRS.",
        "Меньше секунды до соперника. DRS поможет.",
        "Интервал меньше секунды, готовь DRS.",
        "Держи этот темп, DRS будет доступна.",
    ), action="drs_in_range"),
    _spec("drs.out_of_range", _N, (
        "Вышел из зоны DRS.",
        "Интервал вырос, DRS не будет.",
        "Потерял секунду до соперника.",
        "Нужно вернуть интервал меньше секунды.",
    ), action="drs_out_of_range"),
    _spec("drs.enabled", _N, (
        "DRS разрешена.",
        "Можно открывать DRS.",
        "DRS активирована.",
        "Используй DRS на ближайшей зоне.",
    ), action="drs_enabled"),
    _spec("drs.disabled", _N, (
        "DRS сейчас недоступна.",
        "DRS отключена дирекцией гонки.",
        "Гонка проходит без DRS.",
        "Использовать DRS сейчас нельзя.",
    ), action="drs_disabled"),
    _spec("drs.in_range_and_enabled", _N, (
        "Меньше секунды, DRS разрешена — атакуй.",
        "Ты в зоне DRS, и она открыта. Дави.",
        "Зона DRS и разрешение есть. Самое время.",
        "DRS открыта, соперник в секунде. Атакуй.",
    ), action="drs_attack"),

    # ── Фон и старт ──────────────────────────────────────────────────────────
    _spec("session.pep_talk", _N, (
        "Работаем по плану. Удачи на старте.",
        "Машина готова. Хорошего заезда.",
        "Всё под контролем. Спокойный старт.",
        "Готовы. Первый поворот — главное.",
    ), action="pep_talk"),
    # Единственная секция, где LLM разрешён: необязательная аналитика без
    # точных чисел и без требуемого действия (ТЗ §11).
    _spec("ambient.calm", _L, (
        "Темп ровный.",
        "Ситуация под контролем.",
        "Всё стабильно.",
        "Держим как есть.",
    ), allow_llm=True, action="ambient"),
)

REGISTRY: dict[str, PhraseSpec] = {spec.code: spec for spec in _SPECS}


# Подтверждения (ТЗ §10): короткие, вариативные, для PTT-диалога и явной команды
# пилота — а не после каждой автоматической реплики.
ACKNOWLEDGEMENTS: tuple[str, ...] = (
    "Принято.",
    "Понял.",
    "Копирую.",
    "Остаёмся на плане.",
    "Проверяем.",
    "Данные вижу.",
)

# Ответ, когда данных в снимке телеметрии нет (ТЗ §12). Короткий: длинный
# универсальный отказ звучит хуже честного «не вижу».
NO_DATA_ANSWERS: tuple[str, ...] = (
    "Данных нет.",
    "Пока не вижу.",
    "Нет данных по этому.",
    "Не вижу цифр.",
)


def spec_for(code: str) -> PhraseSpec:
    """Спека по semantic code. `PhraseError`, если кода нет в реестре."""
    try:
        return REGISTRY[code]
    except KeyError:
        raise PhraseError(f"unknown phrase code: {code!r}") from None


def select_variant(variants: tuple[str, ...], selector_key: str,
                   *, shortest: bool = False) -> str:
    """Вариант по стабильному ключу — детерминированно и воспроизводимо.

    crc32, а не встроенный `hash()`: тот солится для строк по процессу
    (`PYTHONHASHSEED`), поэтому давал бы разный выбор между запусками и ломал бы
    воспроизводимость тестов. `random` не используется вовсе: один и тот же
    `dedupe_key` обязан давать одну и ту же формулировку, иначе повторный пакет
    телеметрии по той же ситуации переписывал бы уже произнесённую реплику.

    `shortest=True` — режим «коротко» (настройка `phrase_length`): из готовых
    вариантов берётся самый лаконичный. Это НЕ отдельный банк коротких фраз и не
    обрезка текста: все варианты уже проверены на длину и смысл, режим лишь
    смещает выбор. Режима длинных монологов нет намеренно (ТЗ §17).
    """
    if not variants:
        raise PhraseError("phrase spec has no variants")
    if shortest:
        # min по (длина, текст) — при равной длине выбор остаётся
        # детерминированным, а не зависит от порядка в кортеже.
        return min(variants, key=lambda text: (len(text), text))
    index = zlib.crc32(selector_key.encode("utf-8")) % len(variants)
    return variants[index]


def render(
    code: str,
    fields: Mapping[str, Any] | None = None,
    *,
    selector_key: str,
    shortest: bool = False,
) -> str:
    """Готовая фраза по semantic code.

    `fields` подставляются в `required_fields`. `volatile_fields` СОЗНАТЕЛЬНО
    остаются токенами: их значение живёт считанные секунды, и подставлять его
    здесь, за десятки секунд до звука, — та самая ошибка «батарея называет не те
    цифры» (ТЗ §8). Точку подстановки переносит Task 4.

    `PhraseError` — контролируемый отказ ДО постановки в TTS:
    неизвестный код, недостающее обязательное поле или незнакомый токен. Лучше
    промолчать, чем произнести строку с фигурными скобками.
    """
    spec = spec_for(code)
    values = dict(fields or {})

    missing = spec.required_fields - values.keys()
    if missing:
        raise PhraseError(
            f"{code}: missing required field(s) {sorted(missing)}")

    unknown = values.keys() - spec.all_fields
    if unknown:
        raise PhraseError(f"{code}: unknown field(s) {sorted(unknown)}")

    variant = select_variant(spec.variants, selector_key, shortest=shortest)

    # Волатильные токены обязаны выжить: подставляем только required-поля.
    resolved = variant
    for name in spec.required_fields:
        resolved = resolved.replace("{" + name + "}", str(values[name]))

    leftover = tokens_in(resolved) - spec.volatile_fields
    if leftover:
        raise PhraseError(
            f"{code}: unresolved placeholder(s) {sorted(leftover)}")
    return resolved


def compose(
    codes: "Sequence[str]",
    *,
    selector_key: str,
    shortest: bool = False,
    extra: "Sequence[str]" = (),
) -> str:
    """Собрать одну реплику из нескольких фрагментов банка.

    Нужна там, где реплика не выбирается целиком, а СКЛЕИВАЕТСЯ из независимых
    кусков — сегодня это сводка по разрывам (`core/strategy_ai/gap_digest.py`):
    гэп впереди, гэп сзади, заряд, сравнение секторов. Каждый кусок появляется
    или нет по своим условиям, поэтому перечислить готовые комбинации нельзя.

    Каждый фрагмент получает СВОЙ производный селектор: иначе один и тот же
    индекс выбирался бы во всех фрагментах сразу, и сводка звучала бы
    «первый вариант + первый вариант + первый вариант» либо целиком менялась
    от круга к кругу. Ключ остаётся детерминированным.

    `extra` — готовые строки не из банка (сравнение секторов приходит из
    `core/strategy_ai/sector_comparison.py` как свободный текст). Они
    добавляются в конец как есть.

    Неизвестный код фрагмента пропускается, а не роняет всю сводку: лучше
    сказать про гэп без заряда, чем промолчать.
    """
    parts: list[str] = []
    for code in codes:
        try:
            parts.append(render(code, selector_key=f"{selector_key}:{code}",
                                shortest=shortest))
        except PhraseError:
            continue
    parts.extend(str(item).strip() for item in extra if str(item).strip())
    return " ".join(part for part in parts if part)


def acknowledge(selector_key: str = "ack") -> str:
    """Короткое подтверждение для PTT-диалога (ТЗ §10)."""
    return select_variant(ACKNOWLEDGEMENTS, selector_key)


def no_data(selector_key: str | None = None) -> str:
    """Честный короткий ответ, когда данных нет (ТЗ §12).

    Ключ по умолчанию берётся от текущего времени: у отказа нет ситуации, за
    которой его можно закрепить, а один и тот же вариант каждый раз звучал бы
    как заглушка."""
    import time
    return select_variant(NO_DATA_ANSWERS, selector_key or str(int(time.time())))


def codes() -> frozenset[str]:
    return frozenset(REGISTRY)


def specs() -> tuple[PhraseSpec, ...]:
    return _SPECS
