"""tests/test_iam_token.py — IamTokenManager: OAuth->IAM exchange + caching/refresh."""
import asyncio

import config
from yandex_ai.iam_token import IamTokenManager


class _FakeCtx:
    def __init__(self, token: str):
        self._token = token

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    async def json(self):
        return {"iamToken": self._token, "expiresAt": "2099-01-01T00:00:00.123456789Z"}


class _FakeSession:
    def __init__(self, tokens):
        self._tokens = iter(tokens)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return _FakeCtx(next(self._tokens))


def test_get_token_exchanges_oauth_for_iam():
    session = _FakeSession(["iam-token-1"])
    mgr = IamTokenManager()
    token = asyncio.run(mgr.get_token(session, "oauth-abc"))
    assert token == "iam-token-1"
    assert len(session.calls) == 1
    assert session.calls[0]["url"] == config.YANDEX_IAM_URL
    assert session.calls[0]["json"] == {"yandexPassportOauthToken": "oauth-abc"}


def test_get_token_returns_cached_token_before_expiry():
    session = _FakeSession(["iam-token-1", "iam-token-2"])
    mgr = IamTokenManager()

    async def _twice():
        first = await mgr.get_token(session, "oauth-abc")
        second = await mgr.get_token(session, "oauth-abc")
        return first, second

    first, second = asyncio.run(_twice())
    assert first == second == "iam-token-1"
    assert len(session.calls) == 1


def test_get_token_refreshes_after_conservative_ttl_elapses(monkeypatch):
    session = _FakeSession(["iam-token-1", "iam-token-2"])
    mgr = IamTokenManager()

    fake_now = [1000.0]
    monkeypatch.setattr("yandex_ai.iam_token.time.monotonic", lambda: fake_now[0])

    async def _refresh_cycle():
        first = await mgr.get_token(session, "oauth-abc")
        fake_now[0] += config.YANDEX_IAM_REFRESH_INTERVAL_SEC + 1.0
        second = await mgr.get_token(session, "oauth-abc")
        return first, second

    first, second = asyncio.run(_refresh_cycle())
    assert first == "iam-token-1"
    assert second == "iam-token-2"
    assert len(session.calls) == 2


def test_concurrent_get_token_only_exchanges_once():
    session = _FakeSession(["iam-token-1", "iam-token-2"])
    mgr = IamTokenManager()

    async def _concurrent():
        return await asyncio.gather(
            mgr.get_token(session, "oauth-abc"),
            mgr.get_token(session, "oauth-abc"),
        )

    results = asyncio.run(_concurrent())
    assert results == ["iam-token-1", "iam-token-1"]
    assert len(session.calls) == 1
