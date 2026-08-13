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


def _fake_widget_flags(monkeypatch, disabled=()):
    """Галочки «виджет нужен» из памяти, а не с диска разработчика."""
    flags = {widget_id: widget_id not in set(disabled) for widget_id in HUD_WIDGETS}
    stamps = {widget_id: 0.0 for widget_id in HUD_WIDGETS}
    monkeypatch.setattr(
        "core.overlay_process.overlay_layout.load_enabled",
        lambda widget_id: flags.get(widget_id, True))
    monkeypatch.setattr(
        "core.overlay_process.overlay_layout.revision",
        lambda widget_id: stamps.get(widget_id, 0.0))
    return flags, stamps


def _fake_launcher(monkeypatch):
    launched = []
    processes = []

    def launch(command, **kwargs):
        process = _Process()
        processes.append(process)
        launched.append((command, kwargs))
        return process

    monkeypatch.setattr("core.overlay_process.subprocess.Popen", launch)
    monkeypatch.setattr("core.overlay_process.socket.socket", lambda *_args: _Socket())
    return launched, processes


def _widget_of(command):
    return command[command.index("--overlay-widget") + 1]


def _port_of(command):
    return int(command[command.index("--overlay-port") + 1])


def test_overlay_process_uses_separate_python_process_and_authenticated_commands(monkeypatch):
    _Socket.sent = []
    _fake_widget_flags(monkeypatch)
    launched, processes = _fake_launcher(monkeypatch)

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


def _controller(**kwargs):
    return OverlayProcessController(
        entrypoint=r"G:\Spotter App\app.pyw",
        port=8766,
        token="secret",
        parent_pid=42,
        python_executable=r"C:\Python312\pythonw.exe",
        frozen=False,
        **kwargs,
    )


def test_switched_off_widget_costs_no_process_and_leaves_ports_alone(monkeypatch):
    """Смысл выключения — не занимать память на машине, которая тянет F1 25.

    И отдельно: порт обязан оставаться привязанным к МЕСТУ виджета в
    HUD_WIDGETS. Считай мы смещение по запущенным, пропуск одного сдвинул бы
    порты всех следующих, и Ctrl+Alt+O уходил бы не в те окна.
    """
    _Socket.sent = []
    order = list(HUD_WIDGETS)
    off, after = order[1], order[2]
    _fake_widget_flags(monkeypatch, disabled=[off])
    launched, _processes = _fake_launcher(monkeypatch)

    controller = _controller()
    controller._start_enabled()

    started = {_widget_of(command): _port_of(command) for command, _kwargs in launched}
    assert off not in started
    assert len(started) == len(HUD_WIDGETS) - 1
    assert started[after] == 8766 + order.index(after)


def test_switching_a_widget_off_closes_exactly_that_process(monkeypatch):
    """Галочка снимается во время гонки — перезапуск приложения не нужен."""
    _Socket.sent = []
    order = list(HUD_WIDGETS)
    victim = order[3]
    flags, stamps = _fake_widget_flags(monkeypatch)
    launched, processes = _fake_launcher(monkeypatch)

    controller = _controller()
    controller._start_enabled()
    started = len(launched)

    flags[victim] = False
    stamps[victim] = 1.0
    controller.sync_enabled()

    assert (b"secret:close", ("127.0.0.1", 8766 + order.index(victim))) in _Socket.sent
    assert sum(1 for _payload, _address in _Socket.sent) == 1  # соседей не трогали
    assert len(launched) == started  # и никого не поднимали заново


def test_switching_a_widget_back_on_starts_it_again(monkeypatch):
    _Socket.sent = []
    order = list(HUD_WIDGETS)
    victim = order[3]
    flags, stamps = _fake_widget_flags(monkeypatch, disabled=[victim])
    launched, _processes = _fake_launcher(monkeypatch)

    controller = _controller()
    controller._start_enabled()
    assert victim not in {_widget_of(command) for command, _kwargs in launched}

    flags[victim] = True
    stamps[victim] = 1.0
    controller.sync_enabled()

    revived = [command for command, _kwargs in launched if _widget_of(command) == victim]
    assert len(revived) == 1
    assert _port_of(revived[0]) == 8766 + order.index(victim)


def test_unchanged_flags_do_not_re_read_the_documents(monkeypatch):
    """Галочку трогают раз в сезон, а обход идёт каждые пару секунд."""
    _Socket.sent = []
    _fake_widget_flags(monkeypatch)
    _fake_launcher(monkeypatch)
    reads = []
    monkeypatch.setattr(
        "core.overlay_process.overlay_layout.load_enabled",
        lambda widget_id: reads.append(widget_id) or True)

    controller = _controller()
    controller.sync_enabled()  # первый обход запоминает отметки
    reads.clear()

    controller.sync_enabled()

    assert reads == []


def test_shutdown_stops_the_supervisor_from_reviving_widgets(monkeypatch):
    """Иначе супервизор поднимал бы окна ровно в момент закрытия приложения."""
    _Socket.sent = []
    _fake_widget_flags(monkeypatch)
    launched, _processes = _fake_launcher(monkeypatch)

    controller = _controller()
    controller._start_enabled()
    controller.close()
    launched.clear()

    controller.sync_enabled()

    assert launched == []


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
