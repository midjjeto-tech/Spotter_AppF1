"""
core/transliterate.py
======================
Правило-базовая практическая транслитерация латиницы в кириллицу — подстраховка
для имён ВНЕ статических словарей (core/f1_metadata.py::F1_2025_BY_NUMBER/
F1_2026_BY_NUMBER, KNOWN_SURNAMES ниже). Русский Yandex TTS озвучивает сырую
латиницу мусором — транслитерированная кириллица звучит лучше, даже когда
неточна.

ВАЖНО: правила калиброваны на английскую орфографию. Фамилии не-английского
происхождения могут транслитерироваться неверно (пример: "Verstappen" —
голландское произношение с "V" как "ф" — этот модуль даст "Верстаппен", не
"Ферстаппен", как в статическом словаре). Это ПРИНЯТОЕ ограничение самого
алгоритма to_cyrillic()/_transliterate_word() — НЕ чинить его здесь спец-
случаями (см. test_verstappen_mismatches_static_dict_this_is_expected в
tests/test_transliterate.py). Для точных случаев — KNOWN_SURNAMES,
KNOWN_DRIVER_NAMES и их резолверы ниже: отдельный whitelist-фолбэк с
приоритетом выше общего алгоритма, но не подменяющий его поведение.
"""
from __future__ import annotations

import re
import unicodedata

_LATIN_RE = re.compile(r"^[A-Za-z\s\-'.]+$")

# Диграфы — длиннее совпадение приоритетнее однобуквенного. Порядок в списке
# ниже важен только для читаемости, сопоставление всегда идёт по длине.
_DIGRAPHS: dict[str, str] = {
    "th": "т", "ch": "ч", "sh": "ш", "ph": "ф", "ck": "к", "qu": "кв",
    "wh": "в", "ea": "и", "ee": "и", "oo": "у", "ai": "ай", "ay": "ай",
    "ey": "ей", "oy": "ой", "ow": "оу", "ou": "ау", "aw": "оу", "ew": "ью",
    "dj": "дж", "ts": "ц", "kh": "х", "zh": "ж", "gh": "г",
}

_LETTERS: dict[str, str] = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г",
    "h": "х", "i": "и", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н",
    "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т", "u": "у",
    "v": "в", "w": "в", "x": "кс", "y": "и", "z": "з",
}

_MAX_DIGRAPH_LEN = max(len(k) for k in _DIGRAPHS)


def _transliterate_word(word: str) -> str:
    lower = word.lower()
    out: list[str] = []
    i = 0
    while i < len(lower):
        matched = False
        for length in range(_MAX_DIGRAPH_LEN, 1, -1):
            chunk = lower[i:i + length]
            if chunk in _DIGRAPHS:
                out.append(_DIGRAPHS[chunk])
                i += length
                matched = True
                break
        if matched:
            continue
        ch = lower[i]
        out.append(_LETTERS.get(ch, ch))   # не-буква (дефис, апостроф) — как есть
        i += 1
    result = "".join(out)
    return result[:1].upper() + result[1:] if result else result


def is_latin(text: str) -> bool:
    """True, если строка целиком латиница (плюс пробелы/дефис/апостроф) —
    значит транслитерация имеет смысл; кириллицу/смешанный текст не трогаем."""
    return bool(text) and bool(_LATIN_RE.match(text))


def to_cyrillic(latin: str) -> str:
    """Транслитерировать латинское имя (одно слово или полное имя из
    нескольких слов — каждое обрабатывается независимо, разделители
    сохраняются) в кириллицу. Не проверяет is_latin() сама — вызывающий код
    решает, когда транслитерация нужна."""
    if not latin:
        return latin
    return " ".join(_transliterate_word(w) if w else w for w in latin.split(" "))


# Точные фамилии реальных действующих пилотов F1 (Ergast/Jolpica и/или сырое
# UDP-имя отдают латиницей) → кириллица, для случаев, где буквенный алгоритм
# выше документированно ошибается (голландское "V"→"ф" у Verstappen,
# испанское "z"→"с" у Sainz/Perez — см. test_verstappen_mismatches_.../
# test_sainz_mismatches_... в tests/test_transliterate.py). НЕ путать с
# to_cyrillic() выше — тот остаётся общим фолбэком для ВСЕХ остальных имён,
# этот словарь имеет приоритет через known_surname(), но не заменяет и не
# меняет поведение to_cyrillic()/is_latin() самих по себе.
KNOWN_SURNAMES: dict[str, str] = {
    "Verstappen": "Ферстаппен", "Norris": "Норрис", "Leclerc": "Леклер",
    "Piastri": "Пиастри", "Sainz": "Сайнс", "Hamilton": "Хэмилтон",
    "Russell": "Расселл", "Alonso": "Алонсо", "Stroll": "Стролл",
    "Gasly": "Гасли", "Ocon": "Окон", "Albon": "Албон", "Tsunoda": "Цунода",
    "Hulkenberg": "Хюлькенберг", "Hülkenberg": "Хюлькенберг",
    "Antonelli": "Антонелли", "Colapinto": "Колапинто", "Bearman": "Бирман",
    "Hadjar": "Хаджар", "Lawson": "Лоусон", "Bortoleto": "Бортолето",
    "Doohan": "Дун", "Bottas": "Боттас", "Perez": "Перес", "Pérez": "Перес",
    "Lindblad": "Линдблад",
}

# Полные имена нужны не только для отображения: Jolpica возвращает именно
# givenName + familyName, а сохранение одной фамилии теряет имя пилота. Этот
# список также служит последней защитой TTS, если латинское имя пришло не из
# participant-пакета, а из LLM/архива/внешнего источника.
KNOWN_DRIVER_NAMES: dict[str, str] = {
    "Max Verstappen": "Макс Ферстаппен",
    "Lando Norris": "Ландо Норрис",
    "Oscar Piastri": "Оскар Пиастри",
    "Charles Leclerc": "Шарль Леклер",
    "Lewis Hamilton": "Льюис Хэмилтон",
    "George Russell": "Джордж Расселл",
    "Andrea Kimi Antonelli": "Андреа Кими Антонелли",
    "Alexander Albon": "Александр Албон",
    "Carlos Sainz": "Карлос Сайнс",
    "Liam Lawson": "Лиам Лоусон",
    "Arvid Lindblad": "Арвид Линдблад",
    "Fernando Alonso": "Фернандо Алонсо",
    "Lance Stroll": "Лэнс Стролл",
    "Esteban Ocon": "Эстебан Окон",
    "Oliver Bearman": "Оливер Бирман",
    "Gabriel Bortoleto": "Габриэль Бортолето",
    "Nico Hulkenberg": "Нико Хюлькенберг",
    "Nico Hülkenberg": "Нико Хюлькенберг",
    "Pierre Gasly": "Пьер Гасли",
    "Franco Colapinto": "Франко Колапинто",
    "Sergio Perez": "Серхио Перес",
    "Sergio Pérez": "Серхио Перес",
    "Valtteri Bottas": "Валттери Боттас",
    "Isack Hadjar": "Исак Хаджар",
    "Yuki Tsunoda": "Юки Цунода",
    "Jack Doohan": "Джек Дун",
}


def _latin_name_key(value: str) -> str:
    """Case/diacritic-insensitive key for external driver names.

    Jolpica correctly uses ``Pérez`` and ``Hülkenberg`` while game UDP often
    sends ASCII. Both spellings must resolve to the same curated Russian name.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(without_marks.casefold().split())


_KNOWN_SURNAMES_CI: dict[str, str] = {
    _latin_name_key(k): v for k, v in KNOWN_SURNAMES.items()
}
_KNOWN_DRIVER_NAMES_CI: dict[str, str] = {
    _latin_name_key(k): v for k, v in KNOWN_DRIVER_NAMES.items()
}


def known_surname(latin: str | None) -> str | None:
    """Точное соответствие фамилии реального пилота (регистронезависимо,
    берёт последнее слово — работает и с голой фамилией "PEREZ", и с полным
    именем "Sergio Perez"/Jolpica-форматом). None — фамилии нет в словаре
    (в т.ч. любое кастомное/карьерное имя)."""
    if not latin:
        return None
    parts = latin.split()
    if not parts:
        return None
    return _KNOWN_SURNAMES_CI.get(_latin_name_key(parts[-1]))


def known_driver_name(latin: str | None) -> str | None:
    """Точное русское полное имя, либо точная фамилия из последнего токена.

    Сопоставление нечувствительно к регистру и диакритике, поэтому реальные
    ответы Jolpica (``Sergio Pérez``, ``Nico Hülkenberg``) и ASCII из UDP
    проходят по одному пути.
    """
    if not latin:
        return None
    full = _KNOWN_DRIVER_NAMES_CI.get(_latin_name_key(latin))
    if full:
        return full
    return known_surname(latin)


_KNOWN_TEXT_NAMES: dict[str, str] = {
    **KNOWN_SURNAMES,
    **KNOWN_DRIVER_NAMES,
}
_KNOWN_TEXT_RE = re.compile(
    r"(?<![A-Za-zÀ-ÖØ-öø-ÿ])(" + "|".join(
        re.escape(name) for name in sorted(_KNOWN_TEXT_NAMES, key=len, reverse=True)
    ) + r")(?![A-Za-zÀ-ÖØ-öø-ÿ])",
    re.IGNORECASE,
)
_KNOWN_TEXT_NAMES_CI = {
    _latin_name_key(k): v for k, v in _KNOWN_TEXT_NAMES.items()
}


def replace_known_driver_names(text: str) -> str:
    """Заменить известные латинские имена/фамилии внутри произвольной фразы.

    Это страховка на самой границе TTS для текстов LLM, архивов и прочих путей,
    которые не обязаны проходить через :class:`F1Metadata`.
    """
    if not text:
        return text
    return _KNOWN_TEXT_RE.sub(
        lambda match: _KNOWN_TEXT_NAMES_CI[_latin_name_key(match.group(0))],
        text,
    )
