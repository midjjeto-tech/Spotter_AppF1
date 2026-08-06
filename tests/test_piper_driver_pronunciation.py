from new_tts.ru_textnorm import normalize


def test_piper_respells_only_first_names_with_wrong_espeak_stress():
    assert normalize("Серхио Перес") == "Серхйо Перес"
    assert normalize("Ландо Норрис") == "Ландъо Норрис"
    assert normalize("Макс Ферстаппен") == "Макс Ферстаппен"


def test_piper_cyrillizes_latin_driver_names_before_respelling():
    assert normalize("Sergio Pérez") == "Серхйо Перес"
    assert normalize("Max Verstappen") == "Макс Ферстаппен"
    assert normalize("Lando Norris") == "Ландъо Норрис"


def test_piper_respell_produces_expected_primary_stress_phonemes():
    from piper.phonemize_espeak import EspeakPhonemizer

    phonemizer = EspeakPhonemizer()
    sergio = "".join(phonemizer.phonemize("ru", normalize("Серхио"))[0])
    lando = "".join(phonemizer.phonemize("ru", normalize("Ландо"))[0])

    assert sergio == "sʲˈerxjʌ"
    assert lando == "ɭˈɑndʌ"
