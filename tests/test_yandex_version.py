"""
tests/test_yandex_version.py
============================
Tests for Yandex TTS version toggle (v1/v3) in yandex_ai/speech.py
and settings persistence in core/settings.py.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest.mock as mock
from pathlib import Path

import numpy as np
import pytest

import config
from core import settings as settings_mod


# ---------------------------------------------------------------------------
# Settings persistence
# ---------------------------------------------------------------------------

class TestYandexVersionSettings:
    def test_default_is_v3(self):
        # 2026-07-01: v3 по умолчанию (нейро-рендер живее; фолбэк v3→v1 есть per-phrase)
        assert settings_mod.DEFAULTS["yandex_tts_version"] == "v3"

    def test_load_fills_missing_key_with_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            path.write_text(json.dumps({"persona": "hype"}), encoding="utf-8")
            with mock.patch.object(settings_mod, "_PATH", path):
                loaded = settings_mod.load()
            assert loaded["yandex_tts_version"] == "v3"

    def test_load_restores_v3(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            data = dict(settings_mod.DEFAULTS)
            data["yandex_tts_version"] = "v3"
            path.write_text(json.dumps(data), encoding="utf-8")
            with mock.patch.object(settings_mod, "_PATH", path):
                loaded = settings_mod.load()
            assert loaded["yandex_tts_version"] == "v3"

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            updated = dict(settings_mod.DEFAULTS)
            updated["yandex_tts_version"] = "v3"
            with mock.patch.object(settings_mod, "_PATH", path):
                settings_mod.save(updated)
                loaded = settings_mod.load()
            assert loaded["yandex_tts_version"] == "v3"

    def test_unknown_version_string_not_persisted_on_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            # Manually write an invalid version
            bad = dict(settings_mod.DEFAULTS)
            bad["yandex_tts_version"] = "v999"
            path.write_text(json.dumps(bad), encoding="utf-8")
            with mock.patch.object(settings_mod, "_PATH", path):
                loaded = settings_mod.load()
            # load() accepts any value that's in DEFAULTS keys;
            # validation is done by the backend (engine.apply_settings).
            # The raw value is returned as-is — engine filters it.
            assert "yandex_tts_version" in loaded


# ---------------------------------------------------------------------------
# YandexSpeech.set_tts_version / tts_version property
# ---------------------------------------------------------------------------

class TestYandexSpeechVersionToggle:
    def _make_speech(self):
        from yandex_ai.speech import YandexSpeech
        client = mock.MagicMock()
        client.folder_id = "test-folder"
        return YandexSpeech(client)

    def test_default_version_is_v1(self):
        speech = self._make_speech()
        assert speech.tts_version == "v1"

    def test_set_v3(self):
        speech = self._make_speech()
        speech.set_tts_version("v3")
        assert speech.tts_version == "v3"

    def test_set_v1_after_v3(self):
        speech = self._make_speech()
        speech.set_tts_version("v3")
        speech.set_tts_version("v1")
        assert speech.tts_version == "v1"

    def test_invalid_version_ignored(self):
        speech = self._make_speech()
        speech.set_tts_version("v999")
        assert speech.tts_version == "v1"

    def test_set_overrides_propagates(self):
        speech = self._make_speech()
        speech.set_overrides({"tv": {"voice": "ermil"}})
        assert speech._overrides == {"tv": {"voice": "ermil"}}


# ---------------------------------------------------------------------------
# v1 path (patching _try_once)
# ---------------------------------------------------------------------------

class TestV1Path:
    def _make_speech(self):
        from yandex_ai.speech import YandexSpeech
        client = mock.MagicMock()
        client.folder_id = "folder"
        return YandexSpeech(client)

    def test_v1_path_called_when_version_v1(self):
        speech = self._make_speech()
        speech.set_tts_version("v1")
        audio_data = np.zeros(1000, dtype=np.float32)
        with mock.patch.object(speech, "_try_once", return_value=audio_data) as m:
            result, sr = speech.synthesize("Привет", "tv")
        assert result is not None
        call_kwargs = m.call_args
        # version arg is positional index 5
        assert call_kwargs.args[5] == "v1"

    def test_v1_synthesize_returns_audio_sr_tuple(self):
        speech = self._make_speech()
        speech.set_tts_version("v1")
        audio_data = np.zeros(1000, dtype=np.float32)
        with mock.patch.object(speech, "_try_once", return_value=audio_data):
            result, sr = speech.synthesize("Привет", "tv")
        assert result is not None
        assert sr > 0

    def test_v1_neutral_retry_on_emotion_failure(self):
        """Дефолты персон теперь все neutral (премиальные голоса) — non-neutral
        эмоция приходит только через пользовательский оверрайд; retry живёт для неё."""
        speech = self._make_speech()
        speech.set_tts_version("v1")
        speech.set_overrides({"hype": {"voice": "jane", "emotion": "evil"}})
        # First call (with emotion) fails, second call (neutral) succeeds
        audio_data = np.zeros(100, dtype=np.float32)
        call_count = [0]

        def try_once_side(text, voice, emotion, speed, sr, version):
            call_count[0] += 1
            if call_count[0] == 1:
                return None  # fail with emotion
            return audio_data  # succeed with neutral

        with mock.patch.object(speech, "_try_once", side_effect=try_once_side):
            result, sr = speech.synthesize("Привет", "hype")
        assert result is not None
        assert call_count[0] == 2


# ---------------------------------------------------------------------------
# v3 path
# ---------------------------------------------------------------------------

class TestV3Path:
    def _make_speech(self):
        from yandex_ai.speech import YandexSpeech
        client = mock.MagicMock()
        client.folder_id = "folder"
        return YandexSpeech(client)

    def test_v3_path_called_when_version_v3(self):
        speech = self._make_speech()
        speech.set_tts_version("v3")
        audio_data = np.zeros(1000, dtype=np.float32)
        with mock.patch.object(speech, "_try_once", return_value=audio_data) as m:
            result, sr = speech.synthesize("Привет", "tv")
        call_kwargs = m.call_args
        assert call_kwargs.args[5] == "v3"

    def test_v3_returns_audio_on_success(self):
        speech = self._make_speech()
        speech.set_tts_version("v3")
        audio_data = np.ones(500, dtype=np.float32)
        with mock.patch.object(speech, "_try_once", return_value=audio_data):
            result, sr = speech.synthesize("Тест", "tv")
        assert result is not None
        assert len(result) == 500


# ---------------------------------------------------------------------------
# v3 → v1 fallback
# ---------------------------------------------------------------------------

class TestV3Fallback:
    def _make_speech(self):
        from yandex_ai.speech import YandexSpeech
        client = mock.MagicMock()
        client.folder_id = "folder"
        return YandexSpeech(client)

    def test_falls_back_to_v1_when_v3_fails(self):
        speech = self._make_speech()
        speech.set_tts_version("v3")
        audio_data = np.zeros(800, dtype=np.float32)
        call_versions = []

        def try_once_side(text, voice, emotion, speed, sr, version):
            call_versions.append(version)
            if version == "v3":
                return None  # v3 fails
            return audio_data  # v1 succeeds

        with mock.patch.object(speech, "_try_once", side_effect=try_once_side):
            result, sr = speech.synthesize("Привет", "tv")

        assert result is not None
        assert "v3" in call_versions
        assert "v1" in call_versions

    def test_logs_warning_on_v3_fallback(self, caplog):
        import logging
        speech = self._make_speech()
        speech.set_tts_version("v3")
        audio_data = np.zeros(100, dtype=np.float32)

        def try_once_side(text, voice, emotion, speed, sr, version):
            if version == "v3":
                return None
            return audio_data

        with mock.patch.object(speech, "_try_once", side_effect=try_once_side):
            with caplog.at_level(logging.WARNING, logger="yandex_ai.speech"):
                speech.synthesize("Привет", "tv")

        assert any("v3" in r.message and "fall" in r.message for r in caplog.records)

    def test_returns_none_when_both_v3_and_v1_fail(self):
        speech = self._make_speech()
        speech.set_tts_version("v3")
        with mock.patch.object(speech, "_try_once", return_value=None):
            result, sr = speech.synthesize("Привет", "tv")
        assert result is None

    def test_v1_mode_does_not_trigger_v3_fallback(self):
        speech = self._make_speech()
        speech.set_tts_version("v1")
        audio_data = np.zeros(100, dtype=np.float32)
        call_versions = []

        def try_once_side(text, voice, emotion, speed, sr, version):
            call_versions.append(version)
            if version == "v1":
                return audio_data
            return None

        with mock.patch.object(speech, "_try_once", side_effect=try_once_side):
            speech.synthesize("Привет", "tv")

        assert "v3" not in call_versions


# ---------------------------------------------------------------------------
# v1 premium-voice remap (_V1_VOICE_FALLBACK in yandex_ai/speech.py)
# ---------------------------------------------------------------------------

class TestV1PremiumVoiceRemap:
    """Premium neuro voices 400 on v1 (live probe 2026-07-01) — _try_once remaps
    them to a legacy equivalent whenever it actually dispatches to v1, whether
    that's the v3->v1 fallback or v1 selected directly. These tests exercise the
    real _try_once/_asynthesize_v1/_asynthesize_v3 dispatch (client-level mocks),
    not a mocked _try_once, since the remap lives inside _try_once itself."""

    def _client(self):
        from yandex_ai.client import YandexClient
        from yandex_ai.credentials import Credentials
        return YandexClient(Credentials("k", "fld"))

    def test_v3_fallback_remaps_premium_voice_to_legacy_and_forces_neutral(self, monkeypatch):
        from yandex_ai.speech import YandexSpeech
        cl = self._client(); cl.start()
        try:
            captured = {}

            async def fake_json_raw(url, payload, **kw):
                return b""  # v3 "fails" (empty response -> _asynthesize_v3 returns None)

            async def fake_form(url, data, **kw):
                captured["data"] = data
                return np.array([1, 2], dtype="<i2").tobytes()

            monkeypatch.setattr(cl, "post_json_raw", fake_json_raw)
            monkeypatch.setattr(cl, "post_form", fake_form)

            sp = YandexSpeech(cl)
            sp.set_tts_version("v3")
            audio, sr = sp.synthesize("текст", "hype")  # hype -> anton (premium)

            assert audio is not None
            assert captured["data"]["voice"] == "ermil"
            assert captured["data"]["emotion"] == "neutral"
        finally:
            cl.stop()

    def test_v1_fallback_leaves_non_premium_voice_unchanged(self, monkeypatch):
        from yandex_ai.speech import YandexSpeech
        cl = self._client(); cl.start()
        try:
            captured = {}

            async def fake_json_raw(url, payload, **kw):
                return b""

            async def fake_form(url, data, **kw):
                captured["data"] = data
                return np.array([1, 2], dtype="<i2").tobytes()

            monkeypatch.setattr(cl, "post_json_raw", fake_json_raw)
            monkeypatch.setattr(cl, "post_form", fake_form)

            sp = YandexSpeech(cl)
            sp.set_tts_version("v3")
            sp.set_overrides({"hype": {"voice": "jane", "emotion": "good"}})
            audio, sr = sp.synthesize("текст", "hype")

            assert audio is not None
            assert captured["data"]["voice"] == "jane"
            assert captured["data"]["emotion"] == "good"
        finally:
            cl.stop()

    def test_direct_v1_mode_remaps_premium_persona_default(self, monkeypatch):
        from yandex_ai.speech import YandexSpeech
        cl = self._client(); cl.start()
        try:
            captured = {}

            async def fake_form(url, data, **kw):
                captured["data"] = data
                return np.array([1, 2], dtype="<i2").tobytes()

            monkeypatch.setattr(cl, "post_form", fake_form)

            sp = YandexSpeech(cl)
            sp.set_tts_version("v1")
            audio, sr = sp.synthesize("текст", "tv")  # tv -> alexander/neutral/1.05 (premium)

            assert audio is not None
            assert captured["data"]["voice"] == "filipp"
            assert captured["data"]["emotion"] == "neutral"
            assert float(captured["data"]["speed"]) == 1.05
        finally:
            cl.stop()

    def test_v1_voice_fallback_dict_covers_every_voice_that_can_be_requested(self):
        """Покрытие считается по ОБОИМ источникам голоса, а не по одному.

        Раньше набор брался только из `DEFAULT_PERSONA_VOICE`, и это работало
        случайно: каждый голос каста заодно был чьим-то дефолтом персоны. Как
        только `marina` перестала быть голосом персоны `calm` (оставшись
        голосом инженера Соколовой), проверка развалилась — и правильно, потому
        что непокрытый премиальный голос на пути v1 означает HTTP 400 и тишину
        вместо реплики. Голоса приезжают в синтез и через оверрайды каста
        (`voice_cast.resolve` -> `Voice.set_voice_overrides`), поэтому в набор
        входят оба."""
        from yandex_ai.speech import _V1_VOICE_FALLBACK
        from yandex_ai import voices
        from core.radio import voice_cast

        in_use = {spec["voice"] for spec in voices.DEFAULT_PERSONA_VOICE.values()}
        in_use.update(voice_cast.SPOTTER_VOICES)
        for character in voice_cast.CHARACTERS.values():
            in_use.update(character.voices)
        premium_voices_in_use = {v for v in in_use if v in voices.PREMIUM_VOICES}

        missing = premium_voices_in_use - set(_V1_VOICE_FALLBACK)
        assert not missing, f"нет отката на v1 для голосов: {sorted(missing)}"
        for legacy_voice in _V1_VOICE_FALLBACK.values():
            assert legacy_voice not in _V1_VOICE_FALLBACK  # target must not itself need remapping
            assert legacy_voice in voices.AVAILABLE_VOICES
            assert "neutral" in voices.AVAILABLE_VOICES[legacy_voice]


# ---------------------------------------------------------------------------
# Voice.set_tts_version (voice/tts.py)
# ---------------------------------------------------------------------------

class TestVoiceSetTtsVersion:
    def _make_voice_with_mock_yandex(self):
        """Build a Voice with a mocked YandexSpeech attached."""
        from voice.tts import Voice
        v = Voice.__new__(Voice)
        v._yandex = mock.MagicMock()
        return v

    def test_delegates_to_yandex_speech(self):
        from voice.tts import Voice
        v = Voice.__new__(Voice)
        mock_yandex = mock.MagicMock()
        v._yandex = mock_yandex
        v.set_tts_version("v3")
        mock_yandex.set_tts_version.assert_called_once_with("v3")

    def test_no_error_when_yandex_not_attached(self):
        from voice.tts import Voice
        v = Voice.__new__(Voice)
        v._yandex = None
        v.set_tts_version("v3")  # must not raise

    def test_no_error_when_yandex_lacks_method(self):
        from voice.tts import Voice
        v = Voice.__new__(Voice)
        v._yandex = object()  # no set_tts_version method
        v.set_tts_version("v3")  # must not raise


# ---------------------------------------------------------------------------
# v3 async synthesis helpers (unit test the base64 parsing logic)
# ---------------------------------------------------------------------------

class TestV3AudioParsing:
    """Test that _asynthesize_v3 correctly parses the NDJSON response."""

    def _make_speech(self):
        from yandex_ai.speech import YandexSpeech
        client = mock.MagicMock()
        client.folder_id = "folder"
        return YandexSpeech(client)

    def test_parses_single_chunk(self):
        import base64, asyncio, json as _json
        speech = self._make_speech()

        pcm = np.array([0, 1000, -1000, 500], dtype="<i2").tobytes()
        b64 = base64.b64encode(pcm).decode()
        response_body = _json.dumps({"result": {"audioChunk": {"data": b64}}}).encode()

        async def fake_post_json(url, payload, **kwargs):
            return response_body

        speech._client.post_json_raw = fake_post_json

        async def run():
            return await speech._asynthesize_v3("Hi", "filipp", 1.0, 48000)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(run())
        finally:
            loop.close()

        assert result is not None
        assert len(result) == 4

    def test_parses_multi_chunk_ndjson(self):
        import base64, asyncio, json as _json
        speech = self._make_speech()

        pcm1 = np.array([100, 200], dtype="<i2").tobytes()
        pcm2 = np.array([300, 400], dtype="<i2").tobytes()
        b64_1 = base64.b64encode(pcm1).decode()
        b64_2 = base64.b64encode(pcm2).decode()
        ndjson = (
            _json.dumps({"result": {"audioChunk": {"data": b64_1}}}) + "\n"
            + _json.dumps({"result": {"audioChunk": {"data": b64_2}}}) + "\n"
        ).encode()

        async def fake_post_json(url, payload, **kwargs):
            return ndjson

        speech._client.post_json_raw = fake_post_json

        async def run():
            return await speech._asynthesize_v3("Hi", "filipp", 1.0, 48000)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(run())
        finally:
            loop.close()

        assert result is not None
        assert len(result) == 4  # 2 samples per chunk × 2 chunks

    def test_payload_has_no_folder_id_and_uses_raw_transport(self):
        """Regression: v3 must call post_json_raw (bytes) — post_json returns a
        parsed dict in production, which the NDJSON parser cannot decode — and must
        NOT send folderId (v3 has no such body field; it triggers HTTP 400)."""
        import base64, asyncio, json as _json
        speech = self._make_speech()

        pcm = np.array([1, 2], dtype="<i2").tobytes()
        body = _json.dumps({"result": {"audioChunk": {"data": base64.b64encode(pcm).decode()}}}).encode()
        captured = {}

        async def fake_raw(url, payload, **kwargs):
            captured["url"] = url
            captured["payload"] = payload
            return body

        speech._client.post_json_raw = fake_raw

        async def run():
            return await speech._asynthesize_v3("Hi", "filipp", 1.0, 48000)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(run())
        finally:
            loop.close()

        assert result is not None
        assert "folderId" not in captured["payload"]

    def test_returns_none_on_empty_response(self):
        import asyncio
        speech = self._make_speech()

        async def fake_post_json(url, payload, **kwargs):
            return b""

        speech._client.post_json_raw = fake_post_json

        async def run():
            return await speech._asynthesize_v3("Hi", "filipp", 1.0, 48000)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(run())
        finally:
            loop.close()

        assert result is None

    def test_v3_sends_role_hint_for_non_neutral_emotion(self):
        """Эмоция персоны не должна теряться на v3-пути: emotion≠neutral → role-хинт."""
        import base64, asyncio, json as _json
        speech = self._make_speech()

        pcm = np.array([1, 2], dtype="<i2").tobytes()
        body = _json.dumps({"result": {"audioChunk": {"data": base64.b64encode(pcm).decode()}}}).encode()
        captured = {}

        async def fake_raw(url, payload, **kwargs):
            captured["payload"] = payload
            return body

        speech._client.post_json_raw = fake_raw

        async def run():
            return await speech._asynthesize_v3("Hi", "dasha", 1.0, 48000, emotion="friendly")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run())
        finally:
            loop.close()

        assert {"role": "friendly"} in captured["payload"]["hints"]

    def test_v3_omits_role_hint_for_neutral(self):
        """neutral — дефолт голоса, role-хинт не шлём (лишний хинт может дать 400)."""
        import base64, asyncio, json as _json
        speech = self._make_speech()

        pcm = np.array([1, 2], dtype="<i2").tobytes()
        body = _json.dumps({"result": {"audioChunk": {"data": base64.b64encode(pcm).decode()}}}).encode()
        captured = {}

        async def fake_raw(url, payload, **kwargs):
            captured["payload"] = payload
            return body

        speech._client.post_json_raw = fake_raw

        async def run():
            return await speech._asynthesize_v3("Hi", "alexander", 1.0, 48000, emotion="neutral")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run())
        finally:
            loop.close()

        assert not any("role" in h for h in captured["payload"]["hints"])


# ---------------------------------------------------------------------------
# engine.apply_settings() validation
# ---------------------------------------------------------------------------

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
        client.grpc_metadata = mock.AsyncMock(return_value=[("authorization", "Api-Key k")])
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


# ---------------------------------------------------------------------------
# Предохранитель v3 (yandex_ai/speech.py)
# ---------------------------------------------------------------------------

class TestV3CircuitBreaker:
    """Проводка предохранителя, а не арифметика счётчика.

    Живой лог гонки: 13 подряд `future timeout (15s)` на v3, и каждая фраза
    платила таймаут заново. Предохранитель обязан прекратить это после
    нескольких неудач — и, как следствие, перестать чередовать премиальный
    голос с легаси-подменой на одном и том же персонаже.
    """

    def _speech(self, outcomes):
        """outcomes — исходы попыток v3 по порядку. v1 всегда молчит, чтобы в
        `calls` были видны только маршруты, а не успехи."""
        from yandex_ai.speech import YandexSpeech

        speech = YandexSpeech(mock.Mock())
        speech.set_tts_version("v3")
        calls: list[str] = []
        pending = list(outcomes)

        def fake_try_once(text, voice, emotion, speed, sr, version):
            calls.append(version)
            if version != "v3":
                return None
            ok = pending.pop(0) if pending else False
            return np.ones(8, dtype=np.float32) if ok else None

        speech._try_once = fake_try_once
        return speech, calls

    def test_v3_is_skipped_entirely_once_the_breaker_opens(self):
        speech, calls = self._speech([False] * 10)

        for _ in range(config.YANDEX_TTS_V3_FAILURE_THRESHOLD):
            speech.synthesize("тест", "engineer")
        assert calls.count("v3") == config.YANDEX_TTS_V3_FAILURE_THRESHOLD

        calls.clear()
        speech.synthesize("тест", "engineer")
        assert "v3" not in calls, "после размыкания v3 не должна пробоваться вовсе"
        assert calls == ["v1"]

    def test_a_success_resets_the_counter_before_it_trips(self):
        """Считаются ПОДРЯД идущие неудачи: одиночные сбои сети не должны
        накапливаться всю гонку и однажды разомкнуть цепь на ровном месте."""
        speech, calls = self._speech([False, False, True, False, False])

        for _ in range(5):
            speech.synthesize("тест", "engineer")

        assert calls.count("v3") == 5, "цепь не должна была разомкнуться"

    def test_the_breaker_closes_again_after_the_cooldown(self, monkeypatch):
        speech, calls = self._speech([False] * 3 + [True])
        for _ in range(config.YANDEX_TTS_V3_FAILURE_THRESHOLD):
            speech.synthesize("тест", "engineer")

        import time as time_mod
        base = time_mod.monotonic()
        monkeypatch.setattr(
            "yandex_ai.speech.time.monotonic",
            lambda: base + config.YANDEX_TTS_V3_BREAKER_COOLDOWN + 1.0)

        calls.clear()
        speech.synthesize("тест", "engineer")
        assert "v3" in calls, "после остывания v3 обязана получить новый шанс"

    def test_while_open_every_phrase_takes_the_same_route(self):
        """Смысл для пользователя: тембр перестаёт скакать. Пофразный откат
        давал одному персонажу то премиальный голос, то легаси-подмену."""
        speech, calls = self._speech([False] * 3)
        for _ in range(config.YANDEX_TTS_V3_FAILURE_THRESHOLD):
            speech.synthesize("тест", "engineer")

        calls.clear()
        for _ in range(6):
            speech.synthesize("тест", "engineer")

        assert set(calls) == {"v1"}, f"маршрут скачет: {calls}"

    def test_reset_clears_a_tripped_breaker(self):
        speech, calls = self._speech([False] * 3)
        for _ in range(config.YANDEX_TTS_V3_FAILURE_THRESHOLD):
            speech.synthesize("тест", "engineer")

        speech.reset_v3_breaker()
        calls.clear()
        speech.synthesize("тест", "engineer")
        assert "v3" in calls
