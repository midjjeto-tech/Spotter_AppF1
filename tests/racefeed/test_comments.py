import re

import pytest

from core.racefeed.comments import comments_enabled_for, generate_comments
from core.racefeed.models import Post


def _post(category="player_overtake", session_phase="live", post_id="post-1"):
    return Post(
        id=post_id, session_id="s", story_id="story", reporter_id="players_garage",
        category=category, text="Norris passes Russell.",
        created_at=1.0, published_at=10.0, driver="Norris",
        is_player_story=True, session_phase=session_phase,
    )


class _OfflineAI:
    available = False


def test_offline_fallback_is_compact_and_has_no_synthetic_thread():
    comments = generate_comments(_post(), _OfflineAI())

    assert 1 <= len(comments) <= 2
    assert all(comment.post_id == "post-1" for comment in comments)
    assert len({comment.author_id for comment in comments}) == len(comments)
    assert all(comment.parent_id is None for comment in comments)
    assert all(comment.likes == 0 for comment in comments)


class _JsonAI:
    available = True

    def generate_with_system(self, system, user):
        return """```json
        [
          {"persona":"apex_nerd","text":"Разбор.","reply_to":null},
          {"persona":"sector_times","text":"Есть цифры.","reply_to":0}
        ]
        ```"""


def test_valid_ai_batch_is_limited_to_two_independent_expert_notes():
    comments = generate_comments(_post(), _JsonAI())

    assert [comment.text for comment in comments] == ["Разбор.", "Есть цифры."]
    assert all(comment.parent_id is None for comment in comments)


def test_expert_note_reveal_times_are_short_and_deterministic():
    comments = generate_comments(_post(), _OfflineAI())
    times = [c.created_at for c in comments]

    # strictly increasing — later comments "докапываются" after earlier ones
    assert times == sorted(times)
    assert all(b > a for a, b in zip(times, times[1:]))
    assert 8.0 <= times[0] - _post().published_at <= 20.0
    if len(times) == 2:
        assert times[1] - _post().published_at <= 60.0
    # deterministic per post id (volatile + SQLite reads must agree)
    again = [c.created_at for c in generate_comments(_post(), _OfflineAI())]
    assert again == times


def test_offline_expert_notes_vary_between_posts():
    variants = {
        tuple(comment.text for comment in generate_comments(
            _post(post_id=f"post-{index}"), _OfflineAI()))
        for index in range(8)
    }

    assert len(variants) > 1


@pytest.mark.parametrize("category", ["driver_of_the_day", "post_race_interview", "race_recap"])
def test_post_race_fallback_comments_do_not_talk_as_if_race_is_live(category):
    comments = generate_comments(_post(category=category), _OfflineAI())
    text = " ".join(comment.text.casefold() for comment in comments)

    assert 1 <= len(comments) <= 2
    assert "до финиша далеко" not in text
    assert "ещё не конец" not in text
    assert "окно на подходе" not in text
    assert "решать надо сейчас" not in text


class _ExplodingAI:
    """Доступный ИИ, который падает при любом вызове — доказывает, что для
    заглушённых категорий LLM вообще не трогают, а не просто отбрасывают ответ."""

    available = True

    def generate_with_system(self, system, user):
        raise AssertionError("LLM must not be called for a no-comment category")


@pytest.mark.parametrize(
    "category", ["gap_trend", "tyre_status", "fuel_status", "ers_status"]
)
def test_analytics_tick_posts_get_no_comments_and_skip_the_llm(category):
    assert comments_enabled_for(_post(category=category)) is False
    assert generate_comments(_post(category=category), _ExplodingAI()) == []


@pytest.mark.parametrize(
    "category",
    ["penalty", "retirement", "incident", "safety_car", "flag",
     "player_overtake", "player_pit_stop", "player_fastest_lap",
    "player_progression"],
)
def test_newsworthy_categories_keep_compact_expert_notes(category):
    assert comments_enabled_for(_post(category=category)) is True
    assert 1 <= len(generate_comments(_post(category=category), _OfflineAI())) <= 2


def test_unknown_categories_do_not_spend_an_extra_llm_call():
    assert comments_enabled_for(_post(category="brand_new_unknown_category")) is False
    assert generate_comments(
        _post(category="brand_new_unknown_category"), _ExplodingAI()) == []


# --- фаза сессии -----------------------------------------------------------

_LIVE_SPECULATION = ("до финиша далеко", "ещё не конец", "гонка не закончена",
                     "окно на подходе", "решать надо в ближайшие круги",
                     "следующие круги покажут")


@pytest.mark.parametrize(
    "category", ["flag", "championship", "milestone", "player_overtake"]
)
def test_finished_phase_threads_never_speculate_about_the_rest_of_the_race(category):
    """The user-visible bug: a thread under the chequered flag saying "это ещё
    не конец". Phase comes from Post.session_phase, not from the category —
    these four are all published while the race is over."""
    comments = generate_comments(
        _post(category=category, session_phase="finished"), _OfflineAI())
    text = " ".join(comment.text.casefold() for comment in comments)

    assert 1 <= len(comments) <= 2
    for phrase in _LIVE_SPECULATION:
        assert phrase not in text
    assert "пит-стоп" not in text or category == "player_pit_stop"


def test_live_notes_are_expert_personas_not_a_simulated_crowd():
    comments = generate_comments(_post(session_phase="live"), _OfflineAI())

    assert {comment.author_id for comment in comments} <= {
        "apex_nerd", "sector_times", "pitwall", "tyre_whisperer",
    }


def test_post_race_categories_are_finished_even_without_the_field():
    """Posts written before session_phase existed (and DOTD/interview, which
    are post-race by construction) must still get the finished pool."""
    comments = generate_comments(
        _post(category="driver_of_the_day", session_phase="live"), _OfflineAI())
    text = " ".join(comment.text.casefold() for comment in comments)

    for phrase in _LIVE_SPECULATION:
        assert phrase not in text


# --- суть события ----------------------------------------------------------

@pytest.mark.parametrize("category,facts,expected", [
    ("retirement", {"driver": "Норрис"}, "сход"),
    ("penalty", {"driver": "Норрис", "time_seconds": 5}, "5 с"),
    ("incident", {"driver": "Норрис", "target": "Пиастри"}, "пиастри"),
    ("player_overtake", {"driver": "Норрис", "target": "Расселл"}, "расселл"),
    ("safety_car", {"driver": ""}, "нейтрализация"),
    ("player_pit_stop", {"driver": "Норрис", "tyre_compound": "Medium"}, "medium"),
    ("championship", {"driver": "Норрис", "rival": "Ферстаппен"}, "ферстаппен"),
])
def test_offline_thread_talks_about_the_actual_event(category, facts, expected):
    comments = generate_comments(
        _post(category=category), _OfflineAI(), facts)
    text = " ".join(comment.text.casefold() for comment in comments)

    assert expected.casefold() in text


def test_chequered_flag_thread_is_not_a_safety_car_thread():
    """"flag" covers the start, the red flag and the finish. Sharing one pool
    with safety_car put "заезжать сейчас или держать позицию" under the finish."""
    comments = generate_comments(
        _post(category="flag", session_phase="finished"), _OfflineAI(),
        {"event_code": "CHQF"})
    text = " ".join(comment.text.casefold() for comment in comments)

    for phrase in ("заезжать сейчас", "не питовался", "только гонка разошлась",
                   "нейтрализация", "после рестарта"):
        assert phrase not in text


def test_red_flag_keeps_the_neutralisation_thread():
    comments = generate_comments(
        _post(category="flag"), _OfflineAI(), {"event_code": "RDFL"})
    text = " ".join(comment.text.casefold() for comment in comments)

    assert "нейтрализация" in text or "рестарт" in text or "питовался" in text


@pytest.mark.parametrize("facts,forbidden,expected", [
    ({"driver": "Ландо Норрис"}, r"сход норрис\b", "сход норриса"),
    ({"driver": "Норрис", "rival": "Макс Ферстаппен"},
     r"дуэль с ферстаппен\b", "дуэль с ферстаппеном"),
])
def test_names_are_declined_not_glued_in_nominative(facts, forbidden, expected):
    """core/ru_names.py already owns the declension table used by the voice
    pipeline — threads reading «Сход Норрис» is what made the fake community
    look fake."""
    category = "championship" if "rival" in facts else "retirement"
    texts = []
    for index in range(8):
        comments = generate_comments(
            _post(category=category, post_id=f"decl-{index}"), _OfflineAI(), facts)
        texts.extend(comment.text.casefold() for comment in comments)
    joined = " ".join(texts)

    assert expected in joined
    assert re.search(forbidden, joined) is None


def test_retirement_thread_does_not_reuse_the_overtake_pool():
    retirement = generate_comments(
        _post(category="retirement", post_id="same-id"), _OfflineAI(),
        {"driver": "Норрис"})
    overtake = generate_comments(
        _post(category="player_overtake", post_id="same-id"), _OfflineAI(),
        {"driver": "Норрис", "target": "Расселл"})

    # same post id ⇒ same shuffle seed; only the pool differs
    assert [c.text for c in retirement] != [c.text for c in overtake]


class _CapturingAI:
    available = True

    def __init__(self):
        self.prompts = []

    def generate_with_system(self, system, user):
        self.prompts.append((system, user))
        return None


def test_facts_reach_the_llm_prompt_without_technical_fields():
    """Same _INTERNAL_ONLY_KEYS filtering as the post generator — a leaked
    numeric team_id is exactly how "Макс из команды 227" happened."""
    ai = _CapturingAI()
    generate_comments(_post(category="penalty"), ai, {
        "driver": "Норрис", "time_seconds": 5,
        "team_id": 227, "importance": 90, "vehicle_idx": 4, "is_player": True,
    })
    _, user = ai.prompts[0]

    assert "Норрис" in user
    assert "227" not in user
    assert "importance" not in user
    assert "vehicle_idx" not in user


def test_llm_prompt_carries_the_session_phase():
    ai = _CapturingAI()
    generate_comments(_post(session_phase="finished"), ai, {"driver": "Норрис"})
    _, user = ai.prompts[0]

    assert "гонка уже завершена" in user.casefold()


# --- тред не должен выглядеть штампованным ----------------------------------

def _threads(count=25, **post_kwargs):
    return [generate_comments(_post(post_id=f"var-{i}", **post_kwargs), _OfflineAI())
            for i in range(count)]


def test_thread_length_varies_between_posts():
    """Один или два разбора не превращают пост в искусственную толпу."""
    sizes = {len(thread) for thread in _threads()}

    assert len(sizes) > 1
    assert min(sizes) == 1 and max(sizes) == 2


def test_automatic_notes_do_not_invent_popularity():
    assert all(comment.likes == 0 for thread in _threads() for comment in thread)


def test_thread_shape_is_deterministic_per_post():
    """Volatile- и SQLite-чтения обязаны сходиться до последнего лайка."""
    first = generate_comments(_post(post_id="stable"), _OfflineAI())
    second = generate_comments(_post(post_id="stable"), _OfflineAI())

    assert [(c.author_id, c.text, c.likes, c.created_at) for c in first] == \
           [(c.author_id, c.text, c.likes, c.created_at) for c in second]


def test_automatic_notes_never_argue_with_each_other():
    assert all(
        comment.parent_id is None
        for thread in _threads(40)
        for comment in thread
    )


# --- ответы персонажей на реплику читателя ----------------------------------

from core.racefeed.comments import generate_replies


class _ReplyAI:
    available = True

    def __init__(self):
        self.prompts = []

    def generate_with_system(self, system, user):
        self.prompts.append((system, user))
        return '[{"persona":"apex_nerd","text":"По фактам поста вывод разумный."}]'


def test_replies_are_linked_to_the_reader_comment():
    replies = generate_replies(
        post_id="p1", parent_id="c-player", post_text="Контакт в первом повороте.",
        thread=[], player_text="Это был чистый манёвр", ai_provider=_ReplyAI(),
        parent_created_at=1000.0,
    )

    assert len(replies) == 1
    assert replies[0].parent_id == "c-player"
    assert replies[0].post_id == "p1"
    assert replies[0].text == "По фактам поста вывод разумный."
    assert replies[0].likes == 0


def test_replies_land_after_a_pause_not_instantly():
    """Мгновенный ответ выдаёт бота — раскрытие идёт тем же механизмом, что и
    обычные треды."""
    replies = generate_replies(
        post_id="p1", parent_id="c-player", post_text="текст", thread=[],
        player_text="моя реплика", ai_provider=_ReplyAI(),
        parent_created_at=1000.0,
    )

    assert 1010.0 <= replies[0].created_at <= 1040.0


def test_reply_prompt_carries_the_post_thread_and_reader_line():
    ai = _ReplyAI()
    generate_replies(
        post_id="p1", parent_id="c1", post_text="Норрис сходит с дистанции.",
        thread=[{"author_name": "ApexData", "text": "Похоже на технику."}],
        player_text="жаль, шёл вторым", ai_provider=ai, parent_created_at=1.0,
    )
    _, user = ai.prompts[0]

    assert "Норрис сходит с дистанции." in user
    assert "ApexData" in user
    assert "жаль, шёл вторым" in user


def test_offline_reader_still_gets_an_answer():
    replies = generate_replies(
        post_id="p1", parent_id="c1", post_text="текст", thread=[],
        player_text="моя реплика", ai_provider=_OfflineAI(),
        parent_created_at=1.0,
    )

    assert 1 <= len(replies) <= 2
    assert all(r.parent_id == "c1" for r in replies)
    assert all(r.text for r in replies)


def test_replies_are_deterministic_per_reader_comment():
    kwargs = dict(post_id="p1", parent_id="c1", post_text="t", thread=[],
                  player_text="x", parent_created_at=5.0)
    first = generate_replies(ai_provider=_OfflineAI(), **kwargs)
    second = generate_replies(ai_provider=_OfflineAI(), **kwargs)

    assert [(r.author_id, r.text, r.created_at) for r in first] == \
           [(r.author_id, r.text, r.created_at) for r in second]


def test_a_failing_provider_falls_back_instead_of_raising():
    class _Exploding:
        available = True

        def generate_with_system(self, system, user):
            raise RuntimeError("provider down")

    replies = generate_replies(
        post_id="p1", parent_id="c1", post_text="t", thread=[],
        player_text="x", ai_provider=_Exploding(), parent_created_at=1.0,
    )

    assert len(replies) >= 1


def test_two_replies_never_come_from_the_same_persona():
    class _SamePersonaTwice:
        available = True

        def generate_with_system(self, system, user):
            return ('[{"persona":"apex_nerd","text":"раз"},'
                    ' {"persona":"apex_nerd","text":"два"}]')

    replies = generate_replies(
        post_id="p1", parent_id="c1", post_text="t", thread=[],
        player_text="x", ai_provider=_SamePersonaTwice(), parent_created_at=1.0,
    )

    assert len(replies) == 1
