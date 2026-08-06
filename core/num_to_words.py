"""core/num_to_words.py
Convert decimal and integer literals in Russian F1 commentary to spoken-word form.

Why this exists: Yandex TTS reads "+1.2" as "plus adin tochka dva" (ugly); Russian
listeners expect "плюс одна целая две десятых". Applies to any text before synthesis.
"""
from __future__ import annotations

import re

_UNITS = [
    "", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять",
    "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
    "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать",
]
_TENS = [
    "", "", "двадцать", "тридцать", "сорок", "пятьдесят",
    "шестьдесят", "семьдесят", "восемьдесят", "девяносто",
]
_HUNDREDS = [
    "", "сто", "двести", "триста", "четыреста", "пятьсот",
    "шестьсот", "семьсот", "восемьсот", "девятьсот",
]

# Gender-agreement for 1 and 2 (целая/десятых/минута are feminine context).
_FEMININE = {"один": "одна", "два": "две"}


def _int_word(n: int) -> str:
    """0–999 → Russian word. Returns str(n) for out-of-range."""
    if n == 0:
        return "ноль"
    if 0 < n < 20:
        return _UNITS[n]
    if 20 <= n < 100:
        t, u = _TENS[n // 10], _UNITS[n % 10]
        return f"{t} {u}".strip() if u else t
    if 100 <= n < 1000:
        h, rest = _HUNDREDS[n // 100], n % 100
        rest_w = _int_word(rest) if rest else ""
        return f"{h} {rest_w}".strip() if rest_w else h
    return str(n)


def _to_f(w: str) -> str:
    """Feminine-agree the LAST word of w (single or compound, e.g. 'двадцать
    два' -> 'двадцать две'), so 1/2 agree with feminine nouns (целая,
    десятых, минута...) wherever they land in a compound number."""
    head, _, tail = w.rpartition(" ")
    fixed = _FEMININE.get(tail, tail)
    return f"{head} {fixed}".strip() if head else fixed


def _dec_suffix(ndec: int) -> str:
    return "десятых" if ndec == 1 else "сотых" if ndec == 2 else "тысячных"


def _decimal_to_words(sign: str, int_part: int, dec_str: str) -> str:
    dec_val = int(dec_str)
    dec_w = _to_f(_int_word(dec_val))
    suffix = _dec_suffix(len(dec_str))
    sign_w = {"+" : "плюс ", "-": "минус "}.get(sign, "")

    if int_part == 0:
        return f"{sign_w}{dec_w} {suffix}".strip()

    # 1 → "одна целая" (singular); everything else → "N целых" (N gender-agreed).
    if int_part == 1:
        return f"{sign_w}одна целая {dec_w} {suffix}".strip()

    int_w = _to_f(_int_word(int_part))
    return f"{sign_w}{int_w} целых {dec_w} {suffix}".strip()


# Match signed/unsigned decimal numbers.
# Negative lookbehind on [:digit] avoids matching inside lap times like "1:23.4"
# (those are handled separately by _LAPTIME_RE, run first in normalize()).
_DECIMAL_RE = re.compile(r"(?<![:\d])([+-]?)(\d{1,4})\.(\d{1,3})(?!\d)")


def _replace_decimal(m: re.Match) -> str:
    sign, int_s, dec_s = m.group(1), m.group(2), m.group(3)
    int_part = int(int_s)
    # Skip very large integers (>999) that are likely IDs or lap times without ":"
    if int_part > 999:
        return m.group(0)
    return _decimal_to_words(sign, int_part, dec_s)


# Lap/sector times: "1:22.571" or "1:22.5". Left to the TTS engine's own number
# reading before (see git history) — it reads them as verbose duration ("one
# minute twenty two seconds five hundred seventy one milliseconds") instead of
# natural spoken Russian, hence handling this ourselves like every other number.
_LAPTIME_RE = re.compile(r"(?<!\d)([1-9]\d?):([0-5]\d)\.(\d{1,3})(?!\d)")

def ru_plural(n: int, one: str, few: str, many: str) -> str:
    """Русское согласование числительного с существительным: 1→one (кроме
    11-14), 2-4→few (кроме 12-14), иначе→many. Пример: ru_plural(21,
    "минута", "минуты", "минут") → "минута"."""
    if 11 <= n % 100 <= 14:
        return many
    r = n % 10
    if r == 1:
        return one
    if 2 <= r <= 4:
        return few
    return many


def _minute_word(n: int) -> str:
    return ru_plural(n, "минута", "минуты", "минут")


def _replace_laptime(m: re.Match) -> str:
    minutes, sec_s, dec_s = int(m.group(1)), m.group(2), m.group(3)
    minute_phrase = f"{_to_f(_int_word(minutes))} {_minute_word(minutes)}"
    seconds_phrase = _decimal_to_words("", int(sec_s), dec_s)
    return f"{minute_phrase} {seconds_phrase}"


def normalize(text: str) -> str:
    """Replace decimal/lap-time literals with Russian spoken form. Safe to call
    on any text."""
    text = _LAPTIME_RE.sub(_replace_laptime, text)
    return _DECIMAL_RE.sub(_replace_decimal, text)
