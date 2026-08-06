"""YandexGPT: генерация коротких реплик комментатора.

acomplete() — низкоуровневая async-корутина, ПРОБРАСЫВАЕТ исключения (для классификации
в client.validate). generate() — синхронная обёртка для brain.py/ai_provider, исключения
ГЛОТАЕТ и возвращает None (тогда brain уходит в шаблоны).
Запрос НЕ-стриминговый: для фраз <=20 слов выигрыш стриминга ничтожен.
"""
from __future__ import annotations

import logging

import config
from commentator.personas import system_prompt

_log = logging.getLogger(__name__)


class YandexGPT:
    def __init__(self, client, model: str | None = None):
        self._client = client
        self._model = model or config.YANDEX_GPT_MODEL

    async def acomplete(self, system: str, user: str,
                        max_tokens: int = 100, temperature: float = 0.88) -> str | None:
        payload = {
            "modelUri": f"gpt://{self._client.folder_id}/{self._model}/latest",
            "completionOptions": {
                "stream": False,
                "temperature": temperature,
                "maxTokens": str(max_tokens),
            },
            "messages": [
                {"role": "system", "text": system},
                {"role": "user", "text": user},
            ],
        }
        data = await self._client.post_json(
            config.YANDEX_GPT_URL, payload,
            connect=config.YANDEX_GPT_CONNECT_TIMEOUT,
            total=config.YANDEX_GPT_TOTAL_TIMEOUT,
            extra_headers={"x-folder-id": self._client.folder_id},
        )
        alts = data.get("result", {}).get("alternatives", [])
        if not alts:
            return None
        text = alts[0].get("message", {}).get("text", "").strip()
        return text or None

    def generate(self, context: str, persona: str) -> str | None:
        """Автономная генерация: получает сырой текстовый контекст гонки, САМ выбирает
        тему. Возвращает:
        - фразу (str) — что озвучить;
        - '' — модель осознанно молчит (нечего сказать) — валидно, НЕ ошибка;
        - None — сбой сети/HTTP -> brain уходит в шаблоны (Free-режим).
        """
        try:
            fut = self._client.submit(
                self.acomplete(system_prompt(persona), context, max_tokens=60))
            text = fut.result(timeout=config.YANDEX_GPT_TOTAL_TIMEOUT + 1.0)
        except Exception as exc:  # noqa: BLE001 — сеть/HTTP -> шаблоны
            _log.warning("YandexGPT generate failed: %s", exc)
            return None
        # успешный вызов: пустой ответ = модель выбрала молчание (а не ошибка)
        return _sanitize(text) if text else ""

    def generate_raw(self, system: str, user: str) -> str | None:
        """Like .generate(), but takes a caller-supplied system prompt instead of
        resolving one via commentator.personas.system_prompt(persona). Used by
        core.racefeed, whose reporters are not one of the four voice personas.
        Same swallow-exceptions-return-None contract as .generate()."""
        try:
            fut = self._client.submit(self.acomplete(system, user, max_tokens=200))
            text = fut.result(timeout=config.YANDEX_GPT_TOTAL_TIMEOUT + 1.0)
        except Exception as exc:  # noqa: BLE001 — сеть/HTTP -> caller drops the candidate
            _log.warning("YandexGPT generate_raw failed: %s", exc)
            return None
        return _sanitize(text) if text else ""


def _sanitize(text: str) -> str:
    """Привести ответ LLM к одной чистой фразе под TTS: убрать кавычки, markdown,
    маркеры списка; обрезать до первой непустой строки. Без вводных и разметки."""
    t = text.strip().strip('"\'`«»“”').strip()
    if not t:
        return ""
    # первая непустая строка (срезает списки/многострочный вывод, если просочился)
    line = next((ln for ln in (raw.strip() for raw in t.splitlines()) if ln), "")
    line = line.lstrip("-*•").strip()                       # маркер списка
    line = line.replace("**", "").replace("__", "").replace("`", "").strip()  # markdown
    return line
