import sys

import pytest

from yandex_ai import credentials as c
from yandex_ai.credentials import Credentials


def test_auth_header_api_key():
    creds = Credentials(api_key="AQVN123", folder_id="fld", auth_mode="api_key")
    assert c.auth_header(creds) == {"Authorization": "Api-Key AQVN123"}


def test_auth_header_iam():
    creds = Credentials(api_key="t0ken", folder_id="fld", auth_mode="iam")
    assert c.auth_header(creds) == {"Authorization": "Bearer t0ken"}


def test_mask():
    assert c.mask("ABCDEFGH").endswith("EFGH")
    assert c.mask("ABCDEFGH").count("•") == 4
    assert c.mask("") == ""


def test_save_load_roundtrip(tmp_creds):
    creds = Credentials(api_key="secret-key-1234", folder_id="b1gfolder", auth_mode="api_key")
    c.save(creds)
    loaded = c.load()
    assert loaded is not None
    assert loaded.api_key == "secret-key-1234"
    assert loaded.folder_id == "b1gfolder"
    assert loaded.auth_mode == "api_key"


def test_load_missing_returns_none(tmp_creds):
    assert c.load() is None


def test_clear(tmp_creds):
    c.save(Credentials("k", "f"))
    c.clear()
    assert c.load() is None


def test_plaintext_fallback_when_dpapi_unavailable(tmp_creds, monkeypatch):
    monkeypatch.setattr(c, "dpapi_encrypt", lambda s: None)
    c.save(Credentials("plainkey", "fld"))
    import json
    with open(tmp_creds, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["encrypted"] is False
    assert raw["api_key"] == "plainkey"
    # читается даже без DPAPI
    loaded = c.load()
    assert loaded.api_key == "plainkey"


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI только Windows")
def test_dpapi_roundtrip_windows():
    enc = c.dpapi_encrypt("super-secret")
    assert enc is not None and enc != "super-secret"
    assert c.dpapi_decrypt(enc) == "super-secret"
