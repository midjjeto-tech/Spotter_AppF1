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
    client.start()
    try:
        metadata = client.submit(client.grpc_metadata()).result(timeout=2)
        assert metadata == [("authorization", "Api-Key my-key")]
    finally:
        client.stop()


def test_stop_closes_grpc_channel_without_raising():
    client = YandexClient(Credentials("k", "f"))
    client.start()
    client.stop()   # must not raise even though the channel is now closed
