"""GigaChatProvider: тот же контракт, что commentator.ai_provider.AIProvider.

SDK-клиент замокан (сеть не дёргается), но payload собирается настоящими
моделями gigachat.models.Chat/Messages — заодно проверяем, что форма запроса
валидна для реального SDK.
"""
import config
import gigachat

from gigachat_ai.credentials import GigaChatCredentials
from gigachat_ai.provider import GigaChatProvider


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


def _fake_giga(reply="", exc=None, capture=None):
    """Фабрика фейкового GigaChat-клиента для monkeypatch."""
    class _FakeGiga:
        def __init__(self, **kwargs):
            if capture is not None:
                capture.update(kwargs)

        def chat(self, payload):
            if capture is not None:
                capture["payload"] = payload
            if exc is not None:
                raise exc
            return _Resp(reply)

    return _FakeGiga


def test_unavailable_without_credentials():
    p = GigaChatProvider(None)
    assert p.available is False
    assert p.generate("ctx", "tv") is None
    assert p.generate_with_system("SYS", "USER") is None


def test_generate_returns_sanitized_phrase(monkeypatch):
    monkeypatch.setattr(gigachat, "GigaChat",
                        _fake_giga(reply='  "Ферстаппен атакует!"  '))
    p = GigaChatProvider(GigaChatCredentials("key"))
    assert p.available is True
    # _sanitize должен снять кавычки/пробелы
    assert p.generate("ctx", "tv") == "Ферстаппен атакует!"


def test_generate_empty_is_silence_not_error(monkeypatch):
    monkeypatch.setattr(gigachat, "GigaChat", _fake_giga(reply=""))
    p = GigaChatProvider(GigaChatCredentials("key"))
    # пустой ответ = осознанное молчание ('' ), НЕ None
    assert p.generate("ctx", "tv") == ""


def test_generate_none_on_network_error(monkeypatch):
    monkeypatch.setattr(gigachat, "GigaChat",
                        _fake_giga(exc=RuntimeError("network down")))
    p = GigaChatProvider(GigaChatCredentials("key"))
    assert p.generate("ctx", "tv") is None


def test_generate_with_system_builds_system_then_user(monkeypatch):
    capture = {}
    monkeypatch.setattr(gigachat, "GigaChat",
                        _fake_giga(reply="ok", capture=capture))
    p = GigaChatProvider(GigaChatCredentials("key"))
    assert p.generate_with_system("MY_SYSTEM", "USER_MSG") == "ok"
    payload = capture["payload"]
    assert payload.messages[0].content == "MY_SYSTEM"
    assert payload.messages[1].content == "USER_MSG"


def test_validate_success(monkeypatch):
    monkeypatch.setattr(gigachat, "GigaChat", _fake_giga(reply="ok"))
    p = GigaChatProvider(GigaChatCredentials("key"))
    ok, code, _ = p.validate()
    assert ok is True and code == "OK"


def test_validate_no_client_is_no_key():
    p = GigaChatProvider(None)
    ok, code, _ = p.validate()
    assert ok is False and code == "GIGACHAT_NO_KEY"


def test_validate_bad_key_400_is_cred_invalid(monkeypatch):
    # Sber отдаёт 400 «Can't decode Authorization header» на битый ключ —
    # это про КЛЮЧ, а не про сеть.
    exc = RuntimeError("400 https://ngw.devices.sberbank.ru:9443/api/v2/oauth: "
                       "Can't decode 'Authorization' header")
    monkeypatch.setattr(gigachat, "GigaChat", _fake_giga(exc=exc))
    p = GigaChatProvider(GigaChatCredentials("bad"))
    ok, code, _ = p.validate()
    assert ok is False and code == "GIGACHAT_CRED_INVALID"


def test_validate_401_is_cred_invalid(monkeypatch):
    monkeypatch.setattr(gigachat, "GigaChat",
                        _fake_giga(exc=RuntimeError("401 Unauthorized")))
    p = GigaChatProvider(GigaChatCredentials("bad"))
    ok, code, _ = p.validate()
    assert ok is False and code == "GIGACHAT_CRED_INVALID"


def test_validate_real_network_error_is_network(monkeypatch):
    # таймаут/отказ соединения — без HTTP-статуса и упоминания авторизации
    monkeypatch.setattr(gigachat, "GigaChat",
                        _fake_giga(exc=RuntimeError("Connection timed out")))
    p = GigaChatProvider(GigaChatCredentials("key"))
    ok, code, _ = p.validate()
    assert ok is False and code == "GIGACHAT_NETWORK_ERROR"


def test_sdk_missing_reported_distinctly(monkeypatch):
    # Симулируем отсутствие пакета: from gigachat import GigaChat -> ImportError.
    # Это ровно кейс «приложение запущено Python без gigachat» (диагноз 07-25).
    monkeypatch.delattr(gigachat, "GigaChat", raising=False)
    p = GigaChatProvider(GigaChatCredentials("key"))
    assert p.available is False
    ok, code, msg = p.validate()
    assert ok is False
    assert code == "GIGACHAT_SDK_MISSING"


def test_ca_bundle_enables_strict_tls(monkeypatch):
    # Есть бандл Минцифры -> строгая проверка TLS с ним.
    cap = {}
    monkeypatch.setattr(gigachat, "GigaChat", _fake_giga(reply="ok", capture=cap))
    monkeypatch.setattr(config, "GIGACHAT_CA_BUNDLE", "/path/to/bundle.pem")
    GigaChatProvider(GigaChatCredentials("key"))
    assert cap.get("verify_ssl_certs") is True
    assert cap.get("ca_bundle_file") == "/path/to/bundle.pem"


def test_no_ca_bundle_uses_dev_verify_flag(monkeypatch):
    # Нет бандла -> dev-режим по GIGACHAT_VERIFY_SSL, ca_bundle_file не передаётся.
    cap = {}
    monkeypatch.setattr(gigachat, "GigaChat", _fake_giga(reply="ok", capture=cap))
    monkeypatch.setattr(config, "GIGACHAT_CA_BUNDLE", "")
    monkeypatch.setattr(config, "GIGACHAT_VERIFY_SSL", False)
    GigaChatProvider(GigaChatCredentials("key"))
    assert cap.get("verify_ssl_certs") is False
    assert "ca_bundle_file" not in cap


def test_init_passes_key_scope_model(monkeypatch):
    capture = {}
    monkeypatch.setattr(gigachat, "GigaChat",
                        _fake_giga(reply="ok", capture=capture))
    creds = GigaChatCredentials("mykey", scope="GIGACHAT_API_PERS")
    GigaChatProvider(creds, model="GigaChat")
    assert capture.get("credentials") == "mykey"
    assert capture.get("scope") == "GIGACHAT_API_PERS"
    assert capture.get("model") == "GigaChat"
