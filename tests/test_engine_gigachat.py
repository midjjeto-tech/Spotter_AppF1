"""Движок выбирает «мозг» по config.LLM_PROVIDER (голос всегда Yandex).

Yandex-клиент замокан в None (yc.load -> None) — TTS не поднимается; SDK GigaChat
замокан, сеть не дёргается.
"""
import config
import core.engine as eng_mod
from core.engine import F1Engine
from gigachat_ai.credentials import GigaChatCredentials


def _fake_gigachat(monkeypatch):
    import gigachat

    class _Msg:
        def __init__(self, c):
            self.content = c

    class _Choice:
        def __init__(self, c):
            self.message = _Msg(c)

    class _Resp:
        def __init__(self, c):
            self.choices = [_Choice(c)]

    class _FakeGiga:
        def __init__(self, **kw):
            pass

        def chat(self, payload):
            return _Resp("ok")

    monkeypatch.setattr(gigachat, "GigaChat", _FakeGiga)


def test_engine_uses_gigachat_when_flag_set(monkeypatch):
    _fake_gigachat(monkeypatch)
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)   # Yandex-клиент не поднимаем
    import gigachat_ai.credentials as gc
    monkeypatch.setattr(gc, "load", lambda: GigaChatCredentials("key"))
    monkeypatch.setattr(config, "LLM_PROVIDER", "gigachat")

    e = F1Engine({})
    assert type(e.ai).__name__ == "GigaChatProvider"
    assert e.ai.available is True
    assert e.get_state()["llm_engine"] == "GigaChat"


def test_engine_gigachat_without_creds_falls_back_to_templates(monkeypatch):
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    import gigachat_ai.credentials as gc
    monkeypatch.setattr(gc, "load", lambda: None)           # ключ не задан
    monkeypatch.setattr(config, "LLM_PROVIDER", "gigachat")

    e = F1Engine({})
    assert type(e.ai).__name__ == "GigaChatProvider"
    assert e.ai.available is False
    assert e.get_state()["llm_engine"] == "Шаблоны"


def test_engine_default_provider_is_yandex(monkeypatch):
    # дефолт (yandex) — без креденшелов мозг = Шаблоны, как раньше
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    monkeypatch.setattr(config, "LLM_PROVIDER", "yandex")
    e = F1Engine({})
    assert type(e.ai).__name__ == "AIProvider"
    assert e.get_state()["llm_engine"] == "Шаблоны"


def test_apply_gigachat_credentials_success_switches_brain(monkeypatch, tmp_path):
    """BYOK: валидный ключ в gigachat-режиме → сохраняется, мозг = GigaChat."""
    _fake_gigachat(monkeypatch)                      # chat() -> "ok" (валидно)
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    monkeypatch.setattr(config, "LLM_PROVIDER", "gigachat")
    monkeypatch.setattr(config, "GIGACHAT_CREDS_FILE", str(tmp_path / "gc.json"))

    e = F1Engine({})
    assert e.ai.available is False                   # ключа ещё нет
    ok, code, msg = e.apply_gigachat_credentials("some-auth-key")
    assert ok is True and code == "OK"
    assert type(e.ai).__name__ == "GigaChatProvider"
    assert e.ai.available is True
    assert (tmp_path / "gc.json").exists()            # сохранён (шифрованно)

    st = e.gigachat_status()
    assert st["connected"] is True
    assert st["active"] is True
    assert st["masked_key"]                           # непустая маска


def test_apply_gigachat_credentials_invalid_not_saved(monkeypatch, tmp_path):
    """Неверный ключ (401) → GIGACHAT_CRED_INVALID, файл не создаётся."""
    import gigachat

    class _FakeGiga401:
        def __init__(self, **kw):
            pass

        def chat(self, payload):
            raise RuntimeError("HTTP 401 Unauthorized")

    monkeypatch.setattr(gigachat, "GigaChat", _FakeGiga401)
    monkeypatch.setattr(eng_mod.yc, "load", lambda: None)
    monkeypatch.setattr(config, "GIGACHAT_CREDS_FILE", str(tmp_path / "gc.json"))

    e = F1Engine({})
    ok, code, msg = e.apply_gigachat_credentials("bad-key")
    assert ok is False
    assert code == "GIGACHAT_CRED_INVALID"
    assert not (tmp_path / "gc.json").exists()
