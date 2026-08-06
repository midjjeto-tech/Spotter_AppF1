"""Коды готовности: что именно увидит пользователь в визарде.

Тесты держат не формат словаря, а обещания, которые он даёт. Главное из них —
`ok` значит «работает сейчас», а не «настроено»: телеметрия без свежих пакетов
обязана быть `waiting`, иначе визард отпустит пользователя с выключенным в игре
UDP и он решит, что сломано приложение.
"""
from __future__ import annotations

import json

import pytest

import config
import core.engine as eng_mod
from core import diagnostics
from core.telemetry_adapters import ConnectionChanged, SourceStatus


def _facts(**overrides):
    base = dict(
        source_code="ok", source_detail="", connected=True,
        last_packet_at=1_000.0, telemetry_source="f1",
        udp_ip="127.0.0.1", udp_port=20777,
        voice_engine="YandexSpeech", voice_available=True, yandex_healthy=True,
        llm_provider="gigachat", llm_connected=True,
        mic_devices=1, hotkeys_ready=True, now=1_000.5,
    )
    base.update(overrides)
    return base


def test_busy_port_is_reported_as_its_own_cause_not_as_no_connection():
    result = diagnostics.collect(**_facts(
        source_code="port_busy", source_detail="127.0.0.1:20777 — занято",
        connected=False, last_packet_at=0.0))

    assert result["telemetry"]["status"] == "port_busy"
    assert "20777" in result["telemetry"]["detail"]
    assert result["ready"] is False


def test_open_socket_without_fresh_packets_is_waiting_not_ok():
    """Сокет открыт, но игра не шлёт: UDP выключен в настройках F1 или игра не
    запущена. Отпустить визард здесь — значит отправить пользователя играть с
    молчащим приложением."""
    stale = diagnostics.collect(**_facts(
        last_packet_at=1_000.0, now=1_000.0 + diagnostics.PACKET_FRESH_S + 1))

    assert stale["telemetry"]["status"] == "waiting"
    assert stale["ready"] is False


def test_packets_within_the_window_keep_the_status_ok():
    fresh = diagnostics.collect(**_facts(
        last_packet_at=1_000.0, now=1_000.0 + diagnostics.PACKET_FRESH_S - 1))

    assert fresh["telemetry"]["status"] == "ok"
    assert fresh["ready"] is True


def test_missing_keys_are_a_working_free_mode_not_a_failure():
    """Без ключей продукт работает: шаблоны + офлайн-голос Piper. Написать тут
    `none`/`not ready` значило бы соврать пользователю, что всё сломано."""
    free = diagnostics.collect(**_facts(
        voice_engine="Piper", yandex_healthy=False, llm_connected=False))

    assert free["voice"]["status"] == "piper"
    assert free["brain"]["status"] == "templates"
    assert free["ready"] is True


def test_no_voice_at_all_is_the_only_voice_failure():
    dead = diagnostics.collect(**_facts(voice_available=False))

    assert dead["voice"]["status"] == "none"
    assert dead["ready"] is False


def test_optional_subsystems_never_block_readiness():
    """Микрофон и горячие клавиши делают продукт богаче, но держать из-за них
    пользователя в визарде нельзя."""
    result = diagnostics.collect(**_facts(mic_devices=0, hotkeys_ready=False))

    assert result["mic"]["status"] == "no_device"
    assert result["hotkeys"]["status"] == "unavailable"
    assert result["ready"] is True


def test_iracing_without_the_sdk_names_the_missing_library():
    result = diagnostics.collect(**_facts(
        source_code="iracing_no_lib", source_detail="pyirsdk не установлен",
        telemetry_source="iracing", connected=False, last_packet_at=0.0))

    assert result["telemetry"]["status"] == "iracing_no_lib"
    assert result["telemetry"]["source"] == "iracing"


# --- Проводка: движок и HTTP, а не только чистая функция ---------------------

@pytest.fixture(scope="module")
def engine():
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None      # без сети
    try:
        yield eng_mod.F1Engine({})
    finally:
        eng_mod.yc.load = orig


def test_engine_turns_a_source_fault_into_diagnostics(engine):
    engine._consume_telemetry_message(ConnectionChanged(True))
    engine._consume_telemetry_message(
        SourceStatus("port_busy", "127.0.0.1:20777 — занято"))

    assert engine.get_diagnostics()["telemetry"]["status"] == "port_busy"
    # Источник не открылся — «связь есть» обязано погаснуть, иначе UI покажет
    # унаследованное от прошлой сессии состояние.
    assert engine.get_state()["connected"] is False


def test_engine_recovers_the_status_once_the_port_frees_up(engine):
    engine._consume_telemetry_message(SourceStatus("port_busy", "занято"))
    engine._consume_telemetry_message(SourceStatus("ok"))
    engine._consume_telemetry_message(ConnectionChanged(True))

    assert engine.get_diagnostics()["telemetry"]["status"] == "ok"


def test_diagnostics_reports_the_real_udp_endpoint(engine):
    telemetry = engine.get_diagnostics()["telemetry"]

    assert telemetry["udp_ip"] == config.UDP_IP
    assert telemetry["udp_port"] == config.UDP_PORT


def test_http_exposes_diagnostics(engine, tmp_path):
    import web_server

    app = web_server.create_app(engine, {}, str(tmp_path))
    route = next(r for r in app.routes if r.rule == "/api/diagnostics")

    # Не только маршрут: проверяем, что обработчик реально доходит до движка и
    # отдаёт валидный JSON, а не объект (роуты сериализуют сами).
    payload = json.loads(route.call())
    assert payload["telemetry"]["udp_port"] == config.UDP_PORT
    assert set(payload) >= {"telemetry", "voice", "brain", "mic", "hotkeys", "ready"}
