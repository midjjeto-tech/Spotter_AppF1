"""Занятый UDP-порт не должен убивать приложение.

Порт 20777 занимают SimHub, Pits n' Giggles, Telemetry Tool, плагины к F1 и
вторая копия самого Spotter — то есть ровно то, что стоит у нашей аудитории.
До этих тестов bind() на занятом порту поднимал OSError прямо в потоке
телеметрии: поток умирал, traceback в оконном EXE уходил в никуда, а UI
навсегда показывал «нет связи» без причины.
"""
from __future__ import annotations

import logging
import socket
import threading

import pytest

import config
from core.telemetry import Telemetry, TelemetryUnavailable
from core.telemetry_adapters import (
    ConnectionChanged,
    F1TelemetryAdapter,
    SourceStatus,
)


class _Decoder:
    HEADER_SIZE = 1


class _OkTransport:
    """Транспорт, который открылся и сразу отдал один «нет пакетов» тик."""

    def __init__(self, *_args):
        self.closed = False

    def listen(self):
        yield None, False

    def close(self):
        self.closed = True


def test_busy_port_raises_a_named_reason_not_a_bare_oserror():
    squatter = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    squatter.bind((config.UDP_IP, config.UDP_PORT))
    try:
        with pytest.raises(TelemetryUnavailable) as excinfo:
            Telemetry(config.UDP_IP, config.UDP_PORT)
    finally:
        squatter.close()

    assert excinfo.value.code == "port_busy"
    # Деталь обязана называть адрес: без неё пользователь не поймёт, какой
    # именно порт освобождать.
    assert str(config.UDP_PORT) in excinfo.value.detail


def test_failed_bind_does_not_leak_the_socket():
    """Ретрай раз в 5 секунд превратил бы утечку дескриптора в утечку без дна."""
    squatter = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    squatter.bind((config.UDP_IP, config.UDP_PORT))
    leaked = []
    real_socket = socket.socket

    def tracking_socket(*args, **kwargs):
        sock = real_socket(*args, **kwargs)
        leaked.append(sock)
        return sock

    socket.socket = tracking_socket
    try:
        with pytest.raises(TelemetryUnavailable):
            Telemetry(config.UDP_IP, config.UDP_PORT)
    finally:
        socket.socket = real_socket
        squatter.close()

    assert leaked, "тест не поймал создание сокета — проверять нечего"
    assert all(sock.fileno() == -1 for sock in leaked), (
        "сокет неудачного bind остался открытым")


def test_adapter_reports_busy_port_instead_of_dying():
    adapter = F1TelemetryAdapter(
        "127.0.0.1", 20777,
        transport_factory=_always_busy,
        decoder=_Decoder,
        retry_interval=0.0,
    )
    stop = threading.Event()
    messages = []
    for message in adapter.listen(stop):
        messages.append(message)
        if len(messages) == 3:
            stop.set()

    assert messages == [SourceStatus("port_busy", "занято")] * 3


def _always_busy(*_args):
    raise TelemetryUnavailable("port_busy", "занято")


def test_adapter_picks_the_port_up_once_it_is_freed():
    """Пользователь закрывает SimHub уже после старта Spotter — приложение
    обязано подхватить источник само, без перезапуска."""
    attempts = {"n": 0}

    def flaky_factory(*_args):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise TelemetryUnavailable("port_busy", "занято")
        return _OkTransport()

    adapter = F1TelemetryAdapter(
        "127.0.0.1", 20777,
        transport_factory=flaky_factory,
        decoder=_Decoder,
        retry_interval=0.0,
    )

    messages = list(adapter.listen(threading.Event()))

    assert messages == [
        SourceStatus("port_busy", "занято"),
        SourceStatus("port_busy", "занято"),
        SourceStatus("ok"),
        ConnectionChanged(False),
    ]


def test_stop_event_ends_the_retry_loop_without_a_successful_bind():
    stop = threading.Event()
    stop.set()

    adapter = F1TelemetryAdapter(
        "127.0.0.1", 20777,
        transport_factory=_always_busy,
        decoder=_Decoder,
        retry_interval=0.0,
    )

    assert list(adapter.listen(stop)) == []


def test_a_dying_worker_thread_is_logged_not_swallowed(caplog):
    """`threading` печатает traceback в stderr, которого у оконного EXE нет."""
    from core.engine import F1Engine

    def boom():
        raise RuntimeError("воркер упал")

    runner = F1Engine._guarded(boom, "telemetry")
    with caplog.at_level(logging.ERROR, logger="core.engine"):
        with pytest.raises(RuntimeError):
            runner()

    assert any("telemetry" in record.message for record in caplog.records)
    assert any(record.exc_info for record in caplog.records)
