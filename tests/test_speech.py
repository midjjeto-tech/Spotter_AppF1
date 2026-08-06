import numpy as np

from yandex_ai.client import YandexClient
from yandex_ai.credentials import Credentials
from yandex_ai.speech import YandexSpeech


def _client():
    return YandexClient(Credentials("k", "fld"))


def test_asynthesize_lpcm_to_float(monkeypatch):
    cl = _client(); cl.start()
    try:
        # два сэмпла: 0 и 32767 (макс. int16)
        raw = np.array([0, 32767], dtype="<i2").tobytes()
        captured = {}

        async def fake_form(url, data, **kw):
            captured["url"] = url
            captured["data"] = data
            return raw

        monkeypatch.setattr(cl, "post_form", fake_form)
        sp = YandexSpeech(cl)
        pcm = cl.submit(sp.asynthesize("привет", "filipp", "neutral", 1.0)).result(timeout=3)
        assert pcm.dtype == np.float32
        assert pcm.shape == (2,)
        assert abs(pcm[1] - 0.99997) < 1e-3
        assert captured["data"]["voice"] == "filipp"
        assert captured["data"]["format"] == "lpcm"
        assert captured["data"]["folderId"] == "fld"
    finally:
        cl.stop()


def test_synthesize_persona_resolves_voice(monkeypatch):
    cl = _client(); cl.start()
    try:
        raw = np.array([100, -100], dtype="<i2").tobytes()
        captured = {}

        async def fake_form(url, data, **kw):
            captured["data"] = data
            return raw

        monkeypatch.setattr(cl, "post_form", fake_form)
        sp = YandexSpeech(cl)
        audio, sr = sp.synthesize("текст", "hype")  # hype -> anton/neutral/1.15; v1 wire remaps anton -> ermil
        assert sr == 48000
        assert audio is not None
        assert captured["data"]["voice"] == "ermil"  # remapped from anton (premium, v1-unsupported)
        assert captured["data"]["emotion"] == "neutral"
        assert float(captured["data"]["speed"]) == 1.15
    finally:
        cl.stop()


def test_synthesize_error_returns_none(monkeypatch):
    cl = _client(); cl.start()
    try:
        async def boom(*a, **k):
            raise RuntimeError("tts down")
        monkeypatch.setattr(cl, "post_form", boom)
        sp = YandexSpeech(cl)
        audio, sr = sp.synthesize("x", "tv")
        assert audio is None and sr == 48000
    finally:
        cl.stop()
