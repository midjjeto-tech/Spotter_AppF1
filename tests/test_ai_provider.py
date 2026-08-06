from commentator.ai_provider import AIProvider


def test_unavailable_without_client():
    ai = AIProvider(None)
    assert ai.available is False
    assert ai.generate("любой контекст", "tv") is None


def test_delegates_to_gpt(monkeypatch):
    class FakeGPT:
        def __init__(self, *a, **k):
            pass
        def generate(self, context, persona):
            return f"phrase:{context}:{persona}"

    import commentator.ai_provider as mod
    monkeypatch.setattr(mod, "YandexGPT", FakeGPT)
    ai = AIProvider(object())  # любой не-None «клиент»
    assert ai.available is True
    assert ai.generate("CTX", "hype") == "phrase:CTX:hype"


def test_generate_with_system_unavailable_without_client():
    ai = AIProvider(None)
    assert ai.generate_with_system("SYS", "USER") is None


def test_generate_with_system_delegates_to_gpt(monkeypatch):
    class FakeGPT:
        def __init__(self, *a, **k):
            pass
        def generate_raw(self, system, user):
            return f"raw:{system}:{user}"

    import commentator.ai_provider as mod
    monkeypatch.setattr(mod, "YandexGPT", FakeGPT)
    ai = AIProvider(object())
    assert ai.generate_with_system("SYS", "USER") == "raw:SYS:USER"
