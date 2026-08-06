import sys
import types

from voice.listener import VoiceListener, list_input_devices, play_back


def test_record_returns_recorder_output():
    calls = []

    def fake_recorder(max_sec, sr):
        calls.append((max_sec, sr))
        return b"\x00\x01" * 100

    listener = VoiceListener(recorder=fake_recorder)
    audio = listener.record(5.0, sr=48000)
    assert audio == b"\x00\x01" * 100
    assert calls == [(5.0, 48000)]


def test_record_recorder_exception_returns_none():
    def boom(max_sec, sr):
        raise RuntimeError("no input device")

    listener = VoiceListener(recorder=boom)
    assert listener.record(5.0) is None


def test_record_recorder_none_result_returns_none():
    listener = VoiceListener(recorder=lambda max_sec, sr: None)
    assert listener.record(5.0) is None


def test_record_empty_bytes_returns_none():
    listener = VoiceListener(recorder=lambda max_sec, sr: b"")
    assert listener.record(5.0) is None


def test_record_default_sample_rate():
    calls = []
    listener = VoiceListener(recorder=lambda max_sec, sr: calls.append(sr) or b"x")
    listener.record(3.0)
    assert calls == [48000]


class _FakeInputStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, frames):
        import numpy as np
        return np.zeros(frames, dtype=np.int16), False


def test_default_recorder_uses_configured_device(monkeypatch):
    captured = []

    class TrackingInputStream(_FakeInputStream):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            captured.append(kwargs.get("device"))

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.InputStream = TrackingInputStream
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    listener = VoiceListener(device="USB Mic")
    listener.record(1.0, sr=16000)

    assert captured == ["USB Mic"]


def test_set_device_changes_device_used_on_next_record(monkeypatch):
    captured = []

    class TrackingInputStream(_FakeInputStream):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            captured.append(kwargs.get("device"))

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.InputStream = TrackingInputStream
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    listener = VoiceListener()
    listener.record(1.0)
    listener.set_device("Другой микрофон")
    listener.record(1.0)

    assert captured == [None, "Другой микрофон"]


def test_custom_recorder_still_takes_two_args_regardless_of_device():
    calls = []

    def fake_recorder(max_sec, sr):
        calls.append((max_sec, sr))
        return b"\x00\x01"

    listener = VoiceListener(recorder=fake_recorder, device="Some Device")
    audio = listener.record(2.0, sr=16000)

    assert calls == [(2.0, 16000)]
    assert audio == b"\x00\x01"


def test_list_input_devices_filters_and_marks_default(monkeypatch):
    fake_sd = types.ModuleType("sounddevice")
    fake_sd.query_devices = lambda: [
        {"name": "Speakers", "max_input_channels": 0},
        {"name": "USB Mic", "max_input_channels": 2},
        {"name": "Built-in Mic", "max_input_channels": 1},
    ]
    fake_sd.default = types.SimpleNamespace(device=(2, 0))
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    assert list_input_devices() == [
        {"name": "USB Mic", "index": 1, "is_default": False},
        {"name": "Built-in Mic", "index": 2, "is_default": True},
    ]


def test_list_input_devices_default_as_plain_int(monkeypatch):
    fake_sd = types.ModuleType("sounddevice")
    fake_sd.query_devices = lambda: [{"name": "Mic A", "max_input_channels": 1}]
    fake_sd.default = types.SimpleNamespace(device=0)
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    assert list_input_devices() == [{"name": "Mic A", "index": 0, "is_default": True}]


def test_list_input_devices_returns_empty_on_failure(monkeypatch):
    fake_sd = types.ModuleType("sounddevice")

    def _boom():
        raise RuntimeError("no portaudio")

    fake_sd.query_devices = _boom
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    assert list_input_devices() == []


def test_play_back_writes_audio_through_output_stream(monkeypatch):
    captured = {}

    class FakeOutputStream:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def write(self, data):
            captured["data"] = list(data)

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.OutputStream = FakeOutputStream
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    play_back(b"\x01\x00\x02\x00", sr=16000)

    assert captured["kwargs"]["samplerate"] == 16000
    assert captured["kwargs"]["channels"] == 1
    assert captured["data"] == [1, 2]
