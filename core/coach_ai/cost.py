"""
core/coach_ai/cost.py
======================
Сколько стоит ошибка — в миллисекундах на круг.

До этого модуля коуч знал ЧТО пилот делает не так (фаза 1), ГДЕ (привязка к
повороту) и КАК НАДО (фаза 2), но никогда — СКОЛЬКО ЭТО СТОИТ. За круг у пилота
набирается десяток неидеальных мест, и без цены он не может выбрать, чем
заняться: «блокируешь в седьмом» и «поздно на газ в третьем» звучат одинаково
важно, хотя одно может стоить три десятых, а второе четыре сотых. Ровно на этом
коуч и оставался набором наблюдений вместо тренера.

Здесь считаются две разные величины, и путать их нельзя:

    ЦЕНА ПОВОРОТА  — сколько ты РУТИННО теряешь в этом повороте относительно
                     собственного эталона. Медиана по кругам, а не худший
                     случай: тренируют привычку, а не один неудачный проезд.
    ПОТЕНЦИАЛ КРУГА — время круга, который сложился бы из твоих ЖЕ лучших
                     проездов каждого поворота. Это не фантазия и не чужой
                     темп: каждый кусок ты уже проехал сам.

**Нормализация та же, что в `compare.py`, и по той же причине.** Тяжёлая машина
на длинном стинте медленнее в КАЖДОМ повороте — если не вычесть общий сдвиг
круга, «цена» окажется у всех поворотов сразу, сумма надуется, и приоритет
потеряет смысл. Поэтому из разниц круга вычитается их же медиана: равномерное
отставание съедается, локальная потеря остаётся.

Пит-круги сюда не кормят: после въезда на пит-лейн метрики оставшихся поворотов
описывают проезд по другой траектории. Это ответственность вызывающего —
`core/engine.py` уже фильтрует их для `DriverCoach` по тому же признаку.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from core.coach_ai.models import CornerMetrics

#: Меньше — говорить о цене нечего: одна-две попытки это ещё не привычка.
MIN_LAPS = 3

#: Меньше сравнимых поворотов на круге — медиана круга неустойчива, и
#: нормализация превратится в шум. То же число и та же причина, что в compare.py.
MIN_COMPARABLE_CORNERS = 5

#: Ниже этого цена не считается ценой: на дистанции круга это дрожание замера,
#: а не потеря, которую пилот может отыграть.
MIN_COST_MS = 40.0

#: Сколько раз нужно проехать поворот, чтобы его ЛУЧШИЙ проезд можно было
#: считать достижимым, а не единичной удачей замера.
MIN_LAPS_FOR_BEST = 2

#: Потолок вклада ОДНОГО поворота в потенциал круга. Больше двух секунд
#: относительно собственного лучшего проезда — это не запас техники, это разворот
#: или сбитый замер, и обещать такой круг было бы враньём. Ограничение видно в
#: отчёте (`potential_clamped`), а не спрятано.
MAX_CORNER_GAIN_MS = 2000.0


@dataclass
class CornerCost:
    """Рутинная потеря в одном повороте.

    `share` — доля этого поворота в СУММЕ потерь, а не в круге: она отвечает на
    вопрос «сколько внимания сюда», а не «сколько процентов круга».
    """
    corner_id: int
    corner_name: str | None
    cost_ms: float
    laps: int
    share: float

    def to_dict(self) -> dict:
        return {
            "corner_id": self.corner_id, "corner_name": self.corner_name,
            "cost_ms": round(self.cost_ms), "laps": self.laps,
            "share": round(self.share, 3),
        }


@dataclass
class LapPotential:
    """Круг, который пилот уже проехал по частям."""
    best_lap_ms: int
    potential_ms: int
    gain_ms: int
    corners_counted: int
    clamped: bool        # хоть один вклад упёрся в MAX_CORNER_GAIN_MS

    def to_dict(self) -> dict:
        return {
            "best_lap_ms": self.best_lap_ms, "potential_ms": self.potential_ms,
            "gain_ms": self.gain_ms, "corners_counted": self.corners_counted,
            "potential_clamped": self.clamped,
        }


class CornerHistory:
    """Метрики поворотов по кругам за сессию. Один экземпляр на сессию.

    Памяти это стоит около восьмидесяти чисел на круг — столько же, сколько
    занимает эталон, ради которого хранилище уже заведено. Отдельного слоя
    хранения телеметрии не появляется и здесь.
    """

    #: Гонка длиннее этого — уже не гонка, а зависший заезд; держим окно, чтобы
    #: сессия, забытая на ночь, не съедала память бесконечно.
    MAX_LAPS = 200

    def __init__(self) -> None:
        self._laps: list[tuple[int, int, dict[int, CornerMetrics]]] = []

    def reset(self) -> None:
        self._laps.clear()

    def add_lap(self, lap: int, lap_time_ms: int,
                metrics: dict[int, CornerMetrics]) -> None:
        """Завершённый НЕ пит-круг. Круг без времени или без метрик не пишем:
        пустая запись только испортила бы медианы."""
        if lap_time_ms <= 0 or not metrics:
            return
        self._laps.append((lap, lap_time_ms, dict(metrics)))
        if len(self._laps) > self.MAX_LAPS:
            del self._laps[0]

    @property
    def lap_count(self) -> int:
        return len(self._laps)

    def to_rows(self) -> list[dict]:
        """Замеры по кругам в виде, пригодном для файла заезда.

        Зачем это в архиве, когда там уже лежит готовый урок. Урок — это ВЫВОД,
        а разбирать после заезда приходится ВХОД. Когда потенциал круга обещал
        11,4 с при 0,93 с фактически найденных потерь (заезд 2026-08-11),
        восстановить, на каком повороте и на каком круге сломался замер, было
        нечем: в записи лежал только результат. Теперь лежат и числа, из которых
        он посчитан.

        Формат плоский и самодостаточный: `corner_id` строками, потому что JSON
        всё равно сделает их строками, и читателю архива не придётся гадать,
        какой тип ключа он получит.
        """
        return [
            {
                "lap": lap,
                "lap_time_ms": lap_time_ms,
                "corners": {
                    str(corner_id): {
                        "duration_ms": m.duration_ms,
                        "brake_point_m": m.brake_point_m,
                        "min_speed_kmh": m.min_speed_kmh,
                        "throttle_point_m": m.throttle_point_m,
                    }
                    for corner_id, m in sorted(metrics.items())
                },
            }
            for lap, lap_time_ms, metrics in self._laps
        ]

    def costs(self, reference: dict[int, CornerMetrics],
              corner_names: dict[int, str] | None = None,
              window: int | None = None) -> list[CornerCost]:
        """Цена каждого поворота, от дорогого к дешёвому.

        `window` — считать только по последним N кругам. Без него это ИТОГ
        сессии (для разбора), с ним — то, как пилот едет СЕЙЧАС (для работы над
        ошибкой). Разница принципиальная: медиана по всей сессии почти не
        двигается, когда пилот исправился на десятом круге из двадцати, и коуч,
        меряющий прогресс по ней, не заметил бы исправления до самого финиша.

        Пустой список — это «сказать нечего», а не «всё идеально»: причин
        молчания три (мало кругов, мало сравнимых поворотов, все потери ниже
        порога), и различает их вызывающий по `lap_count`."""
        laps = self._window(window)
        if len(laps) < MIN_LAPS or not reference:
            return []
        names = corner_names or {}

        # Превышения по кругам: {corner_id: [нормализованное превышение, ...]}
        excess: dict[int, list[float]] = {}
        for _lap, _lap_ms, metrics in laps:
            deltas = _duration_deltas(metrics, reference)
            if len(deltas) < MIN_COMPARABLE_CORNERS:
                continue
            base = median(deltas.values())
            for corner_id, raw in deltas.items():
                excess.setdefault(corner_id, []).append(raw - base)

        total = 0.0
        rows: list[CornerCost] = []
        for corner_id, values in excess.items():
            if len(values) < MIN_LAPS:
                continue
            # Медиана, а не среднее: один вылет не должен назначать поворот
            # главной проблемой сессии — тренируют привычку, а не случай.
            cost = median(values)
            if cost < MIN_COST_MS:
                continue
            rows.append(CornerCost(
                corner_id=corner_id, corner_name=names.get(corner_id),
                cost_ms=round(cost, 1), laps=len(values), share=0.0))
            total += cost

        if total <= 0:
            return []
        for row in rows:
            row.share = row.cost_ms / total
        rows.sort(key=lambda r: (-r.cost_ms, r.corner_id))
        return rows

    def _window(self, window: int | None,
                ) -> list[tuple[int, int, dict[int, CornerMetrics]]]:
        if window is None or window <= 0:
            return self._laps
        return self._laps[-window:]

    def metric_badness(self, reference: dict[int, CornerMetrics],
                       window: int | None = None,
                       ) -> dict[int, dict[str, float]]:
        """Рутинное отклонение по метрикам-ПРИЧИНАМ: {поворот: {метрика: сверх
        порога}}.

        Значение — отношение превышения к порогу значимости той же метрики, а не
        сама величина: метры и километры в час несравнимы напрямую, и без
        приведения к порогу метры всегда обыгрывали бы скорость. Больше единицы
        = отклонение настоящее.

        Это тот же расчёт, что делает `compare.compare_lap` для ОДНОГО круга, но
        по медиане кругов: причина, объясняющая рутинную потерю, обязана быть
        рутинной сама. Пороги берутся из `compare.METRICS`, своей копии здесь
        нет."""
        laps = self._window(window)
        if len(laps) < MIN_LAPS or not reference:
            return {}
        # Импорт внутри функции: на уровне модуля он ни к чему, а так видно, что
        # таблица порогов приезжает из соседа и не дублируется здесь.
        from core.coach_ai import compare

        samples: dict[int, dict[str, list[float]]] = {}
        for _lap, _lap_ms, metrics in laps:
            for metric in compare.CAUSE_METRICS:
                field, sign, threshold = compare.METRICS[metric]
                deltas = _field_deltas(metrics, reference, field)
                if len(deltas) < MIN_COMPARABLE_CORNERS:
                    continue
                base = median(deltas.values())
                for corner_id, raw in deltas.items():
                    samples.setdefault(corner_id, {}).setdefault(
                        metric, []).append((raw - base) * sign / threshold)

        out: dict[int, dict[str, float]] = {}
        for corner_id, per_metric in samples.items():
            row = {metric: round(median(values), 2)
                   for metric, values in per_metric.items()
                   if len(values) >= MIN_LAPS}
            if row:
                out[corner_id] = row
        return out

    def potential(self) -> LapPotential | None:
        """Круг из собственных лучших проездов каждого поворота.

        Эталон здесь НЕ участвует намеренно: карьерный лучший круг мог быть снят
        на другой машине и другом топливе, и потенциал, посчитанный от него,
        обещал бы недостижимое. Здесь всё своё и всё сегодняшнее.

        **Нормализация обязательна и здесь.** Шапка модуля объясняет почему для
        `costs()`, и ровно та же причина работает для потенциала: тяжёлая машина
        медленнее в КАЖДОМ повороте, и если складывать сырые лучшие проезды, то
        «лучший» каждого поворота приедет с самого лёгкого круга, а сумма таких
        подарков по всем поворотам станет фантазией. Разбор живого заезда
        2026-08-11 показал цену: 11418 мс «потенциала» при 932 мс фактически
        найденных потерь, то есть обещание круга на десять секунд быстрее
        собственного эталона трассы.

        Считаем не длительность, а её отклонение от медианы СВОЕГО круга:
        общий сдвиг круга уходит, локальная потеря остаётся. Абсолютное значение
        отклонения смысла не имеет, а вот разница между кругами по одному и тому
        же повороту — это и есть «здесь ты умеешь быстрее»."""
        if len(self._laps) < MIN_LAPS:
            return None

        # {corner_id: [нормализованное отклонение по кругам]} + отклонения
        # лучшего круга отдельно. Круг, где сравнивать нечего, не участвует
        # вовсе: медиана по трём поворотам — это не сдвиг круга, а шум.
        normalized: dict[int, list[float]] = {}
        best_lap_ms: int | None = None
        best_norm: dict[int, float] = {}
        for _lap, lap_ms, metrics in self._laps:
            durations = {
                corner_id: float(m.duration_ms)
                for corner_id, m in metrics.items()
                if m.duration_ms and m.duration_ms > 0
            }
            if len(durations) < MIN_COMPARABLE_CORNERS:
                continue
            base = median(durations.values())
            lap_norm = {cid: value - base for cid, value in durations.items()}
            for corner_id, value in lap_norm.items():
                normalized.setdefault(corner_id, []).append(value)
            if best_lap_ms is None or lap_ms < best_lap_ms:
                best_lap_ms, best_norm = lap_ms, lap_norm

        if best_lap_ms is None:
            return None

        gain = 0.0
        counted = 0
        clamped = False
        for corner_id, value in best_norm.items():
            samples = normalized.get(corner_id, ())
            # Минимум по одному-двум замерам не эталон, а выброс.
            if len(samples) < MIN_LAPS_FOR_BEST:
                continue
            corner_gain = value - min(samples)
            if corner_gain <= 0:
                counted += 1
                continue
            if corner_gain > MAX_CORNER_GAIN_MS:
                corner_gain = MAX_CORNER_GAIN_MS
                clamped = True
            gain += corner_gain
            counted += 1

        if counted == 0 or gain >= best_lap_ms:
            return None
        return LapPotential(
            best_lap_ms=int(best_lap_ms),
            potential_ms=int(round(best_lap_ms - gain)),
            gain_ms=int(round(gain)),
            corners_counted=counted,
            clamped=clamped,
        )


def _duration_deltas(current: dict[int, CornerMetrics],
                     reference: dict[int, CornerMetrics]) -> dict[int, float]:
    """Разницы времени прохождения по поворотам, где оно есть с ОБЕИХ сторон."""
    out: dict[int, float] = {}
    for corner_id, cur in current.items():
        ref = reference.get(corner_id)
        if ref is None:
            continue
        a, b = cur.duration_ms, ref.duration_ms
        if not a or not b or a <= 0 or b <= 0:
            continue
        out[corner_id] = float(a) - float(b)
    return out


def _field_deltas(current: dict[int, CornerMetrics],
                  reference: dict[int, CornerMetrics],
                  field: str) -> dict[int, float]:
    """То же по любому полю метрик. Отсутствие значения с любой стороны — не
    ноль, а «сравнивать нечего»: пологая связка проходится без тормоза, и
    подставленный ноль сделал бы из этого рекордную точку торможения."""
    out: dict[int, float] = {}
    for corner_id, cur in current.items():
        ref = reference.get(corner_id)
        if ref is None:
            continue
        a, b = getattr(cur, field), getattr(ref, field)
        if a is None or b is None:
            continue
        out[corner_id] = float(a) - float(b)
    return out
