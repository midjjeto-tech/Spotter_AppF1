"""
core/radio/message.py
=======================
`RadioMessage` — единица радиообмена от момента, когда текст уже получен, до
момента, когда звук отыграл или был отменён.

Почему не просто строка. Между «событие случилось» и «звук пошёл» проходит
до десятков секунд (очередь событий, пауза MIN_COMMENT_GAP, очередь синтеза,
сеть Yandex, последовательное воспроизведение). За это время нужно уметь
ответить на вопросы: кто это говорит, можно ли ещё это говорить, что делать с
уже звучащей фразой, не то же ли это самое, что прозвучало 5 секунд назад, и
что показать в интерфейсе. Строка ни на один из них ответить не может.

Неизменяемость намеренная: сообщение пересекает границы трёх потоков
(commentary → tts-queue → воспроизведение). Переход состояния возвращает НОВЫЙ
объект (`with_state`), поэтому ни один поток не может испортить снимок, который
читает другой. Идентичность при этом сохраняется — `id` не меняется.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from enum import Enum
import itertools
import time
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from core.radio import policy, situations, speakers
from core.strategy_ai.gap_digest import volatile_tokens

# ── Состояния ────────────────────────────────────────────────────────────────
STATE_QUEUED = "queued"
STATE_SYNTHESIZING = "synthesizing"
STATE_PLAYING = "playing"
STATE_COMPLETED = "completed"
STATE_CANCELLED = "cancelled"
STATE_INTERRUPTED = "interrupted"

# Конечные состояния: дальше сообщение только читается (история, «повтори»).
_TERMINAL_STATES: frozenset[str] = frozenset({
    STATE_COMPLETED, STATE_CANCELLED, STATE_INTERRUPTED,
})

# Разрешённые переходы. Смысл границ:
#
#  * `queued → interrupted` ЗАПРЕЩЁН. Прервать можно только то, что уже
#    звучало; снятое из очереди до начала синтеза — это `cancelled`. Разница не
#    косметическая: «повтори» обязана игнорировать и то, и другое, но история
#    радио и диагностика должны различать «не успело зазвучать» и «оборвали на
#    полуслове».
#  * `playing → cancelled` ЗАПРЕЩЁН. Звук уже пошёл в динамик; отменить его
#    задним числом нельзя, можно только прервать.
#  * из конечных состояний переходов нет вообще.
#  * `queued → completed` РАЗРЕШЁН, и это не дыра в инварианте: так завершается
#    сообщение, доставленное БЕЗ звука — авто-озвучка выключена, канал приглушён
#    порогом важности, или TTS недоступен. Оно честно выполнило свою работу
#    (субтитр на HUD и строка в ленте), поэтому `cancelled` было бы неправдой:
#    ничего не сломалось и никто его не вытеснял.
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    STATE_QUEUED: frozenset({STATE_SYNTHESIZING, STATE_PLAYING,
                             STATE_COMPLETED, STATE_CANCELLED}),
    STATE_SYNTHESIZING: frozenset({STATE_PLAYING, STATE_CANCELLED, STATE_INTERRUPTED}),
    STATE_PLAYING: frozenset({STATE_COMPLETED, STATE_INTERRUPTED}),
    STATE_COMPLETED: frozenset(),
    STATE_CANCELLED: frozenset(),
    STATE_INTERRUPTED: frozenset(),
}

_STATES: frozenset[str] = frozenset(_ALLOWED_TRANSITIONS)

_ID_PREFIX = "radio-"
_ids = itertools.count(1)

_EMPTY_SNAPSHOT: Mapping[str, Any] = MappingProxyType({})


class RadioCancelReason(str, Enum):
    """Почему сообщение не прозвучало.

    Структурированная причина, а не строка в логе: она нужна тестам, позже
    попадёт в историю радио и в UI, и по ней видно разницу между «данных не
    стало» и «ситуация закончилась». В TTS не уходит никогда и в промпты
    RaceFeed тоже — это внутреннее состояние конвейера."""

    EXPIRED = "expired"                     # истёк TTL
    SUPERSEDED = "superseded"                # заменено более новым о той же ситуации
    SITUATION_ENDED = "situation_ended"      # ситуация закрылась (SC clear, выезд из боксов)
    TARGET_CHANGED = "target_changed"        # соперник/цель сменились
    DATA_UNAVAILABLE = "data_unavailable"    # телеметрии больше нет
    INVALID_DATA = "invalid_data"            # значение вне допустимого диапазона
    QUEUE_EVICTED = "queue_evicted"          # вытеснено из очереди воспроизведения
    SESSION_RESET = "session_reset"          # новая сессия
    FLASHBACK = "flashback"                  # игрок перемотал, событие из будущего
    STOPPED = "stopped"                      # остановка приложения
    RESOLVE_FAILED = "resolve_failed"        # сбой позднего связывания


@dataclass(frozen=True, slots=True)
class RadioMessage:
    """Неизменяемый снимок одной радио-передачи."""

    id: str
    event_code: str
    channel: str
    category: str
    urgency: str
    speaker: str
    voice_persona: str | None
    #: Текст фразы. До финального резолва может содержать волатильные токены —
    #: это НЕ готовый для TTS текст (тот живёт в `ResolvedRadioMessage`).
    phrase: str | None
    #: Semantic code банка (`core/radio/phrases.py`), если фраза оттуда. Нужен
    #: резолверу: политика полей зависит от спеки, а не от текста.
    phrase_code: str | None
    # ДВЕ шкалы времени, и путать их нельзя.
    #
    # `created_mono` / `expires_mono` — monotonic. По ним и только по ним
    # считается срок жизни: wall-clock на Windows умеет прыгать назад (NTP,
    # переход на зимнее время), и прыжок на час превратил бы «истекло 2 секунды
    # назад» в «истечёт через час» — сообщение зависло бы в очереди навсегда
    # либо, наоборот, всё разом объявилось бы просроченным.
    #
    # `created_at` — wall-clock, ТОЛЬКО для показа пользователю («21:43:12» в
    # истории радио). Monotonic для этого не годится: это секунды с
    # произвольной точки, из них нельзя получить время дня.
    created_at: float
    created_mono: float
    expires_mono: float | None
    dedupe_key: str | None
    situation_id: str | None
    # MappingProxyType, а не dict: `frozen=True` защищает только сами поля, а
    # вложенный словарь остался бы изменяемым, и снимок телеметрии «на момент
    # события» мог бы тихо поехать у нас под руками.
    source_snapshot: Mapping[str, Any]
    volatile_fields: tuple[str, ...]
    ui_title: str
    ui_summary: str | None
    state: str = STATE_QUEUED
    started_at: float | None = None
    ended_at: float | None = None
    #: Причина, по которой сообщение не прозвучало. Заполняется вместе с
    #: переходом в cancelled/interrupted.
    cancel_reason: RadioCancelReason | None = None

    # ── Предикаты ────────────────────────────────────────────────────────────

    @property
    def is_terminal(self) -> bool:
        return self.state in _TERMINAL_STATES

    @property
    def is_critical(self) -> bool:
        return self.urgency == policy.URGENCY_CRITICAL

    @property
    def ttl(self) -> float | None:
        """Окно жизни в секундах, либо None если сообщение не устаревает."""
        return (None if self.expires_mono is None
                else self.expires_mono - self.created_mono)

    @property
    def expires_at(self) -> float | None:
        """Дедлайн в wall-clock — ТОЛЬКО для показа в UI.

        Пересчитывается из monotonic-окна, а не хранится: хранить два
        независимых дедлайна значило бы дать им разойтись."""
        ttl = self.ttl
        return None if ttl is None else self.created_at + ttl

    def is_expired(self, now_mono: float) -> bool:
        """Истёк ли срок жизни. Ждёт MONOTONIC время, не wall-clock."""
        return self.expires_mono is not None and now_mono > self.expires_mono

    def needs_late_binding(self) -> bool:
        return bool(self.volatile_fields)

    def can_transition_to(self, state: str) -> bool:
        return state in _ALLOWED_TRANSITIONS.get(self.state, frozenset())

    # ── Переходы ─────────────────────────────────────────────────────────────

    def with_state(self, state: str, *, now: float,
                   reason: RadioCancelReason | None = None) -> "RadioMessage":
        """Новый снимок в другом состоянии. `id` сохраняется.

        `now` — wall-clock: `started_at`/`ended_at` показываются пользователю.
        Решения о сроке жизни принимает `is_expired`, у него своя шкала.

        `reason` обязателен для `cancelled`: сообщение не должно уходить в
        небытие без объяснения — именно эту дыру («не остаётся бесследно в
        неизвестном состоянии») закрывает Task 4."""
        if state not in _STATES:
            raise ValueError(f"unknown radio message state: {state!r}")
        if not self.can_transition_to(state):
            raise ValueError(
                f"forbidden radio message transition: {self.state!r} -> {state!r}")
        if state == STATE_CANCELLED and reason is None:
            raise ValueError("cancelled radio message requires a cancel reason")
        started = now if state == STATE_PLAYING else self.started_at
        ended = now if state in _TERMINAL_STATES else self.ended_at
        return replace(
            self, state=state, started_at=started, ended_at=ended,
            cancel_reason=reason if reason is not None else self.cancel_reason)

    def cancelled(self, reason: RadioCancelReason, *, now: float) -> "RadioMessage":
        """Ярлык для самого частого перехода."""
        return self.with_state(STATE_CANCELLED, now=now, reason=reason)

    def with_phrase(self, phrase: str) -> "RadioMessage":
        """Новый снимок с подставленным текстом (позднее связывание).

        `volatile_fields` пересчитываются: после подстановки токенов в тексте
        обычно уже нет, и повторное связывание не нужно."""
        return replace(self, phrase=phrase, volatile_fields=volatile_tokens(phrase))

    # ── Проекция в UI ────────────────────────────────────────────────────────

    def to_ui_dict(self, *, persona: str | None = None) -> dict[str, Any]:
        """JSON-safe представление для `/api/state`.

        `source_snapshot` не отдаём: это внутренние данные для ре-валидации, а
        не то, что рисует интерфейс (ТЗ §18 — не гнать лишние байты).

        `persona` влияет ТОЛЬКО на профиль комментатора. Профиль не хранится в
        самом сообщении по двум причинам: он зависит от настройки, которая
        живёт снаружи, и он презентация, а не часть решения о том, что и когда
        произнести. Замораживает его вызывающий — `RadioSession` при переходе
        состояния, чтобы смена персоны задним числом не переименовала того, кто
        уже отговорил."""
        profile = speakers.profile_for(self.channel, persona)
        return {
            "id": self.id,
            "channel": self.channel,
            "category": self.category,
            "urgency": self.urgency,
            "speaker": self.speaker,
            # Презентация говорящего (ТЗ §5, §11). `portrait_url` может
            # указывать на отсутствующий файл — фронт падает на инициалы, и это
            # штатный путь, а не ошибка.
            "speaker_id": profile.speaker_id,
            "speaker_name": profile.display_name,
            "speaker_role": profile.role,
            "speaker_initials": profile.initials,
            "portrait_url": profile.portrait_url,
            "accent": profile.accent,
            "text": self.phrase or "",
            "ui_title": self.ui_title,
            "ui_summary": self.ui_summary,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "expires_at": self.expires_at,
            "state": self.state,
            "situation_id": self.situation_id,
            # Сырой код и ключ дедупликации — только для диагностики (журнал,
            # поддержка, экран «Рация» в режиме подробностей). Показывать
            # пользователю нужно ui_title, см. критерий готовности №11.
            "debug_event_code": self.event_code,
            "debug_dedupe_key": self.dedupe_key,
        }


@dataclass(frozen=True, slots=True)
class ResolvedRadioMessage:
    """Готовый для TTS текст на конкретную попытку синтеза и воспроизведения.

    Отдельный тип, а не поле в `RadioMessage`, по двум причинам. Первая:
    смешивать semantic message и готовую строку нельзя — из первого считается
    политика полей и актуальность, из второй строится cache key. Вторая: после
    резолва текст не должен меняться в пределах одной попытки, и отдельный
    frozen-объект делает это структурно невозможным."""

    message_id: str
    text: str
    resolved_at_mono: float
    source_message: "RadioMessage"

    @property
    def voice_persona(self) -> str | None:
        return self.source_message.voice_persona

    @property
    def urgency(self) -> str:
        return self.source_message.urgency


def build_message(
    event: Mapping[str, Any],
    *,
    phrase: str | None,
    phrase_code: str | None = None,
    now: float,
    now_mono: float | None = None,
    telemetry: Mapping[str, Any] | None = None,
    lap: int | None = None,
    session_id: str | None = None,
    timeline_revision: int = 0,
    ui_summary: str | None = None,
) -> RadioMessage:
    """Собрать сообщение из отобранного события и уже полученного текста.

    Обе метки времени берутся ИЗ СОБЫТИЯ, если оно их несёт: срок жизни
    считается от момента события, а не от момента сборки — между ними стоит
    очередь событий (ТЗ §7). `now`/`now_mono` — резерв для событий,
    опубликованных в обход `CommentaryEvents.publish` (так делают тесты и
    несколько прямых вызовов).

    Метка НЕ пересоздаётся ни в одном преобразовании: `with_state` и
    `with_phrase` идут через `dataclasses.replace`, который переносит её как
    есть. Единственная точка присвоения — здесь.
    """
    code = str(event.get("event_code") or "")
    channel = policy.channel_for(event)
    category = policy.category_for(code)
    urgency = policy.urgency_for(event)

    created_at = event.get("created_at")
    if not isinstance(created_at, (int, float)):
        created_at = now
    created_at = float(created_at)

    created_mono = event.get("created_mono")
    if not isinstance(created_mono, (int, float)):
        created_mono = now_mono if now_mono is not None else time.monotonic()
    created_mono = float(created_mono)

    ttl = policy.ttl_for(code)

    return RadioMessage(
        id=f"{_ID_PREFIX}{next(_ids)}",
        event_code=code,
        channel=channel,
        category=category,
        urgency=urgency,
        speaker=policy.speaker_label_for(channel),
        voice_persona=policy.voice_persona_for(channel),
        phrase=phrase,
        phrase_code=phrase_code,
        created_at=created_at,
        created_mono=created_mono,
        expires_mono=None if ttl is None else created_mono + ttl,
        dedupe_key=situations.dedupe_key(
            event, lap=lap, session_id=session_id,
            timeline_revision=timeline_revision),
        situation_id=situations.situation_id(event, lap=lap,
                                             session_id=session_id),
        # deepcopy защищает от мутации вызывающим, MappingProxyType — от мутации
        # через сам снимок. Нужны оба: без первого поедет источник, без второго
        # поедет копия.
        source_snapshot=(MappingProxyType(deepcopy(dict(telemetry)))
                         if telemetry else _EMPTY_SNAPSHOT),
        volatile_fields=volatile_tokens(phrase or ""),
        ui_title=policy.ui_title_for(code),
        ui_summary=ui_summary,
    )
