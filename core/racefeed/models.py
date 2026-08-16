"""core/racefeed/models.py — RaceFeed's own data model. Isolated from engine
internals: Event.from_engine_dict() is the ONLY place that reads engine-shaped
dicts; every other module in core.racefeed only ever sees these dataclasses."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from core.radio.plumbing import PLUMBING_KEY, plumbing

_EVENT_KNOWN_KEYS = {
    "event_code", "driver", "team", "vehicle_idx", "importance",
    "laps_remaining", "description", "enqueued_at",
}

# Служебные поля радио-конвейера (core/radio/*): счётчики ситуаций и метки
# времени, по которым сообщение узнаёт свою ситуацию и свой срок жизни. В
# `extra` они попасть не должны по двум причинам:
#
#  1. `extra` целиком уходит в `facts` (core/racefeed/editorial.py) и оттуда — в
#     промпт LLM. «sc_episode: 1» и «box_call_window: 12» репортёру нечего
#     сказать, а шанс, что модель их проговорит, ненулевой.
#  2. `claim_fingerprint` — sha256 от `[story.id, facts]`. Любое новое поле в
#     facts меняет отпечатки всех затронутых публикаций, то есть тихо влияет на
#     дедупликацию RaceFeed. Переработка RaceFeed вне рамок этой задачи.
#
# Счётчики ситуаций живут в ОДНОМ вложенном пространстве `event["radio"]`
# (core/radio/plumbing.py), поэтому фильтруются одним ключом — добавление
# шестого счётчика не потребует правки этого списка. Метки времени остаются в
# корне рядом с `enqueued_at` и исключаются поимённо.
#
# `damage_severity` здесь СОЗНАТЕЛЬНО отсутствует: насколько сильно разбита
# машина — настоящий журналистский факт, ему в ленте место есть.
_RADIO_PLUMBING_KEYS = {PLUMBING_KEY, "created_at", "created_mono"}

_EVENT_EXCLUDED_FROM_EXTRA = _EVENT_KNOWN_KEYS | _RADIO_PLUMBING_KEYS


def _int_or_none(value: object) -> int | None:
    """Служебные поля приезжают из словаря события, который собирают разные
    трекеры; строка и None там законны, а падать на разборе номера эпизода
    RaceFeed не должна — без него ключ просто вернётся к прежнему виду."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class Event:
    event_code: str
    session_type: str
    driver: str | None
    team: str | None
    vehicle_idx: int | None
    is_player: bool
    importance: int
    laps_remaining: int | None
    description: str
    extra: dict
    enqueued_at: float
    is_player_team: bool = False
    #: Номер эпизода Safety Car — ОТДЕЛЬНЫМ полем, а не через `extra`.
    #:
    #: Это единственное служебное поле радио-конвейера, которое RaceFeed'у
    #: действительно нужно, и нужно оно ровно для одного: отличить второй выезд
    #: машины безопасности от первого при построении ключа Story
    #: (`editorial.py::from_event`). Без него обе развязки склеивались в одну
    #: историю, и второй эпизод выходил её продолжением — с накопленной историей
    #: и стадией первого, то есть репортёр писал про новый выезд, глядя на факты
    #: старого.
    #:
    #: Почему не через `extra`, хотя так было бы на одну строку короче: `extra`
    #: целиком уходит в `facts`, а оттуда в промпт LLM и в `claim_fingerprint`
    #: (sha256 от `[story.id, facts]`). Номер эпизода репортёру сказать нечего, а
    #: новое поле в `facts` сдвинуло бы отпечатки ВСЕХ затронутых публикаций, то
    #: есть тихо поменяло дедупликацию всей ленты. Отдельным полем изменение
    #: заперто там, где оно и задумано: в ключе истории Safety Car. Отпечатки
    #: SC-постов при этом меняются намеренно — два эпизода обязаны быть разными
    #: утверждениями.
    sc_episode: int | None = None

    @classmethod
    def from_engine_dict(cls, d: dict, session_type: str, is_player: bool,
                         player_team: str | None = None,
                         player_name: str | None = None) -> "Event":
        player_team_key = str(player_team or "").strip().casefold()
        event_teams = {
            str(d.get("team") or "").strip().casefold(),
            str(d.get("target_team") or "").strip().casefold(),
        }
        # Several player events are published with driver="" because the voice
        # line addresses the player directly ("ты вышел из боксов") — PIT_EXIT,
        # CAREER_PB, CAREER_SECTOR_PB in core/engine.py. RaceFeed writes about
        # them in the third person, so without a name the post and its comment
        # thread say "пилот". Filled here, on the RaceFeed side only, so the
        # spoken phrase is untouched.
        driver = d.get("driver")
        if is_player and not str(driver or "").strip():
            driver = str(player_name or "").strip() or None
        return cls(
            event_code=d.get("event_code", ""),
            session_type=session_type,
            driver=driver,
            team=d.get("team"),
            vehicle_idx=d.get("vehicle_idx"),
            is_player=is_player,
            importance=int(d.get("importance", 50)),
            laps_remaining=d.get("laps_remaining"),
            description=d.get("description", d.get("event_code", "")),
            extra={k: v for k, v in d.items()
                   if k not in _EVENT_EXCLUDED_FROM_EXTRA},
            enqueued_at=d.get("enqueued_at", time.time()),
            is_player_team=bool(player_team_key and player_team_key in event_teams),
            sc_episode=_int_or_none(plumbing(d).get("sc_episode")),
        )


@dataclass
class Story:
    id: str
    story_key: tuple
    category: str
    session_type: str
    stage: int = 0
    facts: dict = field(default_factory=dict)
    history: list = field(default_factory=list)
    created_at: float = 0.0
    last_update: float = 0.0
    last_publish: float | None = None
    status: str = "developing"          # "developing" | "published"
    post_ids: list = field(default_factory=list)


@dataclass
class Candidate:
    story_id: str
    story_key: tuple
    category: str
    reporter_id: str
    base_importance: int
    priority: str                        # "incident"|"pit_stop"|"statistics"|"analysis"|"default"
    publish_after: tuple                 # (min_s, max_s)
    expires_at: float
    update_policy: str                   # "supersede"|"append"|"ignore_if_pending"
    decision: str = ""                   # "new"|"update" — set by Editor.evaluate()
    facts_snapshot: dict | None = None
    history_snapshot: list | None = None
    story_stage: int | None = None
    story_last_update: float | None = None
    format_id: str = ""
    angle_id: str = ""
    claim_fingerprint: str = ""


@dataclass
class Comment:
    id: str
    post_id: str
    author_id: str
    author_name: str
    avatar: str
    text: str
    created_at: float
    likes: int = 0
    parent_id: str | None = None
    author_badge: str = ""


@dataclass
class Post:
    id: str
    session_id: str
    story_id: str
    reporter_id: str
    category: str
    text: str
    created_at: float
    published_at: float
    driver: str | None
    is_player_story: bool
    story_stage: int = 0
    format_id: str = "live_update"
    angle_id: str = ""
    claim_fingerprint: str = ""
    image: str = ""
    metadata: dict = field(default_factory=dict)
    # "live" | "finished" — explicit session phase at publish time. Comment
    # generation reads it instead of guessing from the category or parsing the
    # post text, which is how threads ended up saying "это ещё не конец" under
    # a chequered-flag post (user report 2026-07-26).
    session_phase: str = "live"
    comments: list[Comment] = field(default_factory=list)
