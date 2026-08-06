import pytest

from yandex_ai.client import YandexClient
from yandex_ai.credentials import Credentials
from yandex_ai.gpt import YandexGPT


def _client():
    return YandexClient(Credentials("k", "fld"))


def test_acomplete_parses_text(monkeypatch):
    cl = _client(); cl.start()
    try:
        captured = {}

        async def fake_json(url, payload, **kw):
            captured["url"] = url
            captured["payload"] = payload
            return {"result": {"alternatives": [{"message": {"text": "  Поехали!  "}}]}}

        monkeypatch.setattr(cl, "post_json", fake_json)
        gpt = YandexGPT(cl)
        txt = cl.submit(gpt.acomplete("sys", "user")).result(timeout=3)
        assert txt == "Поехали!"
        assert captured["payload"]["modelUri"] == "gpt://fld/yandexgpt/latest"
        roles = [m["role"] for m in captured["payload"]["messages"]]
        assert roles == ["system", "user"]
    finally:
        cl.stop()


def test_acomplete_empty_alternatives_returns_none(monkeypatch):
    cl = _client(); cl.start()
    try:
        async def fake_json(*a, **k):
            return {"result": {"alternatives": []}}
        monkeypatch.setattr(cl, "post_json", fake_json)
        gpt = YandexGPT(cl)
        assert cl.submit(gpt.acomplete("s", "u")).result(timeout=3) is None
    finally:
        cl.stop()


def test_generate_swallows_errors(monkeypatch):
    cl = _client(); cl.start()
    try:
        async def boom(*a, **k):
            raise RuntimeError("net down")
        monkeypatch.setattr(cl, "post_json", boom)
        gpt = YandexGPT(cl)
        # сбой сети → None (brain уходит в шаблоны), не исключение
        assert gpt.generate("контекст гонки", "tv") is None
    finally:
        cl.stop()


def test_generate_returns_phrase(monkeypatch):
    cl = _client(); cl.start()
    try:
        async def fake_json(*a, **k):
            return {"result": {"alternatives": [{"message": {"text": "Обгон!"}}]}}
        monkeypatch.setattr(cl, "post_json", fake_json)
        gpt = YandexGPT(cl)
        assert gpt.generate("контекст", "tv") == "Обгон!"
    finally:
        cl.stop()


def test_generate_empty_is_silence_not_error(monkeypatch):
    """Пустой ответ модели = осознанное молчание ('' ), а не сбой (None)."""
    cl = _client(); cl.start()
    try:
        async def fake_json(*a, **k):
            return {"result": {"alternatives": [{"message": {"text": "   "}}]}}
        monkeypatch.setattr(cl, "post_json", fake_json)
        gpt = YandexGPT(cl)
        assert gpt.generate("стабильная ситуация", "calm") == ""
    finally:
        cl.stop()


def test_generate_sanitizes_quotes_and_markdown(monkeypatch):
    cl = _client(); cl.start()
    try:
        async def fake_json(*a, **k):
            return {"result": {"alternatives": [
                {"message": {"text": '"- **Леклер атакует!**"'}}]}}
        monkeypatch.setattr(cl, "post_json", fake_json)
        gpt = YandexGPT(cl)
        assert gpt.generate("контекст", "tv") == "Леклер атакует!"
    finally:
        cl.stop()


def test_generate_raw_swallows_errors(monkeypatch):
    cl = _client(); cl.start()
    try:
        async def boom(*a, **k):
            raise RuntimeError("net down")
        monkeypatch.setattr(cl, "post_json", boom)
        gpt = YandexGPT(cl)
        # сбой сети → None (caller drops the candidate), не исключение
        assert gpt.generate_raw("sys", "user") is None
    finally:
        cl.stop()


def test_generate_raw_returns_phrase(monkeypatch):
    cl = _client(); cl.start()
    try:
        async def fake_json(*a, **k):
            return {"result": {"alternatives": [{"message": {"text": "Журналистский анализ"}}]}}
        monkeypatch.setattr(cl, "post_json", fake_json)
        gpt = YandexGPT(cl)
        assert gpt.generate_raw("system prompt", "user text") == "Журналистский анализ"
    finally:
        cl.stop()


def test_generate_raw_empty_is_silence_not_error(monkeypatch):
    """Пустой ответ модели = осознанное молчание ('' ), а не сбой (None)."""
    cl = _client(); cl.start()
    try:
        async def fake_json(*a, **k):
            return {"result": {"alternatives": [{"message": {"text": "   "}}]}}
        monkeypatch.setattr(cl, "post_json", fake_json)
        gpt = YandexGPT(cl)
        assert gpt.generate_raw("system", "user") == ""
    finally:
        cl.stop()


def test_generate_raw_sanitizes_quotes_and_markdown(monkeypatch):
    cl = _client(); cl.start()
    try:
        async def fake_json(*a, **k):
            return {"result": {"alternatives": [
                {"message": {"text": '"- **Новость от редакции**"'}}]}}
        monkeypatch.setattr(cl, "post_json", fake_json)
        gpt = YandexGPT(cl)
        assert gpt.generate_raw("sys", "user") == "Новость от редакции"
    finally:
        cl.stop()
