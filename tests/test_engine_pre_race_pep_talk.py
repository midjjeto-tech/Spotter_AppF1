import struct

import pytest

import core.engine as eng_mod
from core.engine import F1Engine
from core.radio import voice_cast
from core.packets import HEADER_SIZE, PACKET_SESSION
from tests.telemetry import consume_f1_packet


@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None              # без Yandex/сети → фолбэк
    try:
        yield F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _session_packet(session_type_raw: int, track_id: int = 5) -> bytes:
    """Собрать PACKET_SESSION с заданным сырым session_type (см.
    tests/test_session_type.py для расшифровки офсетов и SESSION_TYPE_MAP)."""
    header = b"\x00" * HEADER_SIZE
    payload = struct.pack("<BBbBHBb", 0, 25, 20, 10, 5793, session_type_raw, track_id)
    return header + payload


class _StubThread:
    """Стенд-ин threading.Thread: не выполняет target, только запоминает start()."""

    def __init__(self, target=None, daemon=None, name=None):
        pass

    def start(self):
        pass


def _patch_thread_spawn(monkeypatch, spawned: list) -> None:
    """monkeypatch eng_mod.threading.Thread так, чтобы имя треда попадало в
    spawned, а не запускался реальный поток (иначе _pre_race_pep_talk реально
    засыпает на config.PRE_RACE_PEP_TALK_DELAY_S секунд в фоне теста)."""
    def _fake_thread(target, daemon, name):
        spawned.append(name)
        return _StubThread()
    monkeypatch.setattr(eng_mod.threading, "Thread", _fake_thread)


def test_transition_to_race_spawns_thread_once(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "unknown"
    engine._pre_race_pep_talk_fired = False
    # Совпадает с track_id по умолчанию в _session_packet(): гасит НЕсвязанную
    # track-change-логику (_start_f1_benchmark_load/_start_career_memory_load,
    # см. core/engine.py::_update_telemetry), которая иначе тоже спавнит
    # потоки через тот же monkeypatched threading.Thread на самом первом
    # пакете свежего движка (self._track_id стартует с -1) и засоряет
    # список spawned посторонними именами.
    engine._track_id = 5
    spawned: list = []
    _patch_thread_spawn(monkeypatch, spawned)

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_SESSION,
                             _session_packet(session_type_raw=15))   # -> "race"
    assert spawned == ["pre-race-pep-talk"]
    assert engine._pre_race_pep_talk_fired is True

    # Повторный тик с тем же session_type НЕ меняет new_st != self._session_type,
    # значит блок вообще не выполняется — поток не спавнится второй раз.
    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_SESSION,
                             _session_packet(session_type_raw=15))
    assert spawned == ["pre-race-pep-talk"]


def test_leaving_race_resets_guard_and_reentering_refires(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = True
    engine._session_type = "race"
    engine._pre_race_pep_talk_fired = True
    spawned: list = []
    _patch_thread_spawn(monkeypatch, spawned)

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_SESSION,
                             _session_packet(session_type_raw=5))    # -> "qualifying"
    assert engine._pre_race_pep_talk_fired is False
    assert spawned == []                                             # не гонка — не спавним

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_SESSION,
                             _session_packet(session_type_raw=15))   # -> "race" снова
    assert spawned == ["pre-race-pep-talk"]
    assert engine._pre_race_pep_talk_fired is True


def test_engineer_chatter_disabled_suppresses_spawn(engine, monkeypatch):
    engine.settings["engineer_chatter_enabled"] = False
    engine._session_type = "unknown"
    engine._pre_race_pep_talk_fired = False
    spawned: list = []
    _patch_thread_spawn(monkeypatch, spawned)

    consume_f1_packet(engine, {"player_car_index": 0}, PACKET_SESSION,
                             _session_packet(session_type_raw=15))
    assert spawned == []
    assert engine._pre_race_pep_talk_fired is False   # не выставлен — включение тумблера сработает сразу
    engine.settings["engineer_chatter_enabled"] = True


def test_generate_pre_race_pep_talk_first_career_race_stays_silent(engine, tmp_path, monkeypatch):
    import analytics.archive as archive_mod
    monkeypatch.setattr(archive_mod, "_GAME_SESSIONS", tmp_path)   # пустой архив
    engine.settings["autovoice_enabled"] = False
    engine._session_type = "race"
    said = []
    monkeypatch.setattr(engine.voice, "say", lambda *a, **kw: said.append(a) or True)
    engine._generate_pre_race_pep_talk()
    assert said == []


def test_generate_pre_race_pep_talk_speaks_with_the_engineer_voice(engine, tmp_path, monkeypatch):
    import analytics.archive as archive_mod
    monkeypatch.setattr(archive_mod, "_GAME_SESSIONS", tmp_path)
    archive_mod._atomic_write(tmp_path / "2026-01-01_10-00-00_000001.json",
                              {"track_name": "Монца", "session_type": "race", "final_position": 2})
    engine.settings["autovoice_enabled"] = True
    engine.settings["critical_events_enabled"] = True
    engine._session_type = "race"
    said = []
    monkeypatch.setattr(engine.voice, "say",
                        lambda text, priority="normal", persona=None:
                        said.append((text, priority, persona)) or True)
    engine._generate_pre_race_pep_talk()
    assert len(said) == 1
    text, priority, persona = said[0]
    assert isinstance(text, str) and len(text) > 0
    assert priority == "normal"
    # Слот инженера, а не персона комментатора "calm". Этот путь не строит
    # RadioMessage, поэтому слот подставляется константой напрямую — но
    # PRE_RACE_PEP_TALK входит в policy._ENGINEER_CODES, и звучать он обязан
    # голосом инженера. С прежним "calm" напутствие перед стартом было
    # единственной репликой инженерского канала, которую произносил
    # комментатор.
    assert persona == voice_cast.SLOT_ENGINEER


def test_generate_pre_race_pep_talk_skips_if_left_race_screen(engine, tmp_path, monkeypatch):
    import analytics.archive as archive_mod
    monkeypatch.setattr(archive_mod, "_GAME_SESSIONS", tmp_path)
    archive_mod._atomic_write(tmp_path / "2026-01-01_10-00-00_000001.json",
                              {"track_name": "Монца", "session_type": "race", "final_position": 2})
    engine._session_type = "qualifying"   # игрок вышел из подготовки
    said = []
    monkeypatch.setattr(engine.voice, "say", lambda *a, **kw: said.append(a) or True)
    engine._generate_pre_race_pep_talk()
    assert said == []
