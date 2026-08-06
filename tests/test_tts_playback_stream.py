"""tests/test_tts_playback_stream.py

Regression test for the SpotterApp.exe native crash (Windows Event Log:
Exception code 0xc0000005 / ACCESS_VIOLATION in ntdll.dll, same fault offset,
3 occurrences). Root cause: voice/tts.py::_play_wav used the module-level
sd.play()/sd.wait() globals, and _interrupt_playback (called from another
thread on a critical-priority event) called the module-level sd.stop() —
both operate on sounddevice's shared global stream pointer, racing when one
thread is starting a new stream while another is stopping it.

Fix: _play_wav now owns a dedicated sd.OutputStream per call, published to
self._current_stream under a lock; _interrupt_playback aborts that specific
instance instead of the ambiguous module global. These tests verify the
threading contract with a fake sounddevice module (no real audio device
needed) — same dependency-injection style as voice/listener.py's
VoiceListener(recorder=...).
"""
import os
import sys
import threading
import types

import numpy as np
import pytest
import soundfile as sf


class FakeOutputStream:
    """Records calls; write() can block until released, to simulate real
    blocking playback and let a test interrupt it from another thread."""

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.closed = False
        self.aborted = False
        self.written = []
        self.entered_write = threading.Event()
        self._release = threading.Event()
        self.block_on_write = False

    def start(self):
        self.started = True

    def write(self, data):
        self.written.append(data)
        self.entered_write.set()
        if self.block_on_write:
            self._release.wait(timeout=2.0)

    def stop(self):
        self.stopped = True

    def abort(self):
        self.aborted = True
        self._release.set()   # unblock any pending write()

    def close(self):
        self.closed = True


def _make_voice(cache_dir=None):
    """Instantiate Voice with all I/O patched out (same pattern as test_volume.py)."""
    from unittest.mock import patch
    from voice.cache import TTSCache
    from voice.tts import Voice
    with (
        patch("voice.tts.TTSQueue"),
        patch("voice.tts.PiperVoiceEngine"),
        patch("voice.tts.TTSCache"),
        patch("threading.Thread"),
    ):
        v = Voice.__new__(Voice)
        v._stream_lock = threading.Lock()
        v._current_stream = None
        v._radio_enabled = False
        v._global_vol = 100
        v._persona_vol = {}
        v._current_persona = "tv"
        v._yandex = None
        v._yandex_healthy = True
        v._voice_overrides = {}
        v._health_reporter = None
        v._last_engine = ""
        v._last_fallback = False
        v.status_message = ""
        v._engine = types.SimpleNamespace(sample_rate=22050,
                                          synthesize_streaming=lambda text, persona: iter(()))
        v._cache = TTSCache(str(cache_dir), version="test") if cache_dir else None
        return v


@pytest.fixture()
def fake_sd(monkeypatch):
    module = types.ModuleType("sounddevice")
    module.OutputStream = FakeOutputStream
    monkeypatch.setitem(sys.modules, "sounddevice", module)
    return module


@pytest.fixture()
def wav_path(tmp_path):
    path = tmp_path / "phrase.wav"
    data = np.zeros(400, dtype=np.float32)
    sf.write(str(path), data, 8000, format="WAV", subtype="PCM_16")
    return str(path)


def test_play_wav_starts_writes_stops_and_clears_current_stream(fake_sd, wav_path):
    v = _make_voice()
    v._play_wav(wav_path)

    assert v._current_stream is None


def test_play_wav_uses_a_single_dedicated_stream_instance(fake_sd, wav_path, monkeypatch):
    created = []
    orig_init = FakeOutputStream.__init__

    def tracking_init(self, *a, **kw):
        orig_init(self, *a, **kw)
        created.append(self)

    monkeypatch.setattr(FakeOutputStream, "__init__", tracking_init)

    v = _make_voice()
    v._play_wav(wav_path)

    assert len(created) == 1
    stream = created[0]
    assert stream.started is True
    assert stream.stopped is True
    assert stream.closed is True
    assert stream.aborted is False
    assert len(stream.written) == 1


def test_interrupt_playback_aborts_the_currently_active_stream(fake_sd, wav_path):
    v = _make_voice()
    result = {}

    def player():
        v._play_wav(wav_path)
        result["done"] = True

    # Make the fake stream block inside write() so we can interrupt mid-flight.
    orig_init = FakeOutputStream.__init__

    def blocking_init(self, *a, **kw):
        orig_init(self, *a, **kw)
        self.block_on_write = True

    FakeOutputStream.__init__ = blocking_init
    try:
        t = threading.Thread(target=player, daemon=True)
        t.start()

        active_stream = None
        deadline = threading.Event()
        # Wait until _play_wav has published its stream and entered write().
        import time
        t0 = time.monotonic()
        while time.monotonic() - t0 < 2.0:
            with v._stream_lock:
                active_stream = v._current_stream
            if active_stream is not None and active_stream.entered_write.is_set():
                break
            time.sleep(0.01)
        assert active_stream is not None
        assert active_stream.entered_write.is_set()

        v._interrupt_playback()

        t.join(timeout=2.0)
        assert result.get("done") is True
        assert active_stream.aborted is True
        assert v._current_stream is None
    finally:
        FakeOutputStream.__init__ = orig_init


def test_interrupt_playback_without_active_stream_is_noop(fake_sd):
    v = _make_voice()
    v._interrupt_playback()   # must not raise
    assert v._current_stream is None


def test_play_wav_close_and_interrupt_playback_are_mutually_exclusive(fake_sd, wav_path):
    """Regression test for the ucrtbase.dll access violation (Windows Event
    Log Id 1000: same faulting module/version/offset 0x00000000000ee44d on
    both 2026-07-09 and 2026-07-13). Root cause: _play_wav's finally called
    stream.close() OUTSIDE self._stream_lock, and _interrupt_playback called
    stream.abort() OUTSIDE the lock too — the natural end-of-playback thread
    (TTSQueue._worker) and a concurrent critical-priority interrupt (called
    synchronously from whatever thread calls voice.say(priority="critical"),
    e.g. core.engine._commentary_loop) could both call native methods on the
    SAME sd.OutputStream with no mutual exclusion. Fix: both calls now happen
    while holding self._stream_lock — this test proves they can never overlap,
    and that a late interrupt (arriving after close() already ran) safely
    no-ops instead of touching the now-closed stream."""
    v = _make_voice()
    created: list[FakeOutputStream] = []
    orig_init = FakeOutputStream.__init__

    def tracking_init(self, *a, **kw):
        orig_init(self, *a, **kw)
        created.append(self)

    entered_close = threading.Event()
    release_close = threading.Event()
    orig_close = FakeOutputStream.close

    def blocking_close(self):
        entered_close.set()
        release_close.wait(timeout=2.0)
        orig_close(self)

    FakeOutputStream.__init__ = tracking_init
    FakeOutputStream.close = blocking_close
    try:
        player = threading.Thread(target=lambda: v._play_wav(wav_path), daemon=True)
        player.start()
        assert entered_close.wait(timeout=2.0)   # now blocked inside close(), lock held

        # While close() holds self._stream_lock, _interrupt_playback() must be
        # BLOCKED acquiring the same lock — not free to call .abort() on the
        # same stream concurrently.
        interrupt_done = threading.Event()

        def do_interrupt():
            v._interrupt_playback()
            interrupt_done.set()

        interrupter = threading.Thread(target=do_interrupt, daemon=True)
        interrupter.start()
        assert not interrupt_done.wait(timeout=0.2)   # still blocked on the lock

        release_close.set()
        player.join(timeout=2.0)
        assert interrupt_done.wait(timeout=2.0)

        # By the time _interrupt_playback acquired the lock, _current_stream
        # was already cleared (set to None before close() runs, same critical
        # section) — it must see "nothing to abort", not call .abort() on the
        # already-closed instance.
        assert v._current_stream is None
        assert len(created) == 1
        assert created[0].closed is True
        assert created[0].aborted is False
    finally:
        FakeOutputStream.__init__ = orig_init
        FakeOutputStream.close = orig_close


def test_play_beep_interrupts_current_playback_first(fake_sd):
    v = _make_voice()
    calls = []
    v._interrupt_playback = lambda: calls.append("interrupt")
    orig_init = FakeOutputStream.__init__

    def tracking_init(self, *a, **kw):
        orig_init(self, *a, **kw)
        calls.append("stream_created")

    FakeOutputStream.__init__ = tracking_init
    try:
        v.play_beep()
    finally:
        FakeOutputStream.__init__ = orig_init

    assert calls == ["interrupt", "stream_created"]


def test_play_beep_creates_single_stream_and_cleans_up(fake_sd):
    v = _make_voice()
    created = []
    orig_init = FakeOutputStream.__init__

    def tracking_init(self, *a, **kw):
        orig_init(self, *a, **kw)
        created.append(self)

    FakeOutputStream.__init__ = tracking_init
    try:
        v.play_beep()
    finally:
        FakeOutputStream.__init__ = orig_init

    assert len(created) == 1
    assert created[0].started is True
    assert created[0].stopped is True
    assert created[0].closed is True
    assert created[0].aborted is False
    assert len(created[0].written) == 1
    assert v._current_stream is None


def test_play_beep_close_and_interrupt_playback_are_mutually_exclusive(fake_sd):
    """Same regression proof as test_play_wav_close_and_interrupt_playback_are_mutually_exclusive
    (see its docstring for the ucrtbase.dll access violation history), but for play_beep()'s own
    stream teardown — play_beep() publishes and closes a SEPARATE sd.OutputStream from _play_wav's,
    so its close()/abort() mutual exclusion needs its own proof, not just _play_wav's."""
    v = _make_voice()
    created: list[FakeOutputStream] = []
    orig_init = FakeOutputStream.__init__

    def tracking_init(self, *a, **kw):
        orig_init(self, *a, **kw)
        created.append(self)

    entered_close = threading.Event()
    release_close = threading.Event()
    orig_close = FakeOutputStream.close

    def blocking_close(self):
        entered_close.set()
        release_close.wait(timeout=2.0)
        orig_close(self)

    FakeOutputStream.__init__ = tracking_init
    FakeOutputStream.close = blocking_close
    try:
        beeper = threading.Thread(target=v.play_beep, daemon=True)
        beeper.start()
        assert entered_close.wait(timeout=2.0)   # now blocked inside close(), lock held

        interrupt_done = threading.Event()

        def do_interrupt():
            v._interrupt_playback()
            interrupt_done.set()

        interrupter = threading.Thread(target=do_interrupt, daemon=True)
        interrupter.start()
        assert not interrupt_done.wait(timeout=0.2)   # still blocked on the lock

        release_close.set()
        beeper.join(timeout=2.0)
        assert interrupt_done.wait(timeout=2.0)

        assert v._current_stream is None
        assert len(created) == 1
        assert created[0].closed is True
        assert created[0].aborted is False
    finally:
        FakeOutputStream.__init__ = orig_init
        FakeOutputStream.close = orig_close


# ---------------------------------------------------------------------------
# Этап B — _play_streaming: Yandex v3-grpc chunk-by-chunk playback
# ---------------------------------------------------------------------------

class _FakeYandexStreamOK:
    tts_version = "v3-grpc"

    def synthesize_streaming(self, text, persona, speed_scale=1.0):
        yield np.array([0.1, 0.2], dtype=np.float32), 22050
        yield np.array([0.3, 0.4], dtype=np.float32), 22050


class _FakeYandexStreamFailsImmediately:
    tts_version = "v3-grpc"

    def synthesize_streaming(self, text, persona, speed_scale=1.0):
        if False:            # noqa: SIM108 — forces generator-function semantics:
            yield             # the real YandexSpeech.synthesize_streaming also only
        raise RuntimeError("grpc down")   # raises on first next(), not on call.


class _FakeYandexStreamFailsAfterOneChunk:
    tts_version = "v3-grpc"

    def synthesize_streaming(self, text, persona, speed_scale=1.0):
        yield np.array([0.5, 0.5], dtype=np.float32), 22050
        raise RuntimeError("stream broke")


class _FakeYandexStreamEmpty:
    """Completes cleanly with zero chunks — no exception at all (e.g. a
    genuinely empty synthesis result)."""
    tts_version = "v3-grpc"

    def synthesize_streaming(self, text, persona, speed_scale=1.0):
        return iter(())


def test_play_streaming_yandex_writes_chunks_and_publishes_current_stream(fake_sd, tmp_path):
    v = _make_voice(cache_dir=tmp_path)
    v._yandex = _FakeYandexStreamOK()

    ok = v._play_streaming("привет", "tv")

    assert ok is True
    assert v._current_stream is None          # cleared after playback
    assert v._last_engine == "Yandex SpeechKit"
    # dry audio saved under the key _play_streaming derives from the ACTUALLY
    # used engine (use_yandex), not a path handed in by the caller.
    expected_path = v._cache.path_for("привет", v._voice_key("tv"))
    assert os.path.exists(expected_path)


def test_play_streaming_yandex_registers_current_stream_during_playback(fake_sd, tmp_path):
    """The pre-Stage-B _play_streaming never published its stream to
    self._current_stream, so a critical-priority interrupt during streaming
    playback would silently fail to abort it (unlike _play_wav). Verify the
    fix: the stream instance is reachable through _current_stream while
    write() is in flight."""
    v = _make_voice(cache_dir=tmp_path)
    v._yandex = _FakeYandexStreamOK()

    captured = []
    orig_write = FakeOutputStream.write

    def probing_write(self, data):
        with v._stream_lock:
            captured.append(v._current_stream is self)
        return orig_write(self, data)

    FakeOutputStream.write = probing_write
    try:
        v._play_streaming("привет", "tv")
    finally:
        FakeOutputStream.write = orig_write

    assert captured and all(captured)


def test_play_streaming_falls_back_when_stream_fails_before_any_chunk(fake_sd, tmp_path):
    v = _make_voice(cache_dir=tmp_path)
    v._yandex = _FakeYandexStreamFailsImmediately()
    reported = []
    v._health_reporter = lambda ok: reported.append(ok)

    ok = v._play_streaming("привет", "tv")

    assert ok is False                # caller (_play_blocking) must fall back
    assert v._current_stream is None
    assert reported == [False]
    expected_path = v._cache.path_for("привет", v._voice_key("tv"))
    assert not os.path.exists(expected_path)


def test_play_streaming_falls_back_on_clean_empty_stream_no_exception(fake_sd, tmp_path):
    """Regression test: a chunk source that completes with ZERO chunks and no
    exception must be treated as a failure requiring fallback, not a silent
    success — otherwise the phrase is dropped entirely with no buffered/Piper
    retry (the buffered v3-grpc path already treats 0 chunks as None -> retry)."""
    v = _make_voice(cache_dir=tmp_path)
    v._yandex = _FakeYandexStreamEmpty()
    reported = []
    v._health_reporter = lambda ok: reported.append(ok)

    ok = v._play_streaming("привет", "tv")

    assert ok is False                # caller (_play_blocking) must fall back
    assert v._current_stream is None
    assert reported == [False]
    expected_path = v._cache.path_for("привет", v._voice_key("tv"))
    assert not os.path.exists(expected_path)


def test_play_streaming_stops_without_fallback_after_partial_failure(fake_sd, tmp_path):
    v = _make_voice(cache_dir=tmp_path)
    v._yandex = _FakeYandexStreamFailsAfterOneChunk()
    reported = []
    v._health_reporter = lambda ok: reported.append(ok)

    ok = v._play_streaming("привет", "tv")

    assert ok is True                 # handled — no replay (would double-speak)
    assert v._current_stream is None
    # A partial failure is still unhealthy for the health-monitor's purposes
    # (a degraded connection that always breaks after chunk 1 must eventually
    # fail over to Piper) — reporting True here would mask that forever.
    assert reported == [False]
    # The truncated recording must NEVER be written to cache — the cache file
    # has no TTL, so a cut-off phrase cached here would play cut-off forever.
    expected_path = v._cache.path_for("привет", v._voice_key("tv"))
    assert not os.path.exists(expected_path)
    assert v._last_engine == "Yandex SpeechKit"   # still reported for UI purposes


def test_play_streaming_toctou_fallback_to_piper_never_writes_yandex_key(fake_sd, tmp_path):
    """Regression test for the cache-poisoning race (health-monitor flips
    _yandex_healthy False between _play_blocking's eligibility check and
    _play_streaming's own re-check): when _play_streaming itself decides to
    use Piper, the saved dry audio must land under the Piper key, never under
    the Yandex vkey — even though the caller may have been eligible for
    Yandex when it decided to call _play_streaming at all."""
    v = _make_voice(cache_dir=tmp_path)
    v._yandex = _FakeYandexStreamOK()
    v._yandex_healthy = False   # flips false by the time _play_streaming re-checks
    v._engine.synthesize_streaming = lambda text, persona: iter(
        [(np.array([0.1, 0.2], dtype=np.float32), 22050)])

    ok = v._play_streaming("привет", "tv")

    assert ok is True
    assert v._last_engine == "Piper (RU)"
    yandex_path = v._cache.path_for("привет", v._voice_key("tv"))
    piper_path = v._cache.path_for("привет", "piper:tv")
    assert not os.path.exists(yandex_path)
    assert os.path.exists(piper_path)


def test_play_streaming_handles_output_stream_constructor_failure(fake_sd, tmp_path, monkeypatch):
    """Regression test: sd.OutputStream(...) constructor must be inside the
    try block. If a PortAudioError-like exception raised from the constructor
    itself (removed/busy output device) escaped this method, it would propagate
    past _play_blocking (uncaught there) into TTSQueue._worker's blanket
    except-pass — dropping the phrase with no fallback and no status message."""
    def raising_init(self, *a, **kw):
        raise RuntimeError("PortAudioError: device unavailable")

    monkeypatch.setattr(FakeOutputStream, "__init__", raising_init)

    v = _make_voice(cache_dir=tmp_path)
    v._yandex = _FakeYandexStreamOK()

    ok = v._play_streaming("привет", "tv")   # must not raise

    assert ok is False                # caller (_play_blocking) can fall back
    assert v._current_stream is None
    expected_path = v._cache.path_for("привет", v._voice_key("tv"))
    assert not os.path.exists(expected_path)


def test_play_blocking_uses_streaming_path_for_yandex_v3_grpc(fake_sd, tmp_path):
    v = _make_voice(cache_dir=tmp_path)
    v._yandex = _FakeYandexStreamOK()
    v._yandex_healthy = True

    v._play_blocking("привет")

    assert v._last_engine == "Yandex SpeechKit"
    assert v._current_stream is None


def test_play_blocking_falls_back_to_buffered_path_on_streaming_failure(fake_sd, tmp_path, monkeypatch):
    v = _make_voice(cache_dir=tmp_path)
    v._yandex = _FakeYandexStreamFailsImmediately()
    v._yandex_healthy = True
    # _synthesize() would normally hit real Yandex/Piper — stub the buffered
    # fallback path so this test isolates the dispatch decision, not synthesis.
    monkeypatch.setattr(v, "_synthesize",
                        lambda text, persona, speed_scale=1.0: (np.zeros(10, dtype=np.float32), 22050))
    monkeypatch.setattr(v, "_play_wav", lambda path, persona=None: None)

    v._play_blocking("привет")   # must not raise, must fall through to buffered path

    assert v._last_engine != "Yandex SpeechKit"


# ---------------------------------------------------------------------------
# Per-utterance persona override (engineer voice split, spec 2026-07-09)
# ---------------------------------------------------------------------------

def test_play_blocking_uses_explicit_persona_for_cache_key(fake_sd, tmp_path):
    """_play_blocking(persona='calm') должен кэшировать под ключом calm,
    даже когда _current_persona = 'tv'."""
    v = _make_voice(cache_dir=tmp_path)
    v._current_persona = "tv"
    v._yandex = None                    # путь Piper: ключ piper:<persona>
    v._engine = types.SimpleNamespace(
        is_ready=True,
        sample_rate=22050,
        synthesize=lambda text, persona: (np.zeros(64, dtype=np.float32), 22050),
    )
    v._play_blocking("привет", persona="calm")
    assert os.path.exists(v._cache.path_for("привет", "piper:calm"))
    assert not os.path.exists(v._cache.path_for("привет", "piper:tv"))


def test_play_blocking_without_persona_uses_current(fake_sd, tmp_path):
    v = _make_voice(cache_dir=tmp_path)
    v._current_persona = "tv"
    v._yandex = None
    v._engine = types.SimpleNamespace(
        is_ready=True,
        sample_rate=22050,
        synthesize=lambda text, persona: (np.zeros(64, dtype=np.float32), 22050),
    )
    v._play_blocking("привет")
    assert os.path.exists(v._cache.path_for("привет", "piper:tv"))


def test_effective_volume_uses_explicit_persona(fake_sd):
    v = _make_voice()
    v._global_vol = 100
    v._persona_vol = {"calm": 40, "tv": 80}
    v._current_persona = "tv"
    assert v._effective_volume("calm") == 0.4
    assert v._effective_volume() == 0.8          # без аргумента — текущая
