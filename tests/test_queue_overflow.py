"""new_tts/queue_handler.py — переполнение очереди больше не молчит.

Раньше здесь стояло `except queue.Full: pass`: фраза исчезала бесследно — ни в
логе, ни в возвращаемом значении. Тесты ниже фиксируют, что у КАЖДОЙ попытки
постановки есть наблюдаемый исход, что critical потерять нельзя, и что
предупреждение споттера нельзя выбросить ради комментария.

Детерминизм: воркер во всех тестах блокируется на первой фразе (`_blocked`),
поэтому очередь наполняется предсказуемо и тесты не зависят от таймингов.
"""
import threading

import pytest

from new_tts.queue_handler import EnqueueOutcome, TTSQueue


@pytest.fixture
def blocked_queue():
    """Очередь, чей воркер намертво занят первой фразой.

    Так `maxsize` достигается детерминированно: воркер держит одну фразу, все
    последующие остаются ожидающими."""
    release = threading.Event()
    started = threading.Event()

    def speak(_text, _persona):
        started.set()
        release.wait(timeout=5.0)

    q = TTSQueue(speak_fn=speak, maxsize=3)
    q.enqueue("занимаем воркер")
    assert started.wait(timeout=2.0), "воркер не начал говорить"
    try:
        yield q
    finally:
        release.set()
        q.stop(timeout=1.0)


def _fill(q, count, urgency="normal"):
    return [q.enqueue(f"{urgency}-{i}", urgency=urgency) for i in range(count)]


# ── Наблюдаемый исход ────────────────────────────────────────────────────────

def test_normal_enqueue_reports_accepted(blocked_queue):
    result = blocked_queue.enqueue("обычная", urgency="normal")
    assert result.outcome is EnqueueOutcome.ACCEPTED
    assert result.accepted


def test_full_queue_rejects_with_an_explicit_reason(blocked_queue):
    """Одинаковая срочность: вытеснять нечего, и отказ обязан быть явным."""
    for _ in range(blocked_queue.maxsize):
        blocked_queue.enqueue("normal", urgency="normal")

    result = blocked_queue.enqueue("ещё одна", urgency="normal")

    assert result.outcome is EnqueueOutcome.REJECTED_FULL
    assert not result.accepted


def test_stopped_queue_rejects_with_its_own_reason():
    q = TTSQueue(speak_fn=lambda _t, _p: None, maxsize=3)
    q.stop(timeout=1.0)

    result = q.enqueue("после остановки")

    assert result.outcome is EnqueueOutcome.REJECTED_STOPPED
    assert not result.accepted


def test_outcome_is_never_none(blocked_queue):
    """Исход есть у любой попытки — именно это и терялось раньше."""
    for _ in range(blocked_queue.maxsize + 3):
        assert blocked_queue.enqueue("x", urgency="low").outcome is not None


# ── Critical нельзя потерять ─────────────────────────────────────────────────

def test_critical_is_accepted_even_when_the_queue_is_full(blocked_queue):
    for _ in range(blocked_queue.maxsize):
        blocked_queue.enqueue("normal", urgency="normal")

    result = blocked_queue.enqueue("Бокс, бокс.", priority="critical")

    assert result.accepted
    assert result.outcome is EnqueueOutcome.ACCEPTED_PREEMPTED


def test_critical_reports_the_pending_messages_it_dropped(blocked_queue):
    blocked_queue.enqueue("a", urgency="normal", message_id="radio-1")
    blocked_queue.enqueue("b", urgency="low", message_id="radio-2")

    result = blocked_queue.enqueue("Держи слева!", priority="critical",
                                   message_id="radio-3")

    assert set(result.evicted_ids) == {"radio-1", "radio-2"}


def test_critical_never_reports_rejection_regardless_of_load(blocked_queue):
    for _ in range(blocked_queue.maxsize * 3):
        blocked_queue.enqueue("шум", urgency="normal")
        assert blocked_queue.enqueue("критика", priority="critical").accepted


# ── Вытеснение по срочности ──────────────────────────────────────────────────

def test_high_evicts_the_least_urgent_pending_message(blocked_queue):
    for i in range(blocked_queue.maxsize):
        blocked_queue.enqueue(f"low-{i}", urgency="low", message_id=f"low-{i}")

    result = blocked_queue.enqueue("Safety Car.", urgency="high",
                                   message_id="high-1")

    assert result.outcome is EnqueueOutcome.ACCEPTED_EVICTED
    assert result.evicted_ids == ("low-0",)   # самое старое из наименее срочных


def test_eviction_prefers_the_oldest_among_the_least_urgent(blocked_queue):
    blocked_queue.enqueue("normal", urgency="normal", message_id="n-1")
    blocked_queue.enqueue("low-old", urgency="low", message_id="low-old")
    blocked_queue.enqueue("low-new", urgency="low", message_id="low-new")

    result = blocked_queue.enqueue("важное", urgency="high")

    assert result.evicted_ids == ("low-old",)


def test_low_cannot_evict_anything(blocked_queue):
    for i in range(blocked_queue.maxsize):
        blocked_queue.enqueue(f"normal-{i}", urgency="normal")

    result = blocked_queue.enqueue("атмосферный комментарий", urgency="low")

    assert result.outcome is EnqueueOutcome.REJECTED_FULL


def test_commentary_cannot_evict_a_spotter_warning(blocked_queue):
    """Главное правило вытеснения: споттер не расходный материал.

    Предупреждение споттера имеет максимальную срочность, а жертва ищется
    СТРОГО менее срочная — поэтому его нельзя выбросить ни комментарием (тот
    вообще никого не вытесняет), ни сообщением уровня high, которое вытеснение
    делать умеет."""
    blocked_queue.enqueue("Держи справа!", urgency="critical",
                          message_id="spotter-1")
    for i in range(blocked_queue.maxsize - 1):
        blocked_queue.enqueue(f"filler-{i}", urgency="low",
                              message_id=f"filler-{i}")

    # low вытеснять не умеет вовсе.
    assert blocked_queue.enqueue(
        "болтовня", urgency="low").outcome is EnqueueOutcome.REJECTED_FULL

    # high умеет — и всё равно забирает filler, а не споттера.
    result = blocked_queue.enqueue("важное", urgency="high")
    assert result.outcome is EnqueueOutcome.ACCEPTED_EVICTED
    assert result.evicted_ids == ("filler-0",)

    # Когда менее срочного не осталось, high получает отказ, а не съедает
    # споттера: очередь теперь spotter(critical) + filler-1(low) + high.
    blocked_queue.enqueue("ещё важное", urgency="high")     # съест filler-1
    assert blocked_queue.enqueue(
        "третье важное", urgency="high").outcome is EnqueueOutcome.REJECTED_FULL


def test_equal_urgency_does_not_evict(blocked_queue):
    """Строгое сравнение: сообщение той же срочности не вытесняет — иначе
    поздняя реплика всегда съедала бы более раннюю такую же."""
    for i in range(blocked_queue.maxsize):
        blocked_queue.enqueue(f"high-{i}", urgency="high", message_id=f"h-{i}")

    result = blocked_queue.enqueue("ещё high", urgency="high")

    assert result.outcome is EnqueueOutcome.REJECTED_FULL
    assert result.evicted_ids == ()


# ── Очередь не разрастается ──────────────────────────────────────────────────

def test_queue_never_exceeds_maxsize(blocked_queue):
    for i in range(50):
        blocked_queue.enqueue(f"phrase-{i}",
                              urgency="high" if i % 3 else "low")
        assert blocked_queue.qsize() <= blocked_queue.maxsize


def test_eviction_keeps_the_rest_of_the_queue_intact(blocked_queue):
    blocked_queue.enqueue("keep-1", urgency="high", message_id="keep-1")
    blocked_queue.enqueue("drop", urgency="low", message_id="drop")
    blocked_queue.enqueue("keep-2", urgency="normal", message_id="keep-2")

    result = blocked_queue.enqueue("new", urgency="high", message_id="new")

    assert result.evicted_ids == ("drop",)
    assert blocked_queue.qsize() == blocked_queue.maxsize


# ── clear() тоже отчитывается ────────────────────────────────────────────────

def test_clear_returns_the_ids_it_dropped(blocked_queue):
    blocked_queue.enqueue("a", message_id="radio-10")
    blocked_queue.enqueue("b", message_id="radio-11")

    dropped = blocked_queue.clear()

    assert set(dropped) == {"radio-10", "radio-11"}
    assert blocked_queue.qsize() == 0


def test_clear_without_ids_is_still_safe(blocked_queue):
    blocked_queue.enqueue("без id")
    assert blocked_queue.clear() == ()


# ── Обратная совместимость старого priority ──────────────────────────────────

def test_priority_critical_still_works_without_the_urgency_argument(blocked_queue):
    blocked_queue.enqueue("a", message_id="radio-1")
    result = blocked_queue.enqueue("критика", priority="critical")

    assert result.outcome is EnqueueOutcome.ACCEPTED_PREEMPTED
    assert result.evicted_ids == ("radio-1",)


def test_plain_enqueue_still_defaults_to_normal(blocked_queue):
    for _ in range(blocked_queue.maxsize):
        blocked_queue.enqueue("legacy")
    # normal против normal — вытеснения нет, как и для явной срочности.
    assert blocked_queue.enqueue("legacy").outcome is EnqueueOutcome.REJECTED_FULL
