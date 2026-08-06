"""ImportanceQueue: очередь по важности события за dict-интерфейсом queue.Queue.
См. docs/superpowers/specs/2026-07-05-comment-planner-importance-design.md."""
import queue

import pytest

from core.event_queue import ImportanceQueue


def test_higher_importance_drains_first():
    q = ImportanceQueue()
    q.put({"event_code": "LOW", "importance": 20})
    q.put({"event_code": "HIGH", "importance": 90})
    assert q.get_nowait()["event_code"] == "HIGH"
    assert q.get_nowait()["event_code"] == "LOW"


def test_equal_importance_is_fifo():
    q = ImportanceQueue()
    q.put({"event_code": "FIRST", "importance": 50})
    q.put({"event_code": "SECOND", "importance": 50})
    assert q.get_nowait()["event_code"] == "FIRST"
    assert q.get_nowait()["event_code"] == "SECOND"


def test_missing_importance_defaults_to_50():
    q = ImportanceQueue()
    q.put({"event_code": "NO_IMPORTANCE"})
    q.put({"event_code": "LOW", "importance": 10})
    assert q.get_nowait()["event_code"] == "NO_IMPORTANCE"
    assert q.get_nowait()["event_code"] == "LOW"


def test_get_nowait_raises_when_empty():
    q = ImportanceQueue()
    with pytest.raises(queue.Empty):
        q.get_nowait()


def test_empty_and_qsize():
    q = ImportanceQueue()
    assert q.empty() is True
    assert q.qsize() == 0
    q.put({"event_code": "X", "importance": 50})
    assert q.empty() is False
    assert q.qsize() == 1


def test_get_blocking_returns_dict():
    q = ImportanceQueue()
    q.put({"event_code": "X", "importance": 50})
    evt = q.get()
    assert evt["event_code"] == "X"
