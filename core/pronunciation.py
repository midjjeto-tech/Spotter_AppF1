"""
core/pronunciation.py
======================
Точечные фонетические подсказки для TTS, для слов, где движок сам может
поставить неверное ударение.

Yandex SpeechKit — документированно поддерживает ручную разметку ударения
знаком `+` перед ударной гласной внутри слова (в отличие от Piper/espeak,
который этот приём игнорирует и читает `+` как слово «плюс» — см.
`new_tts/ru_textnorm.py`). Поэтому подсказки здесь применяются ТОЛЬКО к
тексту, уходящему в Yandex.

Для Piper используются отдельные фонетические написания в
`new_tts/ru_textnorm.py`: синтаксис Yandex с `+` для него неприменим.
Набор ниже закреплён 2026-07-21 после воспроизводимой проверки текста,
который получает Yandex, и фонем espeak для локального Piper.
"""
from __future__ import annotations

import re

from core.transliterate import replace_known_driver_names

# Имя или фамилия (ключ — неизменяемая часть слова) → индекс (0-based) внутри
# найденного совпадения, ПЕРЕД которым ставится '+'. Фамилии склоняются только
# с окончаниями из allowlist ниже: это не даёт основе «перес» задеть обычные
# слова «перестал», «пересечение» и т.п.
_YANDEX_STRESS: dict[str, int] = {
    "серхио": 1,      # С+ерхио
    "перес": 1,       # П+ерес / П+ереса
    "ландо": 1,       # Л+андо
    "норрис": 1,      # Н+оррис / Н+орриса
    "ферстаппен": 5,  # Ферст+аппен / Ферст+аппена
    "бортолето": 6,   # Бортол+ето — ударение на "е" (3-й слог)
}

_YANDEX_SUFFIXES: dict[str, frozenset[str]] = {
    "серхио": frozenset({""}),
    "перес": frozenset({"", "а", "у", "ом", "е"}),
    "ландо": frozenset({""}),
    "норрис": frozenset({"", "а", "у", "ом", "е"}),
    "ферстаппен": frozenset({"", "а", "у", "ом", "е"}),
    "бортолето": frozenset({""}),
}

_YANDEX_RE = re.compile(
    r'(?<![а-яёА-ЯЁ])(' + '|'.join(re.escape(k) for k in sorted(_YANDEX_STRESS, key=len, reverse=True)) + r')([а-яёА-ЯЁ]*)',
    re.IGNORECASE,
)

# Кириллический respell: имя УЖЕ на кириллице (в т.ч. как его пишет GigaChat или
# как отдаёт транслит латиницы), но Yandex читает его неверно. Подменяем ОСНОВУ на
# написание, которое звучит правильно (можно с '+' ударением). Склонение
# сохраняется — суффикс из allowlist приклеивается к замене (Леклер→Лекл+ерк,
# Леклера→Лекл+ерка). Ключ и суффиксы — по образцу _YANDEX_STRESS.
# "леклер"→"Лекл+ерк": пользователь на слух выбрал вариант с "к" и ударением
# (2026-07-25, сэмплы name_samples/leclerc_5_stressk).
_YANDEX_RESPELL: dict[str, str] = {
    "леклер": "Лекл+ерк",
}
_YANDEX_RESPELL_SUFFIXES: dict[str, frozenset[str]] = {
    "леклер": frozenset({"", "а", "у", "ом", "е"}),   # Леклер/Леклера/Леклеру/Леклером/Леклере
}
_YANDEX_RESPELL_RE = re.compile(
    r'(?<![а-яёА-ЯЁ])(' + '|'.join(re.escape(k) for k in sorted(_YANDEX_RESPELL, key=len, reverse=True)) + r')([а-яёА-ЯЁ]*)',
    re.IGNORECASE,
)


def _sub(m: re.Match) -> str:
    stem = m.group(1)
    suffix = m.group(2)
    key = stem.lower()
    if suffix.lower() not in _YANDEX_SUFFIXES[key]:
        return m.group(0)
    idx = _YANDEX_STRESS[key]
    return stem[:idx] + '+' + stem[idx:] + suffix


def _respell_sub(m: re.Match) -> str:
    stem = m.group(1)
    suffix = m.group(2)
    key = stem.lower()
    # "к"/"ка"/… как суффикс не в allowlist → уже написано с "к", не трогаем.
    if suffix.lower() not in _YANDEX_RESPELL_SUFFIXES[key]:
        return m.group(0)
    return _YANDEX_RESPELL[key] + suffix


def apply_yandex(text: str) -> str:
    """Привести текст к написанию, которое Yandex озвучит правильно: перевести
    известную латиницу в кириллицу, подменить проблемные основы (respell) и
    расставить '+' ударения. Не бросает исключений — при ошибке возвращает вход."""
    if not text:
        return text
    try:
        text = replace_known_driver_names(text)
        text = _YANDEX_RESPELL_RE.sub(_respell_sub, text)
        return _YANDEX_RE.sub(_sub, text)
    except Exception:
        return text
