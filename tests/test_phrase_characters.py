"""Характер персонажа меняет формулировку — но только там, где это безопасно.

Боевые команды обязаны звучать одинаково у всех троих: пилот должен узнать
команду с первого слога, а не разгадывать очередную формулировку
(core/radio/phrases.py, комментарий над реестром). Тест на это стоит здесь, а
не в общем файле банка, потому что это правило про ХАРАКТЕР, а не про длину.
"""
import pytest

from core.radio import phrases, voice_cast


#: Спеки, где характер запрещён. Список закрытый и проверяется тестом:
#: добавление сюда новой безопасной команды должно быть осознанным.
SAFETY_CODES = (
    "spotter.left", "spotter.right", "spotter.both", "spotter.clear",
    "box.call_1", "box.call_2", "box.call_3",
    "flag.red", "penalty.received",
    "damage.wing_critical", "damage.engine_critical",
)


def test_safety_specs_have_no_character_variants():
    for code in SAFETY_CODES:
        spec = phrases.spec_for(code)
        assert not spec.character_variants, f"{code}: характер в боевой команде"


@pytest.mark.parametrize("character", list(voice_cast.CHARACTERS))
def test_safety_phrases_are_identical_for_every_character(character):
    """Не просто «нет вариантов в спеке» — проверяем сам рендер."""
    for code in SAFETY_CODES:
        base = phrases.render(code, selector_key="k")
        with_char = phrases.render(code, selector_key="k", character=character)
        assert base == with_char, code


def test_character_changes_the_wording_where_it_is_allowed():
    """Хотя бы одна спека обязана реально различаться — иначе механика есть,
    а эффекта нет, и это заметят только ушами."""
    code = "praise.overtake"
    said = {phrases.render(code, selector_key="k", character=c)
            for c in voice_cast.CHARACTERS}
    assert len(said) > 1, "все персонажи сказали одно и то же"


def test_unknown_character_falls_back_to_the_shared_pool():
    code = "praise.overtake"
    assert (phrases.render(code, selector_key="k", character="нет такого")
            == phrases.render(code, selector_key="k"))


def test_character_variants_respect_the_length_limit():
    """Лимит длины — свойство СИТУАЦИИ (срочность), а не персонажа. Вариант
    характера не имеет права быть длиннее общего."""
    for spec in phrases.specs():
        for variants in spec.character_variants.values():
            for text in variants:
                assert phrases.word_count(text) <= spec.max_words, text


# Инварианты банка (tests/test_radio_phrases.py) обходят только `spec.variants`.
# Пул персонажа — второй источник текста, и без этих трёх тестов он проезжает
# мимо всех проверок сразу: сломать рендер, устроить повтор на всю гонку и
# разойтись в действии можно, не тронув ни одного существующего теста.

def test_character_pools_use_the_same_fields_as_the_spec():
    """Вариант персонажа с чужим набором токенов роняет рендер (PhraseError →
    молчание) ровно для того персонажа, которого выбрал пользователь. Общий пул
    при этом остаётся зелёным, и баг виден только на одной настройке."""
    for spec in phrases.specs():
        for character, variants in spec.character_variants.items():
            for text in variants:
                assert phrases.tokens_in(text) == spec.all_fields, (
                    f"{spec.code}/{character}: {text!r} использует "
                    f"{sorted(phrases.tokens_in(text))}, спека объявляет "
                    f"{sorted(spec.all_fields)}")


def test_character_pools_are_as_varied_as_the_shared_pool():
    """Пул из двух формулировок на гонку — это повтор, а не характер. Персонаж
    не имеет права быть ОДНООБРАЗНЕЕ общего тона: пользователь включил его ради
    разнообразия, а получил бы обратное."""
    for spec in phrases.specs():
        for character, variants in spec.character_variants.items():
            assert len(variants) >= len(spec.variants), (
                f"{spec.code}/{character}: {len(variants)} вариантов против "
                f"{len(spec.variants)} в общем пуле")


def test_character_pools_have_no_duplicates():
    for spec in phrases.specs():
        for character, variants in spec.character_variants.items():
            normalised = [" ".join(v.lower().split()) for v in variants]
            assert len(set(normalised)) == len(normalised), \
                f"{spec.code}/{character}"
