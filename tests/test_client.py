import aiohttp
import pytest

from yandex_ai.client import YandexClient
from yandex_ai.credentials import Credentials


def _client():
    return YandexClient(Credentials("k", "fld", "api_key"))


def test_submit_runs_coroutine():
    cl = _client()
    cl.start()
    try:
        async def add():
            return 40 + 2
        assert cl.submit(add()).result(timeout=3) == 42
    finally:
        cl.stop()


def test_headers_include_auth():
    cl = _client()
    cl.start()
    try:
        h = cl.submit(cl.headers({"X-Test": "1"})).result(timeout=2)
        assert h["Authorization"] == "Api-Key k"
        assert h["X-Test"] == "1"
    finally:
        cl.stop()


def test_validate_invalid_key(monkeypatch):
    cl = _client()
    cl.start()
    try:
        req = aiohttp.RequestInfo(url="http://x", method="POST",
                                  headers=aiohttp.typedefs.CIMultiDict(), real_url="http://x")

        async def boom(*a, **k):
            raise aiohttp.ClientResponseError(req, (), status=401)

        monkeypatch.setattr(cl, "post_json", boom)
        ok, code, _ = cl.submit(cl.validate()).result(timeout=4)
        assert ok is False and code == "YANDEX_CRED_INVALID"
    finally:
        cl.stop()


def test_validate_network_error(monkeypatch):
    cl = _client()
    cl.start()
    try:
        async def boom(*a, **k):
            raise aiohttp.ClientConnectionError("dns")

        monkeypatch.setattr(cl, "post_json", boom)
        ok, code, _ = cl.submit(cl.validate()).result(timeout=4)
        assert ok is False and code == "YANDEX_NETWORK_ERROR"
    finally:
        cl.stop()


def test_validate_success(monkeypatch):
    cl = _client()
    cl.start()
    try:
        async def fake_json(*a, **k):
            return {"result": {"alternatives": [{"message": {"text": "ок"}}]}}

        async def fake_form(*a, **k):
            return b"\x00\x00\x01\x00"

        monkeypatch.setattr(cl, "post_json", fake_json)
        monkeypatch.setattr(cl, "post_form", fake_form)
        ok, code, _ = cl.submit(cl.validate()).result(timeout=4)
        assert ok is True and code == "OK"
    finally:
        cl.stop()


def test_validate_rate_limit(monkeypatch):
    cl = _client()
    cl.start()
    try:
        req = aiohttp.RequestInfo(url="http://x", method="POST",
                                  headers=aiohttp.typedefs.CIMultiDict(), real_url="http://x")

        async def boom(*a, **k):
            raise aiohttp.ClientResponseError(req, (), status=429)

        monkeypatch.setattr(cl, "post_json", boom)
        ok, code, _ = cl.submit(cl.validate()).result(timeout=4)
        assert ok is False and code == "YANDEX_RATE_LIMIT"
    finally:
        cl.stop()


def test_validate_gpt_empty_is_invalid(monkeypatch):
    cl = _client()
    cl.start()
    try:
        async def empty_json(*a, **k):
            return {"result": {"alternatives": []}}

        monkeypatch.setattr(cl, "post_json", empty_json)
        ok, code, _ = cl.submit(cl.validate()).result(timeout=4)
        assert ok is False and code == "YANDEX_CRED_INVALID"
    finally:
        cl.stop()


def test_validate_tts_error_after_gpt_ok(monkeypatch):
    cl = _client()
    cl.start()
    try:
        async def fake_json(*a, **k):
            return {"result": {"alternatives": [{"message": {"text": "ок"}}]}}

        async def tts_boom(*a, **k):
            raise aiohttp.ClientConnectionError("tts down")

        monkeypatch.setattr(cl, "post_json", fake_json)
        monkeypatch.setattr(cl, "post_form", tts_boom)
        ok, code, _ = cl.submit(cl.validate()).result(timeout=4)
        assert ok is False and code == "YANDEX_TTS_ERROR"
    finally:
        cl.stop()


def test_iam_refresh_active_true_for_iam_mode():
    cl = YandexClient(Credentials("oauth-token", "fld", auth_mode="iam"))
    assert cl.iam_refresh_active is True


def test_iam_refresh_active_false_for_api_key_mode():
    cl = YandexClient(Credentials("k", "fld", auth_mode="api_key"))
    assert cl.iam_refresh_active is False


def test_headers_iam_mode_uses_iam_token_manager():
    """auth_mode="iam": api_key is an OAuth token, headers() must carry a
    Bearer IAM token obtained via IamTokenManager, not the raw OAuth token."""
    class _FakeCtx:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            return False
        def raise_for_status(self):
            pass
        async def json(self):
            return {"iamToken": "exchanged-iam-token"}

    class _FakeSession:
        def post(self, url, **kwargs):
            return _FakeCtx()

    cl = YandexClient(Credentials("oauth-token", "fld", auth_mode="iam"))
    cl.start()
    try:
        cl._session = _FakeSession()
        h = cl.submit(cl.headers()).result(timeout=2)
        assert h["Authorization"] == "Bearer exchanged-iam-token"
    finally:
        cl.stop()


def test_grpc_metadata_iam_mode_uses_iam_token_manager():
    class _FakeCtx:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            return False
        def raise_for_status(self):
            pass
        async def json(self):
            return {"iamToken": "exchanged-iam-token"}

    class _FakeSession:
        def post(self, url, **kwargs):
            return _FakeCtx()

    cl = YandexClient(Credentials("oauth-token", "fld", auth_mode="iam"))
    cl.start()
    try:
        cl._session = _FakeSession()
        metadata = cl.submit(cl.grpc_metadata()).result(timeout=2)
        assert metadata == [("authorization", "Bearer exchanged-iam-token")]
    finally:
        cl.stop()


def test_post_audio_sends_raw_body_and_query_params():
    cl = _client()
    cl.start()
    try:
        class _FakeCtx:
            def __init__(self, data: bytes):
                self._data = data
            async def __aenter__(self):
                return self
            async def __aexit__(self, *exc):
                return False
            def raise_for_status(self):
                pass
            async def read(self):
                return self._data

        class _FakeSession:
            def __init__(self, data: bytes):
                self._data = data
                self.last_call = None
            def post(self, url, **kwargs):
                self.last_call = {"url": url, **kwargs}
                return _FakeCtx(self._data)

        fake = _FakeSession(b"\x01\x02")
        cl._session = fake
        raw = cl.submit(cl.post_audio(
            "http://x/stt", b"\x00\x00", {"lang": "ru-RU"},
            connect=1.0, total=2.0,
        )).result(timeout=3)
        assert raw == b"\x01\x02"
        assert fake.last_call["url"] == "http://x/stt"
        assert fake.last_call["params"] == {"lang": "ru-RU"}
        assert fake.last_call["data"] == b"\x00\x00"
    finally:
        cl.stop()
