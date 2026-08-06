"""Lifecycle regression tests for passive construction and bounded shutdown."""
from __future__ import annotations

import threading
import time
import urllib.request
from unittest.mock import patch

import pytest


def test_voice_constructor_does_not_start_threads():
    from voice.tts import Voice

    with patch("threading.Thread") as thread_cls:
        voice = Voice()

    assert not thread_cls.called
    assert voice.status_message == "Голос не запущен"


def test_piper_constructor_does_not_start_threads():
    from new_tts.piper_tts import PiperVoiceEngine

    with patch("threading.Thread") as thread_cls:
        engine = PiperVoiceEngine()

    assert not thread_cls.called
    assert engine.status == "Piper не запущен"


def test_engine_constructor_does_not_start_threads(monkeypatch):
    import core.engine as engine_mod

    monkeypatch.setattr(engine_mod.yc, "load", lambda: None)
    with patch("threading.Thread") as thread_cls:
        engine = engine_mod.F1Engine({})

    assert not thread_cls.called
    assert engine.voice.status_message == "Голос не запущен"


def test_app_runtime_constructor_is_passive(monkeypatch):
    import core.engine as engine_mod
    from core.runtime import AppRuntime

    monkeypatch.setattr(engine_mod.yc, "load", lambda: None)
    with patch("threading.Thread") as thread_cls:
        runtime = AppRuntime({}, base_dir=".", port=0)

    assert not thread_cls.called
    assert runtime.state == "created"


def test_tts_queue_stop_reaps_idle_worker():
    from new_tts.queue_handler import TTSQueue

    queue = TTSQueue(lambda _text, _persona: None)
    queue.stop(timeout=1.0)

    assert not queue._thread.is_alive()


def test_piper_stop_is_bounded_when_loader_is_busy(monkeypatch):
    from new_tts.piper_tts import PiperVoiceEngine

    entered = threading.Event()
    release = threading.Event()
    engine = PiperVoiceEngine()

    def blocked_load():
        entered.set()
        release.wait(2.0)

    monkeypatch.setattr(engine, "_load", blocked_load)
    engine.start()
    assert entered.wait(1.0)

    started = time.monotonic()
    engine.stop(timeout=0.02)
    elapsed = time.monotonic() - started
    release.set()

    assert elapsed < 0.25
    assert engine.status == "Piper остановлен"


def test_engine_start_and_stop_own_workers(monkeypatch):
    import core.engine as engine_mod

    monkeypatch.setattr(engine_mod.yc, "load", lambda: None)
    engine = engine_mod.F1Engine({})
    starts: list[str] = []
    stops: list[str] = []

    monkeypatch.setattr(engine.voice, "start", lambda: starts.append("voice"))
    monkeypatch.setattr(engine.voice, "stop", lambda timeout=0: stops.append("voice"))
    monkeypatch.setattr(engine.metadata, "start", lambda: starts.append("metadata"))
    monkeypatch.setattr(engine.metadata, "stop", lambda timeout=0: stops.append("metadata"))
    monkeypatch.setattr(engine.commentator, "start", lambda: starts.append("commentator"))
    monkeypatch.setattr(engine.commentator, "stop", lambda timeout=0: stops.append("commentator"))

    def owned_worker():
        engine._stop_event.wait(2.0)

    monkeypatch.setattr(engine, "_telemetry_loop", owned_worker)
    monkeypatch.setattr(engine, "_commentary_loop", owned_worker)
    monkeypatch.setattr(engine, "_yandex_health_loop", owned_worker)
    monkeypatch.setattr(engine, "_ambient_loop", owned_worker)
    monkeypatch.setattr(engine, "_engineer_digest_loop", owned_worker)

    engine.start()
    assert starts == ["voice", "metadata", "commentator"]
    assert len(engine._worker_threads) == 5

    engine.stop(timeout=1.0)
    engine.stop(timeout=1.0)

    assert stops == ["voice", "commentator", "metadata"]
    assert all(not thread.is_alive() for thread in engine._worker_threads)


def test_local_web_server_binds_synchronously_and_stops():
    from bottle import Bottle
    from web_server import LocalWebServer

    app = Bottle()

    @app.route("/health")
    def health():
        return "ok"

    server = LocalWebServer(app, port=0)
    server.start()
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{server.port}/health", timeout=2.0) as response:
            assert response.read() == b"ok"
    finally:
        server.stop(timeout=1.0)

    assert server._thread is not None
    assert not server._thread.is_alive()


def test_local_web_server_reports_busy_port_before_thread_start():
    from bottle import Bottle
    from web_server import LocalWebServer

    first = LocalWebServer(Bottle(), port=0)
    first.start()
    second = LocalWebServer(Bottle(), port=first.port)
    try:
        with pytest.raises(OSError):
            second.start()
        assert second._thread is None
    finally:
        first.stop(timeout=1.0)


def test_app_runtime_orders_startup_and_shutdown(monkeypatch):
    import core.runtime as runtime_mod

    calls: list[str] = []

    class FakeEngine:
        def __init__(self, settings):
            calls.append("engine-created")
            self.hotkey_provider = "unset"

        def start(self):
            calls.append("engine-start")

        def stop(self, timeout=0):
            calls.append("engine-stop")

        def set_hotkey_status_provider(self, provider):
            calls.append("hotkeys-provider")
            self.hotkey_provider = provider

    class FakeServer:
        port = 8765

        def stop(self, timeout=0):
            calls.append("http-stop")

    class FakeHotkeys:
        def __init__(self, engine, window, settings):
            calls.append("hotkeys-created")

        def start(self):
            calls.append("hotkeys-start")

        def stop(self, timeout=0):
            calls.append("hotkeys-stop")

        def registration_status(self):
            return {"ready": True, "hotkeys": []}

    monkeypatch.setattr(runtime_mod, "F1Engine", FakeEngine)
    monkeypatch.setattr(
        runtime_mod, "start_api_server",
        lambda *args, **kwargs: calls.append("http-start") or FakeServer())
    monkeypatch.setattr(runtime_mod, "GlobalHotkeyManager", FakeHotkeys)

    runtime = runtime_mod.AppRuntime({}, base_dir=".")
    assert calls == ["engine-created"]
    assert runtime.state == "created"

    runtime.start(window=object())
    runtime.stop(timeout=1.0)
    runtime.stop(timeout=1.0)

    assert calls == [
        "engine-created", "http-start", "engine-start",
        "hotkeys-created", "hotkeys-start", "hotkeys-provider",
        "hotkeys-stop", "http-stop", "engine-stop",
    ]
    assert runtime.state == "stopped"
    # Провайдер статуса хоткеев проброшен в движок — без этого /api/hotkeys/status
    # всегда отвечал бы "available: false" и UI не мог бы показать занятую комбинацию.
    assert runtime.engine.hotkey_provider is not None
    assert runtime.engine.hotkey_provider() == {"ready": True, "hotkeys": []}


def test_app_runtime_rolls_back_mandatory_start_failure(monkeypatch):
    import core.runtime as runtime_mod

    stopped: list[float] = []

    class FakeEngine:
        def __init__(self, settings):
            pass

        def stop(self, timeout=0):
            stopped.append(timeout)

    monkeypatch.setattr(runtime_mod, "F1Engine", FakeEngine)
    monkeypatch.setattr(
        runtime_mod, "start_api_server",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("busy")))

    runtime = runtime_mod.AppRuntime({}, base_dir=".")
    with pytest.raises(OSError, match="busy"):
        runtime.start()

    assert runtime.state == "stopped"
    assert len(stopped) == 1
    with pytest.raises(RuntimeError, match="cannot be restarted"):
        runtime.start()
