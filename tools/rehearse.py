"""
tools/rehearse.py
==================
Сухой прогон гонки — как звучат три канала, без запущенной F1 25.

    ЗАПУСК (из корня проекта):

        .venv\\Scripts\\python.exe tools/rehearse.py
        .venv\\Scripts\\python.exe tools/rehearse.py --persona hype --character sokolova
        .venv\\Scripts\\python.exe tools/rehearse.py --diff prev.txt

Зачем это есть. Вопрос «инженер и комментатор звучат по-разному или это одно и
то же разными голосами» решается ушами, а тесты на него не отвечают: они
проверяют, что функция вернула строку, а не что подряд идущие реплики читаются
как разговор двух разных людей. Живой заезд отвечает, но стоит вечера и
случается раз в день.

Что прогон ПРОВЕРЯЕТ по-настоящему:
  * банк формулировок (`core/radio/phrases.py`) — те самые строки, что уйдут в TTS;
  * раздачу каналов (`core/radio/policy.py`) — кто из троих говорит эту реплику;
  * раздачу голосов (`core/radio/voice_cast.py`) — включая правило «первый
    свободный», из-за которого при одной персоне два канала звучали одинаково;
  * обращение по имени (`core/radio/address.py`) — частота у персонажей разная;
  * потолки длины по срочности (ТЗ §10).

Что прогон НЕ проверяет и проверить не может: парсер пакетов, детекторы срывов
и пороги — им нужна телеметрия, а не сценарий. Зелёный прогон НЕ означает, что
заезд пройдёт хорошо; он означает, что произнесённый текст будет таким.

Сценарий ниже — не выдумка «как бывает»: порядок и состав кодов сняты с
архивных заездов (`game_sessions/*.json`, 30 файлов на момент написания), где
на пять кругов Монреаля пришлись SPTP, OVTK, STLG, FTLP, PENA, COLL_LIGHT,
RCWN и CHQF. Факты (отрывы, номера поворотов) подставлены правдоподобные —
банк всё равно печатает их как есть.
"""
from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from commentator import templates  # noqa: E402
from core.radio import address as radio_address  # noqa: E402
from core.radio import phrases, policy, speakers, voice_cast  # noqa: E402
from core.radio.phrases import PhraseError  # noqa: E402

#: Имя пилота для обращений. Своё, а не из настроек: прогон обязан давать
#: одинаковый вывод на любой машине, иначе `--diff` покажет разницу там, где
#: изменился только чужой профиль.
PLAYER_FIRST_NAME = "Артём"


@dataclass(frozen=True, slots=True)
class Beat:
    """Одна реплика сценария.

    `event_code` — код события (его читает `policy`), `phrase_code` — код в
    банке формулировок. Пара, а не одно поле: банк говорит семантическими
    кодами (`box.call_1`), события — кодами игры (`STRAT_BOX_CALL_1`), и
    отображение между ними живёт в местах вызова внутри движка.
    """

    lap: int
    event_code: str
    #: None означает «эту реплику произносит комментатор» — у него текста в
    #: банке нет, он идёт через шаблоны/LLM.
    phrase_code: str | None = None
    fields: dict = field(default_factory=dict)
    #: Маркер `event["speaker"]`, которым инженерские трекеры помечают свои
    #: реплики. Для кодов вне `_ENGINEER_CODES` он и есть единственное, что
    #: уводит реплику в канал инженера.
    speaker: str | None = None
    #: Пояснение для человека, читающего транскрипт. В озвучку не уходит.
    note: str = ""


SCRIPT: tuple[Beat, ...] = (
    Beat(0, "SESSION_RADIO_CHECK", "session.radio_check", note="проверка связи до старта"),
    Beat(1, "SSTA", note="старт — комментатор"),
    Beat(1, "SPOTTER_CAR_LEFT", "spotter.left", note="первый поворот в пелотоне"),
    Beat(1, "COLL_LIGHT", note="лёгкое касание — градация тяжести"),
    Beat(2, "DRS_ALLOWED_ON", "drs.enabled"),
    Beat(2, "OVTK", note="обгон — комментатор"),
    Beat(2, "PRAISE_OVERTAKE", "praise.overtake", note="инженер о том же обгоне"),
    Beat(3, "ENGINEER_GAP_DIGEST", "gap.digest", fields={}),
    # Коуч едет в канал инженера НЕ по списку кодов, а по маркеру `speaker`
    # (см. `policy.channel_for`). Сценарий обязан нести его так же, как движок:
    # без маркера реплика уехала бы комментатору, и разбор «звучит ли
    # разделено» смотрел бы не на тот канал.
    Beat(3, "COACH_ADVICE", "coach.oversteer", fields={"corner_no": "четвёртом"},
         speaker="engineer", note="коуч называет поворот"),
    Beat(4, "TYRE_WARN", "tyres.wear"),
    Beat(4, "STRAT_BOX_CALL_1", "box.call_1", note="боевая команда, critical"),
    Beat(5, "PENA", "penalty.received", note="штраф"),
    Beat(5, "SAFETY_CAR_DEPLOYED", "flag.safety_car_deployed"),
    Beat(6, "FTLP", note="быстрейший круг — комментатор"),
    Beat(6, "CAREER_PB", "field.sector_strong",
         fields={"rank": "третий", "sector_no": "втором"},
         note="личный рекорд, канал инженера"),
    Beat(7, "SPOTTER_CLEAR", "spotter.clear"),
    Beat(7, "CHQF", note="финиш — комментатор"),
    Beat(7, "SESSION_RESULT", "session.result", fields={"position": "шестой"},
         note="итог от инженера"),
)


def _selector(beat: Beat) -> str:
    """Ключ закрепления варианта за ситуацией.

    В движке это `dedupe_key` события. Здесь — стабильная строка из круга и
    кода: важно не совпасть с движком дословно, а быть детерминированным,
    иначе `--diff` шумел бы на каждом запуске.
    """
    return f"{beat.lap}:{beat.event_code}"


def _engineer_text(beat: Beat, character: str, shortest: bool) -> tuple[str, str]:
    """Строка из банка плюс пометка об отказе.

    Отказ банка возвращается ТЕКСТОМ, а не глотается: сценарий, который тихо
    печатает пустую строку, соврал бы ровно про то, ради чего его запускают.
    """
    if beat.phrase_code is None:
        return "", ""
    try:
        phrase = phrases.render(
            beat.phrase_code, beat.fields or None,
            selector_key=_selector(beat), shortest=shortest, character=character)
    except PhraseError as exc:
        return "", f"ОТКАЗ БАНКА: {exc}"
    return radio_address.apply(
        phrase, PLAYER_FIRST_NAME, character, _selector(beat), allowed=True), ""


def _commentator_text(beat: Beat, persona: str) -> str:
    """Шаблонная реплика комментатора.

    Намеренно без LLM: сухой прогон не должен стоить запросов к GigaChat и
    обязан давать одинаковый вывод дважды подряд. Тон LLM отличается, но
    КАНАЛ, голос и место в очереди у неё те же самые.
    """
    text = templates.render({"event_code": beat.event_code}, persona=persona)
    return text or "(шаблона нет — в бою здесь говорит LLM)"


def _fmt_row(beat: Beat, channel: str, urgency: str, profile, voice: str,
             text: str, problem: str) -> str:
    words = phrases.word_count(text) if text else 0
    limit = phrases._MAX_WORDS_BY_URGENCY.get(urgency)
    over = " ПРЕВЫШЕН ПОТОЛОК" if limit and words > limit else ""
    head = (f"L{beat.lap} | {channel:<11} | {urgency:<8} | "
            f"{profile.display_name:<16} | {voice:<10} | {words:>2} сл.{over}")
    body = f"       {text or problem}"
    tail = f"       ({beat.note})" if beat.note else ""
    return "\n".join(part for part in (head, body, tail) if part.strip())


def rehearse(persona: str, character: str, shortest: bool) -> list[str]:
    """Транскрипт сценария. Чистая функция: ни файлов, ни звука."""
    cast = voice_cast.resolve(persona, character)
    lines: list[str] = []
    for beat in SCRIPT:
        event = {"event_code": beat.event_code}
        if beat.speaker:
            event["speaker"] = beat.speaker
        channel = policy.channel_for(event)
        urgency = policy.urgency_for(event)
        profile = speakers.profile_for(channel, persona, character=character)
        if channel == policy.CHANNEL_COMMENTATOR:
            text, problem = _commentator_text(beat, persona), ""
            voice = f"персона {persona}"
        else:
            text, problem = _engineer_text(beat, character, shortest)
            slot = voice_cast.SLOT_SPOTTER if channel == policy.CHANNEL_SPOTTER \
                else voice_cast.SLOT_ENGINEER
            voice = cast[slot]["voice"]
        lines.append(_fmt_row(beat, channel, urgency, profile, voice, text, problem))
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[2])
    parser.add_argument("--persona", default="tv",
                        help="персона комментатора: tv | hype | calm | toxic")
    parser.add_argument("--character", default=voice_cast.DEFAULT_CHARACTER,
                        help="персонаж инженера: " + " | ".join(voice_cast.CHARACTERS))
    parser.add_argument("--short", action="store_true",
                        help="режим «Коротко» — сужает пул к лаконичным вариантам")
    parser.add_argument("--diff", metavar="ФАЙЛ",
                        help="сравнить с прошлым транскриптом и показать различия")
    parser.add_argument("--out", metavar="ФАЙЛ", help="сохранить транскрипт")
    args = parser.parse_args(argv)

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    lines = rehearse(args.persona, args.character, args.short)
    header = (f"СУХОЙ ПРОГОН · комментатор={args.persona} · "
              f"инженер={args.character} · длина="
              f"{'коротко' if args.short else 'стандарт'}")
    body = "\n".join([header, "=" * len(header), *lines])
    print(body)

    if args.out:
        Path(args.out).write_text(body + "\n", encoding="utf-8")
        print(f"\nсохранено: {args.out}")

    if args.diff:
        import difflib
        old = Path(args.diff).read_text(encoding="utf-8").splitlines()
        delta = [d for d in difflib.unified_diff(
            old, body.splitlines(), fromfile=args.diff, tofile="сейчас", lineterm="")]
        print("\n" + ("\n".join(delta) if delta else "РАЗЛИЧИЙ НЕТ"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
