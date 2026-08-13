"""
core/coach_ai/health.py
========================
Почему коуч молчит — вопрос пользователя, а не разработчика.

Жалоба, с которой началась вся работа над коучем, звучала как «бесполезная
функция, ничего не даёт». Тумблер при этом был включён. Разобраться, что именно
происходит, было нельзя ничем: молчащий коуч выглядит одинаково при выключенном
тумблере, при неповторяющейся ошибке, при не доехавшей телеметрии движения и при
завышенном пороге детектора. Четыре разных диагноза с четырьмя разными
действиями — и ни одного способа их различить, кроме чтения кода.

**Это не полевой журнал.** `core/field_log.py` пишет распределения на диск, живёт
за `SPOTTER_DIAG=1` и адресован тому, кто чинит пороги. Здесь — короткий ответ
пилоту на экране, всегда включённый: сигнал есть или нет, сколько нашли, сколько
сказали и почему не сказали остальное.

**Здоровье сигнала считается по ДВИЖУЩЕЙСЯ машине.** Стоящая на месте машина
честно даёт нули по всем колёсам, и принять это за «данные не приходят» значило
бы пугать пользователя на каждой загрузке сессии.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.coach_ai import slip as slip_mod

#: Ниже этой скорости кадр в оценку сигнала не идёт: нули у стоящей машины —
#: правда, а не поломка.
MIN_MOVING_KMH = 30.0

#: Сколько кадров движения нужно, чтобы вообще выносить вердикт о сигнале.
#: При ~60 Гц это около десяти секунд езды.
MIN_FRAMES_FOR_VERDICT = 600

#: Проскальзывание — величина безразмерная; за пределами этого значения речь уже
#: не о срыве, а о неверно прочитанном офсете пакета.
SANE_MAX_SLIP_RATIO = 3.0

#: Угол увода в радианах. Полтора радиана — это 86°, машина так не едет.
SANE_MAX_SLIP_ANGLE = 1.5

#: Газ, при котором ведущая ось обязана проявить себя. Ниже — поддерживающий
#: газ, по нему о приводе судить нельзя.
DRIVE_CHECK_MIN_THROTTLE_PCT = 80.0

#: Насколько перед должен переспорить зад, чтобы кадр считался «перепутанным».
#: Небольшое положительное проскальзывание на передних под газом бывает от
#: качения и шума замера — интересует систематическое превосходство.
DRIVE_CHECK_MARGIN = 0.05

#: Сколько кадров под газом нужно, чтобы судить о приводе.
DRIVE_CHECK_MIN_FRAMES = 200

#: Доля таких кадров, выше которой порядок колёс считается перепутанным.
DRIVE_CHECK_SWAPPED_SHARE = 0.7

SIGNAL_OK = "ok"
SIGNAL_NO_FRAMES = "no_frames"
SIGNAL_FLAT = "flat"
SIGNAL_IMPLAUSIBLE = "implausible"
SIGNAL_SWAPPED = "swapped"
SIGNAL_WARMING_UP = "warming_up"

#: Причина молчания -> что это значит для пилота. Формулировки говорят, что
#: делать (или что делать нечего), а не пересказывают имя ключа.
SILENCE_RU: dict[str, str] = {
    "coach_disabled_in_settings":
        "Подсказки по пилотажу выключены в настройках.",
    "mistake_repeat_rule":
        "Срывы есть, но не повторяются — коуч ждёт привычку, а не разовый круг.",
    "reference_repeat_rule":
        "Отклонения от эталона не повторяются от круга к кругу.",
    "off_focus":
        "Коуч ведёт один поворот и не отвлекается на остальные.",
    "no_corner_to_name":
        "Срывы происходят вне поворотов — назвать место нечем.",
    "track_limits_just_announced":
        "О том же эпизоде уже сказано как о нарушении границ трассы.",
    "loss_below_spoken":
        "Потеря слишком мала, чтобы её произносить.",
    "gain_below_spoken":
        "Отыгранное время слишком мало, чтобы его произносить.",
}

_SIGNAL_RU: dict[str, str] = {
    SIGNAL_NO_FRAMES: (
        "Телеметрия движения не приходит. В игре: настройки → телеметрия → "
        "UDP включён, формат 2025."),
    SIGNAL_FLAT: (
        "Данные о проскальзывании приходят нулями — коуч не видит срывов, "
        "даже когда они есть."),
    SIGNAL_IMPLAUSIBLE: (
        "Значения проскальзывания вне физического диапазона — раскладка "
        "пакета не сходится, порогам верить нельзя."),
    SIGNAL_SWAPPED: (
        "Под газом буксуют передние колёса, а не задние — порядок колёс в "
        "телеметрии не сходится. Коуч назвал бы не то колесо."),
    SIGNAL_WARMING_UP: "Коуч ещё набирает данные.",
}


@dataclass
class CoachHealth:
    """Один экземпляр на сессию. Кормится из того же тика, что и детекторы."""

    frames: int = 0
    moving_frames: int = 0
    live_frames: int = 0          # кадры движения с ненулевым проскальзыванием
    max_slip_ratio: float = 0.0
    max_slip_angle: float = 0.0
    drive_frames: int = 0         # кадры под сильным газом
    front_driven_frames: int = 0  # из них те, где перед буксует сильнее зада
    mistakes: int = 0
    spoken: int = 0
    silence: dict[str, int] = field(default_factory=dict)

    def reset(self) -> None:
        self.frames = 0
        self.moving_frames = 0
        self.live_frames = 0
        self.max_slip_ratio = 0.0
        self.max_slip_angle = 0.0
        self.drive_frames = 0
        self.front_driven_frames = 0
        self.mistakes = 0
        self.spoken = 0
        self.silence.clear()

    # ── Сбор ────────────────────────────────────────────────────────────────

    def observe_frame(self, frame: dict) -> None:
        """Кадр телеметрии движения. Ошибка здесь не имеет права ронять тик —
        диагностика, ломающая заезд, бессмысленна."""
        self.frames += 1
        try:
            speed = float(frame.get("speed_kmh") or 0.0)
            if speed < MIN_MOVING_KMH:
                return
            self.moving_frames += 1

            ratio = frame.get("slip_ratio") or {}
            angle = frame.get("slip_angle") or {}
            peak_ratio = max((abs(float(v)) for v in ratio.values()), default=0.0)
            peak_angle = max((abs(float(v)) for v in angle.values()), default=0.0)
            self.max_slip_ratio = max(self.max_slip_ratio, peak_ratio)
            self.max_slip_angle = max(self.max_slip_angle, peak_angle)
            if peak_ratio > 0.0 or peak_angle > 0.0:
                self.live_frames += 1

            self._observe_drive(frame, ratio)
        except (TypeError, ValueError):
            return

    def _observe_drive(self, frame: dict, ratio: dict) -> None:
        """Проверка порядка колёс по ВЕДУЩЕЙ оси.

        Это единственный способ поймать перепутанный порядок, не садясь за руль.
        Формула F1 — заднеприводная, и передние колёса под газом буксовать НЕ
        МОГУТ: они ничем не приводятся. Если под сильным газом положительное
        проскальзывание систематически больше на передних, значит пары
        переставлены местами — и коуч назвал бы не то колесо, уверенно.

        Ровно этого опасается запись в CONTEXT.md про порядок `RL, RR, FL, FR`:
        «перепутав его, коуч уверенно называл бы не то колесо, и пилот чинил бы
        то, что не сломано»."""
        throttle = float(frame.get("throttle_pct") or 0.0)
        brake = float(frame.get("brake_pct") or 0.0)
        if throttle < DRIVE_CHECK_MIN_THROTTLE_PCT or brake > 0.0:
            return
        rear = max((float(ratio.get(w, 0.0)) for w in ("rl", "rr")), default=0.0)
        front = max((float(ratio.get(w, 0.0)) for w in ("fl", "fr")), default=0.0)
        self.drive_frames += 1
        if front > rear + DRIVE_CHECK_MARGIN:
            self.front_driven_frames += 1

    def note_mistake(self, *, repeated: bool) -> None:
        """Детектор закрыл срыв. `repeated=False` — правило повтора не пустило
        его в эфир, и это отдельная причина молчания, а не отсутствие ошибок."""
        self.mistakes += 1
        if not repeated:
            self.note_silence("mistake_repeat_rule")

    def note_spoken(self) -> None:
        self.spoken += 1

    def note_silence(self, reason: str) -> None:
        if not reason:
            return
        self.silence[reason] = self.silence.get(reason, 0) + 1

    # ── Вывод ───────────────────────────────────────────────────────────────

    @property
    def wheels_swapped(self) -> bool:
        """Систематическая пробуксовка передних под газом. Формула
        заднеприводная — иначе быть не может, значит переставлены пары."""
        if self.drive_frames < DRIVE_CHECK_MIN_FRAMES:
            return False
        return (self.front_driven_frames / self.drive_frames
                >= DRIVE_CHECK_SWAPPED_SHARE)

    @property
    def signal(self) -> str:
        if self.frames == 0:
            return SIGNAL_NO_FRAMES
        if (self.max_slip_ratio > SANE_MAX_SLIP_RATIO
                or self.max_slip_angle > SANE_MAX_SLIP_ANGLE):
            return SIGNAL_IMPLAUSIBLE
        if self.wheels_swapped:
            return SIGNAL_SWAPPED
        if self.moving_frames < MIN_FRAMES_FOR_VERDICT:
            return SIGNAL_WARMING_UP
        if self.live_frames == 0:
            return SIGNAL_FLAT
        return SIGNAL_OK

    def reason(self, *, coach_enabled: bool) -> str | None:
        """Одна строка «почему молчит», либо None — если объяснять нечего.

        Порядок проверок — это порядок ДЕЙСТВИЙ пилота: сначала то, что чинится
        в настройках игры, потом то, что чинится в настройках приложения, и
        только потом то, что чинится за рулём."""
        signal = self.signal
        # Сломанный поток данных бьёт всё остальное, включая тумблер: коуч,
        # называющий не то колесо, — проблема выше уровнем, чем выключенный
        # коуч.
        if signal in (SIGNAL_NO_FRAMES, SIGNAL_FLAT, SIGNAL_IMPLAUSIBLE,
                      SIGNAL_SWAPPED):
            return _SIGNAL_RU[signal]
        if not coach_enabled:
            return SILENCE_RU["coach_disabled_in_settings"]
        if signal == SIGNAL_WARMING_UP:
            return _SIGNAL_RU[signal]
        if self.spoken > 0:
            # Коуч говорит. Объяснять молчание, которого нет, — значит сеять
            # сомнение в работающей функции.
            return None
        if self.mistakes == 0:
            return ("Сигнал есть, срывов не найдено: либо едешь чисто, "
                    "либо пороги детектора завышены.")
        dominant = self._dominant_silence()
        if dominant is not None:
            return SILENCE_RU.get(dominant)
        return None

    def _dominant_silence(self) -> str | None:
        """Самая частая причина. При равенстве — стабильный порядок по имени,
        иначе отчёт менялся бы от запуска к запуску на одних и тех же данных."""
        if not self.silence:
            return None
        known = {k: v for k, v in self.silence.items() if k in SILENCE_RU}
        if not known:
            return None
        return max(known.items(), key=lambda pair: (pair[1], pair[0]))[0]

    def to_dict(self, *, coach_enabled: bool) -> dict:
        return {
            "signal": self.signal,
            "frames": self.frames,
            "moving_frames": self.moving_frames,
            "mistakes": self.mistakes,
            "spoken": self.spoken,
            "silence": dict(self.silence),
            "reason": self.reason(coach_enabled=coach_enabled),
            "enabled": bool(coach_enabled),
            # Действующие пороги — чтобы «пороги завышены» можно было проверить,
            # а не принимать на веру. Те же самые числа, из модуля детектора:
            # своей копии здесь нет по построению.
            "thresholds": {
                "lockup_slip": slip_mod.LOCKUP_SLIP,
                "wheelspin_slip": slip_mod.WHEELSPIN_SLIP,
                "understeer_slip_angle": slip_mod.UNDERSTEER_SLIP_ANGLE,
                "oversteer_slip_angle": slip_mod.OVERSTEER_SLIP_ANGLE,
                "min_event_duration_s": slip_mod.MIN_EVENT_DURATION_S,
            },
            "peak_slip_ratio": round(self.max_slip_ratio, 3),
            "peak_slip_angle": round(self.max_slip_angle, 3),
        }
