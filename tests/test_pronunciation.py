from core.pronunciation import apply_yandex


def test_problem_driver_full_names_get_explicit_yandex_stress():
    assert apply_yandex("Серхио Перес") == "С+ерхио П+ерес"
    assert apply_yandex("Ландо Норрис") == "Л+андо Н+оррис"
    assert apply_yandex("Макс Ферстаппен") == "Макс Ферст+аппен"


def test_latin_and_jolpica_names_are_cyrillic_before_yandex_stress():
    assert apply_yandex("Sergio Pérez") == "С+ерхио П+ерес"
    assert apply_yandex("Max Verstappen") == "Макс Ферст+аппен"
    assert apply_yandex("Lando Norris") == "Л+андо Н+оррис"


def test_problem_driver_stress_survives_russian_cases():
    assert apply_yandex("позади Переса") == "позади П+ереса"
    assert apply_yandex("атакует Норриса") == "атакует Н+орриса"
    assert apply_yandex("быстрее Ферстаппена") == "быстрее Ферст+аппена"


def test_perez_stem_does_not_touch_unrelated_russian_words():
    text = "Перестал атаковать после пересечения траекторий"
    assert apply_yandex(text) == text


def test_bortoleto_gets_stress_mark_in_nominative():
    assert apply_yandex("Бортолето") == "Бортол+ето"


def test_bortoleto_gets_stress_mark_case_insensitive():
    assert apply_yandex("бортолето") == "бортол+ето"


def test_leclerc_respelled_to_stressed_k_form():
    # GigaChat/транслит пишут "Леклер"/"Леклера" — Yandex читал криво; на слух
    # выбран "Лекл+ерк" (с "к" и ударением, 2026-07-25). Склонения сохраняются.
    assert apply_yandex("Леклер") == "Лекл+ерк"
    assert apply_yandex("атакует Леклера") == "атакует Лекл+ерка"
    assert apply_yandex("Charles Leclerc") == "Шарль Лекл+ерк"
    # уже написано с "к" — не трогаем (без двойного "к")
    assert apply_yandex("Леклерк") == "Леклерк"


def test_other_driver_names_untouched():
    for name in ("Расселл", "Хэмилтон", "Пиастри", "Алонсо"):
        assert apply_yandex(name) == name


def test_empty_and_none_safe():
    assert apply_yandex("") == ""
    assert apply_yandex(None) is None
