"""Canonical commentary event publication and delivery module."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass
import logging
import queue
import time
from typing import Any

from commentator.planner import PlanContext, score_importance
from core.event_queue import ImportanceQueue
from core.racefeed.models import Event as RaceFeedEvent


_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CommentaryEvent(Mapping[str, Any]):
    """Immutable canonical event with a temporary read-only dict interface."""

    _values: dict[str, Any]

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "CommentaryEvent":
        copied = deepcopy(dict(values))
        code = str(copied.get("event_code") or "")
        if not code:
            raise ValueError("commentary event requires event_code")
        copied["event_code"] = code
        copied.setdefault("priority", "normal")
        return cls(copied)

    def __getitem__(self, key: str) -> Any:
        return deepcopy(self._values[key])

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self._values)


class CommentaryEvents:
    """Publish drafts once and deliver normalized events by importance."""

    def __init__(
        self,
        context_provider: Callable[[Mapping[str, Any]], PlanContext],
        *,
        race_feed_provider: Callable[[], Any | None] = lambda: None,
        player_team_provider: Callable[[], str | None] = lambda: None,
        player_name_provider: Callable[[], str | None] = lambda: None,
        media_hook: Callable[[dict, PlanContext], None] = lambda values, context: None,
        scorer: Callable[[Mapping[str, Any], PlanContext], int] = score_importance,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._context_provider = context_provider
        self._race_feed_provider = race_feed_provider
        self._player_team_provider = player_team_provider
        self._player_name_provider = player_name_provider
        self._media_hook = media_hook
        self._scorer = scorer
        self._clock = clock
        self._monotonic = monotonic
        self._queue = ImportanceQueue()

    def publish(self, draft: Mapping[str, Any]) -> CommentaryEvent:
        values = deepcopy(dict(draft))
        try:
            context = self._context_provider(values)
            values["laps_remaining"] = context.laps_remaining
            if "importance" not in values:
                values["importance"] = self._scorer(values, context)
        except Exception:  # noqa: BLE001
            _log.warning(
                "commentary planning failed for %s",
                values.get("event_code"),
                exc_info=True,
            )
            values.setdefault("laps_remaining", None)
            values.setdefault("importance", 50)
            context = PlanContext(
                player_involved=False,
                battle=bool(values.get("battle")),
                laps_remaining=values.get("laps_remaining"),
                session_type="unknown",
            )
        now = self._clock()
        # ТРИ метки времени, и каждая нужна для своего.
        #
        # `enqueued_at` (wall) — когда событие попало в очередь. По ней работает
        # вытеснение бэклога (`CommentaryRuntime.is_stale_backlog_event`), и при
        # повторной постановке она законно обновляется.
        #
        # `created_at` (wall) — когда факт стал правдой, ДЛЯ ПОКАЗА
        # пользователю: «21:43:12» в истории радио. Не сдвигается никогда.
        #
        # `created_mono` (monotonic) — та же точка на монотонной шкале, и
        # ТОЛЬКО по ней считается срок жизни сообщения. Wall-clock на Windows
        # прыгает (NTP, переход на зимнее время): прыжок назад на час превратил
        # бы «просрочено 2 секунды назад» в «истечёт через час», и сообщение
        # зависло бы в очереди; прыжок вперёд разом обнулил бы всю очередь.
        #
        # `setdefault` оставляет публикующему коду возможность передать
        # настоящее время факта, если оно раньше публикации.
        values.setdefault("enqueued_at", now)
        values.setdefault("created_at", now)
        values.setdefault("created_mono", self._monotonic())
        try:
            self._media_hook(values, context)
        except Exception:  # noqa: BLE001 - media is never critical
            _log.debug("media_hook failed for %s", values.get("event_code"), exc_info=True)
        event = CommentaryEvent.from_mapping(values)
        self._queue.put(event)

        race_feed = self._race_feed_provider()
        if race_feed is not None:
            race_feed.ingest(RaceFeedEvent.from_engine_dict(
                event.to_dict(),
                context.session_type,
                context.player_involved,
                player_team=self._player_team_provider(),
                player_name=self._player_name_provider(),
            ))
        return event

    def next(self, timeout: float | None = None) -> CommentaryEvent:
        return self._queue.get(timeout=timeout)

    def get_nowait(self) -> CommentaryEvent:
        return self._queue.get_nowait()

    def clear(self) -> int:
        removed = 0
        while True:
            try:
                self._queue.get_nowait()
                removed += 1
            except queue.Empty:
                return removed

    def empty(self) -> bool:
        return self._queue.empty()

    def qsize(self) -> int:
        return self._queue.qsize()
