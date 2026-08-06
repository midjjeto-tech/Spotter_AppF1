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
