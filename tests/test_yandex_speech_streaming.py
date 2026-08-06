"""tests/test_yandex_speech_streaming.py — YandexSpeech.synthesize_streaming
(Этап B: gRPC chunk-by-chunk bridge from YandexClient's event-loop thread to
a plain sync generator consumed by the caller thread).

Uses a REAL YandexClient (start()/stop()) so the async producer task actually
runs on a background loop, exactly like production — only the gRPC stub is
faked (no network)."""
import numpy as np
import pytest

import config
from yandex_ai.client import YandexClient
from yandex_ai.credentials import Credentials
from yandex_ai.speech import YandexSpeech


class _FakeAudioChunk:
    def __init__(self, data: bytes):
        self.data = data


class _FakeUtteranceResponse:
    def __init__(self, data: bytes):
        self.audio_chunk = _FakeAudioChunk(data)


class _FakeGrpcCall:
    def __init__(self, responses):
        self._responses = responses

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for r in self._responses:
            yield r


class _FakeSynthesizerStub:
    def __init__(self, responses=None, exc=None):
        self._responses = responses or []
        self._exc = exc

    def UtteranceSynthesis(self, request, metadata=None, timeout=None):
        if self._exc is not None:
            raise self._exc
        return _FakeGrpcCall(self._responses)


class _FailingGrpcCall:
    """Yields N good responses then raises mid-stream."""
    def __init__(self, responses, exc):
        self._responses = responses
        self._exc = exc

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for r in self._responses:
            yield r
        raise self._exc


@pytest.fixture()
def client():
    cl = YandexClient(Credentials("k", "f", auth_mode="api_key"))
    cl.start()
    try:
        yield cl
    finally:
        cl.stop()


def _make_speech(client, stub):
    speech = YandexSpeech(client)
    speech.set_tts_version("v3-grpc")
    client.tts_synthesizer_stub = lambda: stub
    return speech


def test_synthesize_streaming_yields_chunks_in_order(client):
    pcm1 = np.array([1, 2], dtype="<i2").tobytes()
    pcm2 = np.array([3, 4], dtype="<i2").tobytes()
    stub = _FakeSynthesizerStub(responses=[_FakeUtteranceResponse(pcm1),
                                           _FakeUtteranceResponse(pcm2)])
    speech = _make_speech(client, stub)

    chunks = list(speech.synthesize_streaming("Привет", "tv"))

    assert len(chunks) == 2
    for audio, sr in chunks:
        assert isinstance(audio, np.ndarray)
        assert sr == config.YANDEX_TTS_SAMPLE_RATE
    assert chunks[0][1] == chunks[1][1]
    np.testing.assert_allclose(chunks[0][0], np.array([1, 2], dtype="<i2").astype(np.float32) / 32768.0)
    np.testing.assert_allclose(chunks[1][0], np.array([3, 4], dtype="<i2").astype(np.float32) / 32768.0)


def test_synthesize_streaming_empty_for_non_grpc_version(client):
    stub = _FakeSynthesizerStub(responses=[])
    speech = _make_speech(client, stub)
    speech.set_tts_version("v1")   # not v3-grpc -> generator must be empty
    assert list(speech.synthesize_streaming("Привет", "tv")) == []


def test_synthesize_streaming_propagates_exception_raised_before_any_chunk(client):
    stub = _FakeSynthesizerStub(exc=RuntimeError("grpc down"))
    speech = _make_speech(client, stub)

    gen = speech.synthesize_streaming("Привет", "tv")
    with pytest.raises(RuntimeError, match="grpc down"):
        next(gen)


def test_synthesize_streaming_propagates_exception_after_some_chunks(client, monkeypatch):
    pcm1 = np.array([1, 2], dtype="<i2").tobytes()

    class _Stub:
        def UtteranceSynthesis(self, request, metadata=None, timeout=None):
            return _FailingGrpcCall([_FakeUtteranceResponse(pcm1)], RuntimeError("stream broke"))

    speech = _make_speech(client, _Stub())

    gen = speech.synthesize_streaming("Привет", "tv")
    first = next(gen)
    assert first[0].tolist() == pytest.approx((np.array([1, 2], dtype="<i2").astype(np.float32) / 32768.0).tolist())
    with pytest.raises(RuntimeError, match="stream broke"):
        next(gen)


def test_synthesize_streaming_raises_timeout_instead_of_hanging_forever(client, monkeypatch):
    """Regression test: if the producer coroutine never actually runs (the
    YandexClient event-loop thread stopped/died between submit() and
    execution — e.g. YandexClient.stop() racing this call), the generator
    must not block the sole TTSQueue playback worker thread forever."""
    monkeypatch.setattr(config, "YANDEX_TTS_GRPC_TIMEOUT", 0.05)   # keep the test fast
    stub = _FakeSynthesizerStub(responses=[])
    speech = _make_speech(client, stub)

    submitted = []

    def _swallowing_submit(coro):
        submitted.append(coro)   # never actually runs it — simulates a dead loop
        return None

    monkeypatch.setattr(client, "submit", _swallowing_submit)

    gen = speech.synthesize_streaming("Привет", "tv")
    try:
        with pytest.raises(TimeoutError):
            next(gen)
    finally:
        for coro in submitted:
            coro.close()   # avoid "coroutine was never awaited" warning
