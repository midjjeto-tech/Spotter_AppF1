import app


class _Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class _Window:
    def __init__(self, title):
        self.title = title
        self.events = type(
            "Events", (), {
                "closed": _Event(),
                "shown": _Event(),
                "loaded": _Event(),
            }
        )()

    def destroy(self):
        pass


def test_main_keeps_native_hud_out_of_primary_webview_process(monkeypatch):
    created = []
    starts = []
    stopped = []
    overlay_calls = []

    def create_window(title, url, **kwargs):
        window = _Window(title)
        created.append((title, url, kwargs, window))
        return window

    class FakeRuntime:
        def __init__(self, settings, *, port, base_dir):
            self.settings = settings

        def start(self, window, overlay_controller=None):
            starts.append((window, overlay_controller))

        def stop(self):
            stopped.append(True)

    class FakeOverlayProcess:
        def __init__(self, *, entrypoint, port):
            overlay_calls.append(("init", entrypoint, port))

        def start(self):
            overlay_calls.append(("start",))

        def close(self):
            overlay_calls.append(("close",))

    monkeypatch.setattr(app.webview, "create_window", create_window)
    monkeypatch.setattr(app.webview, "start", lambda debug=False: None)
    monkeypatch.setattr(app, "AppRuntime", FakeRuntime)
    monkeypatch.setattr(app, "OverlayProcessController", FakeOverlayProcess)
    monkeypatch.setattr(app._settings_store, "load", lambda: {})

    assert app.main() == 0

    # Exactly one webview window in this process — the native HUD controller
    # is never constructed here; only the IPC proxy for the isolated child.
    assert [entry[0] for entry in created] == ["Spotter App"]
    assert starts[0][0] is created[0][3]
    assert starts[0][1] is not None
    assert overlay_calls[0][0] == "init"
    assert "start" in [call[0] for call in overlay_calls]
    assert overlay_calls[-1] == ("close",)
    assert stopped == [True]


def test_overlay_creates_one_compact_widget_window(monkeypatch):
    created = []
    overlay_starts = []
    gui_start_callbacks = []

    def create_window(title, url, **kwargs):
        window = _Window(title)
        created.append((title, url, kwargs, window))
        return window

    class FakeOverlay:
        def __init__(self, window, *, spec, title):
            self.window = window
            self.spec = spec
            self.title = title

        def start(self):
            overlay_starts.append(True)

        def stop(self):
            pass

    class FakeControl:
        def __init__(self, overlay, **kwargs):
            self.overlay = overlay

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(app.webview, "create_window", create_window)
    def start_webview(func=None, debug=False):
        gui_start_callbacks.append(func)
        if func is not None:
            func()

    monkeypatch.setattr(app.webview, "start", start_webview)
    monkeypatch.setattr(app, "OverlayWindowController", FakeOverlay)
    monkeypatch.setattr(app, "OverlayCommandServer", FakeControl)

    assert app.overlay_main(
        port=8766,
        token="secret",
        parent_pid=42,
        widget="inputs",
    ) == 0

    kwargs = created[0][2]
    assert created[0][0] == "Spotter HUD · inputs"
    assert created[0][1].endswith("/overlay.html?widget=inputs")
    assert kwargs["width"] == 450
    assert kwargs["height"] == 120
    assert kwargs["easy_drag"] is True
    # Deliberately opaque: with transparent=True pywebview never assigns the
    # form's BackColor (it only does so on its opaque branch), leaving the
    # default light-grey `Color [Control]` visible as a grey block over the
    # game. WebView2 cannot composite alpha out to the desktop on this host
    # anyway, and each HUD is its own widget-sized window, so opacity is free.
    assert kwargs["transparent"] is False
    assert kwargs["background_color"] == app.OVERLAY_BACKGROUND
    assert kwargs.get("hidden", False) is False
    assert kwargs["width"] < 800
    assert kwargs["height"] < 400
    # pywebview's loaded event is not a reliable startup seam for a hidden,
    # off-screen WebView2 window. The controller must start from webview.start's
    # GUI hook so its native monitor always comes up.
    assert len(gui_start_callbacks) == 1
    assert gui_start_callbacks[0] is not None
    assert overlay_starts == [True]
