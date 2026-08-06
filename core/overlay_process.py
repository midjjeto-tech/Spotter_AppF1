"""Process isolation and localhost control channel for the in-game HUD."""
from __future__ import annotations

import hmac
import logging
import os
import secrets
import socket
import subprocess
import sys
import threading

from core.overlay_window import HUD_WIDGETS

_log = logging.getLogger(__name__)
_HOST = "127.0.0.1"


class OverlayProcessController:
    """Own one isolated single-window subprocess per HUD widget.

    The interface remains start/toggle/close, while the implementation hides
    six independent WebView2 hosts. No process ever owns more than one native
    HUD window and no HUD window is game-sized.
    """

    def __init__(
        self,
        *,
        entrypoint: str,
        port: int,
        token: str | None = None,
        parent_pid: int | None = None,
        python_executable: str | None = None,
        frozen: bool | None = None,
    ) -> None:
        self.entrypoint = os.path.abspath(entrypoint)
        self.port = int(port)
        self.token = token or secrets.token_hex(16)
        self.parent_pid = int(parent_pid or os.getpid())
        self.python_executable = python_executable or sys.executable
        self.frozen = bool(getattr(sys, "frozen", False) if frozen is None else frozen)
        self._processes: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            for offset, widget_id in enumerate(HUD_WIDGETS):
                existing = self._processes.get(widget_id)
                if existing is not None and existing.poll() is None:
                    continue
                command = [self.python_executable]
                if not self.frozen:
                    command.append(self.entrypoint)
                command.extend([
                    "--overlay",
                    "--overlay-widget",
                    widget_id,
                    "--overlay-port",
                    str(self.port + offset),
                    "--overlay-token",
                    self.token,
                    "--parent-pid",
                    str(self.parent_pid),
                ])
                kwargs = {
                    "cwd": os.path.dirname(self.entrypoint),
                    "stdin": subprocess.DEVNULL,
                    "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL,
                }
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if creationflags:
                    kwargs["creationflags"] = creationflags
                try:
                    self._processes[widget_id] = subprocess.Popen(command, **kwargs)
                except OSError:
                    self._processes.pop(widget_id, None)
                    _log.exception(
                        "Unable to start isolated overlay widget: %s", widget_id
                    )

    def toggle_edit_mode(self) -> None:
        for offset, _widget_id in enumerate(HUD_WIDGETS):
            self._send_to(self.port + offset, "toggle")

    def close(self) -> None:
        with self._lock:
            processes = self._processes
            self._processes = {}
        for offset, widget_id in enumerate(HUD_WIDGETS):
            if widget_id in processes:
                self._send_to(self.port + offset, "close")
        for widget_id, process in processes.items():
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    _log.warning(
                        "Overlay widget did not exit after terminate: %s", widget_id
                    )

    def _send_to(self, port: int, command: str) -> None:
        payload = f"{self.token}:{command}".encode("ascii")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as channel:
                channel.sendto(payload, (_HOST, int(port)))
        except OSError:
            _log.debug(
                "Overlay command was not delivered: %s (port %s)", command, port
            )


class OverlayCommandServer:
    """Authenticated UDP command receiver that lives in the overlay process."""

    def __init__(self, overlay, *, port: int, token: str,
                 parent_pid: int | None = None) -> None:
        self.overlay = overlay
        self.port = int(port)
        self.token = token
        self.parent_pid = int(parent_pid or 0)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._serve,
            daemon=True,
            name="overlay-control",
        )
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        self._stop_event.set()
        channel = self._socket
        if channel is not None:
            try:
                channel.close()
            except OSError:
                pass
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))

    def handle_command(self, payload: bytes) -> bool:
        try:
            supplied_token, command = payload.decode("ascii").split(":", 1)
        except (UnicodeDecodeError, ValueError):
            return False
        if not hmac.compare_digest(supplied_token, self.token):
            return False
        if command == "toggle":
            self.overlay.toggle_edit_mode()
            return True
        if command == "close":
            self._stop_event.set()
            self.overlay.close()
            return True
        return False

    def _serve(self) -> None:
        try:
            channel = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        except OSError:
            _log.exception("Overlay control socket could not be created")
            return

        try:
            channel.bind((_HOST, self.port))
        except OSError:
            # A leftover overlay process from a previous run (e.g. one whose
            # WebView2 host wedged and never exited) can still own this port.
            # Losing the control channel only disables the Ctrl+Alt+O edit
            # toggle — it must NOT tear down the visible HUD, otherwise every
            # app restart silently produces no overlay at all until that zombie
            # process is killed by hand.
            _log.exception(
                "Overlay control channel bind failed (port already in use?); "
                "HUD stays visible but the edit-mode toggle is disabled")
            channel.close()
            return

        self._socket = channel
        try:
            channel.settimeout(0.5)
            while not self._stop_event.is_set():
                if self.parent_pid and not _process_exists(self.parent_pid):
                    self.overlay.close()
                    break
                try:
                    payload, _address = channel.recvfrom(512)
                except TimeoutError:
                    continue
                except OSError:
                    if self._stop_event.is_set():
                        break
                    raise
                self.handle_command(payload)
        except OSError:
            _log.exception("Overlay control channel failed")
            self.overlay.close()
        finally:
            try:
                channel.close()
            except OSError:
                pass
            self._socket = None


def _process_exists(pid: int) -> bool:
    try:
        import psutil

        return psutil.pid_exists(pid)
    except Exception:  # noqa: BLE001 - parent check is a cleanup safety net
        return True
