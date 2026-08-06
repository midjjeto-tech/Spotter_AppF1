"""Инженер сам начинает разговор — и корректно принимает ответ.

Две половины одной фичи, и вторая важнее первой. Без неё получается так:
инженер спрашивает «Как шины держат?», пилот отвечает «нормально», а
PTT-конвейер не распознаёт в этом вопроса и выдаёт
`radio_answer.OFF_TOPIC_ANSWER` — «Возьми фокус на гонку, пока не можем
ответить». Отповедь на вопрос, который инженер сам же и задал.
"""
import pytest

from commentator import radio_answer
from core.radio import phrases
from core.strategy_ai.driver_query import (
    BUSY_GAP_MS, CODE_BALANCE, CODE_BRAKES, CODE_FEEL, CODE_TYRES,
    MIN_STINT_LAPS_FOR_TYRES, DriverQueryTracker,
)


@pytest.fixture
def asker():
    return DriverQueryTracker(cooldown=180.0)


def _check(asker, *, front=None, behind=None, tyre_age=20,
           safety_car=False, now=0.0):
    return asker.check(gap_front_ms=front, gap_behind_ms=behind,
                       tyre_age=tyre_age, safety_car=safety_car, now=now)


# ── Когда спрашивать уместно ─────────────────────────────────────────────────

def test_asks_when_the_driver_is_alone(asker):
    assert _check(asker, now=1000.0) is not None


def test_stays_silent_while_fighting_ahead(asker):
    """Вопрос в разгар борьбы — помеха: у пилота руки заняты."""
    assert _check(asker, front=BUSY_GAP_MS - 100, now=1000.0) is None


def test_stays_silent_while_being_attacked(asker):
    assert _check(asker, behind=BUSY_GAP_MS - 100, now=1000.0) is None


def test_an_empty_gap_is_not_busy(asker):
    """Гэпа нет — рядом попросту никого, это самый спокойный момент.
    Считать None занятостью значило бы молчать как раз тогда, когда можно."""
    assert _check(asker, front=None, behind=None, now=1000.0) is not None


def test_stays_silent_under_safety_car(asker):
    """Пилот свободен, но эфир занят организационными вводными."""
    assert _check(asker, safety_car=True, now=1000.0) is None


# ── Как часто и что именно ───────────────────────────────────────────────────

def test_questions_are_rare(asker):
    assert _check(asker, now=1000.0) is not None
    assert _check(asker, now=1100.0) is None
    assert _check(asker, now=1200.0) is not None


def test_the_same_question_is_never_asked_twice(asker):
    """Спросив про шины, инженер не спрашивает про них снова — он уже слышал
    ответ (или не услышал, что тоже ответ)."""
    seen = set()
    now = 1000.0
    for _ in range(4):
        code = _check(asker, now=now)
        if code is None:
            break
        assert code not in seen, code
        seen.add(code)
        now += 200.0
    assert len(seen) >= 3


def test_the_bank_runs_out_politely(asker):
    """Вопросы кончились — инженер молчит, а не зацикливается."""
    now = 1000.0
    for _ in range(10):
        _check(asker, now=now)
        now += 200.0
    assert _check(asker, now=now) is None


def test_tyres_are_not_asked_about_on_fresh_rubber(asker):
    """«Как шины?» на первом круге стинта — вопрос ни о чём, ответа на него
    ещё не существует."""
    assert _check(asker, tyre_age=1, now=1000.0) != CODE_TYRES


def test_tyres_come_first_once_the_stint_is_long_enough(asker):
    """Ответ про шины полезнее остальных для решений по стратегии."""
    assert _check(asker, tyre_age=MIN_STINT_LAPS_FOR_TYRES, now=1000.0) == CODE_TYRES


def test_reset_forgets_everything(asker):
    assert _check(asker, now=1000.0) is not None
    asker.reset()
    assert _check(asker, now=1010.0) is not None


# ── Связь с банком ───────────────────────────────────────────────────────────

def test_every_question_exists_in_the_bank():
    for code in (CODE_TYRES, CODE_BALANCE, CODE_BRAKES, CODE_FEEL):
        assert code in phrases.codes(), code


def test_questions_actually_ask_something():
    """Реплика без вопросительного знака вопросом не прозвучит, и пилот не
    поймёт, что от него ждут ответа."""
    for code in (CODE_TYRES, CODE_BALANCE, CODE_BRAKES, CODE_FEEL):
        spec = phrases.spec_for(code)
        for pool in [spec.variants, *spec.character_variants.values()]:
            for variant in pool:
                assert "?" in variant, f"{code}: {variant!r}"


# ── Приём ответа: вторая половина фичи ───────────────────────────────────────

def test_off_topic_answer_is_what_would_break_the_conversation():
    """Фиксируем исходное поведение, ради которого всё это писалось: без окна
    ответа реплика пилота получает отповедь."""
    assert radio_answer.classify_topic("нормально") is None
    assert radio_answer.classify_command("нормально") is None


PLAYER = 3


@pytest.fixture
def engine(monkeypatch):
    import core.engine as eng_mod
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    e = eng_mod.F1Engine({"engineer_chatter_enabled": True})
    e._player_car_index = PLAYER
    e._session_type = "race"
    e._player_tyre_age = 20
    e._player_gap_front = None
    e._player_gap_behind = None
    return e


def _drain(engine) -> list[dict]:
    out = []
    while not engine._commentary_events.empty():
        out.append(engine._commentary_events.get_nowait())
    return out


def test_tick_publishes_a_question(engine):
    engine._driver_query_tick()
    asked = [e for e in _drain(engine)
             if e.get("event_code") == "ENGINEER_ASKS_DRIVER"]
    assert asked and "?" in asked[0]["phrase"], asked


def test_asking_opens_the_reply_window(engine):
    import time as _time
    assert not engine._ptt_reply_expected(_time.time())
    engine._driver_query_tick()
    assert engine._ptt_reply_expected(_time.time())


def test_the_window_closes_on_its_own(engine):
    import time as _time
    engine._driver_query_tick()
    later = _time.time() + engine.DRIVER_REPLY_WINDOW_S + 1
    assert not engine._ptt_reply_expected(later)


def test_no_questions_outside_a_race(engine):
    engine._session_type = "practice"
    engine._driver_query_tick()
    assert not [e for e in _drain(engine)
                if e.get("event_code") == "ENGINEER_ASKS_DRIVER"]


def test_questions_respect_the_chatter_setting(engine):
    engine.settings["engineer_chatter_enabled"] = False
    engine._driver_query_tick()
    assert not [e for e in _drain(engine)
                if e.get("event_code") == "ENGINEER_ASKS_DRIVER"]


def test_no_question_while_the_driver_is_fighting(engine):
    engine._player_gap_front = 800
    engine._driver_query_tick()
    assert not [e for e in _drain(engine)
                if e.get("event_code") == "ENGINEER_ASKS_DRIVER"]


# ── Сквозной разговор ────────────────────────────────────────────────────────
# Ради этого всё и писалось: инженер спросил — пилот ответил — инженер принял.

class _FakeSTT:
    def __init__(self, text):
        self.text = text

    def recognize(self, audio, sr=48000):
        return self.text


class _FakeVoice:
    engine_name = "fake"
    last_engine = ""
    last_fallback = False
    active_speaker = ""
    status_message = ""
    is_available = True

    def __init__(self):
        self.is_critical_active = False
        self.said = []

    def say(self, text, priority="normal", persona=None, **kwargs):
        self.said.append(text)
        return True

    def play_beep(self):
        pass


@pytest.fixture
def talking(engine, monkeypatch):
    engine.voice = _FakeVoice()
    engine._yandex_healthy = True
    monkeypatch.setattr(engine._voice_listener, "record",
                        lambda *a, **k: b"audio")
    return engine


def test_the_driver_reply_is_acknowledged_not_brushed_off(talking):
    """Инженер спросил «Как шины?», пилот ответил «нормально». Без окна ответа
    прозвучало бы «Возьми фокус на гонку, пока не можем ответить» — отповедь на
    собственный вопрос."""
    talking._driver_query_tick()
    _drain(talking)
    talking._stt = _FakeSTT("нормально")

    talking._run_voice_question()

    answer = talking.get_state()["voice_query"]["answer"]
    assert answer != radio_answer.OFF_TOPIC_ANSWER
    assert answer in phrases.ACKNOWLEDGEMENTS, answer


def test_without_a_question_the_off_topic_answer_stands(talking):
    """Окно НЕ должно проглатывать отповедь всегда: пилот, заговоривший не по
    делу без всякого вопроса, по-прежнему получает прежний ответ."""
    talking._stt = _FakeSTT("нормально")
    talking._run_voice_question()
    assert (talking.get_state()["voice_query"]["answer"]
            == radio_answer.OFF_TOPIC_ANSWER)


def test_a_real_question_in_the_window_still_gets_real_data(talking):
    """«Износ большой» в ответ на «как шины?» — распознаваемая тема, и она
    заслуживает настоящих цифр, а не вежливого «принято»."""
    talking._driver_query_tick()
    _drain(talking)
    talking._player_tyre_wear = 62.0
    talking._stt = _FakeSTT("какой износ шин")

    talking._run_voice_question()

    answer = talking.get_state()["voice_query"]["answer"]
    assert answer not in phrases.ACKNOWLEDGEMENTS
    assert "62" in answer, answer


def test_the_window_is_consumed_by_one_reply(talking):
    """Ответ засчитывается один раз: следующая невнятная реплика — уже не
    ответ, и притворяться, что инженер всё ещё ждёт, нельзя."""
    talking._driver_query_tick()
    _drain(talking)
    talking._stt = _FakeSTT("нормально")
    talking._run_voice_question()
    talking._ui_state.set_voice_query(None)

    talking._run_voice_question()
    assert (talking.get_state()["voice_query"]["answer"]
            == radio_answer.OFF_TOPIC_ANSWER)
