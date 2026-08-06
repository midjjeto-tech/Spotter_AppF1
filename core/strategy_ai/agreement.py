"""
core/strategy_ai/agreement.py
==============================
Договорённость с пилотом: инженер предложил — пилот принял или отказался.

Что эта петля МОЖЕТ и чего не может. Приложение не управляет игрой: «да» пилота
не заводит машину в боксы и не переключает режим ERS. Меняется поведение
ИНЖЕНЕРА — он подтверждает договорённость и перестаёт предлагать то, о чём уже
договорились или от чего пилот отказался. Это настоящий, наблюдаемый эффект, и
обещать больше нельзя: подтверждение, за которым ничего не следует, — худший
вид фальши в системе, которая должна звучать как настоящая рация.

Три состояния и три разных последствия:

  * ПРИНЯТО — не повторяем: договорились;
  * ОТКЛОНЕНО — не повторяем некоторое время: пилот сказал «нет», и долбить
    его тем же предложением значит не слышать ответа;
  * ПРОИГНОРИРОВАНО (окно истекло) — повторить МОЖНО: молчание не согласие и
    не отказ, пилот мог просто не услышать за рулём.

Отказ намеренно НЕ вечен. Обстановка меняется, и через несколько минут тот же
андеркат может стать единственным разумным ходом; вечное «нет» превратило бы
одну реплику пилота в выключенную на весь заезд стратегию.
"""
from __future__ import annotations

#: Сколько секунд после предложения ответ пилота считается решением по нему.
#: Столько же, сколько окно ответа на вопрос инженера (`core/engine.py`):
#: пилот отвечает не мгновенно, сначала он доезжает поворот.
WINDOW_S = 30.0

#: Сколько секунд не повторять предложение после решения пилота.
DECIDED_COOLDOWN_S = 300.0


class StrategyAgreement:
    """Одно висящее предложение и память о принятых решениях."""

    def __init__(self, window: float = WINDOW_S,
                 decline_cooldown: float = DECIDED_COOLDOWN_S):
        self._window = window
        self._cooldown = decline_cooldown
        self._pending: str | None = None
        self._pending_t = 0.0
        #: код предложения -> когда по нему приняли решение
        self._decided: dict[str, float] = {}

    def propose(self, code: str, now: float) -> None:
        """Инженер озвучил предложение — открыть окно решения.

        Новое предложение вытесняет прежнее: висеть двум одновременно нельзя,
        иначе «да» относилось бы неизвестно к чему.
        """
        self._pending = code
        self._pending_t = now

    def pending(self, now: float) -> str | None:
        """Предложение, по которому сейчас ждём решения, либо None."""
        if self._pending is None or now - self._pending_t > self._window:
            return None
        return self._pending

    def accept(self, now: float) -> str | None:
        """Пилот согласился. Возвращает код предложения, либо None если
        предложения не было — тогда это просто реплика, а не решение."""
        return self._close(now)

    def decline(self, now: float) -> str | None:
        """Пилот отказался. Последствие то же, что у согласия: не повторяем.
        Разница только в том, что скажет инженер в ответ."""
        return self._close(now)

    def _close(self, now: float) -> str | None:
        code = self.pending(now)
        if code is None:
            return None
        self._decided[code] = now
        self._pending = None
        return code

    def is_suppressed(self, code: str, now: float) -> bool:
        """True = по этому предложению уже есть решение и повторять его рано."""
        decided_at = self._decided.get(code)
        return decided_at is not None and now - decided_at < self._cooldown

    def reset(self) -> None:
        self._pending = None
        self._pending_t = 0.0
        self._decided.clear()
