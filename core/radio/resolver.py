"""
core/radio/resolver.py
========================
Финальное разрешение быстро меняющихся данных — единственная точка, где
`RadioMessage` превращается в готовый для TTS текст.

Зачем отдельный этап. Между публикацией события и звуком в динамике проходят
десятки секунд: очередь событий, блокирующая пауза `MIN_COMMENT_GAP` (до 9 с),
очередь воспроизведения (до 8 фраз), сетевой синтез Yandex. Заряд ERS успевает
пройти за это время полный цикл разряд-заряд, поэтому число, вписанное в текст
при публикации, к моменту озвучки заведомо неверно (жалоба «батарея вечно
называет не те цифры»). Полная хронология с точками времени —
`docs/superpowers/specs/2026-07-29-f1-manager-radio-redesign.md`, §13.

Резолвер вызывается ПОСЛЕ обеих очередей и паузы, но ДО вычисления cache key и
до сети. Второй раз актуальность проверяется перед самым playback: Yandex может
вернуть звук, когда сообщение уже неактуально.

Здесь нет чтения телеметрии: снимок передают аргументом. Это делает резолвер
чистым и полностью тестируемым без движка.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
import logging
import re
from typing import Any

from core.radio import phrases
from core.radio.message import RadioCancelReason, RadioMessage, ResolvedRadioMessage

_log = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"\{([^{}]*)\}")


class FieldPolicy(str, Enum):
    """Что делать с полем на финальном этапе."""

    #: Взять текущее значение из снимка.
    REFRESH = "refresh"
    #: Значения нет или оно недостоверно — убрать клаузу целиком, остальное
    #: сказать. Молчание про батарею лучше, чем «Батарея —%».
    OMIT_CLAUSE = "omit_clause"
    #: Без этого значения реплика теряет смысл — отменить целиком.
    CANCEL = "cancel"
    #: Исторический факт: «ты вышел из боксов на P5» остаётся верным, даже если
    #: позиция уже другая. Обновлять нельзя.
    KEEP_ORIGINAL = "keep_original"


@dataclass(frozen=True, slots=True)
class Cancellation:
    """Отказ озвучивать с машинно-читаемой причиной."""

    reason: RadioCancelReason
    detail: str = ""


# ── Политика по полю ─────────────────────────────────────────────────────────
# Централизованно: раньше решение «обновлять или нет» существовало только для
# ERS и было вписано в один if внутри движка.
#
# Поле здесь — токен фразы, не имя телеметрии. Политика «что делать, если
# значения нет» задаётся отдельно от «обновлять ли»: у gap и ers одинаковый
# REFRESH, но разная реакция на пропажу данных, потому что «Отрыв впереди»
# без числа не значит ничего, а сводка без клаузы про батарею — значит.
_FIELD_POLICY: dict[str, FieldPolicy] = {
    "ers": FieldPolicy.REFRESH,
    "gap": FieldPolicy.REFRESH,
    "gap_behind": FieldPolicy.REFRESH,
    "position": FieldPolicy.REFRESH,
    "wear": FieldPolicy.REFRESH,
    "fuel": FieldPolicy.REFRESH,
    "laps": FieldPolicy.REFRESH,
    "minutes": FieldPolicy.REFRESH,
    # Имя соперника и состав шин — исторические факты этой реплики. Подменять
    # их на текущие значит сказать про другого пилота или другой комплект.
    "rival": FieldPolicy.KEEP_ORIGINAL,
    "compound": FieldPolicy.KEEP_ORIGINAL,
}

# Реакция на отсутствие значения, по полю. Дефолт — отменить всю реплику:
# безопаснее промолчать, чем произнести фразу с дырой.
_MISSING_POLICY: dict[str, FieldPolicy] = {
    "ers": FieldPolicy.OMIT_CLAUSE,
    "wear": FieldPolicy.OMIT_CLAUSE,
    # OMIT_CLAUSE, а не CANCEL: сводка склеивается из частей, и пропажа
    # разрыва сзади не должна убивать реплику про разрыв впереди. Для
    # ОДИНОЧНОЙ гэп-реплики поведение не меняется: выброс единственной
    # клаузы оставляет пустой текст, и резолвер отменяет её сам
    # ("all clauses omitted").
    "gap": FieldPolicy.OMIT_CLAUSE,
    "gap_behind": FieldPolicy.OMIT_CLAUSE,
    "position": FieldPolicy.CANCEL,
    "minutes": FieldPolicy.CANCEL,
    "laps": FieldPolicy.CANCEL,
    # Топливо — особый случай: критическое предупреждение нельзя терять только
    # из-за отсутствия точного числа. Клауза с числом убирается, а команда
    # «режим экономии» остаётся (ТЗ §5, fuel).
    "fuel": FieldPolicy.OMIT_CLAUSE,
}

# Санитарные диапазоны. Значение вне диапазона — это уехавший после патча игры
# офсет, а не гоночный факт: «Батарея 4200%» произносить нельзя.
_SANITY: dict[str, tuple[float, float]] = {
    "ers": (0.0, 100.0),
    "wear": (0.0, 100.0),
    "fuel": (0.0, 200.0),
    "position": (1.0, 22.0),
    # Гэп в МИЛЛИСЕКУНДАХ (так его отдаёт телеметрия), не в секундах: 600_000 —
    # десять минут, заведомо больше любого реального разрыва на круге. Диапазон
    # в секундах отсекал бы совершенно нормальный отрыв 1,3 с (1300 мс).
    "gap": (0.0, 600_000.0),
    "gap_behind": (0.0, 600_000.0),
    "minutes": (0.0, 180.0),
    "laps": (0.0, 100.0),
}

# Поля, чьё значение читается из снимка телеметрии под другим именем.
_SNAPSHOT_KEY: dict[str, str] = {
    "ers": "ers_percent",
    "gap": "gap_front_ms",
    "gap_behind": "gap_behind_ms",
    "position": "position",
    "wear": "tyre_wear",
    "fuel": "fuel_kg",
    "laps": "laps_remaining",
    "minutes": "rain_minutes",
}


def policy_for(field: str) -> FieldPolicy:
    """Политика обновления поля. Незнакомое поле не обновляем — для него нет
    источника, и попытка «освежить» превратила бы его в дыру."""
    return _FIELD_POLICY.get(field, FieldPolicy.KEEP_ORIGINAL)


def missing_policy_for(field: str) -> FieldPolicy:
    return _MISSING_POLICY.get(field, FieldPolicy.CANCEL)


def is_sane(field: str, value: float) -> bool:
    low, high = _SANITY.get(field, (float("-inf"), float("inf")))
    return low <= value <= high


def _read(snapshot: Mapping[str, Any], field: str) -> Any:
    return snapshot.get(_SNAPSHOT_KEY.get(field, field))


# ── Форматирование ───────────────────────────────────────────────────────────
# Централизованно, потому что русское согласование числительных нельзя оставлять
# в шаблоне: «через {minutes} минут» даёт «через 1 минут». Токен раскрывается в
# полный согласованный фрагмент вместе с единицей (конвенция — см. шапку
# core/radio/phrases.py).

def _format(field: str, value: Any) -> str | None:
    from core.num_to_words import ru_plural

    if field == "ers":
        return f"{round(float(value))} " + ru_plural(
            round(float(value)), "процент", "процента", "процентов")
    if field == "wear":
        return f"{round(float(value))} " + ru_plural(
            round(float(value)), "процент", "процента", "процентов")
    if field in ("gap", "gap_behind"):
        # Гэп приходит в миллисекундах, произносится в секундах с одним знаком.
        seconds = float(value) / 1000.0
        return f"{seconds:.1f}".replace(".", ",")
    if field == "position":
        return position_word(value)
    if field == "fuel":
        kg = round(float(value), 1)
        return f"{kg:.1f}".replace(".", ",") + " " + ru_plural(
            int(kg), "килограмм", "килограмма", "килограммов")
    if field == "laps":
        return f"{int(value)} " + ru_plural(int(value), "круг", "круга", "кругов")
    if field == "minutes":
        return f"{int(value)} " + ru_plural(
            int(value), "минуту", "минуты", "минут")
    return str(value)


_POSITION_WORD: dict[int, str] = {
    1: "первый", 2: "второй", 3: "третий", 4: "четвёртый", 5: "пятый",
    6: "шестой", 7: "седьмой", 8: "восьмой", 9: "девятый", 10: "десятый",
    11: "одиннадцатый", 12: "двенадцатый", 13: "тринадцатый",
    14: "четырнадцатый", 15: "пятнадцатый", 16: "шестнадцатый",
    17: "семнадцатый", 18: "восемнадцатый", 19: "девятнадцатый",
    20: "двадцатый", 21: "двадцать первый", 22: "двадцать второй",
}


def position_word(value: Any) -> str:
    """Позиция словом: 4 -> «четвёртый».

    Публичная, потому что позицию произносит не только волатильный путь. Итог
    сессии (`session.result`, `core/engine.py`) подставляет её как обычное
    required-поле — там `render()` кладёт значение как есть, и число вместо
    слова дало бы «Финиш. 4 — так и запишем.». Держать вторую копию таблицы
    числительных в движке нельзя по той же причине, по которой форматирование
    вообще собрано здесь (см. шапку раздела «Форматирование»)."""
    return _POSITION_WORD.get(int(value), f"на {int(value)} месте")


def _omit_clause(text: str, field: str) -> str:
    """Убрать предложение, содержащее токен поля.

    Клауза удаляется ЦЕЛИКОМ, а не заменяется пустой строкой: «Батарея .»
    звучит хуже молчания. Границы предложения — точка, восклицательный или
    вопросительный знак."""
    token = "{" + field + "}"
    parts = re.split(r"(?<=[.!?])\s+", text)
    kept = [part for part in parts if token not in part]
    return " ".join(kept).strip()


# ── Проверки «ситуация ещё та же» ────────────────────────────────────────────
# Числа обновить недостаточно: реплика может стать неверной не потому, что
# значение устарело, а потому, что закончилась сама ситуация. Свежий гэп до
# ДРУГОГО пилота — это не обновление, это ложь.
#
# Каждая проверка читает текущее состояние из снимка и сравнивает со снимком
# МОМЕНТА СОБЫТИЯ (`message.source_snapshot`). Guard возвращает Cancellation или
# None, ключ — категория сообщения.

def _guard_target(message: RadioMessage,
                  snapshot: Mapping[str, Any]) -> Cancellation | None:
    """Соперник, про которого реплика, должен быть тем же.

    Гэп обновляется, а вот цель — нет: сказать свежий разрыв до пилота, которого
    игрок уже обогнал, хуже, чем промолчать."""
    was = message.source_snapshot.get("gap_target_idx")
    if was is None:
        return None
    now = snapshot.get("gap_target_idx")
    if now is None:
        return Cancellation(RadioCancelReason.TARGET_CHANGED, "target gone")
    if now != was:
        return Cancellation(RadioCancelReason.TARGET_CHANGED,
                            f"{was} -> {now}")
    return None


def _guard_tyre_set(message: RadioMessage,
                    snapshot: Mapping[str, Any]) -> Cancellation | None:
    """Предупреждение про СТАРЫЙ комплект нельзя переносить на новый.

    Состав и момент установки — исторические факты; если после публикации был
    пит-стоп, реплика про износ относится к резине, которой на машине больше
    нет."""
    was = message.source_snapshot.get("tyre_set_id")
    if was is None:
        return None
    now = snapshot.get("tyre_set_id")
    if now is not None and now != was:
        return Cancellation(RadioCancelReason.SITUATION_ENDED,
                            f"tyre set {was} -> {now}")
    return None


def _guard_pit(message: RadioMessage,
               snapshot: Mapping[str, Any]) -> Cancellation | None:
    """Команда в боксы бессмысленна, если игрок уже в пит-лейне.

    `pit_status`: 0 — на трассе, 1/2 — в пит-лейне или на стопе."""
    if snapshot.get("pit_status"):
        return Cancellation(RadioCancelReason.SITUATION_ENDED, "already pitting")
    return None


def _guard_pit_window(message: RadioMessage,
                      snapshot: Mapping[str, Any]) -> Cancellation | None:
    if snapshot.get("pit_status"):
        return Cancellation(RadioCancelReason.SITUATION_ENDED, "already pitting")
    # Окно закрылось, пока сообщение ждало — уведомление уже неверно.
    if message.source_snapshot.get("pit_window_open") and not snapshot.get(
            "pit_window_open", True):
        return Cancellation(RadioCancelReason.SITUATION_ENDED, "window closed")
    return None


# Фаза Safety Car, которую утверждает реплика, и то, чему она противоречит.
_SC_REQUIRES_ACTIVE: frozenset[str] = frozenset({
    "flag.safety_car_deployed", "flag.safety_car_ending",
})


def _guard_safety_car(message: RadioMessage,
                      snapshot: Mapping[str, Any]) -> Cancellation | None:
    """«Safety Car на трассе» не должно звучать после зелёного флага, а
    «возобновляемся» — после нового выезда машины безопасности."""
    status = snapshot.get("safety_car_status")
    if status is None:
        return None
    code = message.phrase_code or ""
    if code in _SC_REQUIRES_ACTIVE and not status:
        return Cancellation(RadioCancelReason.SITUATION_ENDED,
                            "safety car already cleared")
    if code == "flag.safety_car_clear" and status:
        return Cancellation(RadioCancelReason.SITUATION_ENDED,
                            "safety car active again")
    if code:
        return None
    # Фразы без кода банка (ответ на вопрос пилота про SC) сверяем по снимку:
    # фаза сменилась — ответ описывает уже не то, что на трассе.
    was = message.source_snapshot.get("safety_car_status")
    if was is not None and was != status:
        return Cancellation(RadioCancelReason.SITUATION_ENDED,
                            f"safety car phase {was} -> {status}")
    return None


_SITUATION_GUARDS: dict[str, tuple] = {
    "gap_digest": (_guard_target,),
    "battle": (_guard_target,),
    "tyres": (_guard_tyre_set,),
    "box_call": (_guard_pit,),
    "pit_window": (_guard_pit_window,),
    "safety_car": (_guard_safety_car,),
}


def check_situation(message: RadioMessage,
                    snapshot: Mapping[str, Any]) -> Cancellation | None:
    """Ситуация ещё та же? Cancellation с причиной, либо None."""
    for guard in _SITUATION_GUARDS.get(message.category, ()):
        outcome = guard(message, snapshot)
        if outcome is not None:
            return outcome
    return None


def resolve_for_playback(
    message: RadioMessage,
    snapshot: Mapping[str, Any],
    now_mono: float,
) -> ResolvedRadioMessage | Cancellation:
    """Собрать финальный текст на момент, максимально близкий к синтезу.

    Возвращает либо `ResolvedRadioMessage` (текст готов, можно синтезировать),
    либо `Cancellation` с машинно-читаемой причиной. Исключений не бросает: этот
    вызов стоит на пути живого воркера, и падение здесь остановило бы озвучку
    целиком.
    """
    try:
        return _resolve(message, snapshot, now_mono)
    except Exception as exc:  # noqa: BLE001
        _log.warning("radio resolve failed for %s (%s): %r",
                     message.id, message.phrase_code, exc, exc_info=True)
        return Cancellation(RadioCancelReason.RESOLVE_FAILED, repr(exc))


def _resolve(
    message: RadioMessage,
    snapshot: Mapping[str, Any],
    now_mono: float,
) -> ResolvedRadioMessage | Cancellation:
    if message.is_expired(now_mono):
        return Cancellation(
            RadioCancelReason.EXPIRED,
            f"ttl={message.ttl} age={now_mono - message.created_mono:.1f}s")

    # Ситуация проверяется ДО подстановки чисел: свежий гэп до другого пилота
    # не нужно даже считать.
    ended = check_situation(message, snapshot)
    if ended is not None:
        return ended

    text = message.phrase or ""
    if not text.strip():
        return Cancellation(RadioCancelReason.DATA_UNAVAILABLE, "empty phrase")

    # Почему клауза выпала, если выпала. Нужно для ТОЧНОЙ причины отмены, когда
    # выброшено всё: «данных нет» и «данные невозможны» — разные диагнозы, и
    # второй означает уехавший офсет парсера, а не отсутствие телеметрии.
    dropped_as_invalid = False
    for field in sorted(_TOKEN_RE.findall(text)):
        outcome = _resolve_field(text, field, message, snapshot)
        if isinstance(outcome, Cancellation):
            return outcome
        if outcome != text and outcome.count("{") < text.count("{"):
            dropped_as_invalid = dropped_as_invalid or _was_invalid(
                field, snapshot)
        text = outcome

    leftover = _TOKEN_RE.findall(text)
    if leftover:
        # Строку с неразрешёнными токенами нельзя ни произносить, ни кэшировать.
        return Cancellation(
            RadioCancelReason.DATA_UNAVAILABLE,
            f"unresolved={sorted(leftover)}")

    text = " ".join(text.split())
    if not text:
        return Cancellation(
            RadioCancelReason.INVALID_DATA if dropped_as_invalid
            else RadioCancelReason.DATA_UNAVAILABLE,
            "all clauses omitted")

    return ResolvedRadioMessage(
        message_id=message.id,
        text=text,
        resolved_at_mono=now_mono,
        source_message=message,
    )


def _resolve_field(
    text: str,
    field: str,
    message: RadioMessage,
    snapshot: Mapping[str, Any],
) -> str | Cancellation:
    token = "{" + field + "}"
    policy = policy_for(field)

    if policy is FieldPolicy.KEEP_ORIGINAL:
        # Исторический факт: берём значение из снимка МОМЕНТА СОБЫТИЯ, а не
        # текущего. Снимок события живёт в message.source_snapshot.
        original = message.source_snapshot.get(field)
        if original is None:
            return _missing(text, field, message)
        return text.replace(token, str(original))

    value = _read(snapshot, field)
    if value is None:
        return _missing(text, field, message)

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return text.replace(token, str(value))

    if not is_sane(field, numeric):
        _log.info("radio resolve: %s out of range for %s: %r",
                  field, message.id, value)
        if missing_policy_for(field) is FieldPolicy.OMIT_CLAUSE:
            return _omit_clause(text, field)
        return Cancellation(RadioCancelReason.INVALID_DATA,
                            f"{field}={value!r}")

    formatted = _format(field, numeric)
    if formatted is None:
        return _missing(text, field, message)
    return text.replace(token, formatted)


def _was_invalid(field: str, snapshot: Mapping[str, Any]) -> bool:
    """Значение было, но вне допустимого диапазона (в отличие от «его нет»)."""
    raw = _read(snapshot, field)
    if raw is None:
        return False
    try:
        return not is_sane(field, float(raw))
    except (TypeError, ValueError):
        return False


def _missing(text: str, field: str, message: RadioMessage) -> str | Cancellation:
    if missing_policy_for(field) is FieldPolicy.OMIT_CLAUSE:
        return _omit_clause(text, field)
    return Cancellation(RadioCancelReason.DATA_UNAVAILABLE, f"no {field}")


def volatile_fields_of(message: RadioMessage) -> frozenset[str]:
    """Поля позднего связывания сообщения.

    Из спеки банка, если код известен, иначе из токенов самого текста — часть
    фраз собирается трекерами напрямую (`gap_digest` с `{ers_clause}`)."""
    if message.phrase_code:
        try:
            return phrases.spec_for(message.phrase_code).volatile_fields
        except phrases.PhraseError:
            pass
    return frozenset(_TOKEN_RE.findall(message.phrase or ""))
