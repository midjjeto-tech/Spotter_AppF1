"""GigaChatProvider — «мозг» комментатора на Sber GigaChat.

Тот же интерфейс, что commentator.ai_provider.AIProvider
(.available / .generate(context, persona) / .generate_with_system(system, user)),
поэтому brain.py, commentator и core.racefeed работают с ним без изменений —
провайдер выбирается в engine по config.LLM_PROVIDER.

Голос (TTS) он НЕ трогает — озвучка остаётся Yandex SpeechKit.

Контракт возврата — как у YandexGPT.generate:
  - фраза (str) — что озвучить;
  - '' — модель осознанно молчит (валидно, НЕ ошибка);
  - None — сбой сети/HTTP/OAuth -> brain уходит в шаблоны (Free-режим).
Исключения ГЛОТАЮТСЯ (SDK сам делает OAuth/рефреш/сертификат Минцифры).
"""
from __future__ import annotations

import logging

import config
from commentator.personas import system_prompt
from yandex_ai.gpt import _sanitize   # единый санитайзер ответа LLM под TTS

_log = logging.getLogger(__name__)


class GigaChatProvider:
    def __init__(self, credentials=None, model: str | None = None):
        self._client = None
        self._sdk_missing = False   # True, если пакет gigachat не установлен
        self._model = model or config.GIGACHAT_MODEL
        key = getattr(credentials, "authorization_key", "") if credentials else ""
        if key:
            try:
                from gigachat import GigaChat
            except ImportError as exc:  # SDK не установлен в этом окружении
                _log.warning("gigachat SDK not installed: %s "
                             "(pip install gigachat в этот Python)", exc)
                self._sdk_missing = True
                return
            try:
                kwargs = dict(
                    credentials=key,
                    scope=getattr(credentials, "scope", config.GIGACHAT_SCOPE),
                    model=self._model,
                    timeout=config.GIGACHAT_TIMEOUT,
                )
                # Продакшен-путь: если задан корневой CA-бандл Минцифры — включаем
                # строгую проверку TLS с ним. Иначе — dev-режим (verify off).
                ca = getattr(config, "GIGACHAT_CA_BUNDLE", "")
                if ca:
                    kwargs["verify_ssl_certs"] = True
                    kwargs["ca_bundle_file"] = ca
                else:
                    kwargs["verify_ssl_certs"] = config.GIGACHAT_VERIFY_SSL
                self._client = GigaChat(**kwargs)
            except Exception as exc:  # noqa: BLE001 — нет пакета/битый ключ -> провайдер недоступен
                _log.warning("GigaChat init failed: %s", exc)
                self._client = None

    def validate(self) -> tuple[bool, str, str]:
        """Живая проба ключа: (ok, code, message). Дёшево — 1 токен. Используется
        engine.apply_gigachat_credentials перед сохранением ключа."""
        if self._client is None:
            if self._sdk_missing:
                return (False, "GIGACHAT_SDK_MISSING",
                        "SDK gigachat не установлен в этом Python (pip install gigachat)")
            return (False, "GIGACHAT_NO_KEY", "Ключ GigaChat не задан")
        try:
            from gigachat.models import Chat, Messages, MessagesRole
            resp = self._client.chat(Chat(
                messages=[Messages(role=MessagesRole.USER, content="пинг")],
                max_tokens=1))
            _ = resp.choices[0].message.content
            return (True, "OK", "GigaChat подключён")
        except Exception as exc:  # noqa: BLE001
            return self._classify_error(exc)

    @staticmethod
    def _classify_error(exc: Exception) -> tuple[bool, str, str]:
        """Отличить проблему КЛЮЧА от проблемы СЕТИ.

        Sber отвечает 400/401/403 на кривой/неверный Authorization key (напр.
        400 «Can't decode 'Authorization' header» на битый base64) — это про ключ,
        а НЕ «нет связи». Настоящая сетевая ошибка — таймаут/отказ соединения/DNS,
        в тексте которых нет ни HTTP-статуса 4xx, ни упоминания авторизации."""
        # HTTP-статус из атрибутов исключения SDK (если есть) — надёжнее строки.
        status = (getattr(exc, "status_code", None) or getattr(exc, "status", None)
                  or getattr(exc, "code", None))
        m = str(exc)
        low = m.lower()
        cred_markers = ("400", "401", "403", "unauthorized", "forbidden",
                        "authorization", "decode", "invalid", "credentials")
        if status in (400, 401, 403) or any(s in low for s in cred_markers):
            return (False, "GIGACHAT_CRED_INVALID", "Ключ неверен или нет доступа")
        return (False, "GIGACHAT_NETWORK_ERROR", f"Нет связи с GigaChat: {m[:120]}")

    @property
    def available(self) -> bool:
        return self._client is not None

    def generate(self, context: str, persona: str) -> str | None:
        """Автономная генерация: системный промпт по персоне, context — сырой
        текстовый контекст гонки. См. contract в докстринге модуля."""
        return self._complete(system_prompt(persona), context,
                              max_tokens=60, temperature=0.88)

    def generate_with_system(self, system: str, user: str) -> str | None:
        """Как .generate(), но с системным промптом от вызывающего (core.racefeed
        репортёры — не одна из четырёх голосовых персон)."""
        return self._complete(system, user, max_tokens=200, temperature=0.7)

    def _complete(self, system: str, user: str, *, max_tokens: int,
                  temperature: float) -> str | None:
        if self._client is None:
            return None
        try:
            from gigachat.models import Chat, Messages, MessagesRole
            payload = Chat(
                messages=[
                    Messages(role=MessagesRole.SYSTEM, content=system),
                    Messages(role=MessagesRole.USER, content=user),
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            resp = self._client.chat(payload)
        except Exception as exc:  # noqa: BLE001 — сеть/HTTP/OAuth -> шаблоны
            _log.warning("GigaChat generate failed: %s", exc)
            return None
        try:
            text = (resp.choices[0].message.content or "").strip()
        except Exception:  # noqa: BLE001 — неожиданная форма ответа
            _log.warning("GigaChat: unexpected response shape")
            return None
        return _sanitize(text) if text else ""
