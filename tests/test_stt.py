from yandex_ai.client import YandexClient
from yandex_ai.credentials import Credentials
from yandex_ai.stt import YandexSTT


def _client():
    return YandexClient(Credentials("k", "fld"))


def test_recognize_parses_result_text(monkeypatch):
    cl = _client(); cl.start()
    try:
        captured = {}

        async def fake_post_audio(url, audio, params, **kw):
            captured["url"] = url
            captured["audio"] = audio
            captured["params"] = params
            return '{"result": "какой у меня круг"}'.encode("utf-8")

        monkeypatch.setattr(cl, "post_audio", fake_post_audio)
        stt = YandexSTT(cl)
        text = stt.recognize(b"\x00\x00", sr=48000)
        assert text == "какой у меня круг"
        assert captured["params"]["lang"] == "ru-RU"
        assert captured["params"]["format"] == "lpcm"
        assert captured["params"]["sampleRateHertz"] == "48000"
        assert captured["params"]["folderId"] == "fld"
    finally:
        cl.stop()


def test_recognize_empty_result_returns_none(monkeypatch):
    cl = _client(); cl.start()
    try:
        async def fake_post_audio(*a, **k):
            return b'{"result": ""}'
        monkeypatch.setattr(cl, "post_audio", fake_post_audio)
        stt = YandexSTT(cl)
        assert stt.recognize(b"\x00\x00") is None
    finally:
        cl.stop()


def test_recognize_exception_returns_none(monkeypatch):
    cl = _client(); cl.start()
    try:
        async def boom(*a, **k):
            raise RuntimeError("stt down")
        monkeypatch.setattr(cl, "post_audio", boom)
        stt = YandexSTT(cl)
        assert stt.recognize(b"\x00\x00") is None
    finally:
        cl.stop()


def test_recognize_empty_audio_returns_none():
    stt = YandexSTT(_client())
    assert stt.recognize(b"") is None
