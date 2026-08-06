"""Обращение к пилоту по имени: «Макс, шины сдают.»

Не переписывание банка, а необязательный префикс. Требования, каждое из
которых ловит свою ошибку:
  - никогда без имени (кастомный пилот «Моя команда» → first_name_of() = None);
  - НЕ в каждой реплике — иначе приторно и перестаёт работать как акцент;
  - детерминированно: одна и та же ситуация не меняет решение между пакетами
    телеметрии, иначе повтор переписывал бы уже произнесённое;
  - никогда у споттера — там счёт на доли секунды, лишнее слово стоит места.
"""
import pytest

from core.radio import address, voice_cast


def test_no_name_means_no_address():
    assert address.apply("Шины сдают.", None, "sokolova", "k") == "Шины сдают."
    assert address.apply("Шины сдают.", "", "sokolova", "k") == "Шины сдают."


def test_address_is_deterministic_for_the_same_situation():
    first = address.apply("Шины сдают.", "Макс", "sokolova", "k")
    second = address.apply("Шины сдают.", "Макс", "sokolova", "k")
    assert first == second


def test_address_prefixes_the_name_when_it_fires():
    """Ищем ключ, на котором обращение срабатывает, и проверяем форму."""
    for i in range(50):
        out = address.apply("Шины сдают.", "Макс", "sokolova", f"k{i}")
        if out != "Шины сдают.":
            assert out == "Макс, шины сдают."
            return
    pytest.fail("обращение не сработало ни на одном из 50 ключей")


def test_frequency_differs_between_characters():
    """Частота — часть характера: наставник зовёт по имени чаще сухого
    профессионала. Если частоты совпадут, различие персонажей потеряется."""
    def rate(character: str) -> float:
        hits = sum(address.apply("Шины сдают.", "Макс", character, f"k{i}")
                   != "Шины сдают." for i in range(200))
        return hits / 200

    assert rate("sokolova") > rate("volkov")


def test_every_character_has_a_sane_rate():
    for character in voice_cast.CHARACTERS.values():
        assert 0.0 <= character.address_rate <= 0.5, character.character_id


def test_spotter_phrases_are_never_addressed():
    """У споттера счёт на доли секунды — имя стоит места, которого нет."""
    assert address.apply("Слева машина!", "Макс", "sokolova", "k",
                         allowed=False) == "Слева машина!"


def test_critical_engineer_lines_are_never_addressed():
    """Решение, изначально вынесенное пользователю и закрытое разбором
    остатков: критические реплики ИНЖЕНЕРА обращения тоже не получают.

    «Макс, бокс! Бокс!» стоит лишнего слога ровно тогда, когда слог дороже
    всего. Аргумент «счёт на доли секунды» применим к ним в точности так же,
    как к споттеру, а узнаваемость команды важнее личного тона.
    """
    import core.engine as eng_mod
    from core.radio import phrases, policy

    engine = eng_mod.F1Engine.__new__(eng_mod.F1Engine)   # без звука и сети

    for code in ("box.call_3", "flag.red", "damage.engine_critical",
                 "penalty.received"):
        assert phrases.spec_for(code).urgency == policy.URGENCY_CRITICAL, code
        assert not engine._address_allowed({"event_code": "STRAT_BOX_CALL_3"},
                                           code), code

    # А несрочные — получают: иначе обращение исчезло бы вовсе.
    assert engine._address_allowed({"event_code": "ENGINEER_GAP_DIGEST"},
                                   "gap.digest")


def test_an_unknown_code_gets_no_address():
    """Спеки нет — судить не по чему. Промолчать безопаснее, чем угадать."""
    import core.engine as eng_mod

    engine = eng_mod.F1Engine.__new__(eng_mod.F1Engine)
    assert not engine._address_allowed({"event_code": "X"}, "нет.такого")
