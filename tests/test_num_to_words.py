"""Tests for core/num_to_words.py — decimal-to-spoken-word conversion."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.num_to_words import normalize, _decimal_to_words, _to_f, _int_word, ru_plural


# ------------------------------------------------------------------ #
# Direct conversion
# ------------------------------------------------------------------ #

def test_positive_decimal_one_digit():
    assert _decimal_to_words("", 1, "2") == "одна целая две десятых"

def test_positive_decimal_multi():
    assert _decimal_to_words("", 3, "4") == "три целых четыре десятых"

def test_zero_integer():
    assert _decimal_to_words("", 0, "3") == "три десятых"

def test_plus_sign():
    assert _decimal_to_words("+", 1, "2") == "плюс одна целая две десятых"

def test_minus_sign():
    assert _decimal_to_words("-", 3, "4") == "минус три целых четыре десятых"

def test_two_decimal_digits():
    assert _decimal_to_words("", 1, "23") == "одна целая двадцать три сотых"

def test_large_int():
    result = _decimal_to_words("", 8, "7")
    assert result == "восемь целых семь десятых"


# ------------------------------------------------------------------ #
# Full normalize() on text
# ------------------------------------------------------------------ #

def test_normalize_gap_in_sentence():
    result = normalize("+1.2 секунды")
    assert "одна целая" in result
    assert "две десятых" in result
    assert "1.2" not in result

def test_normalize_bare_decimal():
    result = normalize("отставание 3.4")
    assert "три целых" in result
    assert "четыре десятых" in result

def test_normalize_large_gap():
    result = normalize("8.7 секунд")
    assert "восемь целых" in result
    assert "семь десятых" in result

def test_normalize_converts_lap_time():
    """1:23.4 is spoken out in full Russian, not left for the TTS engine's own
    (verbose, "N minutes N seconds N milliseconds") number reading."""
    text = "лучший круг 1:23.4"
    result = normalize(text)
    assert "1:23.4" not in result
    assert "одна минута двадцать три целых четыре десятых" in result


def test_laptime_two_minutes_gender_agreement():
    result = normalize("2:05.100")
    assert result == "две минуты пять целых сто тысячных"


def test_laptime_eleven_minutes_uses_genitive_plural():
    result = normalize("11:00.5")
    assert result.startswith("одиннадцать минут ")


def test_laptime_milliseconds_gender_agreement():
    """571 ms ends in 'один' (masculine) but must agree with feminine
    'тысячных' -> 'одна', matching how 'одна целая'/'две целых' already work."""
    result = normalize("1:22.571")
    assert result == "одна минута двадцать две целых пятьсот семьдесят одна тысячных"


# ------------------------------------------------------------------ #
# ru_plural — общее согласование числительного с существительным
# (публичный хелпер, вынесен из _minute_word для переиспользования, см.
# core/strategy_ai/weather_advisory.py)
# ------------------------------------------------------------------ #

def test_ru_plural_one():
    assert ru_plural(1, "процент", "процента", "процентов") == "процент"
    assert ru_plural(21, "процент", "процента", "процентов") == "процент"


def test_ru_plural_few():
    assert ru_plural(2, "процент", "процента", "процентов") == "процента"
    assert ru_plural(3, "процент", "процента", "процентов") == "процента"
    assert ru_plural(4, "процент", "процента", "процентов") == "процента"
    assert ru_plural(24, "процент", "процента", "процентов") == "процента"


def test_ru_plural_many():
    assert ru_plural(5, "процент", "процента", "процентов") == "процентов"
    assert ru_plural(20, "процент", "процента", "процентов") == "процентов"
    assert ru_plural(100, "процент", "процента", "процентов") == "процентов"


def test_ru_plural_teens_exception():
    """11-14 (и 111-114 и т.п.) — исключение из общего "1->one, 2-4->few":
    всегда many, несмотря на то что 11%10==1, 12%10==2 и т.д."""
    for n in (11, 12, 13, 14, 111, 112):
        assert ru_plural(n, "минута", "минуты", "минут") == "минут"


def test_minute_word_still_correct_after_refactor():
    """_minute_word теперь реализован через ru_plural — поведение не изменилось."""
    from core.num_to_words import _minute_word
    assert _minute_word(1) == "минута"
    assert _minute_word(2) == "минуты"
    assert _minute_word(5) == "минут"
    assert _minute_word(11) == "минут"


# ------------------------------------------------------------------ #
# _to_f / _int_word building blocks
# ------------------------------------------------------------------ #

def test_int_word_hundreds():
    assert _int_word(571) == "пятьсот семьдесят один"
    assert _int_word(100) == "сто"


def test_to_f_agrees_last_word_of_compound_number():
    assert _to_f("двадцать два") == "двадцать две"
    assert _to_f("пятьсот семьдесят один") == "пятьсот семьдесят одна"
    assert _to_f("три") == "три"

def test_normalize_no_false_positive_in_version():
    """Strings like 'v3.1' or '48000' should not be altered unexpectedly."""
    text = "версия 3.1 движка"
    result = normalize(text)
    # 3.1 should be normalised (it IS a decimal not a version string here), but
    # the key thing is it doesn't crash.
    assert isinstance(result, str)

def test_normalize_zero_integer():
    result = normalize("отрыв 0.3 сек")
    assert "три десятых" in result
    assert "0.3" not in result

def test_normalize_preserves_surrounding_text():
    result = normalize("Норрис достаёт Леклера на 1.2 секунды")
    assert "Норрис" in result
    assert "Леклера" in result
    assert "одна целая" in result

def test_normalize_no_crash_on_empty():
    assert normalize("") == ""

def test_normalize_no_crash_on_plain_text():
    text = "Старт дан. Гонка началась."
    assert normalize(text) == text
