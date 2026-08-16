"""
core/coach_ai/focus.py
=======================
Одна работа за раз — и подтверждение, что она сделана.

Это тот слой, из-за отсутствия которого коуч оставался бесполезным даже когда
всё под ним работало правильно. Фазы 1 и 2 честно находили ошибки и честно про
них говорили: блокировка в седьмом, поздний газ в третьем, снос в одиннадцатом.
Каждая реплика по отдельности верна, вместе они — шум. Настоящий тренер за
заезд занимается ОДНОЙ вещью, называет её цену, и главное — говорит, когда
получилось. Без последнего пилот не знает, работает ли то, что он меняет, и
через два заезда перестаёт слушать.

Три события за всю жизнь одного фокуса, не больше:

    set      — взяли в работу: «работаем над седьмым, там уходит три десятых»
    progress — подтверждение, что стало лучше (ровно один раз на фокус)
    fixed    — закрыли, дальше можно брать следующий

**Прогресс меряется по ОКНУ последних кругов, а не по всей сессии.** Медиана
сессии почти не двигается, если пилот исправился на десятом круге из двадцати:
в ней ещё лежат десять старых кругов. Коуч, меряющий прогресс по итогу, не
заметил бы исправления до самого финиша — то есть ровно тогда, когда его похвала
уже ничего не стоит. Окно выбирает вызывающий (`CornerHistory.costs(window=...)`),
здесь принимаются уже посчитанные диагнозы.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.coach_ai.diagnosis import CornerDiagnosis

#: Дешевле — не работа на сессию. За двадцатикруговую гонку это меньше двух с
#: половиной секунд, и просить пилота перестраивать привычку ради этого рано,
#: пока в круге есть что-то дороже.
MIN_FOCUS_COST_MS = 120.0

#: Насколько чужая проблема должна быть дороже текущей, чтобы забрать работу.
#: Без запаса коуч метался бы между двумя поворотами каждый круг — и это хуже,
#: чем работать над вторым по важности.
SWITCH_RATIO = 1.6

#: Сколько кругов фокус нельзя отнимать после того, как его взяли. Привычка не
#: перестраивается за круг, и смена задания раньше этого срока означала бы, что
#: пилот не успел даже попробовать.
MIN_LAPS_BEFORE_SWITCH = 4

#: Отыгранное время, которое стоит назвать прогрессом.
#:
#: Не ниже порога ПРОИЗНОСИМОГО (`core/num_to_words.py::MIN_SPOKEN_MS`), и это
#: не совпадение: подтверждение прогресса даётся ровно один раз на фокус. Если
#: величина окажется непроизносимой, эфир промолчит — а фокус уже пометит
#: похвалу выданной, и второго повода сказать не будет. Пилот не услышит
#: единственную обратную связь, ради которой он коуча и слушает. На связь
#: порогов стоит тест.
PROGRESS_MIN_MS = 100.0

#: Ниже этого поворот считается закрытым. То же число, ниже которого
#: `cost.MIN_COST_MS` вообще не считает потерю потерей: закрытый поворот просто
#: исчезает из списка проблем.
FIXED_MAX_MS = 40.0

#: Сколько кругов подряд наблюдение должно держаться, чтобы стать событием.
#: Один круг — это удачный или неудачный проезд, а не изменение.
CONFIRM_LAPS = 2

#: Пауза между любыми двумя репликами фокуса. Три события на фокус и эта пауза
#: вместе дают потолок: коуч физически не может превратиться в болтуна.
EVENT_COOLDOWN_LAPS = 3

#: Закрытый поворот не берётся в работу снова сразу же: цена меряется медианой
#: по окну, и сразу после закрытия она ещё дрожит около порога.
RELAPSE_LAPS = 6


@dataclass
class FocusEvent:
    """Повод открыть рот. Формулировку даёт банк фраз, не этот модуль."""
    kind: str              # "set" | "progress" | "fixed"
    corner_id: int
    corner_name: str | None
    cost_ms: float         # цена поворота на момент события
    gain_ms: float         # сколько отыграно от базовой линии
    cause: str | None
    lap: int


@dataclass
class Focus:
    """Текущая работа сессии."""
    corner_id: int
    corner_name: str | None
    cause: str | None
    cause_kind: str | None
    evidence: str
    baseline_ms: float
    current_ms: float
    since_lap: int
    status: str            # "working" | "improving"
    progress_reported: bool = False

    @property
    def gain_ms(self) -> float:
        return max(0.0, self.baseline_ms - self.current_ms)

    def to_dict(self) -> dict:
        return {
            "corner_id": self.corner_id, "corner_name": self.corner_name,
            "cause": self.cause, "cause_kind": self.cause_kind,
            "evidence": self.evidence,
            "baseline_ms": round(self.baseline_ms),
            "current_ms": round(self.current_ms),
            "gain_ms": round(self.gain_ms),
            "since_lap": self.since_lap, "status": self.status,
        }


class SessionFocus:
    """Один экземпляр на сессию. `update()` зовётся раз на завершённом круге."""

    def __init__(self) -> None:
        self._focus: Focus | None = None
        self._last_event_lap: int | None = None
        self._fixed_at: dict[int, int] = {}
        self._progress_streak = 0
        self._fixed_streak = 0

    def reset(self) -> None:
        self._focus = None
        self._last_event_lap = None
        self._fixed_at.clear()
        self._progress_streak = 0
        self._fixed_streak = 0

    @property
    def state(self) -> Focus | None:
        return self._focus

    def to_dict(self) -> dict | None:
        return self._focus.to_dict() if self._focus else None

    def update(self, diagnoses: list[CornerDiagnosis], lap: int,
               ) -> FocusEvent | None:
        """Наблюдения круга. Максимум ОДНО событие за вызов — иначе «закрыли
        седьмой» и «берём третий» прозвучали бы одной кашей."""
        by_corner = {d.corner_id: d for d in diagnoses}
        if self._focus is None:
            return self._adopt(diagnoses, lap)

        focus = self._focus
        current = by_corner.get(focus.corner_id)
        # Поворота нет в списке проблем — значит, его цена упала ниже порога, с
        # которого она вообще считается потерей. Это ноль, а не «нет данных».
        focus.current_ms = current.cost_ms if current is not None else 0.0
        if current is not None and current.cause is not None:
            # Причина может уточниться по мере накопления кругов: сначала видно
            # только отклонение техники, потом набирается повтор срыва.
            focus.cause = current.cause
            focus.cause_kind = current.cause_kind
            focus.evidence = current.evidence

        event = self._maybe_fixed(focus, lap)
        if event is not None:
            return event
        event = self._maybe_progress(focus, lap)
        if event is not None:
            return event
        return self._maybe_switch(focus, diagnoses, lap)

    # ── Переходы ────────────────────────────────────────────────────────────

    def _adopt(self, diagnoses: list[CornerDiagnosis], lap: int,
               ) -> FocusEvent | None:
        """Взять работу. Взять и объявить — один и тот же акт: фокус, о котором
        пилоту не сказали, не отличается от его отсутствия."""
        if not self._cooldown_passed(lap):
            return None
        candidate = self._best_candidate(diagnoses, lap)
        if candidate is None:
            return None
        self._focus = Focus(
            corner_id=candidate.corner_id, corner_name=candidate.corner_name,
            cause=candidate.cause, cause_kind=candidate.cause_kind,
            evidence=candidate.evidence, baseline_ms=candidate.cost_ms,
            current_ms=candidate.cost_ms, since_lap=lap, status="working")
        self._progress_streak = 0
        self._fixed_streak = 0
        return self._event("set", self._focus, lap)

    def _maybe_fixed(self, focus: Focus, lap: int) -> FocusEvent | None:
        if focus.current_ms >= FIXED_MAX_MS:
            self._fixed_streak = 0
            return None
        self._fixed_streak += 1
        if self._fixed_streak < CONFIRM_LAPS or not self._cooldown_passed(lap):
            return None
        event = self._event("fixed", focus, lap)
        self._fixed_at[focus.corner_id] = lap
        self._focus = None
        self._progress_streak = 0
        self._fixed_streak = 0
        return event

    def _maybe_progress(self, focus: Focus, lap: int) -> FocusEvent | None:
        """Похвала ровно один раз на фокус.

        Второй раз о том же прогрессе — это уже не подтверждение, а болтовня;
        следующий повод сказать про этот поворот только один — что он закрыт.

        **`status` пересчитывается КАЖДЫЙ круг, до проверки `progress_reported`,
        и это не порядок ради порядка.** Статус читает `_maybe_switch`, который
        не отнимает работу у наметившегося прогресса. Пока выход стоял первым,
        флаг `improving` защёлкивался навсегда: похвала выдана — и дальше сюда
        уже не заходили, даже когда прогресс исчезал. Фокус, откатившийся к
        своей же базовой линии, держал сессию до финиша, а поворот в шесть раз
        дороже не брался вовсе; коуч при этом молчал, потому что все три события
        своей жизни уже потратил. Похвала по-прежнему ровно одна — её сторожит
        `progress_reported`, а не статус."""
        if focus.gain_ms < PROGRESS_MIN_MS:
            self._progress_streak = 0
            # Прогресс исчез — работа снова просто работа, и её снова можно
            # уступить чему-то более дорогому.
            focus.status = "working"
            return None
        focus.status = "improving"
        if focus.progress_reported:
            return None
        self._progress_streak += 1
        if self._progress_streak < CONFIRM_LAPS or not self._cooldown_passed(lap):
            return None
        focus.progress_reported = True
        return self._event("progress", focus, lap)

    def _maybe_switch(self, focus: Focus, diagnoses: list[CornerDiagnosis],
                      lap: int) -> FocusEvent | None:
        if lap - focus.since_lap < MIN_LAPS_BEFORE_SWITCH:
            return None
        # Не бросаем то, что работает: смена задания посреди наметившегося
        # прогресса стирает единственную обратную связь, ради которой пилот и
        # слушает коуча.
        if focus.status == "improving":
            return None
        if not self._cooldown_passed(lap):
            return None
        rival = self._best_candidate(diagnoses, lap, exclude=focus.corner_id)
        if rival is None or rival.cost_ms < focus.current_ms * SWITCH_RATIO:
            return None
        # Текущая работа снимается ТОЛЬКО если новая действительно взялась.
        # Иначе отказ `_adopt` по любой из его собственных проверок оставил бы
        # сессию вообще без работы — и молча: пилот просто перестал бы что-либо
        # слышать, а причина не отличалась бы от «проблем больше нет».
        self._focus = None
        event = self._adopt([rival], lap)
        if event is None:
            self._focus = focus
        return event

    # ── Служебное ───────────────────────────────────────────────────────────

    def _best_candidate(self, diagnoses: list[CornerDiagnosis], lap: int,
                        exclude: int | None = None) -> CornerDiagnosis | None:
        best: CornerDiagnosis | None = None
        for row in diagnoses:
            if row.corner_id == exclude or not row.actionable:
                continue
            if row.cost_ms < MIN_FOCUS_COST_MS:
                continue
            fixed_lap = self._fixed_at.get(row.corner_id)
            if fixed_lap is not None and lap - fixed_lap < RELAPSE_LAPS:
                continue
            if best is None or row.cost_ms > best.cost_ms:
                best = row
        return best

    def _cooldown_passed(self, lap: int) -> bool:
        return (self._last_event_lap is None
                or lap - self._last_event_lap >= EVENT_COOLDOWN_LAPS)

    def _event(self, kind: str, focus: Focus, lap: int) -> FocusEvent:
        self._last_event_lap = lap
        return FocusEvent(
            kind=kind, corner_id=focus.corner_id, corner_name=focus.corner_name,
            cost_ms=focus.current_ms, gain_ms=focus.gain_ms, cause=focus.cause,
            lap=lap)
