"""
commentator/ai_provider.py
============================
Тонкая обёртка над Anthropic API. Если ключ не задан или библиотека не
установлена — provider просто недоступен, и brain.py использует шаблоны.
"""

from __future__ import annotations

from commentator.personas import system_prompt


class AIProvider:

    def __init__(self, api_key: str, model: str):
        self.client = None
        self.model = model

        if not api_key:
            return

        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            print("[!] Библиотека 'anthropic' не установлена — используются шаблоны.")

    @property
    def available(self) -> bool:
        return self.client is not None

    def generate(self, event: dict, persona: str, analytics_context: str | None = None) -> str | None:
        if not self.available:
            return None

        prompt = f"Событие в гонке F1 (с именами и командами): {event}. Прокомментируй это."
        if analytics_context:
            prompt = f"[Контекст реального GP: {analytics_context}]\n" + prompt
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=60,
                system=system_prompt(persona),
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            print(f"[!] Ошибка вызова LLM: {e} -> использую шаблон")
            return None
