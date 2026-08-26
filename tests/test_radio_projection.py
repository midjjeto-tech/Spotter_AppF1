"""Проекция радио для карточки в кадре: персоны, ревизия, портреты.

Дополняет `test_radio_session.py` (активная передача, история, «повтори») и
`test_radio_lifecycle.py` (переходы состояний) — их пункты здесь не
дублируются. Здесь только то, что добавила телевизионная подача: кто говорит,
как это подписано, и почему клиенту не нужно перекачивать историю на каждом
опросе.
"""
import json

import pytest

from core.radio import policy, speakers
from core.radio.message import (
    STATE_COMPLETED, STATE_PLAYING, RadioCancelReason, build_message,
)
from core.radio.session import MAX_HISTORY, RadioSession


def _msg(phrase, *, code="ENGINEER_GAP_DIGEST", speaker="engineer", mono=0.0):
    event = {"event_code": code, "speaker": speaker,
             "created_at": 1000.0, "created_mono": mono}
    return build_message(event, phrase=phrase, now=1000.0, now_mono=mono)


@pytest.fixture
def session():
    return RadioSession(clock=lambda: 1000.0)


# ── Профили говорящих ───────────────────────────────────────────────────────

def test_profile_is_chosen_by_channel():
    """ТЗ §21.10: канал определяет, кто говорит."""
    assert speakers.profile_for(policy.CHANNEL_ENGINEER) is speakers.RACE_ENGINEER
    assert speakers.profile_for(policy.CHANNEL_SPOTTER) is speakers.SPOTTER
    assert speakers.profile_for(speakers.CHANNEL_DRIVER) is speakers.DRIVER
    assert speakers.profile_for(policy.CHANNEL_COMMENTATOR).role == "RACE ANALYST"


@pytest.mark.parametrize("persona", ["tv", "hype", "calm", "toxic", None, "нет такой"])
def test_commentator_persona_never_replaces_the_engineer(persona):
    """ТЗ §21.11 — главная гарантия §15.

    Критическую команду в боксы обязан отдать инженер со своим именем и своей
    ролью, какую бы персону комментатора игрок ни выбрал. Иначе «токсичный
    напарник» однажды объявит box-call, и игрок не поймёт, шутка это или нет."""
    engineer = speakers.profile_for(policy.CHANNEL_ENGINEER, persona)
    spotter = speakers.profile_for(policy.CHANNEL_SPOTTER, persona)

    assert engineer is speakers.RACE_ENGINEER
    assert engineer.display_name == "ИГОРЬ ВОЛКОВ"
    assert engineer.role == "RACE ENGINEER"
    assert spotter is speakers.SPOTTER


def test_engineer_card_names_the_character_the_pilot_chose():
    """Карточка обязана назвать ТОГО, чей голос звучит.

    Настройка `engineer_character` уже меняла две вещи из трёх: голос
    (`voice_cast.resolve`) и пул формулировок (`phrases.variants_for`). Имя в
    кадре бралось из фиксированного профиля, поэтому при выбранном Громе
    карточка подписывала реплику Волковым — голос, слова и подпись
    расходились втроём на одной реплике.

    Роль при этом НЕ меняется: должность у инженера одна, меняется человек.
    """
    for character, expected in (("volkov", "ИГОРЬ ВОЛКОВ"),
                                ("sokolova", "МАРИНА СОКОЛОВА"),
                                ("grom", "ВИКТОР ГРОМ")):
        profile = speakers.profile_for(
            policy.CHANNEL_ENGINEER, character=character)
        assert profile.display_name == expected, character
        assert profile.role == "RACE ENGINEER"
        assert profile.speaker_id == speakers.RACE_ENGINEER.speaker_id
        assert profile.accent == speakers.RACE_ENGINEER.accent


def test_unknown_engineer_character_falls_back_instead_of_blanking_the_card():
    """Настройка приходит из файла, который правят руками.

    Пустая или неизвестная строка не должна оставлять карточку без имени:
    подпись — не то место, где отказ полезнее умолчания."""
    for value in (None, "", "нет такого"):
        assert speakers.profile_for(
            policy.CHANNEL_ENGINEER, character=value) is speakers.RACE_ENGINEER


def test_engineer_character_does_not_leak_into_other_channels():
    """Споттер и комментатор — другие люди, их подпись персонажу не подчиняется."""
    assert speakers.profile_for(
        policy.CHANNEL_SPOTTER, character="grom") is speakers.SPOTTER
    assert speakers.profile_for(
        policy.CHANNEL_COMMENTATOR, "tv", character="grom").role == "RACE ANALYST"


def test_persona_selects_the_commentator_profile():
    names = {persona: speakers.profile_for(policy.CHANNEL_COMMENTATOR, persona).display_name
             for persona in ("tv", "hype", "calm", "toxic")}
    assert len(set(names.values())) == 4, "у каждой персоны своё имя в кадре"
    # Неизвестная персона не роняет проекцию и не остаётся без подписи.
    assert speakers.profile_for(policy.CHANNEL_COMMENTATOR, "нет такой").display_name


def test_profiles_agree_with_the_pipeline_contract():
    """`speakers` и `policy` описывают одного и того же говорящего.

    Короткая подпись и персона голоса живут в `policy` (это конвейер), имя,
    роль и портрет — в `speakers` (это презентация). Разъехаться им нельзя, а
    импортировать друг друга они не могут — циклом. Тест и есть та связь."""
    for channel in (policy.CHANNEL_ENGINEER, policy.CHANNEL_SPOTTER,
                    policy.CHANNEL_COMMENTATOR):
        profile = speakers.profile_for(channel)
        assert profile.short_label == policy.speaker_label_for(channel)
        assert profile.voice_persona == policy.voice_persona_for(channel)


def test_missing_portrait_does_not_break_the_projection(session):
    """ТЗ §21.9: отсутствие портрета — штатный случай, не ошибка.

    Портрет пилота не заведён вовсе, и это правильно: реплика пилота не
    карточка инженера. Проекция обязана остаться валидной и сериализуемой."""
    assert speakers.DRIVER.portrait_url is None
    session.note_driver_line("Какой износ?")
    payload = session.to_ui_dict()

    entry = payload["history"][0]
    assert entry["speaker_name"] == "ПИЛОТ"
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload


def test_portrait_url_is_a_path_not_a_blob():
    """ТЗ §20: base64-портретов в снимке состояния быть не должно —
    иначе каждый опрос тащит картинку заново."""
    url = speakers.RACE_ENGINEER.portrait_url
    assert url == "/assets/radio/engineer.webp"
    assert "base64" not in url


def test_initials_fall_back_readably():
    assert speakers.RACE_ENGINEER.initials == "ИВ"
    # Одно слово даёт одну букву: «СП» читалось бы как обрезанное слово.
    assert speakers.SPOTTER.initials == "С"


def test_active_message_carries_the_speaker(session):
    session.note(_msg("Боксы в конце круга.").with_state(STATE_PLAYING, now=1.0))
    active = session.to_ui_dict()["active_message"]

    assert active["speaker_id"] == "race_engineer"
    assert active["speaker_name"] == "ИГОРЬ ВОЛКОВ"
    assert active["speaker_role"] == "RACE ENGINEER"
    assert active["portrait_url"] == "/assets/radio/engineer.webp"
    assert active["accent"] == "#e32636"


def test_history_freezes_the_speaker_at_the_time_of_speaking():
    """Смена персоны не переписывает того, кто уже отговорил.

    Иначе лента задним числом покажет неправду: реплику произнёс один
    комментатор, а подписана она будет другим."""
    persona = {"value": "tv"}
    session = RadioSession(clock=lambda: 1000.0)
    session.set_persona_provider(lambda: persona["value"])

    spoken = _msg("Норрис проходит.", code="OVTK", speaker="commentator")
    session.note(spoken.with_state(STATE_PLAYING, now=1.0))
    first = session.to_ui_dict()["history"][0]["speaker_name"]

    persona["value"] = "toxic"
    assert session.to_ui_dict()["history"][0]["speaker_name"] == first


def test_broken_persona_provider_does_not_break_the_projection(session):
    """Подпись комментатора не стоит того, чтобы из-за неё пропала панель."""
    def explode():
        raise RuntimeError("настройки недоступны")

    session.set_persona_provider(explode)
    session.note(_msg("Проверка.").with_state(STATE_PLAYING, now=1.0))

    assert session.to_ui_dict()["active_message"]["speaker_name"]


def test_chosen_character_reaches_the_card_and_the_roster(session):
    """Проводка, а не чистая функция.

    `profile_for` научился персонажу отдельным тестом — этот проверяет, что
    выбор доезжает до обоих мест, которые рисует карточка: активного
    сообщения и справочника `speakers`, по которому UI подписывает «слушаю»
    и «проверяю данные» ещё до появления реплики."""
    session.set_character_provider(lambda: "grom")
    session.note(_msg("Место взял. Теперь удержи.").with_state(
        STATE_PLAYING, now=1.0))

    projection = session.to_ui_dict()

    assert projection["active_message"]["speaker_name"] == "ВИКТОР ГРОМ"
    assert projection["active_message"]["speaker_initials"] == "ВГ"
    assert projection["speakers"]["engineer"]["speaker_name"] == "ВИКТОР ГРОМ"
    # Роль и канал остаются прежними: сменился человек, а не должность.
    assert projection["speakers"]["engineer"]["speaker_role"] == "RACE ENGINEER"
    assert projection["speakers"]["spotter"]["speaker_name"] == "СПОТТЕР"


def test_broken_character_provider_still_signs_the_card(session):
    """Тот же принцип, что у персоны: подпись не стоит панели радио."""
    def explode():
        raise RuntimeError("настройки недоступны")

    session.set_character_provider(explode)
    session.note(_msg("Проверка.").with_state(STATE_PLAYING, now=1.0))

    assert session.to_ui_dict()["active_message"]["speaker_name"] == "ИГОРЬ ВОЛКОВ"


# ── Ревизия ─────────────────────────────────────────────────────────────────

def test_revision_does_not_move_without_a_change(session):
    """ТЗ §21.15 и критерий 14 — ради этого ревизия и существует."""
    message = _msg("Отрыв впереди: 1.3.")
    session.note(message)
    settled = session.revision()

    for _ in range(5):
        session.note(message)
    assert session.revision() == settled


def test_revision_moves_on_every_visible_change(session):
    message = _msg("Отрыв впереди: 1.3.")
    session.note(message)
    after_queue = session.revision()

    playing = message.with_state(STATE_PLAYING, now=1.0)
    session.note(playing)
    assert session.revision() > after_queue

    after_play = session.revision()
    session.note(playing.with_state(STATE_COMPLETED, now=2.0))
    assert session.revision() > after_play


def test_revision_moves_when_late_binding_changes_the_text(session):
    """Позднее связывание меняет ТЕКСТ, не трогая состояние.

    Без этого в ленте осталась бы фраза с неразрешённым токеном, а клиент по
    совпадению ревизии даже не запросил бы обновление."""
    message = _msg("Отрыв впереди: {gap}.")
    session.note(message)
    before = session.revision()

    session.note(message.with_phrase("Отрыв впереди: 1.3."))
    assert session.revision() > before
    assert session.to_ui_dict()["history"][0]["text"] == "Отрыв впереди: 1.3."


def test_reset_moves_the_revision_forward_not_back(session):
    """Сброс в ноль клиент прочитал бы как «ничего не изменилось»."""
    session.note(_msg("Первая.").with_state(STATE_PLAYING, now=1.0))
    before = session.revision()

    session.reset()
    assert session.revision() > before
    assert session.to_ui_dict()["active_message"] is None


def test_clearing_empty_history_is_not_a_change(session):
    before = session.revision()
    session.clear_history()
    assert session.revision() == before


# ── PTT-диалог ──────────────────────────────────────────────────────────────

def test_answer_is_linked_to_the_ptt_session(session):
    """ТЗ §21.12: вопрос и ответ — один диалог, связь не угадывается по времени."""
    session.set_ptt("thinking", driver_text="Какой отрыв?")
    answer = _msg("Семь десятых.", code="USER_Q_GAP")
    session.note(answer.with_state(STATE_PLAYING, now=1.0))

    assert session.to_ui_dict()["ptt"]["answer_message_id"] == answer.id


def test_automatic_message_does_not_claim_the_ptt_answer(session):
    session.set_ptt("thinking", driver_text="Какой отрыв?")
    session.note(_msg("Боксы в конце круга.", code="STRAT_BOX_CALL_2")
                 .with_state(STATE_PLAYING, now=1.0))

    assert session.to_ui_dict()["ptt"]["answer_message_id"] is None


def test_new_question_drops_the_previous_answer(session):
    session.set_ptt("thinking", driver_text="Какой отрыв?")
    session.note(_msg("Семь десятых.", code="USER_Q_GAP")
                 .with_state(STATE_PLAYING, now=1.0))

    session.set_ptt("listening")
    assert session.to_ui_dict()["ptt"]["answer_message_id"] is None


def test_idle_ptt_does_not_capture_an_answer(session):
    """Ответ без заданного вопроса — это не диалог."""
    session.note(_msg("Справочно.", code="USER_Q").with_state(STATE_PLAYING, now=1.0))
    assert session.to_ui_dict()["ptt"]["answer_message_id"] is None


def test_repeated_ptt_status_does_not_move_the_revision(session):
    session.set_ptt("listening")
    settled = session.revision()
    session.set_ptt("listening")
    assert session.revision() == settled


# ── История и сериализация ──────────────────────────────────────────────────

def test_history_is_bounded(session):
    """ТЗ §21.13. История уходит в КАЖДЫЙ снимок состояния — предел здесь не
    про память, а про стоимость сериализации."""
    assert 100 <= MAX_HISTORY <= 200
    for index in range(MAX_HISTORY + 40):
        session.note(_msg(f"Реплика {index}.", mono=float(index)))

    assert len(session.to_ui_dict()["history"]) == MAX_HISTORY


def test_cancel_reason_is_serialised_as_a_plain_string(session):
    """ТЗ §21.14: наружу уходит значение enum, а не объект — иначе снимок не
    переживёт `json.dumps`."""
    message = _msg("Отрыв впереди: 1.3.")
    session.note(message)
    session.note(message.cancelled(RadioCancelReason.EXPIRED, now=2.0))

    payload = session.to_ui_dict()
    assert payload["history"][0]["cancel_reason"] == "expired"
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload


def test_projection_has_no_unresolved_placeholders(session):
    """ТЗ §21.18: в UI не должен попасть текст с незакрытым токеном.

    Проверяется на том, что реально дошло до ленты, а не на банке фраз: до
    позднего связывания токен в сообщении законен, после — уже нет."""
    message = _msg("Отрыв впереди: {gap}.")
    session.note(message)
    session.note(message.with_phrase("Отрыв впереди: 1.3.")
                 .with_state(STATE_PLAYING, now=1.0))

    for entry in session.to_ui_dict()["history"]:
        assert "{" not in entry["text"] and "}" not in entry["text"]


# ── Экономия трафика опроса ─────────────────────────────────────────────────

def _state_with(revision: int, history: list) -> dict:
    return {"radio": {"revision": revision, "history": history}}


def test_unchanged_history_is_not_resent():
    """Критерий 14: при совпадении ревизии история не уезжает клиенту заново.

    Оверлей опрашивает состояние 4 раза в секунду, история — до 150 строк."""
    from web_server import _trim_unchanged_radio_history

    state = _state_with(7, [{"id": "a"}])
    _trim_unchanged_radio_history(state, "7")

    assert state["radio"]["history"] is None
    assert state["radio"]["history_unchanged"] is True


def test_changed_history_is_sent_in_full():
    from web_server import _trim_unchanged_radio_history

    state = _state_with(8, [{"id": "a"}])
    _trim_unchanged_radio_history(state, "7")

    assert state["radio"]["history"] == [{"id": "a"}]
    assert "history_unchanged" not in state["radio"]


@pytest.mark.parametrize("since", [None, "", "не число", "7.5"])
def test_missing_or_broken_revision_gets_the_full_payload(since):
    """Старый клиент и мусор в query получают полную историю.

    Панель без данных из-за ошибки в параметре — худший исход, чем лишние
    байты на localhost."""
    from web_server import _trim_unchanged_radio_history

    state = _state_with(7, [{"id": "a"}])
    _trim_unchanged_radio_history(state, since)

    assert state["radio"]["history"] == [{"id": "a"}]


def test_trimming_survives_a_state_without_radio():
    from web_server import _trim_unchanged_radio_history

    state = {"connected": False}
    _trim_unchanged_radio_history(state, "7")

    assert state == {"connected": False}


def test_speaker_plumbing_never_leaks_into_the_event():
    """ТЗ §21.19: презентация не имеет права попасть в доменное событие.

    Словарь события целиком уезжает в `Event.extra` → `facts` → промпт LLM и в
    `claim_fingerprint` RaceFeed. Портрет и HEX-акцент там — это и мусор в
    промпте, и изменившийся отпечаток у всех историй разом. Прецедент уже был:
    `damage_severity` осознанно добавили в корень события и отпечатки
    поехали."""
    event = {"event_code": "OVTK", "speaker": "commentator",
             "created_at": 1000.0, "created_mono": 0.0}
    before = dict(event)

    message = build_message(event, phrase="Норрис проходит.",
                            now=1000.0, now_mono=0.0)
    message.to_ui_dict(persona="toxic")

    assert event == before
    for key in ("speaker_id", "speaker_name", "speaker_role",
                "portrait_url", "accent", "speaker_initials"):
        assert key not in event


def test_every_cancel_reason_has_a_serialisable_value():
    """Новая причина отмены не должна появиться без значения — по этим строкам
    интерфейс подбирает человеческий текст."""
    for reason in RadioCancelReason:
        assert isinstance(reason.value, str) and reason.value
        assert reason.value.islower()
