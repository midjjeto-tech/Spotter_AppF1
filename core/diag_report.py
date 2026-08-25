"""
core/diag_report.py
====================
Полевой журнал → один читаемый отчёт по пунктам.

Журнал (`core/field_log.py`) отвечает на любой вопрос про заезд, но платит за это
объёмом: двадцать кругов дают тысячи строк JSONL, и «прислать лог» перестаёт быть
действием, которое можно выполнить одним сообщением. Отчёт сжимает журнал до
проверок с вердиктом — по одной на подсистему, с цифрами, на которых вердикт
стоит, и с последствием, если вердикт плохой.

**Каждая проверка обязана уметь сказать «НЕТ ДАННЫХ».** Это третий вердикт рядом
с «ОК» и «ПРОБЛЕМА», и он не формальность: «коуч молчал, потому что сигнала не
было» и «коуч молчал, потому что порог не взят» требуют противоположных действий,
а отсутствие раздела между ними не различает.

Чистый модуль: на входе разобранные записи журнала, на выходе текст. Никакого
I/O — файлы читает `tools/diagnose.py`, и поэтому каждая проверка проверяется
питоновским тестом на синтетическом журнале, а не глазами на живом заезде.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

OK = "ОК"
PROBLEM = "ПРОБЛЕМА"
WARN = "ВНИМАНИЕ"
NODATA = "НЕТ ДАННЫХ"

#: Сколько строк-улик показывает одна проверка. Отчёт должен помещаться в одно
#: сообщение целиком — иначе он повторяет судьбу журнала, который сжимает.
MAX_EVIDENCE_LINES = 8

#: Пакеты F1 UDP: номер -> (имя, что сломается без него).
F1_PACKETS: dict[int, tuple[str, str]] = {
    0:  ("Motion", "споттер и радар"),
    1:  ("Session", "тип сессии, трасса, погода"),
    2:  ("Lap Data", "круги, позиции, отрывы — без него не работает ничего"),
    3:  ("Event", "обгоны, штрафы, флаги, сходы"),
    4:  ("Participants", "имена и команды пилотов"),
    5:  ("Car Setups", "блок «Гараж»"),
    6:  ("Car Telemetry", "HUD, вводы пилота, температуры"),
    7:  ("Car Status", "резина, топливо, ERS"),
    8:  ("Final Classification", "итоговая таблица"),
    9:  ("Lobby Info", "лобби (не используется)"),
    10: ("Car Damage", "повреждения и износ резины"),
    11: ("Session History", "положение в поле по секторам, дуэль с напарником"),
    12: ("Tyre Sets", "комплекты резины для стратегии"),
    13: ("Motion Ex", "ВЕСЬ коуч пилотажа — все четыре фазы"),
    14: ("Time Trial", "тайм-атака (не используется)"),
    15: ("Lap Positions", "карта гонки (не используется)"),
}

#: Без этих пакетов заявленные функции не работают вовсе.
ESSENTIAL_PACKETS = (1, 2, 6, 7)

#: Эти нужны конкретным функциям: их отсутствие — не поломка приложения, но
#: молчание подсистемы, и пользователь должен узнать причину.
FEATURE_PACKETS = (13, 11, 5, 10, 0)

#: Синтетический ключ переписи у iRacing — там нет пакетов с номерами.
IRACING_SNAPSHOT_KEY = "-1"

#: Причина молчания -> человеческая формулировка. Своей копии нет: берём ту же
#: таблицу, что показывает экран, иначе отчёт и приложение объясняли бы одно и
#: то же разными словами.
try:  # pragma: no cover — модуль коуча всегда на месте в рабочем дереве
    from core.coach_ai.health import SILENCE_RU
except Exception:  # noqa: BLE001
    SILENCE_RU = {}



# ── Сигналы лога ─────────────────────────────────────────────────────────────
#
# `_check_errors` смотрит только на ERROR/Traceback, и этого оказалось мало.
# Провайдер LLM логирует отказы на WARNING — и правильно, он их обработал, — а
# значит заезд 08-19, где GigaChat был мёртв ОТ СТАРТА ДО ФИНИША (80 строк, 17
# отказов TLS), разбор объявлял чистым: «ошибок не найдено». Отчёт, зелёный на
# сломанном заезде, хуже отсутствующего — ровно то, о чём шапка этого модуля.
#
# Ловятся ИМЕНОВАННЫЕ сигналы, а не все предупреждения подряд: у каждого есть
# проверка, которая умеет его истолковать. Общее ведро из WARNING утопило бы
# отчёт в шуме и повторило бы судьбу журнала, который он сжимает.
LLM_OK_RE = re.compile(r"(GigaChat|YandexGPT) ответил впервые")
LLM_FAIL_RE = re.compile(
    r"(GigaChat|YandexGPT) generate failed"
    r"|уходим на шаблоны"
    r"|CERTIFICATE_VERIFY_FAILED"
    r"|(GigaChat|YandexGPT) init failed"
    r"|SDK not installed")
NAME_FAIL_RE = re.compile(r"имя не разрешилось|нет варианта без имени")

#: Что `tools/diagnose.py` обязан вытащить из лога сверх ошибок.
LOG_SIGNAL_RE = re.compile(
    "|".join(r.pattern for r in (LLM_OK_RE, LLM_FAIL_RE, NAME_FAIL_RE)))

@dataclass
class Check:
    number: int
    title: str
    verdict: str
    lines: list[str] = field(default_factory=list)
    action: str | None = None

    @property
    def bad(self) -> bool:
        return self.verdict in (PROBLEM, WARN)


@dataclass
class Report:
    header: list[str]
    checks: list[Check]

    @property
    def problems(self) -> list[Check]:
        return [c for c in self.checks if c.bad]

    def to_text(self) -> str:
        out: list[str] = ["SPOTTER APP — ДИАГНОСТИКА ЗАЕЗДА", "=" * 62]
        out.extend(self.header)
        out.append("")
        for check in self.checks:
            # Выравнивание по фиксированной колонке, а не по длине заголовка:
            # у «[10]» номер шире, и вердикты десятого пункта уезжали вправо.
            prefix = f"[{check.number}] {check.title} "
            out.append(prefix.ljust(50, ".") + " " + check.verdict)
            for line in check.lines[:MAX_EVIDENCE_LINES]:
                out.append(f"    {line}")
            if check.action:
                out.append(f"    -> {check.action}")
            out.append("")
        out.append("=" * 62)
        problems = self.problems
        if problems:
            out.append(f"ИТОГО: требуют внимания — {len(problems)}")
            for check in problems:
                out.append(f"  [{check.number}] {check.title}: {check.verdict}")
        else:
            out.append("ИТОГО: проблем не найдено")
        return "\n".join(out)


# ── Сборка ───────────────────────────────────────────────────────────────────

def build_report(records: list[dict], log_errors: list[str] | None = None,
                 source_name: str | None = None,
                 log_signals: list[str] | None = None) -> Report:
    """Отчёт по разобранным записям журнала."""
    by_kind: dict[str, list[dict]] = {}
    for record in records:
        if isinstance(record, dict):
            by_kind.setdefault(str(record.get("kind") or "?"), []).append(record)

    return Report(
        header=_header(by_kind, records, source_name),
        checks=[
            _check_environment(by_kind),
            _check_packets(by_kind),
            _check_track(by_kind),
            _check_coach_signal(by_kind),
            _check_mistakes(by_kind),
            _check_reference(by_kind),
            _check_lesson(by_kind),
            _check_field_pace(by_kind),
            _check_silence(by_kind),
            _check_llm(log_signals or []),
            _check_names(log_signals or []),
            _check_errors(log_errors or []),
        ],
    )


def _header(by_kind, records, source_name) -> list[str]:
    lines = []
    if source_name:
        lines.append(f"журнал: {source_name}")
    lines.append(f"записей: {len(records)}")
    # Журнал пишется на живом заезде и может оборваться на середине строки:
    # не-словарь здесь нормальный вход, а не повод потерять весь отчёт.
    times = [r.get("t") for r in records
             if isinstance(r, dict) and isinstance(r.get("t"), (int, float))]
    if len(times) >= 2:
        minutes = (max(times) - min(times)) / 60.0
        lines.append(f"длительность: {minutes:.1f} мин")
    laps = _laps_seen(by_kind)
    lines.append(f"кругов в журнале: {laps if laps else 'нет'}")
    return lines


def _laps_seen(by_kind) -> int:
    laps = {r.get("lap") for kind in ("signals", "packets", "coach_lesson")
            for r in by_kind.get(kind, []) if isinstance(r.get("lap"), int)}
    return len(laps)


# ── Проверки ─────────────────────────────────────────────────────────────────

def _check_environment(by_kind) -> Check:
    starts = by_kind.get("session_start", [])
    if not starts:
        return Check(1, "ОКРУЖЕНИЕ И НАСТРОЙКИ", NODATA,
                     ["журнал не содержит снимка запуска"],
                     "журнал начат не с запуска приложения — снимите заново")
    env = starts[-1]
    lines = [
        f"версия {env.get('app_version', '?')}"
        f"{' (EXE)' if env.get('frozen') else ' (из исходников)'}"
        f", источник {env.get('telemetry_source', '?')}, {env.get('udp', '?')}",
        f"коуч: {'ВКЛ' if env.get('driving_coach_enabled') else 'ВЫКЛ'}"
        f", LLM {env.get('llm_provider', '?')}"
        f", персона {env.get('persona', '?')}"
        f", стиль радио {env.get('radio_style', '?')}",
    ]
    thresholds = env.get("coach_thresholds")
    if isinstance(thresholds, dict):
        lines.append("пороги коуча: " + ", ".join(
            f"{k}={v}" for k, v in list(thresholds.items())[:5]))
    verdict = OK
    action = None
    if not env.get("driving_coach_enabled"):
        verdict = WARN
        action = "коуч выключен — всё, что ниже про него, объясняется этим"
    return Check(1, "ОКРУЖЕНИЕ И НАСТРОЙКИ", verdict, lines, action)


def _check_packets(by_kind) -> Check:
    records = by_kind.get("packets", [])
    if not records:
        return Check(2, "ПАКЕТЫ ТЕЛЕМЕТРИИ", NODATA,
                     ["перепись пакетов пуста — ни одного завершённого круга"],
                     "проехать хотя бы один круг с включённой диагностикой")

    totals: dict[str, int] = {}
    for record in records:
        counts = record.get("counts")
        if isinstance(counts, dict):
            for key, value in counts.items():
                if isinstance(value, int):
                    totals[str(key)] = totals.get(str(key), 0) + value

    if IRACING_SNAPSHOT_KEY in totals:
        return Check(
            2, "ПАКЕТЫ ТЕЛЕМЕТРИИ", WARN,
            [f"источник iRacing: снимков общей памяти {totals[IRACING_SNAPSHOT_KEY]}",
             "адаптер iRacing не отдаёт ни MotionEx, ни сетапов, ни истории сессии"],
            "на iRacing не работают: коуч (все фазы), «Гараж», положение в поле")

    present = {int(k) for k, v in totals.items() if k.lstrip("-").isdigit() and v > 0}
    missing_essential = [p for p in ESSENTIAL_PACKETS if p not in present]
    missing_feature = [p for p in FEATURE_PACKETS if p not in present]

    # Скобки обязательны: `+` связывает раньше `or`, и без них фолбэк относился
    # к уже склеенной строке — то есть был мёртв (префикс всегда непустой), а
    # отчёт при нераспознанных пакетах обрывался на «приходят: ».
    arriving = ", ".join(
        f"{p} {F1_PACKETS.get(p, ('?', ''))[0]}" for p in sorted(present))
    lines = ["приходят: " + (arriving or "ничего")]
    for packet in missing_essential + missing_feature:
        name, breaks = F1_PACKETS.get(packet, ("?", "?"))
        lines.append(f"НЕТ {packet} {name} -> не работает: {breaks}")

    if missing_essential:
        return Check(2, "ПАКЕТЫ ТЕЛЕМЕТРИИ", PROBLEM, lines,
                     "в игре: настройки -> телеметрия -> UDP включён, формат 2025")
    if missing_feature:
        return Check(2, "ПАКЕТЫ ТЕЛЕМЕТРИИ", PROBLEM, lines,
                     "проверить формат UDP в игре: часть пакетов не шлётся")
    return Check(2, "ПАКЕТЫ ТЕЛЕМЕТРИИ", OK, lines)


def _check_track(by_kind) -> Check:
    records = by_kind.get("track", [])
    if not records:
        return Check(3, "ТРАССА И РАЗМЕТКА ПОВОРОТОВ", NODATA,
                     ["смена трассы в журнале не отмечена"])
    last = records[-1]
    corners = last.get("corners")
    lines = [f"track_id={last.get('track_id')} -> {last.get('track') or '—'}"
             f", поворотов размечено: {corners if corners is not None else '—'}"]
    types = last.get("types")
    if isinstance(types, dict) and types:
        lines.append("типы: " + ", ".join(f"{k} {v}" for k, v in sorted(types.items())))
    if not corners:
        return Check(3, "ТРАССА И РАЗМЕТКА ПОВОРОТОВ", PROBLEM, lines,
                     "без разметки коуч не назовёт место и не построит разбор")
    return Check(3, "ТРАССА И РАЗМЕТКА ПОВОРОТОВ", OK, lines)


def _check_coach_signal(by_kind) -> Check:
    records = by_kind.get("signals", [])
    channels: dict[str, dict] = {}
    for record in records:
        for name, stat in (record.get("channels") or {}).items():
            if not isinstance(stat, dict):
                continue
            acc = channels.setdefault(name, {"n": 0, "min": None, "max": None,
                                             "over": 0})
            acc["n"] += int(stat.get("n") or 0)
            for key in ("min", "max"):
                value = stat.get(key)
                if isinstance(value, (int, float)):
                    current = acc[key]
                    if current is None:
                        acc[key] = value
                    elif key == "min":
                        acc[key] = min(current, value)
                    else:
                        acc[key] = max(current, value)
            over = stat.get("over")
            if isinstance(over, dict):
                acc["over"] += sum(v for v in over.values() if isinstance(v, int))

    if not channels:
        return Check(4, "СИГНАЛ КОУЧА (проскальзывание)", NODATA,
                     ["распределений нет: пакет MotionEx не разбирался"],
                     "см. пункт 2 — приходит ли пакет 13")

    slip = {k: v for k, v in channels.items()
            if k.startswith(("lockup.", "wheelspin.", "slip_angle."))}
    lines = []
    for name, acc in sorted(slip.items())[:6]:
        lines.append(f"{name}: n={acc['n']} min={acc['min']} max={acc['max']} "
                     f"порог взят {acc['over']} раз")

    flat = all(abs(acc.get("min") or 0) < 1e-6 and abs(acc.get("max") or 0) < 1e-6
               for acc in slip.values()) if slip else True
    never = slip and all(acc["over"] == 0 for acc in slip.values())
    if flat:
        return Check(4, "СИГНАЛ КОУЧА (проскальзывание)", PROBLEM, lines,
                     "сигнал приходит нулями — раскладка пакета 13 не сходится")
    if never:
        return Check(4, "СИГНАЛ КОУЧА (проскальзывание)", WARN, lines,
                     "сигнал есть, но порогов не достигал ни разу: либо чистый "
                     "заезд, либо пороги завышены")
    return Check(4, "СИГНАЛ КОУЧА (проскальзывание)", OK, lines)


def _check_mistakes(by_kind) -> Check:
    records = by_kind.get("coach_mistake", [])
    if not records:
        return Check(5, "СРЫВЫ (фаза 1)", NODATA,
                     ["ни одного срыва не зафиксировано"],
                     "если срывы были заведомо — см. пункт 4")
    by_type: dict[str, int] = {}
    by_corner: dict[str, int] = {}
    pending = 0
    for record in records:
        kind = str(record.get("mistake_kind") or "?")
        by_type[kind] = by_type.get(kind, 0) + 1
        corner = record.get("corner_id")
        key = f"поворот {corner}" if corner is not None else "вне поворота"
        by_corner[key] = by_corner.get(key, 0) + 1
        if record.get("speak") == "pending":
            pending += 1
    lines = [
        "найдено: " + ", ".join(f"{k} ×{v}" for k, v in sorted(
            by_type.items(), key=lambda p: -p[1])),
        "по местам: " + ", ".join(f"{k} ×{v}" for k, v in sorted(
            by_corner.items(), key=lambda p: -p[1])[:5]),
        f"прошло правило повтора: {pending} из {len(records)}",
    ]
    outside = by_corner.get("вне поворота", 0)
    if outside and outside >= len(records) / 2:
        return Check(5, "СРЫВЫ (фаза 1)", WARN, lines,
                     "больше половины срывов вне поворотов — их коуч не озвучивает")
    return Check(5, "СРЫВЫ (фаза 1)", OK, lines)


def _check_reference(by_kind) -> Check:
    records = by_kind.get("coach_reference_lap", [])
    if not records:
        return Check(6, "ЭТАЛОННЫЙ КРУГ (фаза 2)", NODATA,
                     ["сравнений с эталоном не было"],
                     "нужен хотя бы один завершённый круг с эталоном")
    last = records[-1]
    with_advice = sum(1 for r in records if r.get("advice"))
    metrics: dict[str, int] = {}
    for record in records:
        advice = record.get("advice")
        if isinstance(advice, dict):
            metric = str(advice.get("metric") or "?")
            metrics[metric] = metrics.get(metric, 0) + 1
    lines = [
        f"эталон: {last.get('reference_source') or '—'}"
        f", {last.get('reference_ms') or '—'} мс"
        f", сравнимых поворотов {last.get('corners_compared') or 0}",
        f"кругов сравнено: {len(records)}, отклонение найдено на {with_advice}",
    ]
    if metrics:
        lines.append("побеждали метрики: " + ", ".join(
            f"{k} ×{v}" for k, v in sorted(metrics.items(), key=lambda p: -p[1])))
    if (last.get("corners_compared") or 0) < 5:
        return Check(6, "ЭТАЛОННЫЙ КРУГ (фаза 2)", PROBLEM, lines,
                     "меньше пяти сравнимых поворотов — сравнение не публикуется")
    if with_advice == 0:
        return Check(6, "ЭТАЛОННЫЙ КРУГ (фаза 2)", WARN, lines,
                     "ни одного отклонения сверх порога: пороги compare.py могут "
                     "быть завышены")
    return Check(6, "ЭТАЛОННЫЙ КРУГ (фаза 2)", OK, lines)


def _check_lesson(by_kind) -> Check:
    records = by_kind.get("coach_lesson", [])
    if not records:
        return Check(7, "РАБОТА СЕССИИ И РАЗБОР (фаза 4)", NODATA,
                     ["разбор не собирался"],
                     "нужен эталон и минимум три не-пит-круга")
    last = records[-1]
    events = [r.get("focus_event") for r in records if r.get("focus_event")]
    focus = last.get("focus") if isinstance(last.get("focus"), dict) else None
    lines = [
        f"потенциал круга: {last.get('potential') or '—'} мс",
        "события работы: " + (", ".join(str(e) for e in events) or "не было"),
    ]
    if focus:
        lines.append(f"в работе поворот {focus.get('corner_id')}: "
                     f"{focus.get('baseline_ms')} -> {focus.get('current_ms')} мс"
                     f", статус {focus.get('status')}")
    top = last.get("top")
    if isinstance(top, list) and top:
        lines.append("дороже всего: " + ", ".join(
            f"поворот {row.get('corner_id')} {row.get('cost_ms')} мс"
            for row in top[:3] if isinstance(row, dict)))
    if not events:
        return Check(7, "РАБОТА СЕССИИ И РАЗБОР (фаза 4)", WARN, lines,
                     "работа сессии не назначалась: либо потери ниже порога, "
                     "либо у них не нашлось причины")
    return Check(7, "РАБОТА СЕССИИ И РАЗБОР (фаза 4)", OK, lines)


def _check_field_pace(by_kind) -> Check:
    records = by_kind.get("field_pace", [])
    silent = by_kind.get("field_pace_silent", [])
    if not records:
        return Check(8, "ПОЛОЖЕНИЕ В ПОЛЕ", NODATA,
                     ["раскладка по секторам не считалась"],
                     "нужен пакет 11 и минимум четыре машины со временем")
    last = records[-1]
    lines = [
        f"тема «{last.get('topic')}»: сектор {last.get('sector')}"
        f", место {last.get('rank')} из {last.get('field_size')}"
        f", отрыв {last.get('gap_ms')} мс",
        f"пересчётов: {len(records)}",
    ]
    if silent:
        reasons: dict[str, int] = {}
        for record in silent:
            key = str(record.get("why") or "?")
            reasons[key] = reasons.get(key, 0) + 1
        lines.append("молчал: " + ", ".join(
            f"{k} ×{v}" for k, v in sorted(reasons.items(), key=lambda p: -p[1])))
    if (last.get("field_size") or 0) < 4:
        return Check(8, "ПОЛОЖЕНИЕ В ПОЛЕ", WARN, lines,
                     "в поле меньше четырёх машин со временем — место не считается")
    return Check(8, "ПОЛОЖЕНИЕ В ПОЛЕ", OK, lines)


def _check_silence(by_kind) -> Check:
    records = by_kind.get("coach_silent", [])
    if not records:
        return Check(9, "ПОЧЕМУ КОУЧ МОЛЧАЛ", NODATA,
                     ["записей о молчании нет"])
    reasons: dict[str, int] = {}
    for record in records:
        key = str(record.get("why") or "?")
        reasons[key] = reasons.get(key, 0) + 1
    ranked = sorted(reasons.items(), key=lambda p: -p[1])
    lines = [f"{key} ×{count}" + (f" — {SILENCE_RU[key]}" if key in SILENCE_RU else "")
             for key, count in ranked]
    top = ranked[0][0]
    if top == "coach_disabled_in_settings":
        return Check(9, "ПОЧЕМУ КОУЧ МОЛЧАЛ", PROBLEM, lines,
                     "включить «Подсказки по пилотажу» на экране «Голос»")
    return Check(9, "ПОЧЕМУ КОУЧ МОЛЧАЛ", OK, lines)



def _check_llm(log_signals: list[str]) -> Check:
    """Жив ли «мозг». Отдельно от ошибок: отказ LLM штатно обработан и в
    ERROR не попадает, но заезд без него — совсем другой продукт."""
    ok = [ln for ln in log_signals if LLM_OK_RE.search(ln)]
    fails = [ln for ln in log_signals if LLM_FAIL_RE.search(ln)]

    if not ok and not fails:
        # Успех молчит, отказ молчит — различить нечем. Это НЕ «всё хорошо».
        return Check(10, "МОЗГ (LLM)", NODATA,
                     ["ни одного сигнала провайдера в логе",
                      "успех логируется один раз за сессию; если строки нет —"
                      " провайдер либо не настроен, либо не вызывался"])

    tls = [ln for ln in fails if "CERTIFICATE_VERIFY_FAILED" in ln]
    breaker = [ln for ln in fails if "уходим на шаблоны" in ln]
    lines = [f"отказов: {len(fails)}, подтверждённых ответов: {len(ok)}"]
    if tls:
        lines.append(f"из них TLS-отказов: {len(tls)} — цепочка Минцифры не "
                     f"проверяется, нужен certs/gigachat_ca_bundle.pem")
    if breaker:
        lines.append(f"предохранитель срабатывал: {len(breaker)} раз "
                     f"(каждый раз ~90 с на шаблонах)")

    if fails and not ok:
        return Check(10, "МОЗГ (LLM)", PROBLEM, lines,
                     "провайдер не ответил НИ РАЗУ — весь заезд прошёл на "
                     "шаблонах" + (
                         "; собрать бандл: python scripts/setup_gigachat_certs.py"
                         if tls else ""))
    if fails:
        return Check(10, "МОЗГ (LLM)", WARN, lines,
                     "провайдер отвечал, но с перебоями — часть реплик пришла "
                     "из шаблонов")
    return Check(10, "МОЗГ (LLM)", OK, lines)


def _check_names(log_signals: list[str]) -> Check:
    """Разрешались ли имена пилотов.

    Утечка плейсхолдера в эфир («Победа! гонщик...») закрыта подменой на фразу
    без имени, и теперь она НЕ СЛЫШНА. Значит единственный способ узнать о ней —
    этот пункт: иначе правка меняет заметный баг на невидимый."""
    signals = [ln for ln in log_signals if NAME_FAIL_RE.search(ln)]
    if not signals:
        return Check(11, "ИМЕНА ПИЛОТОВ", OK, ["неразрешённых имён не было"])

    unknown = [ln for ln in signals if "известен=False" in ln]
    known = [ln for ln in signals if "известен=True" in ln]
    lines = [f"случаев: {len(signals)}"]
    if unknown:
        lines.append(f"индекс ВНЕ словаря: {len(unknown)} — вопрос к разбору "
                     f"пакета, не к резолверу")
    if known:
        lines.append(f"индекс известен, имени нет: {len(known)} — участник не "
                     f"сопоставлен")
    lines.extend(ln.strip()[-110:] for ln in signals[:3])
    return Check(11, "ИМЕНА ПИЛОТОВ", PROBLEM, lines,
                 "прислать эти строки: они различают две разные причины")


def _check_errors(log_errors: list[str]) -> Check:
    if not log_errors:
        return Check(12, "ОШИБКИ И ИСКЛЮЧЕНИЯ", OK,
                     ["в spotter.log ошибок не найдено"])
    unique: list[str] = []
    for line in log_errors:
        text = line.strip()
        if text and text not in unique:
            unique.append(text)
    lines = [f"строк с ошибкой: {len(log_errors)}, различных: {len(unique)}"]
    lines.extend(unique[:4])
    return Check(12, "ОШИБКИ И ИСКЛЮЧЕНИЯ", PROBLEM, lines,
                 "прислать эти строки вместе с отчётом")
