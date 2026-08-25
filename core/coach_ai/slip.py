"""
core/coach_ai/slip.py
======================
Детекторы срывов сцепления по MotionEx. Чистые конечные автоматы: на вход —
кадр телеметрии, на выходе — список завершённых `CornerMistake`.

Событие публикуется ТОЛЬКО по окончании срыва: до этого неизвестен пик, а пик
и есть степень ошибки. Автомат на каждый вид ошибки отдельный — они идут
одновременно (заблокировать переднее на входе и снести машину там же это две
разные проблемы с разными указаниями пилоту), и `tick` возвращает СПИСОК, а не
одно событие: при одновременном закрытии двух срывов второй иначе терялся бы
молча.

Пороги ниже НЕ откалиброваны на живых данных (см. Task 13 плана
docs/superpowers/plans/2026-08-06-driving-coach-phase1.md). До калибровки фича
выключена по умолчанию: `driving_coach_enabled=False`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from core.coach_ai.models import CornerMistake
from core.packets import SURFACE_ON_TRACK

_log = logging.getLogger(__name__)

# ── Пороги (НЕ откалиброваны, см. Task 13) ───────────────────────────────────
LOCKUP_SLIP = -0.25                # slip_ratio ниже этого при нажатом тормозе
LOCKUP_MIN_BRAKE_PCT = 20.0
WHEELSPIN_SLIP = 0.20              # slip_ratio выше этого при открытом газе
WHEELSPIN_MIN_THROTTLE_PCT = 40.0
UNDERSTEER_SLIP_ANGLE = 0.12       # передние, рад
UNDERSTEER_MIN_STEER = 0.25        # |steer|, доля хода руля
UNDERSTEER_MAX_YAW_RATE = 0.10     # кузов не доворачивает, рад/с
OVERSTEER_SLIP_ANGLE = 0.15        # задние, рад
OFFTRACK_MIN_WHEELS = 2            # поребрик за выезд не считается
MIN_EVENT_DURATION_S = 0.20        # короче — шум подвески, не потеря сцепления

#: Дольше — это уже не дискретная ошибка в повороте. Разбор живого заезда
#: 2026-08-11 дал `lockup` длиной 9,7 с и `oversteer` 3,2 с: сигнал держался
#: (или пропал вместе с телеметрией), автомат не закрывался, и событие
#: получало прописку там, где НАЧАЛОСЬ, — на прямой. Такие срывы не просто
#: бесполезны для урока: девятисекундное событие проезжает несколько поворотов
#: и уносит их привязку с собой. Отбрасываем и пишем в лог.
MAX_EVENT_DURATION_S = 3.0

#: Ниже этой скорости кадр в детектор не идёт.
#:
#: Проскальзывание — отношение (скорость колеса − скорость земли) к скорости
#: земли. У стоящей машины знаменатель около нуля, и величина взлетает: свод
#: всех срывов архива 2026-08-25 дал пять `wheelspin`, из них ТРИ с пиком
#: 5.386–5.417 при собственном потолке достоверности `health.SANE_MAX_SLIP_RATIO
#: = 3.0`, и все три — при `speed_kmh = 0`, круг 1, поворот 1. Это старт с
#: решётки трёх разных гонок, а не сбитая раскладка пакета: остальные два
#: `wheelspin` (0.27 и 0.42 при 49 и 56 км/ч) совершенно нормальны.
#:
#: Значение то же, что у `health.MIN_MOVING_KMH`, и это НЕ совпадение — оно
#: здесь одно на два модуля. Гейт по движению существовал в health.py с самого
#: начала, с прямым объяснением («нули стоящей машины — правда, а не
#: поломка»), но до детектора это решение не довели. Порог лежит заведомо ниже
#: гоночных скоростей: самый медленный поворот календаря проходится примерно
#: на 45–50 км/ч.
MIN_MOVING_KMH = 30.0


def _is_moving(frame: dict) -> bool:
    """Едет ли машина настолько, чтобы её проскальзывание что-то значило.

    Скорость ОТСУТСТВУЕТ — считаем, что едет. «Данных нет» и «машина стоит» —
    разные ответы, и подменять первый вторым значило бы выключить коуча целиком
    на источнике без этого поля (iRacing, фазы 2/3) и ни словом об этом не
    сообщить."""
    speed = frame.get("speed_kmh")
    if speed is None:
        return True
    try:
        return float(speed) >= MIN_MOVING_KMH
    except (TypeError, ValueError):
        return True


_REAR = ("rl", "rr")
_FRONT = ("fl", "fr")


@dataclass
class _Ongoing:
    kind: str
    wheel: str | None
    started_at: float
    peak: float
    corner_id: int | None
    corner_name: str | None
    phase: str
    lap: int
    speed_kmh: int | None


class SlipDetector:
    """Один экземпляр на сессию. `tick()` зовётся на каждом MotionEx."""

    def __init__(self) -> None:
        self._ongoing: dict[str, _Ongoing] = {}
        #: Виды, чей срыв был отброшен как зависший. Пока сигнал не отпустит,
        #: новый срыв того же вида не открывается: иначе выброшенное событие
        #: тут же порождало бы следующее из того же самого залипшего сигнала —
        #: и вместо одной мусорной записи мы получали бы поток.
        self._suppressed: set[str] = set()

    def reset(self) -> None:
        """Смена сессии или флэшбек: незакрытые события выбрасываются, а не
        дозакрываются — их место на трассе уже неактуально."""
        self._ongoing.clear()
        self._suppressed.clear()

    def tick(
        self,
        frame: dict,
        now: float,
        lap: int,
        corner_id: int | None,
        corner_name: str | None,
        phase: str,
    ) -> list[CornerMistake]:
        """Один кадр. Возвращает завершившиеся на нём ошибки (обычно пустой
        список).

        Место и фаза берутся на НАЧАЛЕ срыва, а не на конце: пилот ошибается на
        входе в поворот, а отпускает уже в апексе — «блокировка в апексе»
        отправила бы его чинить не то место.

        Открытые срывы принудительно закрываются на смене круга и по
        `MAX_EVENT_DURATION_S`: без этого автомат зависал, и событие уезжало на
        чужой круг с пропиской на прямой.
        """
        finished: list[CornerMistake] = []
        self._expire(now, lap)

        if not _is_moving(frame):
            # Машина стоит — открывать новые срывы нельзя, а УЖЕ открытые надо
            # закрыть штатно: разворот гасит скорость, и занос, начавшийся на
            # 180 км/ч, обязан доехать до урока. Обратное правило меняло бы
            # один ложный вывод на потерю настоящих ошибок.
            for kind in list(self._ongoing):
                done = self._close(kind, now)
                if done is not None:
                    finished.append(done)
            self._suppressed.clear()
            return finished

        for kind, wheel, magnitude in self._candidates(frame):
            if magnitude is None:
                # Сигнал отпустил — снимаем и подавление, и открытое событие.
                self._suppressed.discard(kind)
                done = self._close(kind, now)
                if done is not None:
                    finished.append(done)
                continue
            if kind in self._suppressed:
                continue
            cur = self._ongoing.get(kind)
            if cur is None:
                self._ongoing[kind] = _Ongoing(
                    kind=kind, wheel=wheel, started_at=now, peak=magnitude,
                    corner_id=corner_id, corner_name=corner_name, phase=phase,
                    lap=lap, speed_kmh=frame.get("speed_kmh"),
                )
            elif magnitude > cur.peak:
                cur.peak = magnitude
                cur.wheel = wheel
        return finished

    def _expire(self, now: float, lap: int) -> None:
        """Выбросить зависшие срывы. Ничего не возвращает намеренно: такое
        событие нельзя ни озвучить, ни положить в урок — у него недостоверны и
        длительность, и место. Но и потеряться молча оно не должно."""
        for kind, cur in list(self._ongoing.items()):
            duration = now - cur.started_at
            too_long = duration > MAX_EVENT_DURATION_S
            crossed_line = lap != cur.lap
            if not (too_long or crossed_line):
                continue
            del self._ongoing[kind]
            if too_long:
                # Смена круга — событие штатное, сигнал при этом здоров.
                # Залипший сигнал — нет, и открывать по нему новое нельзя.
                self._suppressed.add(kind)
            _log.info(
                "coach: срыв %s отброшен — %s (длительность %.1fс, круг %s→%s)",
                kind, "слишком длинный" if too_long else "пересёк линию круга",
                duration, cur.lap, lap)

    def _close(self, kind: str, now: float) -> CornerMistake | None:
        cur = self._ongoing.pop(kind, None)
        if cur is None:
            return None
        duration = now - cur.started_at
        if duration < MIN_EVENT_DURATION_S:
            return None
        return CornerMistake(
            kind=cur.kind, wheel=cur.wheel, corner_id=cur.corner_id,
            corner_name=cur.corner_name, phase=cur.phase, lap=cur.lap,
            peak=round(cur.peak, 3), duration_s=round(duration, 2),
            speed_kmh=cur.speed_kmh,
        )

    def _candidates(self, frame: dict):
        """(вид, колесо, величина) по каждому виду ошибки. Величина None —
        сейчас не срывает."""
        ratio = frame.get("slip_ratio") or {}
        angle = frame.get("slip_angle") or {}
        brake = frame.get("brake_pct") or 0.0
        throttle = frame.get("throttle_pct") or 0.0
        steer = frame.get("steer") or 0.0
        yaw = frame.get("yaw_rate") or 0.0

        yield ("lockup", *_worst(
            ratio,
            lambda v: v <= LOCKUP_SLIP and brake >= LOCKUP_MIN_BRAKE_PCT,
            key=lambda v: -v))
        # Пробуксовка — только ведущая ось: передние колёса под газом не буксуют.
        yield ("wheelspin", *_worst(
            {w: ratio.get(w, 0.0) for w in _REAR},
            lambda v: v >= WHEELSPIN_SLIP and throttle >= WHEELSPIN_MIN_THROTTLE_PCT,
            key=lambda v: v))

        front = max((abs(angle.get(w, 0.0)) for w in _FRONT), default=0.0)
        rear = max((abs(angle.get(w, 0.0)) for w in _REAR), default=0.0)

        # Снос: передние скользят сильнее задних, руль повёрнут, а кузов почти
        # не доворачивает. Без проверки руля любой быстрый поворот считался бы
        # ошибкой.
        understeer = (
            front >= UNDERSTEER_SLIP_ANGLE
            and front > rear
            and abs(steer) >= UNDERSTEER_MIN_STEER
            and abs(yaw) <= UNDERSTEER_MAX_YAW_RATE
        )
        yield ("understeer", None, front if understeer else None)

        # Занос: задние скользят сильнее передних И пилот уже ловит машину —
        # руль в одну сторону, разворот кузова в другую. Без контр-руления это
        # просто поворот на пределе, а не ошибка.
        counter_steering = steer * yaw < 0
        oversteer = (
            rear >= OVERSTEER_SLIP_ANGLE and rear > front and counter_steering
        )
        yield ("oversteer", None, rear if oversteer else None)

        surface = frame.get("surface") or {}
        off_wheels = sum(
            1 for s in surface.values()
            if s not in SURFACE_ON_TRACK and s != "unknown"
        )
        yield ("offtrack", None,
               float(off_wheels) if off_wheels >= OFFTRACK_MIN_WHEELS else None)


def _worst(values: dict, predicate, key):
    """Худшее колесо среди сработавших: (колесо, величина) или (None, None)."""
    hits = [(w, v) for w, v in values.items() if predicate(v)]
    if not hits:
        return None, None
    wheel, value = max(hits, key=lambda wv: key(wv[1]))
    return wheel, abs(value)
