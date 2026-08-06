"""
commentator/brain.py
======================
Автономный ИИ-аналитик гонки (не набор триггеров «событие → заготовка»).

Логика:
- Если LLM доступен И здоров (ai_ok) — отдаём ему ПОЛНЫЙ контекст гонки (таймлайн
  ситуации/динамики/событий из commentator/timeline.py). ИИ сам решает, что сейчас
  важнее всего, и может вернуть '' — осознанно промолчать (не спамить пилоту).
- Если LLM недоступен/упал — для РЕАЛЬНОГО события берём шаблон (Free-режим),
  продукт продолжает работать без сети. Для ambient-тика шаблонов нет — молчим.

Возвращаемое значение create()/create_ambient():
- непустая строка — что озвучить;
- '' — молчим (ИИ так решил, либо ambient без LLM).
"""

from __future__ import annotations

from commentator import templates
from commentator.ai_provider import AIProvider
from commentator.memory import PhraseMemory
from commentator.planner import CommentPlan

try:
    from commentator.rag import F1RAG
except Exception:  # noqa: BLE001 — любая ошибка импорта не ломает приложение
    F1RAG = None  # type: ignore[assignment,misc]

# Модель не всегда умеет вернуть по-настоящему ПУСТОЙ ответ на просьбу молчать:
# иногда она отвечает сентинелом ТИШИНА (так и просим в personas.py) или эхом
# самой инструкции («Ничего не писать»). Такие ответы = осознанная тишина, их
# нельзя озвучивать. Сравниваем ЦЕЛИКОМ (не подстрокой), чтобы не задушить
# настоящую реплику, где эти слова встретились внутри фразы.
_SILENCE_ECHOES = frozenset({
    "тишина",
    "ничего не писать",
    "ничего не пишу",
    "ничего не пиши",
    "пустая строка",
    "пустую строку",
    "молчу",
    "промолчу",
})


def _is_silence(phrase: str) -> bool:
    normalized = phrase.strip().strip('"\'«»“”.,!…—-()').strip().lower()
    return normalized in _SILENCE_ECHOES


# Императивные box-call коды НИКОГДА не идут в LLM — гарантированная,
# мгновенная, ровно одобренная формулировка для решающей команды.
# См. docs/superpowers/specs/2026-07-09-precise-box-call-design.md.
_TEMPLATE_ONLY_CODES = frozenset({
    "STRAT_BOX_CALL_1", "STRAT_BOX_CALL_2", "STRAT_BOX_CALL_3",
})


class Commentator:

    def __init__(self, ai_provider: AIProvider, persona: str):
        self.ai = ai_provider
        self.persona = persona
        self.analytics_context: str | None = None
        self.broadcast_director = None  # set via set_broadcast_director()
        self.memory = PhraseMemory()
        self.rag = F1RAG() if F1RAG is not None else None

    def start(self) -> None:
        if self.rag is not None:
            self.rag.start()

    def stop(self, timeout: float = 1.0) -> None:
        if self.rag is not None:
            self.rag.stop(timeout=timeout)

    def set_broadcast_director(self, director) -> None:
        """Attach a BroadcastDirector for race_ai events."""
        self.broadcast_director = director

    def reset_session(self) -> None:
        """Reset race-local broadcast state without erasing restart-safe memory.

        PhraseMemory deliberately spans a short real-time window, so restarting
        the app mid-race still prevents repeats.  Only the in-memory Director
        cooldown/context belongs strictly to one race.
        """
        if self.broadcast_director is not None:
            self.broadcast_director.reset_session()

    def create_broadcast(self, event: dict, ai_ok: bool = True) -> str:
        """Broadcast Director path for race_ai events.

        Uses self.ai (always current AIProvider) via BroadcastDirector.
        Falls back to engineer.get_message() template on any failure.
        """
        code = event.get("event_code", "")
        if self.broadcast_director is not None:
            msg = self.broadcast_director.generate(event, self.ai, self.persona, ai_ok)
            if msg is not None:
                if msg.text:
                    self.memory.append(msg.text, code)
                return msg.text
        from commentator import engineer
        race_ai_data = dict(event.get("race_ai_data") or {})
        race_ai_data["driver"] = event.get("driver") or "Соперник"
        phrase = engineer.get_message(
            event.get("race_ai_type", "stable"),
            race_ai_data,
        )
        if phrase:
            self.memory.append(phrase, code)
        return phrase

    def _render_template(self, event: dict, code: str) -> str:
        """Шаблонная фраза + учёт в памяти — общий хвост для bypass-ветки
        (_TEMPLATE_ONLY_CODES) и обычного LLM-фолбэка ниже."""
        phrase = templates.render(event, self.persona)
        if phrase:
            self.memory.append(phrase, code)
        return phrase

    def create(self, event: dict | None, context: str = "", ai_ok: bool = True,
               plan: CommentPlan | None = None) -> str:
        """Сгенерировать реплику на событие с учётом полного контекста гонки.

        event — спровоцировавшее событие (или {'event_code': 'AMBIENT'} для тика);
        context — рендер RaceTimeline; ai_ok — здоров ли Yandex (health-monitor);
        plan — директива Comment Planner (commentator/planner.py): ЧТО и КАК
        комментировать. При plan=None (ambient без триггера, старые вызовы) LLM
        по-прежнему сам выбирает тему — поведение байт-в-байт как раньше.

        code in _TEMPLATE_ONLY_CODES (box-call) — безусловный шаблонный bypass,
        ДО обращения к LLM, независимо от ai_ok/available."""
        code = (event or {}).get("event_code", "")
        if code in _TEMPLATE_ONLY_CODES:
            return self._render_template(event, code)

        if self.ai.available and ai_ok:
            phrase = self.ai.generate(self._compose(context, event, plan), self.persona)
            if phrase is not None:
                if phrase and _is_silence(phrase):
                    phrase = ""          # сентинел/эхо инструкции = осознанная тишина
                if phrase:  # непустая = реальная фраза, запоминаем
                    self.memory.append(phrase, code)
                return phrase            # '' = осознанная тишина; иначе — фраза ИИ
            # None = сбой LLM → шаблоны ниже (только для реального события)

        if event is not None and code != "AMBIENT":
            return self._render_template(event, code)
        return ""

    def create_ambient(self, context: str, ai_ok: bool = True) -> str:
        """Медленный «тик»: LLM когда доступен, ambient-шаблон когда нет.

        '' = LLM осознанно промолчал; иначе — LLM-реплика или ambient-шаблон."""
        result = self.create({"event_code": "AMBIENT"}, context, ai_ok)
        if result == "" and not (self.ai.available and ai_ok):
            phrase = templates.render_ambient(self.persona)
            if phrase:
                self.memory.append(phrase, "AMBIENT")
            return phrase
        return result

    def _compose(self, context: str, event: dict | None,
                 plan: CommentPlan | None = None) -> str:
        """Собрать финальный контекст для LLM: план (если есть) → таймлайн →
        GP-сверка → RAG → анти-повтор. Директива плана — ПЕРВЫЙ блок: LLM должен
        увидеть ЧТО комментировать раньше, чем старый контекст таймлайна, который
        иначе перетягивает внимание на предыдущую драму (см. design spec)."""
        parts: list[str] = []
        if plan is not None:
            directive = (
                f"ЗАДАЧА: прокомментируй ИМЕННО это: {plan.focus}.\n"
                f"Тип реакции: {plan.reaction}. Стиль: {plan.length}, {plan.emotion}."
            )
            if plan.must_mention:
                directive += f"\nОбязательно упомяни: {', '.join(plan.must_mention)}."
            if plan.narrative:
                directive += "\nСтиль: свяжи с ходом гонки, не отдельная реплика."
            directive += "\nОстальной контекст ниже — только фон, НЕ пересказывай его."
            parts.append(directive)
        if self.analytics_context:
            parts.append(f"[Сверка с реальным GP: {self.analytics_context}]")
        if context:
            parts.append(context)
        if not parts:
            # таймлайн пуст (старт) — дать хотя бы сырой триггер, чтобы было от чего плясать
            if event is not None and event.get("event_code") != "AMBIENT":
                parts.append(f"Событие: {event.get('event_code')} "
                             f"{event.get('driver', '')}".strip())

        # RAG: добавляем релевантные факты. k=5 если есть конкретный пилот/цель, иначе k=3.
        if self.rag is not None:
            query = self._rag_query(event)
            k = self._rag_k(event)
            rag_ctx = self.rag.get_relevant_context(query, k=k)
            if rag_ctx:
                parts.append(f"ЗНАНИЯ ПО ТЕМЕ:\n{rag_ctx}")

        # Анти-повтор: последние N фраз (из долгосрочной памяти) — LLM не должен их повторять
        recent = self.memory.recent()
        if recent:
            memory_block = "НЕДАВНО СКАЗАНО:\n" + "\n".join(f"- {p}" for p in recent)
            parts.append(memory_block)

        return "\n\n".join(parts)

    def _rag_query(self, event: dict | None) -> str:
        """Сформировать поисковый запрос по событию для RAG."""
        if event is None:
            return ""
        parts: list[str] = []
        code = event.get("event_code", "")
        if code and code != "AMBIENT":
            parts.append(code)
        driver = event.get("driver") or ""
        if driver:
            parts.append(driver)
        target = event.get("target") or ""
        if target:
            parts.append(target)
        return " ".join(parts)

    def _rag_k(self, event: dict | None) -> int:
        """Количество фактов для RAG: 5 если упомянут конкретный пилот/цель, иначе 3."""
        if event is None:
            return 3
        has_specific = bool(event.get("driver") or event.get("target"))
        return 5 if has_specific else 3
