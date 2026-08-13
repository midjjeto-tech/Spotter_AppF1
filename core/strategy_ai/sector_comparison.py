"""
core/strategy_ai/sector_comparison.py
========================================
Сравнение лучших секторов игрока и соперника за сессию (Session History,
packet 11) — "ты быстрее его во втором секторе" в гэп-дайджесте. Чистая
функция, без I/O — тот же паттерн, что gap_digest.py/drs_advisory.py.

**Строка отсюда идёт в эфир МИМО банка фраз** (`core/engine.py` склеивает её с
фрагментами банка через `radio_phrases.compose(extra=...)`). Значит, ни одна из
защит банка на неё не распространяется: ни тест на падежи имён, ни запрет
цифровых порядковых, ни согласование числительных. Поэтому всё это соблюдается
здесь вручную — и на каждое правило стоит свой тест:

    фамилия, а не полное имя  — радио говорит «Норрис», а не «Ландо Норрис»;
    родительный после «быстрее» — «быстрее Норриса», иначе имя не склоняется;
    порядковое СЛОВОМ         — «в первом секторе»; «в 1-м» офлайновый Piper
                                читает посимвольно (тот же класс брака, что
                                чинили для номеров поворотов у коуча);
    величина фрагментом       — `seconds_phrase` даёт «три десятых», а не
                                «0.3с», которое num_to_words превращал в
                                «ноль целых три десятых с».

См. docs/superpowers/plans/2026-07-20-session-history-sector-comparison.md.
"""
from __future__ import annotations

from core.num_to_words import seconds_phrase
from core.radio.corner_words import ordinal_prepositional
from core.radio.euphony import fix_prepositions
from core.ru_names import decline


def compare_best_sectors(player_best_ms: dict[int, int], rival_best_ms: dict[int, int],
                         rival_name: str) -> str | None:
    """Возвращает готовую фразу по сектору с НАИБОЛЬШЕЙ разницей среди тех,
    что есть в обоих словарях (самое показательное сравнение для короткой
    рутинной сводки — не зачитывать все 3 сектора каждый раз).

    None — если общих секторов нет, результаты совпадают или разница НИЖЕ
    произносимой (`num_to_words.MIN_SPOKEN_MS`). Последнее не придирка: на
    четырёх сотых секунды сравнение секторов не значит ничего, а прежняя версия
    зачитывала его как «ноль целых ноль десятых»."""
    common = set(player_best_ms) & set(rival_best_ms)
    if not common:
        return None
    sector = max(common, key=lambda s: abs(player_best_ms[s] - rival_best_ms[s]))
    delta_ms = player_best_ms[sector] - rival_best_ms[sector]

    # Сектор — существительное мужского рода, как и поворот, поэтому таблица
    # предложного падежа общая с core/radio/corner_words.py. Своей копии
    # числительных здесь быть не должно.
    ordinal = ordinal_prepositional(sector)
    spoken = seconds_phrase(abs(delta_ms))
    if ordinal is None or spoken is None:
        return None

    if delta_ms < 0:
        text = (f"Ты быстрее {decline(rival_name, 'gen')} "
                f"в {ordinal} секторе на {spoken}.")
    else:
        text = (f"{decline(rival_name, 'nom')} быстрее тебя "
                f"в {ordinal} секторе на {spoken}.")
    # «в втором» → «во втором». Строка идёт в эфир мимо банка, где то же
    # правило применяется в `render()`, — поэтому зовём его здесь сами.
    return fix_prepositions(text)
