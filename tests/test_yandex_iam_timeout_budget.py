"""tests/test_yandex_iam_timeout_budget.py — _try_once's fut.result() timeout
budget must account for a possible IAM token exchange happening INSIDE the
submitted coroutine (auth_mode="iam") before the request itself even starts.
Without this margin, a slow-network IAM refresh could spuriously time out
_try_once while the coroutine keeps running to completion in the background."""
import unittest.mock as mock

import numpy as np
import pytest

import config
from yandex_ai.speech import YandexSpeech


class _FakeFuture:
    def __init__(self, result):
        self._result = result
        self.captured_timeout = None

    def result(self, timeout=None):
        self.captured_timeout = timeout
        return self._result


def _make_speech(iam_refresh_active: bool):
    client = mock.MagicMock()
    client.folder_id = "folder"
    client.iam_refresh_active = iam_refresh_active
    fut = _FakeFuture(np.zeros(4, dtype=np.float32))

    def submit(coro):
        # This unit test owns no event loop. A real YandexClient schedules the
        # coroutine; the fake must explicitly release the object it accepts.
        coro.close()
        return fut

    client.submit.side_effect = submit
    return YandexSpeech(client), fut


@pytest.mark.parametrize("version,base_timeout", [
    ("v1", config.YANDEX_TTS_TOTAL_TIMEOUT),
    ("v3", config.YANDEX_TTS_V3_TOTAL_TIMEOUT),
    ("v3-grpc", config.YANDEX_TTS_GRPC_TIMEOUT),
])
def test_timeout_includes_iam_margin_when_iam_active(version, base_timeout):
    speech, fut = _make_speech(iam_refresh_active=True)
    speech._try_once("hi", "filipp", "neutral", 1.0, 48000, version)
    assert fut.captured_timeout == pytest.approx(
        base_timeout + 1.0 + config.YANDEX_IAM_TOTAL_TIMEOUT)


@pytest.mark.parametrize("version,base_timeout", [
    ("v1", config.YANDEX_TTS_TOTAL_TIMEOUT),
    ("v3", config.YANDEX_TTS_V3_TOTAL_TIMEOUT),
    ("v3-grpc", config.YANDEX_TTS_GRPC_TIMEOUT),
])
def test_timeout_excludes_iam_margin_when_api_key(version, base_timeout):
    speech, fut = _make_speech(iam_refresh_active=False)
    speech._try_once("hi", "filipp", "neutral", 1.0, 48000, version)
    assert fut.captured_timeout == pytest.approx(base_timeout + 1.0)
