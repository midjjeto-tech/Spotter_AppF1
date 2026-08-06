# SpeechKit gRPC Transport (Phase A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third TTS backend option, `"v3-grpc"`, that synthesizes speech via Yandex SpeechKit v3's gRPC `Synthesizer.UtteranceSynthesis` streaming RPC instead of REST/NDJSON — same "collect all chunks, then decode" behavior as today's `"v3"`, just a different transport. Playback, caching, and the radio effect are unchanged (that's Phase B, not this plan).

**Architecture:** A long-lived `grpc.aio` channel lives on `YandexClient` (parallel to its existing aiohttp session). `yandex_ai/speech.py` gains `_asynthesize_v3_grpc()`, dispatched from the existing `_try_once()`/`synthesize()` machinery exactly like `"v1"`/`"v3"` are today, with the same v3→v1 fallback chain. A live spike (already run manually, see design doc) confirmed the `yandexcloud` pip package bundles working compiled stubs for `yandex.cloud.ai.tts.v3.Synthesizer`, and that `Api-Key` auth works over gRPC metadata exactly as it does over REST headers.

**Tech Stack:** Python 3.12, `grpcio` (via the `yandexcloud` package), `grpc.aio`, pytest. New dependency: `yandexcloud`.

**Design doc:** `docs/superpowers/specs/2026-07-09-speechkit-grpc-transport-design.md`

**Note on git:** this project is not under version control. No `git commit` steps — each task ends with a verification checkpoint instead.

**Note on the live spike:** the design doc records two manual, already-executed live gRPC calls that proved the package/auth/async-fit all work. This plan does NOT repeat that live call as an automated test — unit tests mock the gRPC stub (see Task 4), matching how `_asynthesize_v3`'s existing tests mock `post_json_raw` rather than hitting the real network.

---

### Task 1: Install `yandexcloud` into the project's requirements

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Confirm the installed version**

Run: `py -3.12 -m pip show yandexcloud`
Record the `Version:` line from the output — call it `<YC_VERSION>` below. (This package was already installed into the dev venv during the design spike — this step just records which version to pin, it does not reinstall anything.)

- [ ] **Step 2: Add it to `requirements.txt`**

Read the current `requirements.txt`, then add a new line (grouped near the other Yandex-related comment, if one exists, otherwise at the end):

```
yandexcloud==<YC_VERSION>       # gRPC client for SpeechKit v3 (Synthesizer.UtteranceSynthesis)
```

Replace `<YC_VERSION>` with the real value from Step 1 — do not leave it as a literal placeholder.

- [ ] **Step 3: Checkpoint**

Run: `py -3.12 -c "from yandex.cloud.ai.tts.v3 import tts_pb2, tts_service_pb2_grpc; print('OK')"`
Expected: `OK` (confirms the package's bundled stubs import cleanly in this interpreter). No git commit needed (project has no git repo). Move to Task 2.

---

### Task 2: `yandex_ai/credentials.py` — gRPC metadata helper

**Files:**
- Modify: `yandex_ai/credentials.py`
- Test: `tests/test_yandex_credentials.py` (create if it doesn't exist, otherwise extend it)

- [ ] **Step 1: Write the failing tests**

First check whether `tests/test_yandex_credentials.py` already exists (`ls tests/test_yandex_credentials.py`). If it exists, read it and add the two tests below in a style consistent with its existing tests. If it doesn't exist, create it with exactly this content:

```python
"""tests/test_yandex_credentials.py — Credentials + auth header/metadata helpers."""
from yandex_ai.credentials import Credentials, auth_header, grpc_auth_metadata


def test_grpc_auth_metadata_api_key():
    creds = Credentials("my-key", "my-folder", auth_mode="api_key")
    assert grpc_auth_metadata(creds) == [("authorization", "Api-Key my-key")]


def test_grpc_auth_metadata_iam():
    creds = Credentials("my-token", "my-folder", auth_mode="iam")
    assert grpc_auth_metadata(creds) == [("authorization", "Bearer my-token")]


def test_grpc_auth_metadata_matches_auth_header_value():
    """grpc_auth_metadata must carry the exact same Authorization VALUE that
    auth_header() sends over REST — same credential, same header content,
    only the transport (gRPC metadata tuple vs. HTTP header dict) differs."""
    creds = Credentials("k", "f", auth_mode="api_key")
    assert grpc_auth_metadata(creds)[0][1] == auth_header(creds)["Authorization"]
```

(If `Credentials(...)` doesn't accept positional `(api_key, folder_id, auth_mode=...)` — read the actual `Credentials` class definition in `yandex_ai/credentials.py` first and adjust the test calls to match its real constructor signature before proceeding.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_yandex_credentials.py -v`
Expected: FAIL with `ImportError: cannot import name 'grpc_auth_metadata'`

- [ ] **Step 3: Implement**

In `yandex_ai/credentials.py`, find the existing `auth_header` function:

```python
def auth_header(creds: Credentials) -> dict:
    if creds.auth_mode == "iam":
        return {"Authorization": f"Bearer {creds.api_key}"}
    return {"Authorization": f"Api-Key {creds.api_key}"}
```

Add a new function right after it:

```python
def grpc_auth_metadata(creds: Credentials) -> list[tuple[str, str]]:
    """То же значение Authorization, что и auth_header(), но как gRPC-metadata
    (нижний регистр ключа — требование gRPC), не HTTP-заголовок. Переиспользует
    auth_header() — ветка iam/api_key не дублируется в двух местах."""
    value = auth_header(creds)["Authorization"]
    return [("authorization", value)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_yandex_credentials.py -v`
Expected: all PASS

- [ ] **Step 5: Checkpoint**

Move to Task 3.

---

### Task 3: `yandex_ai/client.py` — long-lived gRPC channel + `config.py` constants

**Files:**
- Modify: `config.py`
- Modify: `yandex_ai/client.py`
- Test: `tests/test_yandex_client_grpc.py` (new)

- [ ] **Step 1: Add config constants**

In `config.py`, find where `YANDEX_TTS_V3_URL` and its sibling timeout constants are defined (search for `YANDEX_TTS_V3_URL`), and add two new constants nearby:

```python
YANDEX_TTS_GRPC_ENDPOINT = "tts.api.cloud.yandex.net:443"
YANDEX_TTS_GRPC_TIMEOUT = 10.0   # секунд, тот же порядок что YANDEX_TTS_V3_TOTAL_TIMEOUT
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_yandex_client_grpc.py`:

```python
"""tests/test_yandex_client_grpc.py — YandexClient gRPC channel lifecycle."""
import unittest.mock as mock

from yandex_ai.client import YandexClient
from yandex_ai.credentials import Credentials


def test_grpc_channel_created_on_start():
    client = YandexClient(Credentials("k", "f"))
    client.start()
    try:
        assert client._grpc_channel is not None
    finally:
        client.stop()


def test_tts_synthesizer_stub_returns_stub_bound_to_channel():
    client = YandexClient(Credentials("k", "f"))
    client.start()
    try:
        stub = client.tts_synthesizer_stub()
        assert stub is not None
        assert hasattr(stub, "UtteranceSynthesis")
    finally:
        client.stop()


def test_grpc_metadata_delegates_to_credentials_helper():
    client = YandexClient(Credentials("my-key", "f", auth_mode="api_key"))
    assert client.grpc_metadata() == [("authorization", "Api-Key my-key")]


def test_stop_closes_grpc_channel_without_raising():
    client = YandexClient(Credentials("k", "f"))
    client.start()
    client.stop()   # must not raise even though the channel is now closed
```

(As in Task 2, if `Credentials(...)`'s constructor signature differs from `Credentials("k", "f")`/`Credentials("k", "f", auth_mode="api_key")`, read the real class first and adjust.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_yandex_client_grpc.py -v`
Expected: FAIL — `AttributeError: 'YandexClient' object has no attribute '_grpc_channel'`

- [ ] **Step 4: Implement**

In `yandex_ai/client.py`:

4a. Add an import near the top (alongside the existing `import aiohttp`):

```python
import grpc
```

4b. In `__init__`, add a new attribute after `self._session: aiohttp.ClientSession | None = None`:

```python
        self._session: aiohttp.ClientSession | None = None
        self._grpc_channel: "grpc.aio.Channel | None" = None
        self._ready = threading.Event()
```

4c. In `_run_loop`'s inner `_init_session()` coroutine, create the gRPC channel alongside the aiohttp session:

```python
        async def _init_session() -> None:
            # aiohttp 3.14: ClientSession must be constructed inside a running
            # event loop (it calls asyncio.get_running_loop()).
            self._session = aiohttp.ClientSession()
            # grpc.aio channel — long-lived, multiplexed, same lifecycle as
            # the aiohttp session above (created once, reused for every call).
            import config as _config
            self._grpc_channel = grpc.aio.secure_channel(
                _config.YANDEX_TTS_GRPC_ENDPOINT, grpc.ssl_channel_credentials())
```

4d. In `stop()`'s inner `_close()` coroutine, close the gRPC channel too:

```python
        async def _close():
            if self._session:
                await self._session.close()
            if self._grpc_channel:
                await self._grpc_channel.close()
```

4e. Add two new public methods, near the existing `headers()` method:

```python
    def grpc_metadata(self) -> list[tuple[str, str]]:
        return creds_mod.grpc_auth_metadata(self._creds)

    def tts_synthesizer_stub(self):
        from yandex.cloud.ai.tts.v3 import tts_service_pb2_grpc
        return tts_service_pb2_grpc.SynthesizerStub(self._grpc_channel)
```

Read the actual current `yandex_ai/client.py` first to confirm exact surrounding lines before editing — the snippets above show the target end state of small, surgical additions, not a full-file rewrite.

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_yandex_client_grpc.py -v`
Expected: all PASS

- [ ] **Step 6: Checkpoint**

Run the existing client tests to confirm nothing broke: `py -3.12 -m pytest tests/test_yandex_version.py -v` (this file mocks `YandexClient` heavily via `mock.MagicMock()`, so it shouldn't be affected, but confirm). No git commit needed (project has no git repo). Move to Task 4.

---

### Task 4: `yandex_ai/speech.py` — `_asynthesize_v3_grpc()` + dispatch + fallback

**Files:**
- Modify: `yandex_ai/speech.py`
- Test: `tests/test_yandex_version.py` (extend)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_yandex_version.py`, near the existing `TestV3AudioParsing` class:

```python
# ---------------------------------------------------------------------------
# v3-grpc: new backend option (Phase A — transport swap, same "wait for all
# chunks then decode" behavior as v3/REST)
# ---------------------------------------------------------------------------

class _FakeAudioChunk:
    def __init__(self, data: bytes):
        self.data = data


class _FakeUtteranceResponse:
    def __init__(self, data: bytes, start_ms: int = 0, length_ms: int = 0):
        self.audio_chunk = _FakeAudioChunk(data)
        self.start_ms = start_ms
        self.length_ms = length_ms


class _FakeGrpcCall:
    """Mimics the async-iterable object returned by stub.UtteranceSynthesis()."""
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
        if self._exc:
            raise self._exc
        return _FakeGrpcCall(self._responses)


class TestV3GrpcVersionToggle:
    def _make_speech(self):
        from yandex_ai.speech import YandexSpeech
        client = mock.MagicMock()
        client.folder_id = "folder"
        return YandexSpeech(client)

    def test_set_v3_grpc(self):
        speech = self._make_speech()
        speech.set_tts_version("v3-grpc")
        assert speech.tts_version == "v3-grpc"

    def test_v3_grpc_path_called_when_version_v3_grpc(self):
        speech = self._make_speech()
        speech.set_tts_version("v3-grpc")
        audio_data = np.zeros(1000, dtype=np.float32)
        with mock.patch.object(speech, "_try_once", return_value=audio_data) as m:
            result, sr = speech.synthesize("Привет", "tv")
        assert m.call_args.args[5] == "v3-grpc"

    def test_falls_back_to_v1_when_v3_grpc_fails(self):
        speech = self._make_speech()
        speech.set_tts_version("v3-grpc")
        audio_data = np.zeros(800, dtype=np.float32)
        call_versions = []

        def try_once_side(text, voice, emotion, speed, sr, version):
            call_versions.append(version)
            if version == "v3-grpc":
                return None
            return audio_data

        with mock.patch.object(speech, "_try_once", side_effect=try_once_side):
            result, sr = speech.synthesize("Привет", "tv")

        assert result is not None
        assert "v3-grpc" in call_versions
        assert "v1" in call_versions


class TestV3GrpcAudioParsing:
    """Test _asynthesize_v3_grpc directly against a fake gRPC stub (no network)."""

    def _make_speech(self):
        from yandex_ai.speech import YandexSpeech
        client = mock.MagicMock()
        client.folder_id = "folder"
        client.grpc_metadata.return_value = [("authorization", "Api-Key k")]
        return YandexSpeech(client), client

    def test_parses_single_chunk(self):
        import asyncio
        speech, client = self._make_speech()
        pcm = np.array([0, 1000, -1000, 500], dtype="<i2").tobytes()
        client.tts_synthesizer_stub.return_value = _FakeSynthesizerStub(
            responses=[_FakeUtteranceResponse(pcm)])

        async def run():
            return await speech._asynthesize_v3_grpc("Hi", "filipp", 1.0, 48000)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(run())
        finally:
            loop.close()

        assert result is not None
        assert len(result) == 4

    def test_parses_multiple_chunks(self):
        import asyncio
        speech, client = self._make_speech()
        pcm1 = np.array([100, 200], dtype="<i2").tobytes()
        pcm2 = np.array([300, 400], dtype="<i2").tobytes()
        client.tts_synthesizer_stub.return_value = _FakeSynthesizerStub(
            responses=[_FakeUtteranceResponse(pcm1), _FakeUtteranceResponse(pcm2)])

        async def run():
            return await speech._asynthesize_v3_grpc("Hi", "filipp", 1.0, 48000)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(run())
        finally:
            loop.close()

        assert result is not None
        assert len(result) == 4

    def test_returns_none_on_empty_stream(self):
        import asyncio
        speech, client = self._make_speech()
        client.tts_synthesizer_stub.return_value = _FakeSynthesizerStub(responses=[])

        async def run():
            return await speech._asynthesize_v3_grpc("Hi", "filipp", 1.0, 48000)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(run())
        finally:
            loop.close()

        assert result is None

    def test_sends_role_hint_for_non_neutral_emotion(self):
        import asyncio
        speech, client = self._make_speech()
        captured = {}

        def capture_stub():
            stub = _FakeSynthesizerStub(
                responses=[_FakeUtteranceResponse(np.array([1, 2], dtype="<i2").tobytes())])
            original = stub.UtteranceSynthesis

            def wrapped(request, metadata=None, timeout=None):
                captured["request"] = request
                return original(request, metadata=metadata, timeout=timeout)
            stub.UtteranceSynthesis = wrapped
            return stub

        client.tts_synthesizer_stub.side_effect = capture_stub

        async def run():
            return await speech._asynthesize_v3_grpc("Hi", "dasha", 1.0, 48000, emotion="friendly")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run())
        finally:
            loop.close()

        roles = [h.role for h in captured["request"].hints if h.role]
        assert roles == ["friendly"]

    def test_omits_role_hint_for_neutral(self):
        import asyncio
        speech, client = self._make_speech()
        captured = {}

        def capture_stub():
            stub = _FakeSynthesizerStub(
                responses=[_FakeUtteranceResponse(np.array([1, 2], dtype="<i2").tobytes())])
            original = stub.UtteranceSynthesis

            def wrapped(request, metadata=None, timeout=None):
                captured["request"] = request
                return original(request, metadata=metadata, timeout=timeout)
            stub.UtteranceSynthesis = wrapped
            return stub

        client.tts_synthesizer_stub.side_effect = capture_stub

        async def run():
            return await speech._asynthesize_v3_grpc("Hi", "alexander", 1.0, 48000, emotion="neutral")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run())
        finally:
            loop.close()

        roles = [h.role for h in captured["request"].hints if h.role]
        assert roles == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_yandex_version.py::TestV3GrpcVersionToggle -v`
Expected: FAIL — `set_tts_version("v3-grpc")` doesn't stick (`tts_version` stays `"v1"`), since `"v3-grpc"` isn't in the accepted set yet.

- [ ] **Step 3: Implement.** Four edits to `yandex_ai/speech.py`:

3a. Add an import near the top (alongside the existing `import numpy as np`):

```python
import config
```

(Skip this if `config` is already imported — read the actual current file first; it likely already imports `config` since `_asynthesize_v1` already uses `config.YANDEX_TTS_URL`.)

3b. Add the new synthesis method, right after `_asynthesize_v3`:

```python
    async def _asynthesize_v3_grpc(self, text: str, voice: str, speed: float,
                                    sr: int, emotion: str = "neutral") -> np.ndarray | None:
        """Synthesize using SpeechKit v3 Synthesizer.UtteranceSynthesis (gRPC,
        server-streaming). Этап A: собираем ВСЕ чанки, потом декодируем — то же
        поведение, что _asynthesize_v3 (REST/NDJSON), другой транспорт. Настоящий
        streaming playback — Этап B, отдельная задача (voice/tts.py)."""
        from yandex.cloud.ai.tts.v3 import tts_pb2
        hints = [tts_pb2.Hints(voice=voice), tts_pb2.Hints(speed=speed)]
        if emotion and emotion != "neutral":
            hints.append(tts_pb2.Hints(role=emotion))
        request = tts_pb2.UtteranceSynthesisRequest(
            text=text,
            hints=hints,
            output_audio_spec=tts_pb2.AudioFormatOptions(
                raw_audio=tts_pb2.RawAudio(
                    audio_encoding=tts_pb2.RawAudio.LINEAR16_PCM,
                    sample_rate_hertz=sr,
                )
            ),
            loudness_normalization_type=tts_pb2.UtteranceSynthesisRequest.LUFS,
        )
        metadata = self._client.grpc_metadata()
        stub = self._client.tts_synthesizer_stub()
        chunks: list[bytes] = []
        call = stub.UtteranceSynthesis(request, metadata=metadata,
                                       timeout=config.YANDEX_TTS_GRPC_TIMEOUT)
        async for response in call:
            chunks.append(response.audio_chunk.data)
        if not chunks:
            return None
        raw_pcm = b"".join(chunks)
        return np.frombuffer(raw_pcm, dtype="<i2").astype(np.float32) / 32768.0
```

3c. In `_try_once()`, add a new branch right after the existing `if version == "v3":` branch:

```python
        try:
            if version == "v3":
                coro = self._asynthesize_v3(text, voice, speed, sr, emotion=emotion)
                timeout = config.YANDEX_TTS_V3_TOTAL_TIMEOUT + 1.0
            elif version == "v3-grpc":
                coro = self._asynthesize_v3_grpc(text, voice, speed, sr, emotion=emotion)
                timeout = config.YANDEX_TTS_GRPC_TIMEOUT + 1.0
            else:
                coro = self._asynthesize_v1(text, voice, emotion, speed, sr)
                timeout = config.YANDEX_TTS_TOTAL_TIMEOUT + 1.0
            fut = self._client.submit(coro)
            return fut.result(timeout=timeout)
```

Also, in `_try_once()`'s exception classification block, add a gRPC-specific reason right after the existing `elif hasattr(exc, "status"):` (aiohttp) branch:

```python
            elif hasattr(exc, "status"):          # aiohttp.ClientResponseError
                reason = f"HTTP {exc.status}: {msg}"
            elif hasattr(exc, "code") and callable(getattr(exc, "code", None)):
                reason = f"gRPC {exc.code()}: {exc.details()}"   # grpc.aio.AioRpcError
            elif "JSONDecodeError" in etype:
                reason = f"NDJSON parse error: {msg}"
```

3d. In `set_tts_version()`, extend the accepted set:

```python
    def set_tts_version(self, version: str) -> None:
        """Select active TTS backend version. Ignored if value not in
        ("v1", "v3", "v3-grpc")."""
        if version in ("v1", "v3", "v3-grpc"):
```

3e. In `synthesize()`, extend the v3-fallback condition to also cover `v3-grpc`:

```python
        # v3/v3-grpc graceful fallback to v1
        if audio is None and version in ("v3", "v3-grpc"):
            _log.warning(
                "YandexSpeech fallback: %s failed for persona=%s voice=%s — trying v1 "
                "(reason logged above)",
                version, persona, spec["voice"],
            )
```

Read the actual current `yandex_ai/speech.py` first — all five edits above are small, surgical insertions/replacements into the existing structure you already read earlier in this task; don't rewrite unrelated code.

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_yandex_version.py -v`
Expected: all PASS (existing v1/v3 tests plus new v3-grpc tests)

- [ ] **Step 5: Checkpoint**

Move to Task 5.

---

### Task 5: `core/engine.py` — accept `"v3-grpc"` in settings validation

**Files:**
- Modify: `core/engine.py:328`
- Test: `tests/test_engine_settings.py` (extend if it covers this line, otherwise add to `tests/test_yandex_version.py`)

- [ ] **Step 1: Write the failing test**

First check whether `tests/test_engine_settings.py` already has a test for `yandex_tts_version` validation (search: `grep -n "yandex_tts_version" tests/test_engine_settings.py`). If it does, add a sibling test there following its existing style. Otherwise, add this to `tests/test_yandex_version.py`:

```python
class TestEngineAcceptsV3Grpc:
    def test_apply_settings_accepts_v3_grpc(self):
        import core.engine as eng_mod
        orig = eng_mod.yc.load
        eng_mod.yc.load = lambda: None
        try:
            engine = eng_mod.F1Engine({})
            engine.voice.set_tts_version = mock.MagicMock()
            engine.apply_settings({"yandex_tts_version": "v3-grpc"})
            engine.voice.set_tts_version.assert_called_once_with("v3-grpc")
        finally:
            eng_mod.yc.load = orig
```

(If `apply_settings` is not the actual method name containing the `if version in ("v1", "v3"):` check — re-read `core/engine.py` around line 328 to confirm the enclosing method's real name and adjust the test to call it correctly.)

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest tests/test_yandex_version.py::TestEngineAcceptsV3Grpc -v`
Expected: FAIL — `set_tts_version` not called (because `"v3-grpc"` isn't in the accepted tuple yet)

- [ ] **Step 3: Implement**

In `core/engine.py`, find:

```python
        if "yandex_tts_version" in settings:
            version = settings["yandex_tts_version"]
            if version in ("v1", "v3"):
```

Change to:

```python
        if "yandex_tts_version" in settings:
            version = settings["yandex_tts_version"]
            if version in ("v1", "v3", "v3-grpc"):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest tests/test_yandex_version.py -v`
Expected: all PASS

- [ ] **Step 5: Checkpoint**

Run `py -3.12 -m pytest tests/test_engine_settings.py -v` to confirm no regressions in the broader settings-handling test file. No git commit needed (project has no git repo). Move to Task 6.

---

### Task 6: Packaging — `SpotterApp.spec` + `build.ps1` + real EXE build

**Files:**
- Modify: `SpotterApp.spec`
- Modify: `build.ps1`
- No automated test — this task's verification IS a real build + manual run

- [ ] **Step 1: Add to `build.ps1`'s dependency gate**

In `build.ps1`, find:

```powershell
$deps = @("bottle","webview","win32gui","sounddevice","soundfile","piper",
          "onnxruntime","numpy","psutil","aiohttp","pandas")
$pipName = @{ webview = "pywebview"; win32gui = "pywin32"; piper = "piper-tts" }
```

Change to:

```powershell
$deps = @("bottle","webview","win32gui","sounddevice","soundfile","piper",
          "onnxruntime","numpy","psutil","aiohttp","pandas","grpc","yandexcloud")
$pipName = @{ webview = "pywebview"; win32gui = "pywin32"; piper = "piper-tts"; grpc = "grpcio" }
```

- [ ] **Step 2: Add to `SpotterApp.spec`'s collection list**

In `SpotterApp.spec`, find the `# pandas — fastf1 analytics` block (the last `collect_all` call before the blank lines and `a = Analysis(...)`):

```python
# pandas — fastf1 analytics
tmp_ret = collect_all('pandas')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
```

Add a new block right after it:

```python
# gRPC — SpeechKit v3 Synthesizer (yandex_ai/client.py). Native extension
# (_cygrpc) — collect_all alone has previously NOT been sufficient for native
# extensions in this project (see torch DLL lesson in CONTEXT.md); if the
# built EXE fails to import grpc at runtime, add an explicit
# collect_dynamic_libs('grpc') call here — diagnose from the real failure,
# don't guess preemptively.
for _pkg in ('grpc', 'yandexcloud'):
    tmp_ret = _safe_collect(_pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
```

- [ ] **Step 3: Install the build-interpreter dependencies**

Run: `py -3.12 -m pip install yandexcloud grpcio` (idempotent if already installed from the design spike).

- [ ] **Step 4: Run the real build**

Run: `powershell -File build.ps1` (or however this project's build is normally invoked — check the file for its actual invocation convention first). This takes several minutes. Watch for the dependency gate passing (Step 1's new entries) and for the build completing without PyInstaller errors related to `grpc`/`yandexcloud`.

Expected: `dist/SpotterApp.exe` produced successfully.

- [ ] **Step 5: Manually verify gRPC works inside the frozen EXE**

This step requires temporarily setting `yandex_tts_version` to `"v3-grpc"` (e.g. via the Settings UI once the app is running, or by editing `DATA_DIR/settings.json` next to the EXE before launch) and confirming a commentary phrase is actually synthesized and played through the `v3-grpc` path — check the app's log output for `"YandexSpeech synthesize: version=v3-grpc"` (from the existing `_log.info` in `synthesize()`) and for the absence of a `"YandexSpeech fallback"` warning right after it (which would mean gRPC failed and it silently fell back to v1 — the EXE would still work, but the packaging goal wouldn't actually be proven).

If this step reveals a packaging failure (e.g. `ImportError: DLL load failed` for grpc's native extension), that's the real risk this task exists to catch — fix by adding `from PyInstaller.utils.hooks import collect_dynamic_libs` and calling `collect_dynamic_libs('grpc')` alongside the `collect_all` calls added in Step 2, then rebuild and retest. Do not skip this verification or assume it will "probably work" — the whole point of this task is to replace that assumption with a real answer.

- [ ] **Step 6: Checkpoint**

Confirm the EXE builds and `v3-grpc` synthesizes real audio when selected. No git commit needed (project has no git repo). Move to Task 7.

---

### Task 7: Full regression + `CONTEXT.md` session note

**Files:**
- Modify: `CONTEXT.md`
- No further code changes

- [ ] **Step 1: Run the full test suite**

Run: `py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q`
Expected: 0 failed. Note the exact "N passed, M skipped" line (baseline before this feature was 1023 passed, 1 skipped) — call this count `<TOTAL>` below.

- [ ] **Step 2: Import smoke test**

Run: `py -3.12 -c "import yandex_ai.client, yandex_ai.speech, yandex_ai.credentials, core.engine"`
Expected: no output, exit code 0

- [ ] **Step 3: Add a new session section to `CONTEXT.md`**

Read the current `CONTEXT.md` first (it changes between sessions). Insert a new session section directly above the current newest session entry, and update "На чём остановились" to point at this closure. Use this template, filling in the real `<TOTAL>` from Step 1 and the real EXE-build outcome from Task 6:

```markdown
## Сессия 2026-07-09 — SpeechKit v3 gRPC-транспорт (Этап A), 7/7 ✅

Закрывает первую половину бэклог-пункта «SpeechKit v3 через gRPC streaming
(сейчас REST/NDJSON)» — ТОЛЬКО транспорт, воспроизведение (кэш, радио-эффект,
streaming playback) сознательно не тронуто, это Этап B, отдельный будущий
цикл. План: `docs/superpowers/plans/2026-07-09-speechkit-grpc-transport.md`,
спека: `docs/superpowers/specs/2026-07-09-speechkit-grpc-transport-design.md`.

**Живой спайк ДО дизайна (не предположения):** `yandexcloud` (pip) содержит
готовые скомпилированные gRPC-стабы `yandex.cloud.ai.tts.v3.*` — ручная
компиляция `.proto` не нужна. Живой вызов `Synthesizer.UtteranceSynthesis`
через `grpc.aio` с metadata `authorization: Api-Key <ключ>` (ТОТ ЖЕ ключ, что
уже шлёт REST) сработал с первой попытки — вернул реальное LPCM-аудио.

- **`yandex_ai/credentials.py`** — `grpc_auth_metadata()`, переиспользует
  `auth_header()` (не дублирует ветку iam/api_key).
- **`yandex_ai/client.py`** — долгоживущий `grpc.aio.Channel` рядом с
  aiohttp-сессией (создаётся один раз при старте, закрывается при `stop()`),
  `tts_synthesizer_stub()`/`grpc_metadata()`.
- **`yandex_ai/speech.py`** — новый `_asynthesize_v3_grpc()`, третий вариант
  тумблера `"v3-grpc"` рядом с `"v1"/"v3"` (дефолт НЕ меняется, остаётся
  `"v3"`). Собирает ВСЕ чанки, потом декодирует — то же поведение, что REST
  v3, другой транспорт (настоящий streaming playback — Этап B). Фолбэк на
  сбое — та же цепочка, что у v3: `v3-grpc → v1`.
- **Упаковка** — `yandexcloud`/`grpcio` добавлены в `requirements.txt`,
  `SpotterApp.spec` (`collect_all`), `build.ps1` (dependency gate). Реальная
  сборка EXE выполнена — [ЗАПОЛНИТЬ: успешно / потребовался
  collect_dynamic_libs('grpc') из-за нативного расширения].

**Верификация:** новые тесты в `tests/test_yandex_credentials.py`,
`tests/test_yandex_client_grpc.py`, `tests/test_yandex_version.py` (все мокают
gRPC-стаб, без реальной сети — живая проверка сделана вручную спайком до
реализации, см. выше). Полный прогон
`py -3.12 -u -m pytest --ignore=tests/test_gpt.py -q` — **<TOTAL>** (было
1023 passed, 1 skipped). Импорт-смоук — без ошибок. Реальная сборка EXE — см.
Task 6.

**Вне рамок (Этап B, следующий цикл):** настоящий streaming playback — начать
воспроизведение по мере поступления чанков, а не после полного синтеза.
Требует переделки `voice/tts.py::_play_wav`/`TTSQueue` под инкрементальную
игру, взаимодействия с диск-кэшем (`voice/cache.py` — сейчас кэш хранит целый
WAV) и радио-эффектом (`voice/radio_fx.py` — сейчас применяется к целому
буферу).
```

Replace `<TOTAL>` with the actual line from Step 1, and fill in the Task 6 EXE-build outcome bracket honestly — don't leave placeholder text in the shipped file.

- [ ] **Step 4: Checkpoint (final)**

Confirm `CONTEXT.md` renders correctly, full suite green, import smoke clean, EXE build outcome accurately recorded. Feature (Phase A) complete.

---

## Plan Self-Review Notes

- **Spec coverage:** all 6 design sections (credentials helper, client channel,
  config constants, speech.py dispatch, engine.py validation, packaging) map
  1:1 to Tasks 1-6. The design doc's explicit non-goal ("not touching
  playback") is respected — no task touches `voice/tts.py`, `voice/cache.py`,
  or `voice/radio_fx.py`.
- **No placeholder scan:** Task 7's CONTEXT.md template has one intentional
  bracket (`[ЗАПОЛНИТЬ: ...]`) that MUST be replaced with the real Task 6
  outcome before the step is considered done — flagged explicitly in the step
  text, not left as silent TODO.
- **Type/signature consistency:** `grpc_auth_metadata(creds) -> list[tuple[str,
  str]]`, `YandexClient.grpc_metadata() -> list[tuple[str, str]]` (delegates),
  `YandexClient.tts_synthesizer_stub()`, `_asynthesize_v3_grpc(text, voice,
  speed, sr, emotion="neutral") -> np.ndarray | None` (same positional-arg
  shape as sibling `_asynthesize_v3`) — consistent across Tasks 2-4 and their
  tests.
- **Risk sequencing:** the single highest-risk unknown (does gRPC/auth/package
  work at all) was already resolved via a live spike BEFORE this plan was
  written (see design doc) — so Tasks 1-5 are now low-risk, well-specified
  coding work. The SECOND highest risk (EXE packaging) is deliberately its own
  task (6) with a real build+run gate, not folded into the coding tasks, so a
  packaging failure doesn't block or muddy the review of the actual synthesis
  logic in Task 4.
