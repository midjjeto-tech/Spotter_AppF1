import socket
import subprocess

from core.overlay_process import OverlayCommandServer, OverlayProcessController
from core.overlay_window import HUD_WIDGETS


class _Process:
    def __init__(self):
        self.waited = []
        self.terminated = False

    def poll(self):
        return None

    def wait(self, timeout):
        self.waited.append(timeout)
        return 0

    def terminate(self):
        self.terminated = True


class _Socket:
    sent = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def sendto(self, payload, address):
        self.sent.append((payload, address))


def test_overlay_process_uses_separate_python_process_and_authenticated_commands(monkeypatch):
    launched = []
    processes = []
    _Socket.sent = []

    def launch(command, **kwargs):
        process = _Process()
        processes.append(process)
        launched.append((command, kwargs))
        return process

    monkeypatch.setattr(
        "core.overlay_process.subprocess.Popen",
        launch,
    )
    monkeypatch.setattr("core.overlay_process.socket.socket", lambda *_args: _Socket())

    controller = OverlayProcessController(
        entrypoint=r"G:\Spotter App\app.pyw",
        port=8766,
        token="secret",
        parent_pid=42,
        python_executable=r"C:\Python312\pythonw.exe",
        frozen=False,
    )

    controller.start()
    controller.toggle_edit_mode()
    controller.close()

    # Derived from HUD_WIDGETS rather than hard-coded: the widget set is a
    # product decision that changes, the contract under test ("exactly one
    # process per widget, each on its own port") is not.
    assert len(launched) == len(HUD_WIDGETS)
    assert {
        command[command.index("--overlay-widget") + 1]
        for command, _kwargs in launched
    } == set(HUD_WIDGETS)
    assert {
        int(command[command.index("--overlay-port") + 1])
        for command, _kwargs in launched
    } == set(range(8766, 8766 + len(HUD_WIDGETS)))
    assert all(command[:2] == [
        r"C:\Python312\pythonw.exe",
        r"G:\Spotter App\app.pyw",
    ] for command, _kwargs in launched)
    for port in range(8766, 8772):
        assert (b"secret:toggle", ("127.0.0.1", port)) in _Socket.sent
        assert (b"secret:close", ("127.0.0.1", port)) in _Socket.sent
    assert all(process.waited == [2.0] for process in processes)


class _Overlay:
    def __init__(self):
        self.toggles = 0
        self.closed = 0

    def toggle_edit_mode(self):
        self.toggles += 1

    def close(self):
        self.closed += 1


def test_command_server_rejects_wrong_token_and_dispatches_valid_commands():
    overlay = _Overlay()
    server = OverlayCommandServer(overlay, port=8766, token="secret", parent_pid=42)

    assert server.handle_command(b"wrong:toggle") is False
    assert server.handle_command(b"secret:toggle") is True
    assert overlay.toggles == 1
    assert server.handle_command(b"secret:close") is True
    assert overlay.closed == 1


def test_bind_failure_keeps_hud_visible_instead_of_closing_it():
    # A zombie overlay from a previous run already owns the control port. The
    # new overlay's control server must NOT commit suicide (self.overlay.close)
    # when it cannot bind — otherwise every restart silently yields no HUD.
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("127.0.0.1", 0))
    held_port = blocker.getsockname()[1]
    try:
        overlay = _Overlay()
        server = OverlayCommandServer(
            overlay, port=held_port, token="secret", parent_pid=0)
        # _serve runs inline here (no thread) so the assertion is deterministic.
        server._serve()
        assert overlay.closed == 0
    finally:
        blocker.close()
