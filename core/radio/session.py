"""
core/radio/session.py
=======================
Состояние радиообмена для интерфейса: что звучит сейчас, что было раньше, и что
именно повторить по команде «повтори».

Почему отдельный модуль, а не поля в движке. Три причины. Первая: это
единственный владелец истории, и её лимит должен быть в одном месте — иначе за
двухчасовую гонку список растёт без предела. Вторая: «последнее завершённое
инженерское сообщение» обязано отличаться от «последнего события» и от
«прерванной реплики», а такие различия быстро расползаются по движку в виде
четырёх почти одинаковых полей. Третья: проекция в UI должна собираться под
одним локом и отдавать только сериализуемое.

Разграничение, которое легко потерять (ТЗ §12): «повтори» повторяет ТОЛЬКО
последнее ПОЛНОСТЬЮ ПРОЗВУЧАВШЕЕ сообщение ИНЖЕНЕРСКОГО канала. Не последнее
событие, не текст комментатора, не прерванную на полуслове реплику и не
отменённую до озвучки. Иначе «повтори» после прерывания повторяет то, чего пилот
не слышал целиком, — то есть отвечает не на заданный вопрос.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable
import threading
import time
from typing import Any

from core.radio import policy, speakers
from core.radio.message import (
    STATE_COMPLETED,
    STATE_INTERRUPTED,
    STATE_PLAYING,
    STATE_SYNTHESIZING,
    RadioMessage,
)

#: Сколько передач держим в истории. Плотная техническая лента, а не чат.
#: 150 строк покрывают гоночный отрезок целиком и укладываются в вилку ТЗ §11
#: (100–200). Верхняя граница существует не ради памяти, а ради стоимости
#: сериализации: история уходит в каждый снимок `/api/state`.
MAX_HISTORY = 150

# Состояния PTT — те же, что уже отдаёт `state["voice_query"]` (см.
# core/ui_state.py). Продублированы здесь как константы, чтобы проекция радио не
# зависела от порядка полей в другой секции.
PTT_IDLE = "idle"
PTT_LISTENING = "listening"
PTT_RECOGNIZING = "recognizing"
PTT_THINKING = "thinking"
PTT_DONE = "done"
PTT_ERROR = "error"

#: Кто «говорит» строку истории. `driver` — реплика пилота из PTT; остальные
#: приходят из `RadioMessage.channel`.
SOURCE_DRIVER = "driver"


class RadioSession:
    """Активная передача, история и состояние PTT-сеанса."""

    def __init__(self, *, max_history: int = MAX_HISTORY,
                 clock=time.time) -> None:
        self._lock = threading.RLock()
        self._max_history = max_history
        self._clock = clock
        self._messages: dict[str, RadioMessage] = {}
        self._history: deque[dict[str, Any]] = deque(maxlen=max_history)
        self._active_id: str | None = None
        self._last_completed_engineer: RadioMessage | None = None
        self._ptt: dict[str, Any] = self._idle_ptt()
        # Монотонный счётчик изменений. Растёт ТОЛЬКО когда состояние реально
        # поменялось: клиент опрашивает раз в 250 мс и по совпадению ревизии
        # пропускает и пересылку истории, и перерисовку (ТЗ §11, критерий 14).
        # Инкремент «на всякий случай» обесценил бы весь механизм.
        self._revision = 0
        self._persona_provider = None
        self._character_provider = None

    @staticmethod
    def _idle_ptt() -> dict[str, Any]:
        return {
            "state": PTT_IDLE, "driver_text": None,
            "engineer_text": None, "error": None, "updated_at": 0.0,
            # id инженерского сообщения, которое отвечает на текущий запрос.
            # Позволяет UI показать вопрос и ответ как один диалог, не угадывая
            # связь по времени (ТЗ §14).
            "answer_message_id": None,
        }

    # ── Персона комментатора ────────────────────────────────────────────────

    def set_persona_provider(self, provider) -> None:
        """Откуда брать выбранную персону комментатора.

        Провайдер, а не значение: персона меняется в настройках и голосовой
        командой «смени комментатора», и сессия не должна знать про оба пути.
        Ставится снаружи (`web_server.create_app`) — тот же приём, что у
        `set_hotkey_status_provider`."""
        self._persona_provider = provider

    def _persona(self) -> str | None:
        """Текущая персона, либо None если провайдер не поставлен или упал.

        Исключение здесь не имеет права уронить проекцию: подпись комментатора
        не стоит того, чтобы вместе с ней пропала вся панель радио."""
        provider = self._persona_provider
        if provider is None:
            return None
        try:
            return provider()
        except Exception:
            return None

    def set_character_provider(self, provider) -> None:
        """Откуда брать выбранного персонажа инженера (`engineer_character`).

        Отдельный провайдер, а не поле в персоне: это две независимые
        настройки, и связывать их значило бы вернуть ту самую путаницу, из-за
        которой персона комментатора однажды переименовала инженера."""
        self._character_provider = provider

    def _character(self) -> str | None:
        """Текущий персонаж инженера, либо None при отсутствии/сбое провайдера.

        Отказ читается как «персонаж по умолчанию»: карточка обязана быть
        подписана всегда, а `profile_for` на None отдаёт базовый профиль."""
        provider = self._character_provider
        if provider is None:
            return None
        try:
            return provider()
        except Exception:
            return None

    # ── Приём переходов состояний ────────────────────────────────────────────

    def note(self, message: RadioMessage) -> None:
        """Учесть снимок сообщения в его текущем состоянии.

        Идемпотентно по (id, state): движок вызывает это на каждом переходе, и
        повторный вызов с тем же состоянием не должен дублировать строку
        истории — иначе одно событие превратится в две одинаковые строки, что
        ТЗ §15 прямо запрещает."""
        with self._lock:
            previous = self._messages.get(message.id)
            self._messages[message.id] = message

            if message.state in (STATE_SYNTHESIZING, STATE_PLAYING):
                self._active_id = message.id
            elif self._active_id == message.id and message.is_terminal:
                self._active_id = None

            # Полностью прозвучавшая реплика инженера — то, что повторяет
            # «повтори». Прерванная и отменённая сюда НЕ попадают.
            if (message.state == STATE_COMPLETED
                    and message.channel == policy.CHANNEL_ENGINEER
                    and (message.phrase or "").strip()):
                self._last_completed_engineer = message

            # Ответ на запрос пилота привязывается к текущему PTT-сеансу здесь,
            # а не в движке: связь «вопрос → ответ» это свойство диалога, а
            # диалогом владеет сессия. Проверка по коду, а не по времени —
            # между вопросом и ответом успевает пройти автоматическая реплика.
            if (message.event_code in policy.PTT_ANSWER_CODES
                    and self._ptt["state"] != PTT_IDLE):
                self._ptt["answer_message_id"] = message.id

            if self._changed(previous, message):
                self._append_history(message)
                self._revision += 1

            self._prune_messages()

    @staticmethod
    def _changed(previous: RadioMessage | None, message: RadioMessage) -> bool:
        """Изменилось ли то, что видит пользователь.

        Состояния мало: позднее связывание меняет ТЕКСТ, не трогая состояние
        (`with_phrase` на пути к синтезу), и без этой проверки в ленте осталась
        бы фраза с неразрешённым токеном. Отмена меняет причину."""
        if previous is None:
            return True
        return (previous.state != message.state
                or previous.phrase != message.phrase
                or previous.cancel_reason != message.cancel_reason)

    def _append_history(self, message: RadioMessage) -> None:
        """Обновить строку истории для сообщения, либо создать её.

        Строка ОДНА на сообщение: состояние в ней меняется по месту. Заводить
        новую на каждый переход значило бы показать пользователю одну реплику
        четыре раза (queued/synthesizing/playing/completed)."""
        entry = self._history_entry(message)
        for index, existing in enumerate(self._history):
            if existing.get("id") == message.id:
                self._history[index] = entry
                return
        self._history.append(entry)

    def _history_entry(self, message: RadioMessage) -> dict[str, Any]:
        # Профиль резолвится СЕЙЧАС и замораживается в строке. Смена персоны
        # комментатора после реплики не должна переименовать того, кто её уже
        # произнёс, — иначе лента задним числом покажет неправду.
        profile = speakers.profile_for(message.channel, self._persona(),
                                       character=self._character())
        return {
            "id": message.id,
            "source": message.channel,
            "speaker": message.speaker,
            "speaker_id": profile.speaker_id,
            "speaker_name": profile.display_name,
            "speaker_role": profile.role,
            "accent": profile.accent,
            "urgency": message.urgency,
            "title": message.ui_title,
            "text": message.phrase or "",
            "state": message.state,
            "cancel_reason": (message.cancel_reason.value
                              if message.cancel_reason else None),
            "created_at": message.created_at,
            "started_at": message.started_at,
            "ended_at": message.ended_at,
        }

    def _prune_messages(self) -> None:
        """Не держать снимки сообщений, вышедших из истории.

        `_messages` нужен только для дедупликации переходов и для активного
        сообщения; без обрезки он растёт всю гонку."""
        if len(self._messages) <= self._max_history * 2:
            return
        keep = {entry["id"] for entry in self._history}
        keep.add(self._active_id)
        if self._last_completed_engineer is not None:
            keep.add(self._last_completed_engineer.id)
        self._messages = {mid: msg for mid, msg in self._messages.items()
                          if mid in keep}

    # ── Реплика пилота (PTT) ────────────────────────────────────────────────

    def note_driver_line(self, text: str) -> None:
        """Добавить в историю распознанную фразу пилота.

        Только для PTT: у автоматических сообщений реплики пилота нет, и
        придумывать её нельзя (ТЗ §13)."""
        if not (text or "").strip():
            return
        profile = speakers.DRIVER
        with self._lock:
            self._history.append({
                "id": f"driver-{len(self._history)}-{int(self._clock())}",
                "source": SOURCE_DRIVER,
                "speaker": profile.short_label,
                "speaker_id": profile.speaker_id,
                "speaker_name": profile.display_name,
                "speaker_role": profile.role,
                "accent": profile.accent,
                "urgency": policy.URGENCY_NORMAL,
                "title": "Запрос пилота",
                "text": text.strip(),
                "state": STATE_COMPLETED,
                "cancel_reason": None,
                "created_at": self._clock(),
                "started_at": None,
                "ended_at": self._clock(),
            })
            self._revision += 1

    # ── PTT-сеанс ───────────────────────────────────────────────────────────

    def set_ptt(self, state: str, *, driver_text: str | None = None,
                engineer_text: str | None = None,
                error: str | None = None) -> None:
        with self._lock:
            previous = self._ptt
            # Новый запрос закрывает предыдущий диалог: ответ на прошлый вопрос
            # не имеет права переехать в новый сеанс и выдать себя за ответ на
            # только что заданный (ТЗ §14).
            answer_id = (None if state == PTT_LISTENING
                         else previous.get("answer_message_id"))
            updated = {
                "state": state,
                "driver_text": driver_text,
                "engineer_text": engineer_text,
                "error": error,
                "updated_at": self._clock(),
                "answer_message_id": answer_id,
            }
            if self._same_ptt(previous, updated):
                return
            self._ptt = updated
            self._revision += 1

    @staticmethod
    def _same_ptt(before: dict[str, Any], after: dict[str, Any]) -> bool:
        """Совпадают ли два состояния PTT по существу.

        `updated_at` из сравнения исключён намеренно: он меняется при каждом
        вызове, и с ним ревизия росла бы на пустом месте — ровно то, от чего
        ревизия должна была защитить."""
        return all(before.get(key) == after.get(key) for key in
                   ("state", "driver_text", "engineer_text", "error",
                    "answer_message_id"))

    def ptt_state(self) -> str:
        with self._lock:
            return str(self._ptt["state"])

    # ── Запросы ─────────────────────────────────────────────────────────────

    def active(self) -> RadioMessage | None:
        with self._lock:
            return (self._messages.get(self._active_id)
                    if self._active_id else None)

    def last_completed_engineer(self) -> RadioMessage | None:
        """Последняя ПОЛНОСТЬЮ прозвучавшая реплика инженера, либо None.

        Именно её повторяет команда «повтори». Прерванная, отменённая и реплика
        комментатора здесь не появляются никогда."""
        with self._lock:
            return self._last_completed_engineer

    def repeatable_text(self) -> str | None:
        message = self.last_completed_engineer()
        return (message.phrase or "").strip() or None if message else None

    def history(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(dict(entry) for entry in self._history)

    def status(self) -> str:
        """Одно слово о состоянии канала — для заголовка панели."""
        with self._lock:
            ptt = str(self._ptt["state"])
            if ptt in (PTT_LISTENING, PTT_RECOGNIZING, PTT_THINKING):
                return ptt
            active = self._messages.get(self._active_id) if self._active_id else None
        if active is not None:
            return active.state
        return "idle"

    def to_ui_dict(self) -> dict[str, Any]:
        """JSON-safe проекция для `/api/state`.

        Собирается под локом, но НИ ОДИН лок не удерживается вызывающим после
        возврата: наружу уходят только копии простых типов (ТЗ §18)."""
        persona = self._persona()
        character = self._character()
        with self._lock:
            active = self._messages.get(self._active_id) if self._active_id else None
            history = [dict(entry) for entry in self._history]
            ptt = dict(self._ptt)
            last = self._last_completed_engineer
            revision = self._revision
        return {
            # Клиент сравнивает ревизию со своей и при совпадении не трогает ни
            # сеть, ни React-состояние. Смысл есть только пока она растёт
            # строго по делу — см. комментарий у `_revision`.
            "revision": revision,
            # Справочник профилей по каналам. Нужен интерфейсу до появления
            # активного сообщения: на «слушаю» и «проверяю данные» карточка уже
            # подписана инженером, а сообщения ещё нет. Без справочника имя
            # пришлось бы захардкодить в React — ровно то, что запрещает ТЗ §5.
            "speakers": {
                channel: {
                    "speaker_id": profile.speaker_id,
                    "speaker_name": profile.display_name,
                    "speaker_role": profile.role,
                    "speaker_initials": profile.initials,
                    "portrait_url": profile.portrait_url,
                    "accent": profile.accent,
                }
                for channel, profile in (
                    (policy.CHANNEL_ENGINEER,
                     speakers.profile_for(policy.CHANNEL_ENGINEER,
                                          character=character)),
                    (policy.CHANNEL_SPOTTER,
                     speakers.profile_for(policy.CHANNEL_SPOTTER)),
                    (policy.CHANNEL_COMMENTATOR,
                     speakers.profile_for(policy.CHANNEL_COMMENTATOR, persona)),
                    (speakers.CHANNEL_DRIVER, speakers.DRIVER),
                )
            },
            "status": self.status(),
            "active_message": (active.to_ui_dict(persona=persona,
                                                 character=character)
                               if active else None),
            "history": history,
            "ptt": ptt,
            # Что вернёт «повтори» — UI показывает это как доступное действие.
            "repeatable": (last.phrase or "") if last else None,
        }

    def revision(self) -> int:
        with self._lock:
            return self._revision

    def reset(self) -> None:
        """Новая сессия: история и активная передача обнуляются."""
        with self._lock:
            self._messages.clear()
            self._history.clear()
            self._active_id = None
            self._last_completed_engineer = None
            self._ptt = self._idle_ptt()
            # Ревизия НЕ обнуляется вместе с состоянием: клиент хранит своё
            # последнее значение, и сброс счётчика в ноль выглядел бы для него
            # как «ничего не изменилось» — панель осталась бы с историей
            # прошлой сессии до первой новой реплики.
            self._revision += 1

    def clear_history(self) -> None:
        """Очистить ленту, не трогая активную передачу и «повтори»."""
        with self._lock:
            if not self._history:
                return
            self._history.clear()
            self._revision += 1
