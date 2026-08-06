"""
core/rivals/intel.py
====================
Что из знания о сопернике стоит СКАЗАТЬ пилоту и когда.

Почему отдельно от `tracker.py`. Трекер отвечает на вопрос «что мы знаем про
эту машину» и обновляется каждый тик. Здесь другой вопрос — «что из этого
сейчас достойно эфира». Смешивать нельзя: знание накапливается постоянно, а
говорить можно редко.

Зачем это вообще. Стиль пилотажа, возраст резины и недавние ошибки соперников
трекер собирал и раньше, но уезжало это ТОЛЬКО в контекст LLM-комментатора и
стратегии (`core/engine.py`, обогащение OVTK). Инженер — тот, кто по смыслу
должен быть глазами пилота на то, чего пилот не видит, — не произносил ничего
из этого. Данные лежали готовыми.

Три правила, каждое лечит свою болезнь:

  * ОДИН факт за раз. Знаем мы про соперника три вещи сразу, но «шины старше,
    и он ошибся, и он агрессивный» — это не разведка, это поток. Выбирается
    самый ценный факт, остальные ждут.
  * Один и тот же факт про одного и того же соперника — один раз. Возраст шин
    растёт непрерывно, и без этого правила инженер пересказывал бы его каждый
    круг.
  * Кулдаун между любыми двумя разведданными: даже разные факты, сказанные
    подряд, превращают инженера в диктора статистики.

Порядок ценности — по СРОЧНОСТИ ДЛЯ ДЕЙСТВИЯ, а не по редкости:
ошибка соперника (окно для атаки живёт секунды) > разница по шинам (влияет на
план на несколько кругов) > стиль (фон, полезен один раз за встречу).
"""
from __future__ import annotations

#: Разница в возрасте резины, ниже которой говорить не о чем. Пять кругов —
#: примерно та величина, с которой разница начинает быть слышна в темпе; на
#: двух кругах реплика была бы шумом с точным числом.
MIN_TYRE_DELTA_LAPS = 5

#: Кулдаун между любыми двумя разведданными, секунды. Заметно больше кулдауна
#: обычных советов: разведка — приправа, а не основное блюдо.
COOLDOWN_S = 45.0

#: Стили, о которых стоит предупредить. `consistent` не говорит ничего
#: полезного, а `charging` уже слышно по сокращающемуся разрыву — его озвучит
#: сводка, и дублировать её незачем.
_WORTH_TELLING_STYLES = frozenset({"aggressive", "fading"})

CODE_MISTAKE = "rival.mistake"
CODE_TYRES_OLDER = "rival.tyres_older"
CODE_TYRES_FRESHER = "rival.tyres_fresher"
CODE_STYLE_AGGRESSIVE = "rival.style_aggressive"
CODE_STYLE_FADING = "rival.style_fading"


class RivalIntelTracker:
    """Решает, какой факт о сопернике впереди озвучить — и озвучивать ли."""

    def __init__(self, cooldown: float = COOLDOWN_S):
        self._cooldown = cooldown
        self._last_t = 0.0
        #: (vehicle_idx, код факта) — что уже рассказано про кого.
        self._told: set[tuple[int, str]] = set()

    def check(self, *, rival_idx: int | None, tyre_delta: int | None,
              recent_mistake: bool, style: str | None,
              now: float) -> tuple[str, dict] | None:
        """(semantic code, поля) для реплики, либо None если говорить нечего.

        `tyre_delta` — возраст резины СОПЕРНИКА минус возраст резины игрока в
        кругах: положительное значит «у него старше». None — данных нет
        (машина ещё не профилирована, шины соперника не приходили).
        """
        if rival_idx is None:
            return None
        if now - self._last_t < self._cooldown:
            return None

        for code, fields in self._candidates(tyre_delta, recent_mistake, style):
            if (rival_idx, code) in self._told:
                continue
            self._told.add((rival_idx, code))
            self._last_t = now
            return code, fields
        return None

    @staticmethod
    def _candidates(tyre_delta: int | None, recent_mistake: bool,
                    style: str | None) -> list[tuple[str, dict]]:
        """Факты, достойные эфира, в порядке убывания срочности для действия."""
        out: list[tuple[str, dict]] = []
        if recent_mistake:
            out.append((CODE_MISTAKE, {}))
        if tyre_delta is not None and abs(tyre_delta) >= MIN_TYRE_DELTA_LAPS:
            code = CODE_TYRES_OLDER if tyre_delta > 0 else CODE_TYRES_FRESHER
            out.append((code, {"laps": abs(tyre_delta)}))
        if style in _WORTH_TELLING_STYLES:
            out.append((CODE_STYLE_AGGRESSIVE if style == "aggressive"
                        else CODE_STYLE_FADING, {}))
        return out

    def reset(self, reason: str = "") -> None:
        """Забыть рассказанное. Новый заезд — новые соперники впереди, и даже те
        же самые машины к этому моменту в другом состоянии."""
        self._last_t = 0.0
        self._told.clear()
