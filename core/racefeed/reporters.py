"""core/racefeed/reporters.py — reporter personalities: a coverage filter plus
propose(). Deliberately cheap and LLM-free; only Story objects (never raw
Events) reach a reporter — see StoryBuilder in engine.py. Actual text generation
happens later, in generators.py, only for candidates the Editor has approved
(see design doc for why LLM calls are deferred to publish time)."""
from __future__ import annotations

import copy
import time

from core.racefeed.models import Candidate, Story
from core.racefeed.scheduler import PUBLISH_DELAY_S

_EXPIRY_S = 60.0

RACE_CONTROL_CATEGORIES = {
    "penalty":     ("incident", "supersede"),
    "retirement":  ("incident", "supersede"),
    "incident":    ("incident", "supersede"),
    "safety_car":  ("incident", "append"),
    "flag":        ("incident", "append"),
}

SPOTTER_ANALYTICS_CATEGORIES = {
    "gap_trend":   ("statistics", "ignore_if_pending"),
    "tyre_status": ("statistics", "ignore_if_pending"),
    "fuel_status": ("statistics", "ignore_if_pending"),
    "ers_status":  ("statistics", "ignore_if_pending"),
}

PLAYERS_GARAGE_CATEGORIES = {
    "player_pit_stop":     ("pit_stop", "supersede"),
    "player_overtake":     ("incident", "supersede"),
    "player_fastest_lap":  ("incident", "supersede"),
    "player_progression":  ("analysis", "ignore_if_pending"),
}

# Qualifying coverage: the same event codes StoryBuilder already maps (no
# session-gating there) become a story during a quali session — they just had
# no reporter until now. This desk owns the whole quali narrative (hot laps,
# penalties, incidents, segment flags, the player's personal bests) rather than
# splitting it across the race-only reporters, so nothing here overlaps their
# session_type=="race" coverage. Overtakes/pit-stops are intentionally omitted
# (not meaningful drama on a flying lap); the tick-fed analytics categories
# never occur here because _maybe_tick stays race-only.
QUALIFYING_CATEGORIES = {
    "penalty":            ("incident", "supersede"),
    "retirement":         ("incident", "supersede"),
    "incident":           ("incident", "supersede"),
    "flag":               ("incident", "append"),
    "player_fastest_lap": ("incident", "supersede"),
    "player_progression": ("analysis", "ignore_if_pending"),
}

# One evolving "title fight" story per race weekend: each race supersedes any
# still-pending championship candidate and, once published, the next race's
# changed facts land as an update (see Editor). Race sessions only.
CHAMPIONSHIP_CATEGORIES = {
    "championship": ("analysis", "supersede"),
}


def _make_candidate(story: Story, reporter_id: str, priority: str,
                     update_policy: str, base_importance: int) -> Candidate:
    now = time.time()
    return Candidate(
        story_id=story.id, story_key=story.story_key, category=story.category,
        reporter_id=reporter_id, base_importance=base_importance, priority=priority,
        publish_after=PUBLISH_DELAY_S.get(priority, PUBLISH_DELAY_S["default"]),
        expires_at=now + _EXPIRY_S, update_policy=update_policy,
        facts_snapshot=copy.deepcopy(story.facts),
        history_snapshot=copy.deepcopy(story.history),
        story_stage=story.stage, story_last_update=story.last_update,
    )


class RaceControlReporter:
    id = "race_control"

    def covers(self, story: Story) -> bool:
        return (story.session_type == "race"
                and story.category in RACE_CONTROL_CATEGORIES)

    def propose(self, story: Story) -> Candidate | None:
        if not self.covers(story):
            return None
        priority, update_policy = RACE_CONTROL_CATEGORIES[story.category]
        # default (70) is above editor.PUBLISH_THRESHOLD (60) — missing
        # importance data fails open (publish), not silently suppressed
        base_importance = int(story.facts.get("importance", 70))
        return _make_candidate(story, self.id, priority, update_policy, base_importance)


class SpotterAnalyticsReporter:
    id = "spotter_analytics"

    def covers(self, story: Story) -> bool:
        return (story.session_type == "race"
                and story.category in SPOTTER_ANALYTICS_CATEGORIES)

    def propose(self, story: Story) -> Candidate | None:
        if not self.covers(story):
            return None
        priority, update_policy = SPOTTER_ANALYTICS_CATEGORIES[story.category]
        # default (65) is above editor.PUBLISH_THRESHOLD (60) — missing
        # importance data fails open (publish), not silently suppressed
        base_importance = int(story.facts.get("importance", 65))
        return _make_candidate(story, self.id, priority, update_policy, base_importance)


class PlayersGarageReporter:
    id = "players_garage"

    def covers(self, story: Story) -> bool:
        return (story.session_type == "race"
                and story.category in PLAYERS_GARAGE_CATEGORIES
                and bool(story.facts.get("is_player", False)
                         or story.facts.get("is_player_team", False)))

    def propose(self, story: Story) -> Candidate | None:
        if not self.covers(story):
            return None
        priority, update_policy = PLAYERS_GARAGE_CATEGORIES[story.category]
        # default (75) is above editor.PUBLISH_THRESHOLD (60) — missing
        # importance data fails open (publish), not silently suppressed
        base_importance = int(story.facts.get("importance", 75))
        return _make_candidate(story, self.id, priority, update_policy, base_importance)


class QualifyingReporter:
    id = "qualifying_control"

    def covers(self, story: Story) -> bool:
        return (story.session_type == "qualifying"
                and story.category in QUALIFYING_CATEGORIES)

    def propose(self, story: Story) -> Candidate | None:
        if not self.covers(story):
            return None
        priority, update_policy = QUALIFYING_CATEGORIES[story.category]
        # default (70) is above editor.PUBLISH_THRESHOLD (60) — missing
        # importance data fails open (publish), not silently suppressed
        base_importance = int(story.facts.get("importance", 70))
        return _make_candidate(story, self.id, priority, update_policy, base_importance)


class ChampionshipReporter:
    id = "championship_desk"

    def covers(self, story: Story) -> bool:
        return (story.session_type == "race"
                and story.category in CHAMPIONSHIP_CATEGORIES)

    def propose(self, story: Story) -> Candidate | None:
        if not self.covers(story):
            return None
        priority, update_policy = CHAMPIONSHIP_CATEGORIES[story.category]
        # default (70) is above editor.PUBLISH_THRESHOLD (60) — a championship
        # update is always worth a post; missing importance fails open.
        base_importance = int(story.facts.get("importance", 70))
        return _make_candidate(story, self.id, priority, update_policy, base_importance)


# Career/season achievement posts (see core/milestones.py). One evolving story
# per race weekend, superseded if a bigger milestone arrives before publish.
MILESTONE_CATEGORIES = {
    "milestone": ("analysis", "supersede"),
}


class AchievementsReporter:
    id = "achievements"

    def covers(self, story: Story) -> bool:
        return (story.session_type == "race"
                and story.category in MILESTONE_CATEGORIES)

    def propose(self, story: Story) -> Candidate | None:
        if not self.covers(story):
            return None
        priority, update_policy = MILESTONE_CATEGORIES[story.category]
        # default (80) is above editor.PUBLISH_THRESHOLD (60) — a milestone
        # always earns its post; missing importance fails open.
        base_importance = int(story.facts.get("importance", 80))
        return _make_candidate(story, self.id, priority, update_policy, base_importance)


PADDOCK_CATEGORIES = {
    "race_recap": ("statistics", "ignore_if_pending"),
    "driver_of_the_day": ("analysis", "ignore_if_pending"),
    "post_race_interview": ("default", "ignore_if_pending"),
}


class PaddockReporter:
    id = "paddock"

    def covers(self, story: Story) -> bool:
        return (
            story.session_type == "race"
            and story.category in PADDOCK_CATEGORIES
        )

    def propose(self, story: Story) -> Candidate | None:
        if not self.covers(story):
            return None
        priority, update_policy = PADDOCK_CATEGORIES[story.category]
        base_importance = int(story.facts.get("importance", 82))
        return _make_candidate(
            story, self.id, priority, update_policy, base_importance
        )


REPORTERS = [RaceControlReporter(), SpotterAnalyticsReporter(),
             PlayersGarageReporter(), QualifyingReporter(),
             ChampionshipReporter(), AchievementsReporter(), PaddockReporter()]
