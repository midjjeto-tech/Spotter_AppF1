"""
new_tts/queue_handler.py
Очередь воспроизведения: события озвучиваются по одному без наложений.
"""
from __future__ import annotations

import queue
import threading
from typing import Callable


class TTSQueue:
    def __init__(self, speak_fn: Callable[[str], None], maxsize: int = 8):
        self._speak_fn = speak_fn
        self._queue: queue.Queue[str] = queue.Queue(maxsize=maxsize)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._worker, daemon=True, name="tts-queue"
        )
        self._thread.start()

    def enqueue(self, text: str) -> None:
        """Добавить фразу в очередь. При переполнении — пропускает."""
        try:
            self._queue.put_nowait(text)
        except queue.Full:
            pass

    def clear(self) -> None:
        """Очистить ожидающие фразы (текущее воспроизведение не прерывает)."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def stop(self) -> None:
        self._stop.set()

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                text = self._queue.get(timeout=0.1)
                self._speak_fn(text)
            except queue.Empty:
                continue
            except Exception:
                pass
