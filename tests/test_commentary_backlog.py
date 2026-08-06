"""Анти-спам: комментатор не должен "утюжить" накопившийся бэклог событий без
пауз, догоняя уже устаревшую ситуацию (core/engine.py::_is_stale_backlog_event).

С Comment Planner (см. docs/superpowers/specs/2026-07-05-comment-planner-importance-design.md)
критерий "устарело" — важность события ниже PLAN_STALE_IMPORTANCE И событие лежит
в очереди дольше PLAN_STALE_S секунд (штамп `enqueued_at`, см. _enqueue_event()).
Раньше было "не critical И в очереди уже ждёт что-то новее" — привязка к qsize()
означала, что ОДНО-единственное событие никогда не считалось устаревшим, сколько
бы оно ни ждало; теперь у каждого события есть собственные "часы".

Bug (истрия проблемы): MIN_COMMENT_GAP=4.0 + неограниченная очередь без сброса
устаревших событий давали почти непрерывную озвучку в насыщенной гонке.
"""
import time

import pytest

import core.engine as eng_mod
from core.engine import F1Engine
import config


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def test_low_importance_event_is_stale_after_ttl(engine):
    now = 1000.0
    event = {"event_code": "OVTK", "importance": 50,
             "enqueued_at": now - config.PLAN_STALE_S - 1}
    assert engine._commentary_runtime.is_stale_backlog_event(event, now) is True


def test_low_importance_event_is_not_stale_within_ttl(engine):
    now = 1000.0
    event = {"event_code": "OVTK", "importance": 50, "enqueued_at": now - 1}
    assert engine._commentary_runtime.is_stale_backlog_event(event, now) is False


def test_high_importance_event_is_never_stale(engine):
    now = 1000.0
    event = {"event_code": "PENA", "importance": 90,
             "enqueued_at": now - config.PLAN_STALE_S - 100}
    assert engine._commentary_runtime.is_stale_backlog_event(event, now) is False


def test_importance_exactly_at_stale_threshold_is_not_stale(engine):
    now = 1000.0
    event = {"event_code": "OVTK", "importance": config.PLAN_STALE_IMPORTANCE,
             "enqueued_at": now - config.PLAN_STALE_S - 100}
    assert engine._commentary_runtime.is_stale_backlog_event(event, now) is False


def test_missing_importance_defaults_to_50_and_can_go_stale(engine):
    now = 1000.0
    event = {"event_code": "OVTK", "enqueued_at": now - config.PLAN_STALE_S - 1}
    assert engine._commentary_runtime.is_stale_backlog_event(event, now) is True


def test_missing_enqueued_at_is_treated_as_epoch_and_is_stale(engine):
    # событие без enqueued_at (не прошло через _enqueue_event) - консервативно
    # трактуем как "давно в очереди", а не как "только что положили".
    event = {"event_code": "OVTK", "importance": 50}
    assert engine._commentary_runtime.is_stale_backlog_event(event, time.time()) is True


def test_bypass_speak_threshold_event_never_goes_stale(engine):
    """Регрессия (найдена финальным сквозным ревью Фазы 2, gap-digest):
    ENGINEER_GAP_DIGEST/PIT_CALL_NOTICE несут bypass_speak_threshold, чтобы
    пройти _muted_by_threshold, — но БЕЗ отдельного исключения здесь их
    важность по умолчанию (50 < PLAN_STALE_IMPORTANCE=70) всё равно давала бы
    им молча утонуть в загруженной гонке, так и не дойдя до
    _muted_by_threshold, где bypass_speak_threshold уже должен был спасти."""
    now = 1000.0
    event = {"event_code": "ENGINEER_GAP_DIGEST", "importance": 50,
             "bypass_speak_threshold": True,
             "enqueued_at": now - config.PLAN_STALE_S - 100}
    assert engine._commentary_runtime.is_stale_backlog_event(event, now) is False
