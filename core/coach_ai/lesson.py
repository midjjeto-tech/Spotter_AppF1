"""
core/coach_ai/lesson.py
========================
Вердикт сессии — то, ради чего пилот открывает экран «Итоги».

До этого модуля дебриф показывал цифры: консистентность 78%, слабый сектор S2,
дельта темпа +0,4 с, топ-3 поворота по числу ошибок, таблица отклонений. Всё
правда, и всё вместе не отвечает ни на один вопрос, который у пилота есть после
заезда: сколько я оставил на трассе, где именно, и что делать в следующий раз.
Экран цифр без вывода — это отчёт, а не разбор.

Три вещи, которые здесь появляются:

    ПОТЕНЦИАЛ  — круг, собранный из твоих же лучших поворотов. Не чужой темп и
                 не мечта: каждый кусок ты уже проехал сам.
    КУДА УШЛО  — потери по поворотам в миллисекундах и долях, а не по счётчику
                 срывов: три блокировки в медленной шпильке могут стоить меньше
                 одной ошибки на быстром выходе.
    ЧТО ДАЛЬШЕ — одна строка. Не список из семи пунктов, который никто не
                 выполнит.

И четвёртая, если трасса знакомая: ПРОГРЕСС относительно прошлого визита. Без
него каждая сессия начинается с чистого листа, а пилот не видит, что стал
быстрее — единственное, ради чего он вообще тренируется.

Текст здесь, а не в UI, по двум причинам: урок уезжает в файл сессии вместе с
заездом (архив должен быть читаемым сам по себе), и вторая копия формулировок в
TypeScript разошлась бы с этой при первой же правке.
"""
from __future__ import annotations

from dataclasses import replace

from core.coach_ai.cost import LapPotential
from core.coach_ai.diagnosis import CornerDiagnosis
from core.coach_ai.focus import Focus
from core.num_to_words import ru_plural

#: Сколько поворотов показывать в разборе. Больше трёх — это уже не вывод, а
#: та же таблица, из которой пилот опять сам выбирает, чем заняться.
TOP_LOSSES = 3

#: Ниже этого запас круга не стоит называть: он в пределах точности замера
#: времени поворота и обещал бы то, чего нет.
MIN_POTENTIAL_GAIN_MS = 150

#: Доля топ-двойки, при которой честно сказать «потеря сосредоточена».
CONCENTRATED_SHARE = 0.6

#: Доля, выше которой говорим «вся потеря», а не проценты. См.
#: `_concentration_sentence`.
ALL_LOSS_SHARE = 0.97


def build_lesson(diagnoses: list[CornerDiagnosis],
                 potential: LapPotential | None,
                 focus: Focus | None = None,
                 previous: dict | None = None) -> dict | None:
    """Урок сессии, либо None — если говорить пока не о чем.

    None, а не пустой словарь с нулями: блок «Урок» на экране должен
    отсутствовать, пока данных нет, а не показывать прочерки. Прочерк читается
    как поломка."""
    losses = [d for d in diagnoses if d.cost_ms > 0]
    if potential is None and not losses:
        return None
    losses = _reconciled(losses, focus)

    total_loss = sum(d.cost_ms for d in losses)
    top = losses[:TOP_LOSSES]
    concentration = (sum(d.share for d in top) if total_loss > 0 else 0.0)

    lesson: dict = {
        "best_lap_ms": potential.best_lap_ms if potential else None,
        "potential_ms": potential.potential_ms if potential else None,
        "gain_ms": potential.gain_ms if potential else None,
        "potential_clamped": bool(potential.clamped) if potential else False,
        "total_loss_ms": round(total_loss),
        # Доля ПОКАЗАННЫХ поворотов в общей потере — экрану, чтобы он мог
        # сказать «остальное размазано по кругу», не пересчитывая ничего сам.
        "concentration": round(concentration, 3),
        "losses": [d.to_dict() for d in top],
        "headline": _headline(top, potential, concentration),
        "next_step": _next_step(losses),
        "focus": focus.to_dict() if focus is not None else None,
    }
    progress = _progress(previous, losses, potential)
    if progress is not None:
        lesson["progress"] = progress
    return lesson


# ── Формулировки ─────────────────────────────────────────────────────────────

def _headline(top: list[CornerDiagnosis], potential: LapPotential | None,
              concentration: float) -> str:
    """Одна строка про сессию целиком.

    `concentration` здесь НЕ используется для процента в тексте: она считается
    по всем показанным поворотам, а фраза называет только два. Процент обязан
    относиться ровно к тем поворотам, которые назвали, иначе разбор говорит
    «сто процентов потери в двух поворотах», перечислив их два из трёх."""
    pair = top[:2]
    if _potential_is_promisable(potential):
        head = (f"В круге осталось {_sec(potential.gain_ms)}: "
                f"потенциал {_lap_time(potential.potential_ms)} "
                f"против {_lap_time(potential.best_lap_ms)}.")
        if _is_concentrated(pair):
            return head + " " + _concentration_sentence(pair)
        return head

    if _is_concentrated(pair):
        return _concentration_sentence(pair)
    if top:
        return (f"Основная потеря круга — в {_corner_word(1)} "
                f"{_corner_list(top[:1])}: {_sec(top[0].cost_ms)} за круг.")
    return "Круг ровный: рутинных потерь по поворотам не видно."


def _reconciled(losses: list[CornerDiagnosis],
                focus: Focus | None) -> list[CornerDiagnosis]:
    """Урок не должен спорить сам с собой про один и тот же поворот.

    Разбор живого заезда 2026-08-11: в `losses` Turn 17 шёл с «причина не
    найдена», а блок `focus` про ТОТ ЖЕ поворот говорил «проходишь апекс
    медленнее, чем умеешь». Технически расхождение законное — диагноз считается
    по всей сессии, фокус по последним кругам, и рутинного отклонения за сессию
    там действительно не набралось. Но на экране это выглядит как спор с самим
    собой, а пилот читает оба блока сразу.

    Правило: если у потери причины нет, а фокус по этому повороту её знает —
    берём её оттуда. Придумывать причину, которой не нашли ОБА, по-прежнему
    нельзя: `cause: null` остаётся законным ответом.
    """
    if focus is None or not focus.cause:
        return losses
    out: list[CornerDiagnosis] = []
    for row in losses:
        if row.corner_id == focus.corner_id and not row.cause:
            row = replace(row, cause=focus.cause, cause_kind=focus.cause_kind,
                          evidence=focus.evidence)
        out.append(row)
    return out


def _potential_is_promisable(potential: LapPotential | None) -> bool:
    """Можно ли назвать пилоту это число вслух.

    Два условия, и второе добавлено по разбору живого заезда 2026-08-11.
    Заголовок обещал «В круге осталось 11,42 с» — потенциал 1:17,76 при лучшем
    круге 1:29,18 и сумме всех найденных потерь 0,93 с. Обещание было на порядок
    больше того, что разбор сумел объяснить, и на десять секунд быстрее
    собственного эталона трассы.

    `clamped` означает, что хотя бы один поворот упёрся в `MAX_CORNER_GAIN_MS`,
    то есть его «запас» превысил две секунды. Модуль цены прямо говорит, что это
    не запас техники, а разворот или сбитый замер. Раз само вычисление знает,
    что в него попало неправдоподобное, обещать результат нельзя — остальные
    строки урока (главная потеря, следующий шаг) при этом работают как обычно, и
    число остаётся в данных для экрана.
    """
    if potential is None or potential.gain_ms < MIN_POTENTIAL_GAIN_MS:
        return False
    return not potential.clamped


def _is_concentrated(pair: list[CornerDiagnosis]) -> bool:
    return len(pair) >= 2 and sum(row.share for row in pair) >= CONCENTRATED_SHARE


def _concentration_sentence(pair: list[CornerDiagnosis]) -> str:
    """«Вся потеря» вместо «100% потери» — не косметика.

    Прогон разбора на синтетическом заезде дал «100% потери — в поворотах 3 и
    7»: формально верно, а читается как артефакт округления, будто число
    посчиталось неправильно. Пилот в такой строке усомнится ровно там, где
    цифра как раз точна."""
    share = sum(row.share for row in pair)
    corners = f"в {_corner_word(len(pair))} {_corner_list(pair)}"
    if share >= ALL_LOSS_SHARE:
        return f"Вся потеря круга — {corners}."
    return f"{int(round(share * 100))}% потери — {corners}."


def _next_step(losses: list[CornerDiagnosis]) -> str | None:
    """Одна вещь на следующий раз — и только та, с которой есть что делать."""
    actionable = [d for d in losses if d.actionable]
    if actionable:
        row = actionable[0]
        return (f"Следующий заезд начни с поворота {row.corner_id}: "
                f"{row.evidence}. Цена — {_sec(row.cost_ms)} за круг.")
    if losses:
        # Потери есть, причины нет — и врать про причину нельзя. Пилоту честнее
        # сказать, что они разовые, чем выдать догадку за вывод.
        return ("Потери есть, но повторяющейся причины не видно — "
                "они разовые. Поможет только ровный темп.")
    return None


def _progress(previous: dict | None, losses: list[CornerDiagnosis],
              potential: LapPotential | None) -> dict | None:
    """Сравнение с прошлым визитом на эту трассу.

    Прошлый урок приходит из архива как обычный JSON: любое поле может
    отсутствовать или оказаться не того типа, и ни одно из этого не повод
    потерять весь разбор."""
    if not isinstance(previous, dict):
        return None

    prev_best = _int_or_none(previous.get("best_lap_ms"))
    prev_focus = previous.get("focus")
    prev_corner = None
    prev_cost = None
    if isinstance(prev_focus, dict):
        prev_corner = _int_or_none(prev_focus.get("corner_id"))
        prev_cost = _int_or_none(prev_focus.get("current_ms"))
    if prev_corner is None:
        prev_losses = previous.get("losses")
        if isinstance(prev_losses, list) and prev_losses:
            first = prev_losses[0]
            if isinstance(first, dict):
                prev_corner = _int_or_none(first.get("corner_id"))
                prev_cost = _int_or_none(first.get("cost_ms"))

    now_by_corner = {d.corner_id: d.cost_ms for d in losses}
    now_cost = (round(now_by_corner.get(prev_corner, 0.0))
                if prev_corner is not None else None)

    best_delta = None
    if prev_best is not None and potential is not None:
        best_delta = potential.best_lap_ms - prev_best

    parts: list[str] = []
    if best_delta is not None:
        if best_delta < 0:
            parts.append(f"Быстрее прошлого визита на {_sec(-best_delta)}.")
        elif best_delta > 0:
            parts.append(f"Медленнее прошлого визита на {_sec(best_delta)}.")
        else:
            parts.append("Ровно как в прошлый визит.")
    if prev_corner is not None and prev_cost is not None and now_cost is not None:
        if now_cost < prev_cost:
            parts.append(
                f"В прошлый раз работали над поворотом {prev_corner}: "
                f"было {_sec(prev_cost)}, стало {_sec(now_cost)}.")
        elif now_cost > prev_cost:
            parts.append(
                f"Поворот {prev_corner}, над которым работали в прошлый раз, "
                f"стоит уже {_sec(now_cost)}.")
        else:
            parts.append(
                f"Поворот {prev_corner} с прошлого раза не сдвинулся.")

    if not parts:
        return None
    return {
        "previous_best_lap_ms": prev_best,
        "best_delta_ms": best_delta,
        "focus_corner_id": prev_corner,
        "focus_then_ms": prev_cost,
        "focus_now_ms": now_cost,
        "text": " ".join(parts),
    }


# ── Числа словами для экрана ─────────────────────────────────────────────────

def _sec(ms: float) -> str:
    """0,35 с — с запятой и без хвостового нуля. Экран, не эфир: в эфире те же
    величины произносит `core/num_to_words.py`, и правила там другие."""
    value = abs(float(ms)) / 1000.0
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    if not text:
        text = "0"
    return text.replace(".", ",") + " с"


def _lap_time(ms: int | None) -> str:
    if not ms or ms <= 0:
        return "—"
    minutes, rest = divmod(int(ms), 60_000)
    seconds, millis = divmod(rest, 1000)
    if minutes:
        return f"{minutes}:{seconds:02d},{millis // 10:02d}"
    return f"{seconds},{millis // 10:02d}"


def _corner_word(n: int) -> str:
    return ru_plural(n, "повороте", "поворотах", "поворотах")


def _corner_list(rows: list[CornerDiagnosis]) -> str:
    """Номерами, а не именами: имя есть у трети поворотов календаря, и все —
    латиницей (см. `core/radio/corner_words.py`). На экране номер ещё и точнее:
    пилот ищет его на схеме круга."""
    return " и ".join(str(row.corner_id) for row in rows)


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)
