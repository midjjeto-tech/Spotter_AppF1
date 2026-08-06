import time

import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from commentator.radio_answer import OFF_TOPIC_ANSWER


class FakeVoice:
    # Read-only surface get_state() snapshots (engine.get_state reads these off
    # self.voice); real Voice exposes them, so the fake must too.
    engine_name = "fake"
    last_engine = ""
    last_fallback = False
    active_speaker = ""
    status_message = ""
    is_available = True

    def __init__(self):
        self.is_critical_active = False
        self.said = []
        self.beeped = False

    def say(self, text, priority="normal", persona=None, **kwargs):
        """`**kwargs` намеренно: реальный `Voice.say` принимает необязательные
        `urgency`/`message_id`/`prepare`/`still_valid`, и двойник не должен
        падать на каждом новом из них. Без этого TypeError уходил в
        `_run_voice_question`'s except и превращался в «Внутренняя ошибка» —
        то есть тест ловил бы не поведение, а рассинхрон двойника."""
        self.said.append((text, priority))
        self.said_kwargs = {"persona": persona, **kwargs}
        return True

    def play_beep(self):
        self.beeped = True

    def set_persona(self, persona):
        self.last_persona = persona


class FakeListener:
    def __init__(self, audio):
        self.audio = audio

    def record(self, max_sec, sr=48000):
        return self.audio


class _BoomListener:
    def record(self, max_sec, sr=48000):
        raise RuntimeError("boom")


class FakeSTT:
    def __init__(self, text):
        self.text = text

    def recognize(self, audio, sr=48000):
        return self.text


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None      # без Yandex/сети -> ai.available=False, _stt=None
    try:
        e = F1Engine({})
        e.voice = FakeVoice()
        yield e
    finally:
        eng_mod.yc.load = orig


def _reset(engine):
    """Базовая линия «всё доступно» — каждый тест переопределяет только нужное."""
    engine._ui_state.set_voice_query(None)
    engine.voice.is_critical_active = False
    engine.voice.said.clear()
    engine.voice.beeped = False
    engine._yandex_healthy = True
    engine._stt = FakeSTT("вопрос")
    engine._voice_listener = FakeListener(b"\x00\x00")


def test_run_voice_question_plays_beep_before_recording(engine):
    _reset(engine)
    order = []
    orig_play_beep = engine.voice.play_beep

    def tracking_beep():
        order.append("beep")

    engine.voice.play_beep = tracking_beep
    orig_record = engine._voice_listener.record

    def tracking_record(max_sec, sr=48000):
        order.append("record")
        return orig_record(max_sec, sr)

    engine._voice_listener.record = tracking_record
    try:
        engine._run_voice_question()
        assert order == ["beep", "record"]
    finally:
        engine.voice.play_beep = orig_play_beep


def test_run_voice_question_no_beep_when_stt_unavailable(engine):
    _reset(engine)
    engine._stt = None
    engine._run_voice_question()
    assert engine.voice.beeped is False


def test_full_pipeline_off_topic_question_returns_fixed_phrase(engine):
    """Вопрос не про погоду/гэп/шины -> OFF_TOPIC_ANSWER, весь конвейер
    (listening->recognizing->thinking->done) отрабатывает, голос вызван с priority=normal."""
    _reset(engine)
    engine._stt = FakeSTT("какая тут музыка играет")
    engine._run_voice_question()
    vq = engine.get_state()["voice_query"]
    assert vq["status"] == "done"
    assert vq["question"] == "какая тут музыка играет"
    assert vq["answer"] == OFF_TOPIC_ANSWER
    assert engine.voice.said == [(OFF_TOPIC_ANSWER, "normal")]


def test_full_pipeline_weather_question_uses_telemetry(engine):
    _reset(engine)
    engine._stt = FakeSTT("какая погода")
    engine._current_weather = {"weather": 0, "track_temp": 30, "air_temp": 22}
    engine._rain_forecast = None
    engine._run_voice_question()
    vq = engine.get_state()["voice_query"]
    assert vq["status"] == "done"
    assert vq["answer"] == "Ясно, 30° на трассе. Дождя не ожидается."


def test_full_pipeline_gap_question_uses_telemetry(engine):
    _reset(engine)
    engine._stt = FakeSTT("какой гэп впереди")
    engine._player_gap_front = 1500
    engine._player_gap_behind = None
    engine._run_voice_question()
    vq = engine.get_state()["voice_query"]
    assert vq["status"] == "done"
    # До машины впереди — отставание; «отрыв» оставляем для преимущества
    # над машиной сзади (тот же контракт, что у radio_answer/_phrase bank).
    assert vq["answer"] == "До машины впереди 1.5."


def test_full_pipeline_tyres_question_uses_telemetry(engine):
    _reset(engine)
    engine._stt = FakeSTT("как шины")
    engine._player_tyre_wear = 55.0
    engine._run_voice_question()
    vq = engine.get_state()["voice_query"]
    assert vq["status"] == "done"
    assert vq["answer"] == "Износ шин 55%."


# --------------------------------------------------------------------------- #
# Voice Q&A expansion (3 -> 8 topics + voice commands). См. docs/superpowers/
# plans/2026-07-19-voice-qa-expansion.md.
# --------------------------------------------------------------------------- #

def test_full_pipeline_gap_question_includes_neighbor_names(engine):
    """"кто сзади" остаётся темой gap (не отдельной темой), но ответ теперь
    включает имя через self._neighbor_names()."""
    _reset(engine)
    engine._stt = FakeSTT("кто сзади")
    engine._player_car_index = 0
    engine._player_pos = 3
    engine._positions = {0: 3, 1: 2, 2: 4}
    engine._player_gap_front = None
    engine._player_gap_behind = 3000
    try:
        engine._run_voice_question()
        vq = engine.get_state()["voice_query"]
        assert vq["answer"] == "Отрыв сзади 3.0 — это гонщик."
    finally:
        engine._player_car_index = 255
        engine._player_pos = None
        engine._positions = {}


def test_full_pipeline_position_question_uses_telemetry(engine):
    _reset(engine)
    engine._stt = FakeSTT("какая у меня позиция")
    engine._player_pos = 7
    try:
        engine._run_voice_question()
        vq = engine.get_state()["voice_query"]
        assert vq["answer"] == "Ты на 7-м месте из 22."
    finally:
        engine._player_pos = None


def test_full_pipeline_penalties_question_uses_telemetry(engine):
    _reset(engine)
    engine._stt = FakeSTT("сколько у меня штрафов")
    engine._player_penalty_count = 2
    engine._player_penalty_seconds = 10
    try:
        engine._run_voice_question()
        vq = engine.get_state()["voice_query"]
        assert vq["answer"] == "У тебя 2 штрафа, 10 секунд."
    finally:
        engine._player_penalty_count = 0
        engine._player_penalty_seconds = 0


def test_full_pipeline_damage_question_uses_state(engine):
    _reset(engine)
    engine._stt = FakeSTT("какие повреждения")
    engine._player_damage = {"wing_damage": 45, "floor_damage": 0,
                             "gearbox_damage": 0, "engine_damage": 0}
    try:
        engine._run_voice_question()
        vq = engine.get_state()["voice_query"]
        assert vq["answer"] == "Повреждено: крыло 45%."
    finally:
        engine._player_damage = None


def test_full_pipeline_fuel_question_uses_telemetry(engine):
    _reset(engine)
    engine._stt = FakeSTT("сколько топлива")
    engine._player_fuel = 25.4
    try:
        engine._run_voice_question()
        vq = engine.get_state()["voice_query"]
        assert vq["answer"] == "Топлива 25.4 кг."
    finally:
        engine._player_fuel = None


def test_full_pipeline_ers_question_uses_telemetry(engine):
    _reset(engine)
    engine._stt = FakeSTT("сколько эрс")
    engine._player_ers_percent = 65.0
    engine._player_ers_deploy_mode = 1
    try:
        engine._run_voice_question()
        vq = engine.get_state()["voice_query"]
        assert vq["answer"] == "Заряд ERS 65%, режим — средний."
    finally:
        engine._player_ers_percent = None
        engine._player_ers_deploy_mode = None


def test_full_pipeline_laps_remaining_question_uses_telemetry(engine):
    _reset(engine)
    engine._stt = FakeSTT("сколько кругов осталось")
    engine._total_laps = 50
    engine._player_lap = 45
    try:
        engine._run_voice_question()
        vq = engine.get_state()["voice_query"]
        assert vq["answer"] == "Осталось 5 кругов."
    finally:
        engine._total_laps = None
        engine._player_lap = None


def test_full_pipeline_pit_window_question_uses_telemetry(engine):
    _reset(engine)
    engine._stt = FakeSTT("когда мне в питы")
    engine._player_tyre_age = 35
    engine._player_tyre_wear = 65.0
    engine._player_tyre_compound = "M"
    engine._total_laps = 50
    engine._player_lap = 35
    try:
        engine._run_voice_question()
        vq = engine.get_state()["voice_query"]
        assert vq["answer"] == "Окно пит-стопа открыто — заезжай в этом круге."
    finally:
        engine._player_tyre_age = None
        engine._player_tyre_wear = None
        engine._player_tyre_compound = None
        engine._total_laps = None
        engine._player_lap = None


def test_full_pipeline_tyre_sets_question_uses_telemetry(engine):
    _reset(engine)
    engine._stt = FakeSTT("сколько у меня комплектов")
    engine._player_tyre_sets_available = {"M": 2, "H": 1}
    try:
        engine._run_voice_question()
        vq = engine.get_state()["voice_query"]
        assert vq["answer"] == "Доступно: 2 медиум, 1 хард."
    finally:
        engine._player_tyre_sets_available = None


def test_full_pipeline_toggle_commentary_command_turns_off(engine):
    _reset(engine)
    original = engine.settings.get("commentary_enabled", True)
    engine.apply_settings({"commentary_enabled": True})
    engine._stt = FakeSTT("замолчи")
    try:
        engine._run_voice_question()
        vq = engine.get_state()["voice_query"]
        assert engine.settings["commentary_enabled"] is False
        assert vq["status"] == "done"
        assert vq["answer"] == "Понял, молчу."
    finally:
        engine.apply_settings({"commentary_enabled": original})


def test_full_pipeline_toggle_commentary_command_turns_on(engine):
    _reset(engine)
    original = engine.settings.get("commentary_enabled", True)
    engine.apply_settings({"commentary_enabled": False})
    engine._stt = FakeSTT("хватит болтать")
    try:
        engine._run_voice_question()
        vq = engine.get_state()["voice_query"]
        assert engine.settings["commentary_enabled"] is True
        assert vq["answer"] == "Хорошо, снова на связи."
    finally:
        engine.apply_settings({"commentary_enabled": original})


def test_full_pipeline_next_persona_command_cycles(engine):
    _reset(engine)
    original = engine.settings.get("persona", "tv")
    engine.apply_settings({"persona": "tv"})
    engine._stt = FakeSTT("смени персону")
    try:
        engine._run_voice_question()
        vq = engine.get_state()["voice_query"]
        assert engine.settings["persona"] == "hype"
        assert vq["answer"] == "Переключаю на хайп-фаната."
    finally:
        engine.apply_settings({"persona": original})


def test_full_pipeline_next_persona_command_wraps_around(engine):
    _reset(engine)
    original = engine.settings.get("persona", "tv")
    engine.apply_settings({"persona": "toxic"})
    engine._stt = FakeSTT("смени голос")
    try:
        engine._run_voice_question()
        vq = engine.get_state()["voice_query"]
        assert engine.settings["persona"] == "tv"
        assert vq["answer"] == "Переключаю на телекомментатора."
    finally:
        engine.apply_settings({"persona": original})


def test_stt_none_is_error(engine):
    _reset(engine)
    engine._stt = None
    engine._run_voice_question()
    vq = engine.get_state()["voice_query"]
    assert vq["status"] == "error" and vq["error"]


def test_yandex_unhealthy_is_error(engine):
    _reset(engine)
    engine._yandex_healthy = False
    engine._run_voice_question()
    vq = engine.get_state()["voice_query"]
    assert vq["status"] == "error" and vq["error"]


def test_mic_unavailable_is_error(engine):
    _reset(engine)
    engine._voice_listener = FakeListener(None)
    engine._run_voice_question()
    vq = engine.get_state()["voice_query"]
    assert vq["status"] == "error" and vq["error"]


def test_recognize_none_is_error(engine):
    _reset(engine)
    engine._stt = FakeSTT(None)
    engine._run_voice_question()
    vq = engine.get_state()["voice_query"]
    assert vq["status"] == "error" and vq["error"]


def test_unexpected_exception_sets_error_not_stuck(engine):
    """Неожиданный сбой не должен оставлять voice_query подвешенным в recognizing/thinking."""
    _reset(engine)
    engine._voice_listener = _BoomListener()
    engine._run_voice_question()
    vq = engine.get_state()["voice_query"]
    assert vq["status"] == "error"


def test_ask_voice_question_busy_when_in_progress(engine):
    _reset(engine)
    engine._ui_state.set_voice_query({
        "status": "thinking", "question": "q", "answer": None, "error": None,
    })
    assert engine.ask_voice_question() == {"ok": False, "busy": True, "reason": "in_progress"}


def test_ask_voice_question_busy_when_critical(engine):
    _reset(engine)
    engine.voice.is_critical_active = True
    result = engine.ask_voice_question()
    assert result == {"ok": False, "busy": True, "reason": "critical"}
    assert engine.get_state()["voice_query"] is None      # ничего не тронули


def test_ask_voice_question_runs_in_background(engine):
    _reset(engine)
    assert engine.ask_voice_question() == {"ok": True}
    deadline = time.time() + 2.0
    while engine.get_state()["voice_query"]["status"] not in ("done", "error") and time.time() < deadline:
        time.sleep(0.02)
    assert engine.get_state()["voice_query"]["status"] == "done"


def test_test_mic_success(engine, monkeypatch):
    _reset(engine)
    engine._voice_listener = FakeListener(b"\x00\x01")
    played = []
    monkeypatch.setattr(eng_mod, "play_back", lambda audio, sr=48000: played.append(audio))
    result = engine.test_mic()
    assert result == {"ok": True}
    assert played == [b"\x00\x01"]


def test_test_mic_no_microphone_is_error(engine):
    _reset(engine)
    engine._voice_listener = FakeListener(None)
    result = engine.test_mic()
    assert result == {"ok": False, "error": "Микрофон недоступен"}


def test_test_mic_playback_failure_is_error(engine, monkeypatch):
    _reset(engine)
    engine._voice_listener = FakeListener(b"\x00\x01")

    def _boom(audio, sr=48000):
        raise RuntimeError("no output device")

    monkeypatch.setattr(eng_mod, "play_back", _boom)
    result = engine.test_mic()
    assert result == {"ok": False, "error": "Не удалось воспроизвести"}
