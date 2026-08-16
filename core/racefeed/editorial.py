"""Deep RaceFeed editorial module.

EditorialDesk owns the whole deterministic decision path from Event/snapshot
to a due publication: Story construction and memory, Reporter coverage,
materiality, session pacing, deferred Incident Stories and Candidate timing.
RaceFeedEngine owns the worker, LLM, comments and persistence on the other side
of this seam.
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass

from core.racefeed.editor import Editor, PUBLISH_THRESHOLD, StoryMemory
from core.racefeed.models import Candidate, Event, Story
from core.racefeed.reporters import REPORTERS
from core.racefeed.scheduler import Scheduler

_RACE_CONTROL_CODES: dict[str, str] = {
    "PENA": "penalty",
    "RTMT": "retirement",
    # Три градации контакта (core/engine.py::_grade_contact). `COLL_HEAVY` тут
    # обязателен: контакт игрока публикуется движком уже ОЦЕНЁННЫМ, и без этой
    # строки самая тяжёлая авария заезда получала `category=None` и вылетала из
    # ленты целиком (`from_event` ниже возвращает None), тогда как средний
    # `COLL` публиковался как раньше — то есть терялось ровно то событие,
    # которое ценнее всех остальных.
    #
    # `COLL_LIGHT` здесь НЕТ намеренно: это притирка, у которой последствия по
    # построению нет (прирост повреждений ниже порога и позиция не потеряна).
    # Заводить на неё Incident Story значит вернуть тот же поток, ради которого
    # градация и делалась — за гонку 2026-08-11 пришло 32 COLL.
    "COLL": "incident",
    "COLL_HEAVY": "incident",
    "SAFETY_CAR_DEPLOYED": "safety_car",
    "SAFETY_CAR_ENDING": "safety_car",
    "SAFETY_CAR_CLEAR": "safety_car",
    "RDFL": "flag",
    "CHQF": "flag",
    "SSTA": "flag",
    "SEND": "flag",
    "RACEFEED_DOTD": "driver_of_the_day",
    "POST_RACE_INTERVIEW": "post_race_interview",
}

_PLAYER_ONLY_CODES: dict[str, str] = {
    "PIT_EXIT": "player_pit_stop",
    "OVTK": "player_overtake",
    "FTLP": "player_fastest_lap",
    "CAREER_PB": "player_progression",
    "CAREER_SECTOR_PB": "player_progression",
    "CAREER_RECAP": "player_progression",
    "CHAMPIONSHIP": "championship",
    "MILESTONE": "milestone",
    "RACE_RECAP": "race_recap",
}

WORKING_BUDGET = 20
NONCRITICAL_CEILING = 30
HIGH_IMPORTANCE_AFTER_BUDGET = 80
ANALYTICS_BUDGET: dict[str, int] = {
    "gap_trend": 2,
    "tyre_status": 2,
    "fuel_status": 1,
    "ers_status": 1,
}
ACTION_BUDGET: dict[str, int] = {
    "player_overtake": 8,
    "incident": 4,
    "penalty": 4,
    "player_pit_stop": 4,
    "player_fastest_lap": 2,
    "player_progression": 2,
}
MIN_ACTION_BUDGET: dict[str, int] = {
    "player_overtake": 4,
    "incident": 2,
    "penalty": 2,
    "player_pit_stop": 2,
    "player_fastest_lap": 1,
    "player_progression": 1,
}
MAX_BATTLE_PUBLICATIONS = 2
MAX_INCIDENT_PUBLICATIONS = 1
INCIDENT_WINDOW_S = 30.0

# Below this distance the working budget stops being a journalistic range and
# starts being spam: the constants above were written for a normal-length race.
FULL_DISTANCE_LAPS = 25
MIN_WORKING_BUDGET = 6


def scale_budgets(total_laps: int | None) -> tuple[int, int, dict[str, int]]:
    """(working budget, non-critical ceiling, analytics caps) for a race of this
    length. A 25+ lap race keeps the designed 20/30; below that the budget falls
    to at most one post per lap, and the analytics caps shrink with it — a 5-lap
    sprint is pure action and needs no tyre-wear trend piece. Critical
    publications ignore all of this (see _pacing_allows)."""
    if not total_laps or total_laps >= FULL_DISTANCE_LAPS:
        return WORKING_BUDGET, NONCRITICAL_CEILING, dict(ANALYTICS_BUDGET)
    working = max(MIN_WORKING_BUDGET, int(total_laps))
    ceiling = round(working * 1.5)
    ratio = working / WORKING_BUDGET
    # floor, not round: at half distance two gap posts is right, one fuel post
    # rounded up from 0.5 is not.
    analytics = {category: int(cap * ratio)
                 for category, cap in ANALYTICS_BUDGET.items()}
    return working, ceiling, analytics


def scale_action_budgets(total_laps: int | None) -> dict[str, int]:
    """Cap repetitive live actions while the final summary keeps the totals.

    A race with fifteen overtakes is still represented by its strongest live
    moments; Driver of the Day carries the authoritative total after the flag.
    """
    if not total_laps or total_laps >= FULL_DISTANCE_LAPS:
        return dict(ACTION_BUDGET)
    ratio = max(0.0, int(total_laps) / FULL_DISTANCE_LAPS)
    return {
        category: max(MIN_ACTION_BUDGET[category], round(cap * ratio))
        for category, cap in ACTION_BUDGET.items()
    }

_CRITICAL_CODES = {
    "CHQF",
    "SEND",
    "RDFL",
    "RTMT",
    "SAFETY_CAR_DEPLOYED",
    "SAFETY_CAR_ENDING",
    "SAFETY_CAR_CLEAR",
    "CHAMPIONSHIP",
    "MILESTONE",
    "RACEFEED_DOTD",
    "POST_RACE_INTERVIEW",
    "RACE_RECAP",
}
_CRITICAL_CATEGORIES = {
    "retirement",
    "safety_car",
    "championship",
    "milestone",
    "driver_of_the_day",
    "post_race_interview",
    "race_recap",
}
_PLAYER_CRITICAL_CATEGORIES = {
    "incident",
    "penalty",
    "player_overtake",
    "player_pit_stop",
    "player_fastest_lap",
    "player_progression",
}


def is_critical_story(story: Story) -> bool:
    """A publication the feed must not lose: finish, SC/red flag, retirement, a
    key player event, championship or milestone (see CONTEXT.md's «Критичная
    RaceFeed-публикация»). Used by pacing here and by generators.py to decide
    which categories deserve a template fallback when the LLM is unavailable."""
    code = str(story.facts.get("event_code") or "")
    if code in _CRITICAL_CODES or story.category in _CRITICAL_CATEGORIES:
        return True
    return (
        bool(story.facts.get("is_player", False))
        and story.category in _PLAYER_CRITICAL_CATEGORIES
    )


@dataclass(frozen=True)
class EditorialResult:
    proposed: int = 0
    suppressed: int = 0
    scheduled: int = 0
    deferred: int = 0

    def __add__(self, other: "EditorialResult") -> "EditorialResult":
        return EditorialResult(
            proposed=self.proposed + other.proposed,
            suppressed=self.suppressed + other.suppressed,
            scheduled=self.scheduled + other.scheduled,
            deferred=self.deferred + other.deferred,
        )


@dataclass(frozen=True)
class ReadyPublication:
    candidate: Candidate
    story: Story


@dataclass
class _IncidentEpisode:
    story_key: tuple
    last_at: float
    lap: int | None


@dataclass
class _DeferredIncident:
    story: Story
    participants: frozenset[int]
    deferred_at: float


class StoryBuilder:
    """Convert canonical Events and periodic snapshots into evolving Stories."""

    def __init__(self, story_memory: StoryMemory):
        self._memory = story_memory
        self._incident_episodes: dict[tuple, _IncidentEpisode] = {}
        self._incident_counter = 0

    @staticmethod
    def _pair(event: Event, first_key: str, second_key: str) -> tuple | None:
        first = event.extra.get(first_key)
        second = event.extra.get(second_key)
        if first is not None and second is not None:
            return tuple(sorted((int(first), int(second))))
        target = event.extra.get("target")
        if event.driver and target:
            return tuple(sorted((str(event.driver), str(target))))
        return None

    def _incident_story_key(self, event: Event) -> tuple:
        pair = self._pair(event, "vehicle1_idx", "vehicle2_idx")
        if pair is None:
            subject = event.driver or event.vehicle_idx or event.event_code
            return ("incident", subject)

        now = event.enqueued_at
        raw_lap = event.extra.get("lap", event.extra.get("lap_num"))
        try:
            lap = int(raw_lap) if raw_lap is not None else None
        except (TypeError, ValueError):
            lap = None
        previous = self._incident_episodes.get(pair)
        same_episode = (
            previous is not None
            and (
                now - previous.last_at <= INCIDENT_WINDOW_S
                or (lap is not None and previous.lap == lap)
            )
        )
        if same_episode:
            previous.last_at = now
            previous.lap = lap if lap is not None else previous.lap
            return previous.story_key

        self._incident_counter += 1
        story_key = ("incident", f"{pair[0]}:{pair[1]}:e{self._incident_counter}")
        self._incident_episodes[pair] = _IncidentEpisode(story_key, now, lap)
        return story_key

    def from_event(self, event: Event) -> Story | None:
        category = _RACE_CONTROL_CODES.get(event.event_code)
        if category is None and (event.is_player or event.is_player_team):
            category = _PLAYER_ONLY_CODES.get(event.event_code)
        if category is None:
            return None

        if category == "incident":
            story_key = self._incident_story_key(event)
        elif category == "player_overtake":
            pair = self._pair(event, "overtaking_idx", "being_overtaken_idx")
            if pair is None:
                subject = event.driver or event.vehicle_idx or event.event_code
            else:
                subject = f"{pair[0]}:{pair[1]}"
            story_key = (category, subject)
        elif category == "safety_car":
            # Тип + НОМЕР ЭПИЗОДА. Три кода (выехал / уходит / чисто) — стадии
            # одной ситуации и обязаны делить Story, поэтому эпизод в ключе, а не
            # код: движок нумерует его только на деплое и проставляет всем трём
            # (core/engine.py::_handle_race_event). Без номера второй выезд
            # машины безопасности за гонку попадал в историю первого — репортёр
            # получал стадию 2 и накопленные факты чужого эпизода и писал новую
            # развязку как продолжение старой.
            #
            # `sc_episode` приезжает отдельным полем Event, а не через `extra`:
            # см. models.py, где объяснено, почему ему нельзя в `facts`.
            sc_type = event.extra.get("sc_type") or "safety_car"
            story_key = (
                (category, f"{sc_type}:e{event.sc_episode}")
                if event.sc_episode is not None
                else (category, sc_type)
            )
        elif category == "player_progression":
            driver_key = event.driver or event.vehicle_idx or event.event_code
            story_key = (category, f"{driver_key}:{event.event_code}")
        else:
            subject = event.driver or event.vehicle_idx or event.event_code
            story_key = (category, subject)

        facts = {
            **event.extra,
            "event_code": event.event_code,
            "vehicle_idx": event.vehicle_idx,
            "importance": event.importance,
            "driver": event.driver,
            "team": event.team,
            "description": event.description,
            "is_player": event.is_player,
            "is_player_team": event.is_player_team,
        }
        return self._memory.upsert(story_key, category, event.session_type, facts)

    def from_snapshot(self, snapshot: dict, session_type: str) -> list[Story]:
        stories: list[Story] = []
        if (snapshot.get("gap_front_ms") is not None
                or snapshot.get("gap_behind_ms") is not None):
            stories.append(self._memory.upsert(
                ("gap_trend", "player"),
                "gap_trend",
                session_type,
                {
                    "importance": 65,
                    "is_player": True,
                    "gap_front_ms": snapshot.get("gap_front_ms"),
                    "gap_behind_ms": snapshot.get("gap_behind_ms"),
                },
            ))
        if snapshot.get("player_tyre_wear") is not None:
            stories.append(self._memory.upsert(
                ("tyre_status", "player"),
                "tyre_status",
                session_type,
                {
                    "importance": 60,
                    "is_player": True,
                    "tyre_wear": snapshot.get("player_tyre_wear"),
                    "tyre_age": snapshot.get("player_tyre_age"),
                    "tyre_compound": snapshot.get("player_tyre_compound"),
                },
            ))
        if snapshot.get("player_fuel") is not None:
            fuel = snapshot.get("player_fuel")
            stories.append(self._memory.upsert(
                ("fuel_status", "player"),
                "fuel_status",
                session_type,
                {
                    "importance": 65 if fuel <= 10.0 else 55,
                    "is_player": True,
                    "fuel": fuel,
                },
            ))
        if snapshot.get("player_ers_percent") is not None:
            ers_percent = snapshot.get("player_ers_percent")
            stories.append(self._memory.upsert(
                ("ers_status", "player"),
                "ers_status",
                session_type,
                {
                    "importance": 65 if ers_percent <= 20.0 else 55,
                    "is_player": True,
                    "ers_percent": ers_percent,
                },
            ))
        return stories

    def from_tick(self, snapshot: dict, session_type: str) -> list[Story]:
        """Compatibility alias for callers using the pre-module name."""
        return self.from_snapshot(snapshot, session_type)

    def reset(self) -> None:
        self._incident_episodes.clear()
        self._incident_counter = 0


class EditorialDesk:
    """Deep deterministic editorial module used by production and tests."""

    def __init__(self):
        self._memory = StoryMemory()
        self._builder = StoryBuilder(self._memory)
        self._editor = Editor()
        self._scheduler = Scheduler()
        self._accepted_total = 0
        self._accepted_by_category: dict[str, int] = {}
        self._accepted_by_story: dict[str, int] = {}
        self._deferred_incidents: dict[str, _DeferredIncident] = {}
        self._race_distance: int | None = None
        (self._working_budget, self._noncritical_ceiling,
         self._analytics_budget) = scale_budgets(None)
        self._action_budget = scale_action_budgets(None)

    def observe_event(self, event: Event, now: float | None = None) -> EditorialResult:
        observed_at = event.enqueued_at if now is None else now
        self._prune_incidents(observed_at)
        story = self._builder.from_event(event)
        if story is None:
            return EditorialResult()

        if story.category == "incident" and not story.facts.get("is_player", False):
            self._deferred_incidents[story.id] = _DeferredIncident(
                story=story,
                participants=self._incident_participants(story),
                deferred_at=observed_at,
            )
            return EditorialResult(deferred=1)

        result = EditorialResult()
        for incident in self._release_consequential_incidents(story, observed_at):
            result += self._consider(incident, observed_at)
        result += self._consider(story, observed_at)
        return result

    def observe_snapshot(
        self,
        snapshot: dict,
        session_type: str,
        now: float | None = None,
    ) -> EditorialResult:
        observed_at = time.time() if now is None else now
        self._apply_race_distance(snapshot.get("total_laps"))
        result = EditorialResult()
        for story in self._builder.from_snapshot(snapshot, session_type):
            result += self._consider(story, observed_at)
        return result

    def _consider(self, story: Story, now: float) -> EditorialResult:
        result = EditorialResult()
        for reporter in REPORTERS:
            candidate = reporter.propose(story)
            if candidate is None:
                continue
            result += EditorialResult(proposed=1)
            decision = self._editor.evaluate(candidate, story)
            if decision == "suppress" and self._is_critical(story):
                candidate.base_importance = max(
                    candidate.base_importance, PUBLISH_THRESHOLD
                )
                decision = self._editor.evaluate(candidate, story)
            if decision == "suppress":
                result += EditorialResult(suppressed=1)
                continue
            candidate.decision = decision

            pending = self._scheduler.has_pending(candidate.story_id)
            reuses_slot = pending and candidate.update_policy == "supersede"
            if pending and candidate.update_policy == "ignore_if_pending":
                result += EditorialResult(suppressed=1)
                continue
            if not reuses_slot and not self._pacing_allows(candidate, story):
                result += EditorialResult(suppressed=1)
                continue

            outcome = self._scheduler.schedule(candidate, now)
            if outcome == "ignored":
                result += EditorialResult(suppressed=1)
                continue
            if outcome == "scheduled":
                self._reserve(candidate, story)
            result += EditorialResult(scheduled=1)
        return result

    def _apply_race_distance(self, total_laps) -> None:
        """Set the pacing budget from the first known race distance and keep it.
        Re-scaling mid-race would move the goalposts under publications already
        counted against the old budget. Events that arrive before the first tick
        (race-only, every 20s) are paced by the full-distance defaults."""
        if self._race_distance is not None or not total_laps:
            return
        try:
            laps = int(total_laps)
        except (TypeError, ValueError):
            return
        if laps <= 0:
            return
        self._race_distance = laps
        (self._working_budget, self._noncritical_ceiling,
         self._analytics_budget) = scale_budgets(laps)
        self._action_budget = scale_action_budgets(laps)

    def _pacing_allows(self, candidate: Candidate, story: Story) -> bool:
        story_count = self._accepted_by_story.get(story.id, 0)
        if (story.category == "player_overtake"
                and story_count >= MAX_BATTLE_PUBLICATIONS):
            return False
        if story.category == "incident" and story_count >= MAX_INCIDENT_PUBLICATIONS:
            return False

        action_limit = self._action_budget.get(story.category)
        if (action_limit is not None
                and self._accepted_by_category.get(story.category, 0) >= action_limit):
            return False

        category_limit = self._analytics_budget.get(story.category)
        if (category_limit is not None
                and self._accepted_by_category.get(story.category, 0) >= category_limit):
            return False

        if self._is_critical(story):
            return True
        if self._accepted_total >= self._noncritical_ceiling:
            return False
        if (self._accepted_total >= self._working_budget
                and candidate.base_importance < HIGH_IMPORTANCE_AFTER_BUDGET):
            return False
        return True

    @staticmethod
    def _is_critical(story: Story) -> bool:
        return is_critical_story(story)

    def _reserve(self, candidate: Candidate, story: Story) -> None:
        self._accepted_total += 1
        self._accepted_by_category[story.category] = (
            self._accepted_by_category.get(story.category, 0) + 1
        )
        self._accepted_by_story[candidate.story_id] = (
            self._accepted_by_story.get(candidate.story_id, 0) + 1
        )

    @staticmethod
    def _incident_participants(story: Story) -> frozenset[int]:
        participants = set()
        for key in ("vehicle1_idx", "vehicle2_idx"):
            value = story.facts.get(key)
            if isinstance(value, int):
                participants.add(value)
        return frozenset(participants)

    def _release_consequential_incidents(
        self,
        consequence: Story,
        now: float,
    ) -> list[Story]:
        if consequence.category not in {"penalty", "retirement", "safety_car"}:
            return []
        if (
            consequence.category == "safety_car"
            and consequence.facts.get("event_code") != "SAFETY_CAR_DEPLOYED"
        ):
            return []

        matches: list[_DeferredIncident] = []
        vehicle_idx = consequence.facts.get("vehicle_idx")
        if consequence.category in {"penalty", "retirement"} and isinstance(vehicle_idx, int):
            matches = [
                item for item in self._deferred_incidents.values()
                if vehicle_idx in item.participants
            ]
        elif consequence.category == "safety_car" and self._deferred_incidents:
            matches = [max(
                self._deferred_incidents.values(),
                key=lambda item: item.deferred_at,
            )]

        released = []
        for item in sorted(matches, key=lambda value: value.deferred_at):
            if now - item.deferred_at > INCIDENT_WINDOW_S:
                continue
            self._deferred_incidents.pop(item.story.id, None)
            released.append(item.story)
        return released

    def _prune_incidents(self, now: float) -> None:
        stale = [
            story_id
            for story_id, item in self._deferred_incidents.items()
            if now - item.deferred_at > INCIDENT_WINDOW_S
        ]
        for story_id in stale:
            self._deferred_incidents.pop(story_id, None)

    def due(self, now: float | None = None) -> list[ReadyPublication]:
        due_at = time.time() if now is None else now
        publications = []
        for candidate in self._scheduler.due(due_at):
            story = self._memory.get(candidate.story_id)
            if story is not None:
                publications.append(ReadyPublication(candidate, story))
        return publications

    def mark_published(
        self,
        publication: ReadyPublication,
        post_id: str,
        *,
        published_at: float,
    ) -> None:
        self._memory.mark_published(
            publication.story,
            post_id,
            published_at=published_at,
            facts_snapshot=publication.candidate.facts_snapshot,
        )

    def advanced_story(
        self,
        publication: ReadyPublication,
        post_id: str,
        *,
        published_at: float,
    ) -> Story:
        """Return the advanced durable snapshot without mutating live memory."""
        story = copy.deepcopy(publication.story)
        self._memory.mark_published(
            story,
            post_id,
            published_at=published_at,
            facts_snapshot=publication.candidate.facts_snapshot,
        )
        return story

    def story(self, story_id: str) -> Story | None:
        """Return a read-only diagnostic snapshot of an editorial story."""
        story = self._memory.get(story_id)
        return copy.deepcopy(story) if story is not None else None

    def clear(self) -> None:
        self._scheduler.clear()
        self._memory.clear()
        self._editor.reset()
        self._builder.reset()
        self._accepted_total = 0
        self._accepted_by_category.clear()
        self._accepted_by_story.clear()
        self._race_distance = None
        (self._working_budget, self._noncritical_ceiling,
         self._analytics_budget) = scale_budgets(None)
        self._action_budget = scale_action_budgets(None)
        self._deferred_incidents.clear()
