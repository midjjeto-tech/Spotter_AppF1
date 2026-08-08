"""Сигнал «идёт речь» из воркера очереди TTS — то, чем управляется приглушение
игры (core/audio_ducking.py).

Отдельного потока у приглушения нет намеренно: у воркера и так есть цикл с
таймаутом, и он единственный точно знает, началась речь или очередь опустела.
"""
import time

from new_tts.queue_handler import TTSQueue


def _drain(q, timeout=2.0):
    """Дождаться, пока воркер разберёт очередь."""
    deadline = time.monotonic() + timeout
    while q.qsize() and time.monotonic() < deadline:
        time.sleep(0.02)


def test_busy_goes_true_before_speaking_and_false_when_idle():
    events = []
    q = TTSQueue(speak_fn=lambda text, persona: None,
                 on_busy_change=events.append, release_delay_s=0.05)
    try:
        q.enqueue("привет")
        _drain(q)
        deadline = time.monotonic() + 2.0
        while events[-1:] != [False] and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        q.stop()

    assert events[0] is True
    assert events[-1] is False


def test_back_to_back_phrases_do_not_pump():
    """Две фразы подряд — одно приглушение, а не два: иначе громкость игры
    прыгает вверх-вниз между репликами."""
    events = []
    q = TTSQueue(speak_fn=lambda text, persona: time.sleep(0.02),
                 on_busy_change=events.append, release_delay_s=0.4)
    try:
        q.enqueue("раз")
        q.enqueue("два")
        q.enqueue("три")
        _drain(q)
        time.sleep(0.1)
        assert events == [True], f"ожидалось одно приглушение, получено {events}"
    finally:
        q.stop()


def test_stop_releases_a_held_duck():
    """Остановка приложения не должна оставить игру тихой."""
    events = []
    q = TTSQueue(speak_fn=lambda text, persona: None,
                 on_busy_change=events.append, release_delay_s=10.0)
    q.enqueue("привет")
    _drain(q)
    q.stop()

    assert events[-1] is False


def test_queue_without_callback_still_works():
    q = TTSQueue(speak_fn=lambda text, persona: None)
    try:
        assert q.enqueue("привет").accepted
        _drain(q)
    finally:
        q.stop()
