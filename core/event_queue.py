"""
core/event_queue.py
=====================
ImportanceQueue — обёртка над queue.PriorityQueue, скрывающая сортировочный
кортеж от вызывающего кода: put()/get()/get_nowait() работают с обычными
dict-событиями, как раньше работал queue.Queue. Сортировка — по
event["importance"] (выше важность -> раньше достаётся из очереди), при равной
важности — стабильный FIFO (монотонный счётчик как tie-breaker).

Важность в событие кладёт F1Engine._enqueue_event() ДО put(); если её там нет
(прямой put() в обход движка, как делают некоторые тесты) — нейтральный дефолт.

Thread-safe: вся блокировка делегирована внутреннему queue.PriorityQueue
(эта очередь пересекает границу поток-производитель/поток-потребитель в engine).
"""
from __future__ import annotations

import itertools
import queue
from collections.abc import Mapping
from typing import Any

_DEFAULT_IMPORTANCE = 50


class ImportanceQueue:
    def __init__(self) -> None:
        self._q: "queue.PriorityQueue[tuple[int, int, Mapping[str, Any]]]" = queue.PriorityQueue()
        self._counter = itertools.count()

    def put(self, event: Mapping[str, Any]) -> None:
        importance = event.get("importance", _DEFAULT_IMPORTANCE)
        self._q.put((-importance, next(self._counter), event))

    def get(self, timeout: float | None = None) -> Mapping[str, Any]:
        return self._q.get(timeout=timeout)[2]

    def get_nowait(self) -> Mapping[str, Any]:
        return self._q.get_nowait()[2]

    def empty(self) -> bool:
        return self._q.empty()

    def qsize(self) -> int:
        return self._q.qsize()
