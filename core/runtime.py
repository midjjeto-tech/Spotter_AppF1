"""Application lifecycle ownership for Spotter App.

Construction is passive. ``start()`` binds the mandatory local HTTP server,
then starts degradable engine resources and optional hotkeys. ``stop()`` is
idempotent and bounded; a stopped instance is intentionally not restartable.
"""
from __future__ import annotations

import logging
import threading
import time

import config
from core.engine import F1Engine
from core.hotkeys import GlobalHotkeyManager
from web_server import API_PORT, LocalWebServer, start_api_server

_log = logging.getLogger(__name__)


class AppRuntime:
    def __init__(self, settings: dict, *, base_dir: str | None = None,
                 port: int = API_PORT):
        self.settings = settings
        self.base_dir = base_dir or config.BASE_DIR
        self.port = port
        self.engine = F1Engine(settings)
        self._server: LocalWebServer | None = None
        self._hotkeys: GlobalHotkeyManager | None = None
        self._state = "created"
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def start(self, window=None, overlay_controller=None) -> None:
        with self._lock:
            if self._state == "running":
                return
            if self._state != "created":
                raise RuntimeError("stopped runtime cannot be restarted")
            self._state = "starting"

        try:
            # Mandatory resource: bind synchronously so startup can roll back.
            self._server = start_api_server(
                self.engine, self.settings, port=self.port,
                base_dir=self.base_dir)
            self.port = self._server.port

            # Engine internals are degradable and report their own status.
            self.engine.start()

            if window is not None:
                try:
                    if overlay_controller is None:
                        self._hotkeys = GlobalHotkeyManager(
                            self.engine, window, self.settings)
                    else:
                        self._hotkeys = GlobalHotkeyManager(
                            self.engine, window, self.settings,
                            overlay_controller=overlay_controller)
                    self._hotkeys.start()
                    # UI должен уметь показать, что комбинацию перехватила
                    # другая программа — иначе хоткей выглядит настроенным и
                    # молча не работает (см. core/hotkeys.py::_register).
                    self.engine.set_hotkey_status_provider(
                        self._hotkeys.registration_status)
                except Exception:  # noqa: BLE001
                    self._hotkeys = None
                    self.engine.set_hotkey_status_provider(None)
                    _log.exception("Global hotkeys unavailable; continuing")
        except Exception:
            self.stop()
            raise

        with self._lock:
            self._state = "running"

    def stop(self, timeout: float = 6.0) -> None:
        with self._lock:
            if self._state == "stopped":
                return
            self._state = "stopping"

        deadline = time.monotonic() + max(0.0, timeout)
        remaining = lambda: max(0.0, deadline - time.monotonic())

        hotkeys = self._hotkeys
        if hotkeys is not None:
            try:
                hotkeys.stop(timeout=min(1.0, remaining()))
            except Exception:  # noqa: BLE001
                _log.exception("Hotkey shutdown failed")

        # Stop accepting UI work before tearing down the engine it calls.
        server = self._server
        if server is not None:
            try:
                server.stop(timeout=min(2.0, remaining()))
            except Exception:  # noqa: BLE001
                _log.exception("HTTP shutdown failed")

        try:
            self.engine.stop(timeout=remaining())
        except Exception:  # noqa: BLE001
            _log.exception("Engine shutdown failed")

        with self._lock:
            self._state = "stopped"
