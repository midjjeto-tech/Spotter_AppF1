import core.screenshot as screenshot


class _Shot:
    def __init__(self, rgb, size):
        self.rgb = rgb
        self.size = size


def test_is_near_black_true_for_dark_and_false_for_bright():
    assert screenshot._is_near_black(b"\x00" * 300) is True
    assert screenshot._is_near_black(b"\xff" * 300) is False
    assert screenshot._is_near_black(b"") is True


def test_capture_to_writes_when_frame_is_bright(tmp_path):
    calls = {}
    def fake_write(rgb, size, path):
        calls["path"] = path
    ok = screenshot.capture_to(
        str(tmp_path / "x.png"), region=None,
        grab=lambda region: _Shot(b"\xff" * 300, (10, 10)),
        write=fake_write)
    assert ok is True
    assert calls["path"].endswith("x.png")


def test_capture_to_skips_black_frame(tmp_path):
    calls = {}
    ok = screenshot.capture_to(
        str(tmp_path / "x.png"), region=None,
        grab=lambda region: _Shot(b"\x00" * 300, (10, 10)),
        write=lambda *a: calls.setdefault("wrote", True))
    assert ok is False
    assert "wrote" not in calls


def test_capture_to_never_raises_on_grab_error(tmp_path):
    def boom(region):
        raise RuntimeError("no display")
    assert screenshot.capture_to(str(tmp_path / "x.png"), region=None,
                                 grab=boom, write=lambda *a: None) is False
