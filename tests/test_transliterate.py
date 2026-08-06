from core.transliterate import (
    KNOWN_DRIVER_NAMES,
    is_latin,
    known_driver_name,
    known_surname,
    replace_known_driver_names,
    to_cyrillic,
)


# --- known-good matches (calibrated against this project's own static dicts) ---

def test_bearman_matches_static_dict_via_ea_digraph():
    assert to_cyrillic("Bearman") == "Бирман"


def test_norris():
    assert to_cyrillic("Norris") == "Норрис"


def test_piastri():
    assert to_cyrillic("Piastri") == "Пиастри"


def test_tsunoda_matches_static_dict_via_ts_digraph():
    assert to_cyrillic("Tsunoda") == "Цунода"


def test_alonso():
    assert to_cyrillic("Alonso") == "Алонсо"


def test_antonelli():
    assert to_cyrillic("Antonelli") == "Антонелли"


def test_colapinto():
    assert to_cyrillic("Colapinto") == "Колапинто"


def test_gasly():
    assert to_cyrillic("Gasly") == "Гасли"


def test_ocon():
    assert to_cyrillic("Ocon") == "Окон"


def test_stroll():
    assert to_cyrillic("Stroll") == "Стролл"


def test_albon():
    assert to_cyrillic("Albon") == "Албон"


def test_lawson_matches_static_dict_via_aw_digraph():
    assert to_cyrillic("Lawson") == "Лоусон"


def test_hadjar_matches_static_dict_via_dj_digraph():
    assert to_cyrillic("Hadjar") == "Хаджар"


# --- accepted mismatches (documented limitations, not bugs) ---

def test_verstappen_mismatches_static_dict_this_is_expected():
    """Static dict says "Ферстаппен" (Dutch pronunciation: 'V' sounds like 'f').
    Letter-based rules can't know this — they produce the English-style
    reading. This is the documented, accepted limitation: the algorithm is a
    fallback for names NOT in the static dict, not a replacement for it. If
    this assertion ever starts failing because someone "fixed" the algorithm
    to special-case Dutch names, that's scope creep — put the exact name in
    F1_2025_BY_NUMBER/F1_2026_BY_NUMBER instead."""
    assert to_cyrillic("Verstappen") == "Верстаппен"


def test_sainz_mismatches_static_dict_this_is_expected():
    """Static dict says "Сайнс" (Spanish-origin surname, softer final
    consonant). Letter rules map the final "z" to "з" (the general English
    convention), giving "Сайнз" instead. Same class of accepted limitation as
    Verstappen above — do not "fix" this in the algorithm, add exact names to
    the static dict instead."""
    assert to_cyrillic("Sainz") == "Сайнз"


# --- multi-word names ---

def test_full_name_transliterated_word_by_word():
    assert to_cyrillic("Oliver Bearman") == "Оливер Бирман"


# --- is_latin() ---

def test_is_latin_true_for_latin_text():
    assert is_latin("Bearman") is True


def test_is_latin_false_for_cyrillic_text():
    assert is_latin("Бирман") is False


def test_is_latin_false_for_mixed_text():
    assert is_latin("Bearman Бирман") is False


def test_is_latin_false_for_empty_string():
    assert is_latin("") is False


def test_is_latin_false_for_none():
    assert is_latin(None) is False


def test_is_latin_true_for_hyphenated_name():
    assert is_latin("Jean-Eric") is True


# --- known_surname() ---

def test_known_surname_exact_match():
    assert known_surname("Verstappen") == "Ферстаппен"


def test_known_surname_case_insensitive_raw_udp_caps():
    assert known_surname("PEREZ") == "Перес"


def test_known_surname_lindblad_case_insensitive():
    assert known_surname("LINDBLAD") == "Линдблад"


def test_known_surname_matches_last_word_of_full_name():
    assert known_surname("Sergio Perez") == "Перес"


def test_known_surname_none_for_unknown_name():
    assert known_surname("Magnussen") is None


def test_known_surname_none_for_custom_driver_name():
    assert known_surname("Кастомный Гонщик") is None


def test_known_surname_none_for_empty_and_none():
    assert known_surname("") is None
    assert known_surname(None) is None


def test_known_driver_name_accepts_jolpica_diacritics():
    assert known_driver_name("Sergio Pérez") == "Серхио Перес"
    assert known_driver_name("Nico Hülkenberg") == "Нико Хюлькенберг"


def test_every_known_full_name_is_safe_inside_tts_text():
    for latin, russian in KNOWN_DRIVER_NAMES.items():
        assert replace_known_driver_names(f"Впереди {latin}.") == f"Впереди {russian}."


def test_known_name_replacement_does_not_touch_larger_latin_words():
    assert replace_known_driver_names("Maximize pace") == "Maximize pace"


def test_known_surname_does_not_affect_to_cyrillic_algorithm():
    """known_surname() — отдельный whitelist-фолбэк, не подменяет поведение
    to_cyrillic()/is_latin() (см. test_verstappen_mismatches_... выше — то,
    что видит общий алгоритм, должно остаться неизменным)."""
    assert to_cyrillic("Verstappen") == "Верстаппен"
    assert to_cyrillic("Sainz") == "Сайнз"
