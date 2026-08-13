import threading
import time

from new_tts.queue_handler import TTSQueue


def test_critical_calls_stop_fn_immediately():
    stopped = []
    # speak_fn долгая, чтобы воркер «застрял» — проверяем синхронный вызов stop_fn
    q = TTSQueue(speak_fn=lambda t, p: time.sleep(0.5),
                 stop_fn=lambda: stopped.append(1))
    q.enqueue("urgent", priority="critical")
    assert stopped == [1]   # stop_fn вызван синхронно в enqueue
    q.stop()


def test_critical_clears_pending():
    """Детерминированно: воркер парковано держим на «a» через Event, затем
    ставим «b» и critical «urgent» — «urgent» вытесняет «b» из очереди ожидания."""
    spoken = []
    a_started = threading.Event()
    release = threading.Event()

    def speak(t, p):
        if t == "a":
            a_started.set()
            release.wait(timeout=2.0)   # держим воркер занятым на «a»
        spoken.append(t)

    q = TTSQueue(speak_fn=speak)
    q.enqueue("a")
    assert a_started.wait(timeout=2.0)            # «a» точно играет, воркер занят
    q.enqueue("b")                                # встаёт в очередь за «a»
    q.enqueue("urgent", priority="critical")      # очищает «b», встаёт первой
    release.set()                                 # отпускаем воркер с «a»

    deadline = time.time() + 2.0
    while "urgent" not in spoken and time.time() < deadline:
        time.sleep(0.01)
    assert "urgent" in spoken
    assert "b" not in spoken                      # вытеснено
    q.stop()


def test_normal_enqueue_plays():
    spoken = []
    q = TTSQueue(speak_fn=lambda t, p: spoken.append(t))
    q.enqueue("hello")
    time.sleep(0.3)
    assert spoken == ["hello"]
    q.stop()


def test_critical_active_true_only_while_critical_plays():
    started = threading.Event()
    release = threading.Event()
    seen_during = []

    def speak(t, p):
        if t == "urgent":
            started.set()
            release.wait(timeout=2.0)

    q = TTSQueue(speak_fn=speak)
    assert q.critical_active is False
    q.enqueue("urgent", priority="critical")
    assert started.wait(timeout=2.0)
    seen_during.append(q.critical_active)
    release.set()

    deadline = time.time() + 2.0
    while q.critical_active and time.time() < deadline:
        time.sleep(0.01)

    assert seen_during == [True]
    assert q.critical_active is False
    q.stop()


def test_critical_active_false_for_normal_priority():
    q = TTSQueue(speak_fn=lambda t, p: time.sleep(0.05))
    q.enqueue("hello")
    time.sleep(0.02)
    assert q.critical_active is False
    q.stop()


def test_critical_active_clears_when_speak_fn_raises():
    raised = threading.Event()

    def speak(t, p):
        raised.set()
        raise RuntimeError("synth blew up")

    q = TTSQueue(speak_fn=speak)
    q.enqueue("urgent", priority="critical")
    assert raised.wait(timeout=2.0)
    deadline = time.time() + 2.0
    while q.critical_active and time.time() < deadline:
        time.sleep(0.01)
    assert q.critical_active is False   # finally cleared it despite the raise
    q.stop()


def test_enqueue_delivers_persona_to_speak_fn():
    seen = []
    q = TTSQueue(speak_fn=lambda t, p: seen.append((t, p)))
    q.enqueue("фраза", persona="calm")
    deadline = time.time() + 2.0
    while not seen and time.time() < deadline:
        time.sleep(0.01)
    assert seen == [("фраза", "calm")]
    q.stop()


def test_enqueue_without_persona_delivers_none():
    seen = []
    q = TTSQueue(speak_fn=lambda t, p: seen.append((t, p)))
    q.enqueue("фраза")
    deadline = time.time() + 2.0
    while not seen and time.time() < deadline:
        time.sleep(0.01)
    assert seen == [("фраза", None)]
    q.stop()


def test_critical_enqueue_carries_persona():
    seen = []
    q = TTSQueue(speak_fn=lambda t, p: seen.append((t, p)))
    q.enqueue("боксы", priority="critical", persona="calm")
    deadline = time.time() + 2.0
    while not seen and time.time() < deadline:
        time.sleep(0.01)
    assert seen == [("боксы", "calm")]
    q.stop()


# --------------------------------------------------------------------------- #
# Critical не рвёт звучащую реплику ТОЙ ЖЕ категории (_NO_SELF_INTERRUPT).
# Разбор живого заезда 2026-08-11: 63 обрыва на полуслове за 33 минуты гонки,
# потому что каждое предупреждение споттера рвало предыдущее предупреждение
# споттера. Право рвать ИНЖЕНЕРА И КОММЕНТАТОРА при этом сохраняется — споттер
# остаётся безопасностью.
# --------------------------------------------------------------------------- #

def _busy_queue(stopped):
    """Очередь, воркер которой заведомо занят первой репликой."""
    started = threading.Event()
    release = threading.Event()

    def speak(t, p):
        started.set()
        release.wait(timeout=2.0)

    q = TTSQueue(speak_fn=speak, stop_fn=lambda: stopped.append(1))
    return q, started, release


def test_spotter_does_not_interrupt_another_spotter():
    stopped = []
    q, started, release = _busy_queue(stopped)
    q.enqueue("машина слева", priority="critical", category="spotter_side")
    assert started.wait(timeout=2.0)
    # Первая постановка тоже звала stop_fn — играть тогда было нечего. Считаем
    # ПРИРОСТ: важно, что второе предупреждение не оборвало первое.
    before = len(stopped)

    q.enqueue("машина справа", priority="critical", category="spotter_side")

    assert len(stopped) == before   # звучащее предупреждение договорило
    release.set()
    q.stop()


def test_spotter_still_interrupts_other_categories():
    stopped = []
    q, started, release = _busy_queue(stopped)
    q.enqueue("длинный комментарий", priority="normal", category="position")
    assert started.wait(timeout=2.0)

    q.enqueue("машина слева", priority="critical", category="spotter_side")

    assert stopped == [1]         # безопасность рвёт болтовню
    release.set()
    q.stop()


def test_critical_without_category_interrupts_as_before():
    """Старые вызывающие (category не передан) работают как раньше."""
    stopped = []
    q, started, release = _busy_queue(stopped)
    q.enqueue("что-то", priority="critical")
    assert started.wait(timeout=2.0)

    q.enqueue("срочное", priority="critical")

    assert stopped == [1, 1]
    release.set()
    q.stop()
