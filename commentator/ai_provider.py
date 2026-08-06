"""
commentator/ai_provider.py
============================
Тонкая обёртка над YandexGPT. Если клиент не передан (нет/невалиден ключ) —
provider недоступен, и brain.py использует шаблоны (Free-режим).
Форма класса сохранена: brain.py зависит только от .available и .generate(...).
"""
from __future__ import annotations

import config
from yandex_ai.gpt import YandexGPT


class AIProvider:
    def __init__(self, client=None, model: str | None = None):
        self._gpt = None
        if client is not None:
            self._gpt = YandexGPT(client, model or config.YANDEX_GPT_MODEL)

    @property
    def available(self) -> bool:
        return self._gpt is not None

    def generate(self, context: str, persona: str) -> str | None:
        """context — сырой текстовый контекст гонки (см. commentator/timeline.py).
        Возвращает фразу, '' (молчание) или None (LLM недоступен/сбой)."""
        if self._gpt is None:
            return None
        return self._gpt.generate(context, persona)

    def generate_with_system(self, system: str, user: str) -> str | None:
        """Like .generate(), but with a caller-supplied system prompt instead of a
        persona lookup. Used by core.racefeed (see core/racefeed/prompts.py for
        its reporter-specific system prompts)."""
        if self._gpt is None:
            return None
        return self._gpt.generate_raw(system, user)
