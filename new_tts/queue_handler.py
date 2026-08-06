"""
new_tts/queue_handler.py
==========================
Очередь воспроизведения с приоритетом и НАБЛЮДАЕМЫМ результатом постановки.

- critical: очищает ожидающие + прерывает текущее воспроизведение (stop_fn),
  играет первой.
- остальные: становятся в очередь по срочности, внутри срочности — FIFO.
- Каждый элемент несёт опциональный persona-override, который доставляется в
  speak_fn(text, persona) при проигрывании.

Про переполнение. Раньше здесь стояло `except queue.Full: pass` — фраза
исчезала бесследно: ни в логе, ни в UI, ни в возвращаемом значении. При всплеске
событий (контакт + штраф + споттер + сводка в одну секунду) это означало, что
инженер молча проглатывал команду, и понять это по логу было нельзя. Теперь у
каждой попытки есть исход (`EnqueueOutcome`), отказ пишется в лог, а вызывающий
получает результат и может отметить сообщение отменённым.

Порядок вытеснения устроен так, чтобы предупреждение споттера нельзя было
выбросить ради комментария: жертва ищется только СТРОГО менее срочная, чем
входящее сообщение, а споттер приходит с максимальной срочностью.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
import queue
import threading
from typing import Callable

_log = logging.getLogger(__name__)


class EnqueueOutcome(str, Enum):
    """Что произошло с попыткой поставить фразу в очередь."""

    ACCEPTED = "accepted"
    #: Принято, но пришлось выбросить менее срочное сообщение (очередь была полна).
    ACCEPTED_EVICTED = "accepted_evicted"
    #: Принято, а ожидающие сброшены — так работает critical.
    ACCEPTED_PREEMPTED = "accepted_preempted"
    #: Отказ: очередь полна, и ничего менее срочного в ней нет.
    REJECTED_FULL = "rejected_full"
    #: Отказ: очередь остановлена (shutdown).
    REJECTED_STOPPED = "rejected_stopped"


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    outcome: EnqueueOutcome
    #: id вытесненного сообщения, если вытеснение было — вызывающий обязан
    #: перевести его в `cancelled`, иначе состояние останется неизвестным.
    evicted_ids: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.outcome in _ACCEPTED_OUTCOMES


_ACCEPTED_OUTCOMES = frozenset({
    EnqueueOutcome.ACCEPTED,
    EnqueueOutcome.ACCEPTED_EVICTED,
    EnqueueOutcome.ACCEPTED_PREEMPTED,
})

# Ранг срочности: меньше = важнее. Совпадает с core/radio/policy.py, но
# продублирован намеренно — new_tts не должен зависеть от core (движок
# импортирует new_tts, обратная связь замкнула бы граф импортов).
_URGENCY_RANK: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "normal": 2,
    "low": 3,
}
_DEFAULT_RANK = _URGENCY_RANK["normal"]


@dataclass(frozen=True, slots=True)
class _Item:
    rank: int
    seq: int
    text: str
    persona: str | None
    message_id: str | None
    #: Финальное разрешение волатильных данных. Вызывается ВОРКЕРОМ, за миг до
    #: синтеза: только там позади остались и пауза MIN_COMMENT_GAP, и ожидание в
    #: этой очереди. Возвращает готовый текст либо None — «уже неактуально, не
    #: озвучивать». Очередь не знает, что внутри: телеметрия остаётся у движка.
    prepare: Callable[[], str | None] | None = None
    #: Повторная проверка перед самым playback — после сетевого синтеза, который
    #: сам занимает секунды. Читается владельцем `speak_fn` через `current_item`.
    still_valid: Callable[[], bool] | None = None
    #: Срочность реплики (`core/radio/policy.py`). Раньше она участвовала только
    #: в расчёте `rank` и на элементе не сохранялась. Теперь от неё зависит ещё
    #: и ТЕМП синтеза: владелец `speak_fn` читает её отсюда через
    #: `current_item` — тем же приёмом, что и `still_valid`, не меняя сигнатуру
    #: колбэка. Поле последнее: `_Item` создаётся позиционно.
    urgency: str | None = None

    def resolve_text(self) -> str | None:
        """Текст для синтеза, либо None если сообщение потеряло актуальность."""
        if self.prepare is None:
            return self.text
        return self.prepare()


class TTSQueue:
    def __init__(self, speak_fn: Callable[[str, str | None], None],
                 stop_fn: Callable[[], None] | None = None, maxsize: int = 8):
        self._speak_fn = speak_fn
        self._stop_fn = stop_fn            # прерывание текущего воспроизведения
        self._maxsize = maxsize
        # (rank, seq) — уникальный ключ сортировки: seq монотонен, поэтому
        # сравнение никогда не доходит до _Item и не требует от него __lt__.
        self._queue: "queue.PriorityQueue[tuple[int, int, _Item]]" = (
            queue.PriorityQueue(maxsize=maxsize))
        self._seq = 0
        # Один лок на всю составную операцию постановки: без него между clear()
        # и put_nowait() другой поток успевает заполнить очередь, и critical
        # получает REJECTED_FULL — ровно та потеря, которую мы закрываем.
        self._enqueue_lock = threading.Lock()
        self._stop = threading.Event()
        self._critical_active = threading.Event()
        self._current_item: _Item | None = None
        self._thread = threading.Thread(target=self._worker, daemon=True, name="tts-queue")
        self._thread.start()

    # ------------------------------------------------------------------ #
    # Постановка                                                          #
    # ------------------------------------------------------------------ #

    def enqueue(self, text: str, priority: str = "normal",
                persona: str | None = None, *,
                urgency: str | None = None,
                message_id: str | None = None,
                prepare: Callable[[], str | None] | None = None,
                still_valid: Callable[[], bool] | None = None) -> EnqueueResult:
        """Поставить фразу в очередь. Возвращает ИСХОД, который нельзя терять.

        `priority` — прежнее двухуровневое поле ("normal" | "critical"), от него
        зависит вытеснение ожидающих и прерывание звучащего. `urgency` — новая
        четырёхуровневая шкала (core/radio/policy.py); если не передана,
        выводится из `priority`, поэтому старые вызывающие работают как раньше.
        """
        rank = self._rank(priority, urgency)

        with self._enqueue_lock:
            if self._stop.is_set():
                _log.info("TTSQueue.enqueue rejected (stopped): %r", text)
                return EnqueueResult(EnqueueOutcome.REJECTED_STOPPED)

            if priority == "critical":
                # Critical вытесняет ВСЁ ожидающее и рвёт звучащее. Очередь
                # после этого пуста, поэтому critical физически не может
                # получить REJECTED_FULL — гарантия «critical нельзя молча
                # потерять» держится на этом, плюс на локе выше.
                dropped = self._drain_locked()
                if self._stop_fn is not None:
                    try:
                        self._stop_fn()
                    except Exception:  # noqa: BLE001
                        pass
                self._put_locked(rank, text, persona, message_id,
                                 prepare, still_valid, urgency)
                if dropped:
                    _log.info(
                        "TTSQueue: critical preempted %d pending phrase(s)",
                        len(dropped))
                    return EnqueueResult(
                        EnqueueOutcome.ACCEPTED_PREEMPTED,
                        tuple(i.message_id for i in dropped if i.message_id))
                return EnqueueResult(EnqueueOutcome.ACCEPTED_PREEMPTED)

            if self._queue.qsize() < self._maxsize:
                self._put_locked(rank, text, persona, message_id,
                                 prepare, still_valid, urgency)
                return EnqueueResult(EnqueueOutcome.ACCEPTED)

            victim = self._evict_locked(rank)
            if victim is None:
                # Ничего менее срочного нет — новое сообщение отклонено, и это
                # видно: и в логе, и в возвращаемом исходе.
                _log.warning(
                    "TTSQueue full (%d), rejecting %s phrase: %r",
                    self._maxsize, priority, text)
                return EnqueueResult(EnqueueOutcome.REJECTED_FULL)

            _log.info(
                "TTSQueue full (%d), evicted rank=%d to admit rank=%d",
                self._maxsize, victim.rank, rank)
            self._put_locked(rank, text, persona, message_id,
                             prepare, still_valid, urgency)
            return EnqueueResult(
                EnqueueOutcome.ACCEPTED_EVICTED,
                (victim.message_id,) if victim.message_id else ())

    @staticmethod
    def _rank(priority: str, urgency: str | None) -> int:
        if urgency is not None:
            return _URGENCY_RANK.get(urgency, _DEFAULT_RANK)
        return _URGENCY_RANK["critical"] if priority == "critical" else _DEFAULT_RANK

    def _put_locked(self, rank: int, text: str, persona: str | None,
                    message_id: str | None,
                    prepare: Callable[[], str | None] | None = None,
                    still_valid: Callable[[], bool] | None = None,
                    urgency: str | None = None) -> None:
        self._seq += 1
        item = _Item(rank, self._seq, text, persona, message_id,
                     prepare, still_valid, urgency)
        # put_nowait не может бросить Full: вызывающие ветки уже освободили
        # место (проверка qsize / вытеснение / полный сброс под тем же локом).
        self._queue.put_nowait((rank, item.seq, item))

    def _evict_locked(self, incoming_rank: int) -> _Item | None:
        """Выбросить самое старое сообщение СТРОГО менее срочное, чем входящее.

        Возвращает жертву, либо None если жертвы нет (тогда входящее отклоняется).
        Строгое сравнение — то, что защищает споттера: критическая реплика имеет
        ранг 0, и никакое сообщение не может её вытеснить.

        Из наименее срочных берётся САМОЕ СТАРОЕ: оно и ближе всех к истечению
        TTL, и дольше всех перестало описывать текущую гонку.
        """
        items = self._drain_locked()
        victim: _Item | None = None
        for item in items:
            if item.rank <= incoming_rank:
                continue
            if victim is None or (item.rank, -item.seq) > (victim.rank, -victim.seq):
                victim = item
        for item in items:
            if item is not victim:
                self._queue.put_nowait((item.rank, item.seq, item))
        return victim

    def _drain_locked(self) -> list[_Item]:
        items: list[_Item] = []
        while True:
            try:
                items.append(self._queue.get_nowait()[2])
            except queue.Empty:
                return items

    # ------------------------------------------------------------------ #
    # Управление                                                          #
    # ------------------------------------------------------------------ #

    def clear(self) -> tuple[str, ...]:
        """Очистить ожидающие (текущее воспроизведение не трогает).

        Возвращает id сброшенных сообщений: вызывающий переводит их в
        `cancelled`, чтобы состояние не осталось неизвестным."""
        with self._enqueue_lock:
            dropped = self._drain_locked()
        return tuple(item.message_id for item in dropped if item.message_id)

    def stop(self, timeout: float = 1.0) -> None:
        """Stop accepting work, interrupt playback and reap the worker."""
        self._stop.set()
        self.clear()
        if self._stop_fn is not None:
            try:
                self._stop_fn()
            except Exception:  # noqa: BLE001
                pass
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=max(0.0, timeout))

    @property
    def critical_active(self) -> bool:
        """True, пока воркер ЗАНЯТ critical-репликой — весь вызов _speak_fn,
        т.е. синтез (возможно сетевой) И воспроизведение, не только звук.
        Гейт намеренно консервативен: см. voice/tts.py Voice.is_critical_active."""
        return self._critical_active.is_set()

    def qsize(self) -> int:
        return self._queue.qsize()

    @property
    def maxsize(self) -> int:
        return self._maxsize

    @property
    def current_item(self) -> _Item | None:
        """Элемент, который воркер обрабатывает сейчас, либо None.

        Нужен владельцу `speak_fn` (`voice/tts.py`), чтобы после сетевого
        синтеза спросить `still_valid()` перед playback. Чтение родителем своего
        же объекта, а не сквозное состояние: очередь строго последовательна —
        одновременно обрабатывается ровно один элемент."""
        return self._current_item

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                rank, _seq, item = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if rank == 0:
                self._critical_active.set()
            self._current_item = item
            try:
                # Финальное разрешение ЗДЕСЬ: позади и пауза MIN_COMMENT_GAP, и
                # ожидание в этой очереди, а впереди — вычисление cache key и
                # сеть. Раньше текст фиксировался на десятки секунд раньше.
                text = item.resolve_text()
                if not text:
                    _log.info("TTSQueue: %s dropped before synthesis "
                              "(no longer current)", item.message_id or "phrase")
                    continue
                self._speak_fn(text, item.persona)
            except Exception:  # noqa: BLE001
                _log.warning("TTSQueue: speak failed for %s",
                             item.message_id or "phrase", exc_info=True)
            finally:
                self._current_item = None
                if rank == 0:
                    self._critical_active.clear()
