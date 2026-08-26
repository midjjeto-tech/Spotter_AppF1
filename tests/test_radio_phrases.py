"""core/radio/phrases.py — реестр формулировок инженерского канала.

Тесты СВОЙСТВ: обходят реестр целиком, поэтому новая спека автоматически попадает
под все ограничения ТЗ §10–11 без правки тестов. Именно это и требуется от банка
— чтобы нельзя было тихо добавить двадцатисловную реплику споттера или critical,
который разрешено переписывать LLM.
"""
import re

import pytest

from core.radio import phrases, policy
from core.radio.phrases import PhraseError

ALL_SPECS = phrases.specs()
ALL_VARIANTS = [(s, v) for s in ALL_SPECS for v in s.variants]


def _for_every_variant(check):
    """Прогнать проверку по каждому варианту каждой спеки.

    Циклом, а не через parametrize: per-variant параметризация раздувала набор
    почти на две тысячи кейсов (половина всего pytest-прогона) при том же
    покрытии. Сообщение assert внутри проверки содержит код спеки и саму
    строку, поэтому диагностика от схлопывания не страдает."""
    def wrapper():
        for spec in ALL_SPECS:
            for variant in spec.variants:
                check(spec, variant)
    wrapper.__name__ = check.__name__
    wrapper.__doc__ = check.__doc__
    return wrapper


def _key(spec):
    """Стабильный selector_key для рендера в тестах."""
    return f"test:{spec.code}"


# ── Реестр ───────────────────────────────────────────────────────────────────

def test_registry_is_not_empty():
    assert ALL_SPECS


def test_codes_are_unique():
    codes = [s.code for s in ALL_SPECS]
    assert len(set(codes)) == len(codes)


def test_semantic_codes_are_stable_and_readable():
    for spec in ALL_SPECS:
        assert re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", spec.code), spec.code


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.code)
def test_no_spec_has_empty_variants(spec):
    assert spec.variants
    assert all(v.strip() for v in spec.variants)


def test_non_safety_engineer_pools_have_session_scale_variety():
    narrow_prefixes = ("spotter.", "box.call_", "flag.")
    narrow_codes = {
        "penalty.received",
        "damage.wing_critical",
        "damage.engine_critical",
    }
    broad = [
        spec for spec in ALL_SPECS
        if not spec.code.startswith(narrow_prefixes)
        and spec.code not in narrow_codes
    ]
    assert all(len(spec.variants) >= 6 for spec in broad)


#: Поля, значение которых раскрывается СТРОЧНЫМ фрагментом: числительное
#: («четвёртый»), число с единицей («12 кругов»), доля секунды («1,4»).
#: Противоположность им — `rival`/`corner`: там подставляется имя собственное с
#: заглавной, и открывать предложение им можно.
_LOWERCASE_FIELDS = frozenset({
    "position", "gap", "gap_behind", "wear", "ers", "fuel", "laps", "minutes",
    # «седьмом» у коуча — тоже строчная. Поле называется corner_no, а НЕ
    # corner: в battle.* под именем corner ездит ИМЯ поворота («Tamburello 1»),
    # с заглавной, и ему открывать предложение можно. Совпадение имён под
    # разным смыслом этот же тест и поймал.
    "corner_no",
    # Цена и отыгрыш у коуча: «три десятых», «полсекунды» — тоже строчные
    # (core/num_to_words.py::seconds_phrase).
    "loss", "gain",
    # Положение в поле: «в третьем секторе» и «восемнадцатый».
    "sector_no", "rank",
})

_SENTENCE_START_TOKEN = re.compile(r"(?:^|[.!?]\s+)\{([^{}]+)\}")


def test_lowercase_fields_never_open_a_sentence():
    """«Финиш. {position} — так и запишем.» превращается в «Финиш. четвёртый —
    так и запишем.»: строчная буква после точки.

    Тест существует потому, что этот брак НЕ ловится ничем остальным — ни длина,
    ни набор токенов, ни рендер без ошибок от него не меняются. Найден при
    вычитке вслух спеки `session.result` (этап 2 каста голосов); проверяются оба
    пула, общий и характерный, — иначе правило обходится вариантом персонажа."""
    for spec in ALL_SPECS:
        pools = [spec.variants, *spec.character_variants.values()]
        for pool in pools:
            for variant in pool:
                for field in _SENTENCE_START_TOKEN.findall(variant):
                    assert field not in _LOWERCASE_FIELDS, (
                        f"{spec.code}: {{{field}}} открывает предложение — "
                        f"{variant!r}")


#: Слова, по которым в реплике опознаётся ПОВРЕЖДЁННАЯ ДЕТАЛЬ.
_DAMAGE_PART_STEMS: dict[str, tuple[str, ...]] = {
    "wing": ("крыл",),
    "floor": ("днищ", "пол"),
    "gearbox": ("коробк", "трансмисс", "переключ"),
    "engine": ("двигател", "мотор", "силовая"),
}


def test_every_damage_line_names_the_broken_part():
    """Сообщение о повреждении обязано называть, ЧТО сломано: «есть потеря
    прижима» не говорит пилоту, ехать ли дальше или беречь машину.

    Тест появился после того, как анти-повтор (core/radio/variety.py) сделал
    достижимым вариант, до которого crc32 просто не доходил, — и один такой
    безымянный вариант в `damage.wing` немедленно всплыл. Это общее свойство
    анти-повтора: он вытаскивает на свет ровно те строки, что раньше лежали
    мёртвым грузом, поэтому проверять надо ВСЕ, а не только звучавшие."""
    for spec in ALL_SPECS:
        part = spec.code.split(".")[1].replace("_critical", "")
        stems = _DAMAGE_PART_STEMS.get(part) if spec.code.startswith("damage.") else None
        if not stems:
            continue
        for pool in [spec.variants, *spec.character_variants.values()]:
            for variant in pool:
                assert any(stem in variant.lower() for stem in stems), (
                    f"{spec.code}: не названа деталь — {variant!r}")


#: Предлоги, требующие косвенного падежа. Имя после них обязано склоняться, а
#: `{rival}`/`{corner}` подставляются КАК ЕСТЬ, в именительном.
#: Плюс несколько слов, управляющих падежом без предлога: «атака {rival}»,
#: «давление {rival}», «уступай {rival}». Список ЧАСТНЫЙ и полным быть не
#: может — полноценный разбор управления потребовал бы морфологии, которой у
#: нас нет. Он ловит те случаи, что реально встретились при слиянии банков;
#: остальное остаётся за вычиткой вслух.
_OBLIQUE_PREPOSITIONS = frozenset({
    "от", "у", "с", "со", "для", "к", "ко", "по", "о", "об", "про", "за",
    "над", "под", "между", "без", "до", "из", "на", "при",
    "атака", "атаку", "давление", "уступай", "уступать", "мешай",
})
#: Только `{rival}`. `{corner}` сознательно не проверяется: названия поворотов —
#: заимствованные имена собственные, которые в русском не склоняются («к Стоу»,
#: «до Копса»), и требовать от них падежа значило бы ловить несуществующую
#: ошибку.
_NAME_TOKENS = ("rival",)


def test_names_are_never_put_in_an_oblique_position():
    """«Атака от {rival}» превращается в «атака от Норрис» — имя не склоняется.

    Банк подставляет required-поля как есть, а выразить падеж одним токеном
    нельзя: `core/ru_names.py::decline` требует знать нужную форму, а её знает
    только автор конкретной фразы. Поэтому правило простое и проверяемое —
    имя стоит в именительном, а фраза строится вокруг него.

    Тест появился при слиянии банков: перенесённые формулировки принесли с
    собой «DRS у {rival}» и «тормозите с {rival}», и на слух это резало сразу.
    """
    for spec in ALL_SPECS:
        for pool in [spec.variants, *spec.character_variants.values()]:
            for variant in pool:
                for token in _NAME_TOKENS:
                    marker = "{" + token + "}"
                    idx = variant.find(marker)
                    while idx != -1:
                        head = variant[:idx].rstrip()
                        # Разделитель прямо перед именем означает НОВУЮ клаузу:
                        # «…не уступай, {rival} рядом» — там именительный верен,
                        # и предыдущее слово к имени отношения не имеет.
                        starts_clause = not head or head[-1] in ".,:;—-!?«("
                        words = head.split()
                        if words and not starts_clause:
                            word = words[-1].lower()
                            assert word not in _OBLIQUE_PREPOSITIONS, (
                                f"{spec.code}: «{word} {marker}» требует "
                                f"склонения — {variant!r}")
                        idx = variant.find(marker, idx + 1)


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.code)
def test_variants_are_unique_after_normalisation(spec):
    normalised = [" ".join(v.lower().split()) for v in spec.variants]
    assert len(set(normalised)) == len(normalised), spec.code


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.code)
def test_variants_are_a_tuple(spec):
    assert isinstance(spec.variants, tuple)


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.code)
def test_urgency_is_a_real_urgency(spec):
    assert spec.urgency in {
        policy.URGENCY_CRITICAL, policy.URGENCY_HIGH,
        policy.URGENCY_NORMAL, policy.URGENCY_LOW}


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.code)
def test_every_spec_declares_its_action(spec):
    """Действие нужно, чтобы тест мог сверить: варианты одной спеки не
    расходятся в смысле."""
    assert spec.action


# ── Длина (ТЗ §10) ───────────────────────────────────────────────────────────

def test_word_count_ignores_punctuation():
    assert phrases.word_count("Боксы в конце круга. Бокс, бокс.") == 6


@_for_every_variant
def test_variant_respects_the_word_limit(spec, variant):
    count = phrases.word_count(variant)
    assert count <= spec.max_words, (
        f"{spec.code}: {count} слов > {spec.max_words}: {variant!r}")


def test_spotter_never_exceeds_five_words():
    for spec in ALL_SPECS:
        if not spec.code.startswith("spotter."):
            continue
        assert spec.max_words == phrases.MAX_WORDS_SPOTTER
        for variant in spec.variants:
            assert phrases.word_count(variant) <= 5, variant


def test_limits_follow_urgency():
    assert phrases.spec_for("box.call_2").max_words == phrases.MAX_WORDS_CRITICAL
    assert phrases.spec_for("weather.rain_soon").max_words == phrases.MAX_WORDS_HIGH
    assert phrases.spec_for("gap.digest").max_words == phrases.MAX_WORDS_NORMAL


def test_low_urgency_is_not_a_licence_for_monologues():
    assert phrases.spec_for("ambient.calm").max_words <= phrases.MAX_WORDS_NORMAL


# ── Placeholders ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.code)
def test_all_variants_of_a_spec_use_the_same_required_fields(spec):
    """Иначе выбор варианта менял бы набор обязательных данных, и рендер падал
    бы через раз в зависимости от crc32."""
    for variant in spec.variants:
        used = phrases.tokens_in(variant)
        assert used == spec.all_fields, (
            f"{spec.code}: вариант {variant!r} использует {sorted(used)}, "
            f"спека объявляет {sorted(spec.all_fields)}")


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.code)
def test_required_and_volatile_fields_do_not_overlap(spec):
    assert not (spec.required_fields & spec.volatile_fields), spec.code


@_for_every_variant
def test_no_unbalanced_braces(spec, variant):
    assert variant.count("{") == variant.count("}"), f"{spec.code}: {variant!r}"


def test_missing_required_field_is_rejected():
    # position.leader_change требует `rival` — имя лидера это ИСТОРИЧЕСКИЙ факт
    # реплики, не волатильное значение.
    with pytest.raises(PhraseError, match="missing required field"):
        phrases.render("position.leader_change", {}, selector_key="k")


def test_unknown_field_is_rejected():
    with pytest.raises(PhraseError, match="unknown field"):
        phrases.render("tyres.ok", {"nonsense": 1}, selector_key="k")


def test_unknown_code_is_rejected():
    with pytest.raises(PhraseError, match="unknown phrase code"):
        phrases.render("no.such_code", selector_key="k")


def test_render_leaves_no_curly_placeholders_for_required_fields():
    rendered = phrases.render("position.leader_change", {"rival": "Норрис"},
                              selector_key="k")
    assert "{" not in rendered and "}" not in rendered
    assert "Норрис" in rendered


def test_render_of_a_plain_spec_has_no_placeholders():
    for spec in ALL_SPECS:
        if spec.all_fields:
            continue
        rendered = phrases.render(spec.code, selector_key=_key(spec))
        assert "{" not in rendered, f"{spec.code}: {rendered!r}"


# ── Volatile: не разрешаются слишком рано (ТЗ §8) ────────────────────────────

def test_volatile_placeholder_survives_render():
    """Task 3 только создаёт шаблон. Подставить заряд здесь — значит вернуть тот
    самый баг «батарея называет не те цифры»: между рендером и звуком проходят
    десятки секунд."""
    rendered = phrases.render("ers.level", selector_key="k")
    assert "{ers}" in rendered


def test_volatile_field_is_not_required_at_render_time():
    phrases.render("gap.digest", selector_key="k")        # не должно бросать
    phrases.render("position.current", selector_key="k")


def test_passing_a_volatile_value_early_is_still_not_substituted():
    """Даже если вызывающий передал значение, волатильный токен обязан выжить —
    иначе точка подстановки тихо расползётся обратно на раннюю стадию."""
    rendered = phrases.render("ers.level", {"ers": "18 процентов"},
                              selector_key="k")
    assert "{ers}" in rendered
    assert "18 процентов" not in rendered


def test_every_volatile_spec_is_known_to_the_volatile_vocabulary():
    """Токены позднего связывания должны быть теми же, что понимает резолвер
    (`core/strategy_ai/gap_digest.py`), иначе Task 4 их не найдёт."""
    declared = set()
    for spec in ALL_SPECS:
        declared |= spec.volatile_fields
    assert declared <= {"ers", "gap", "gap_behind", "position", "wear", "fuel",
                        "laps", "minutes"}


# ── LLM boundaries (ТЗ §11) ──────────────────────────────────────────────────

@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.code)
def test_critical_specs_never_allow_llm(spec):
    if spec.urgency == policy.URGENCY_CRITICAL:
        assert not spec.allow_llm, spec.code


@pytest.mark.parametrize("prefix", [
    "spotter.", "box.", "flag.", "penalty.", "damage.", "track_limits.",
])
def test_protected_sections_never_allow_llm(prefix):
    """Сторона машины, команда в боксы, тип флага, штраф, тип повреждения —
    ТЗ §11 запрещает отдавать их модели."""
    covered = [s for s in ALL_SPECS if s.code.startswith(prefix)]
    assert covered, f"нет спек с префиксом {prefix}"
    for spec in covered:
        assert not spec.allow_llm, spec.code


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.code)
def test_specs_with_exact_numbers_never_allow_llm(spec):
    """Сообщение с точным числом модель переписывать не может: она изменит
    число."""
    if spec.all_fields & {"gap", "ers", "wear", "fuel", "laps", "minutes",
                          "position"}:
        assert not spec.allow_llm, spec.code


def test_llm_is_allowed_only_for_optional_analytics():
    allowed = [s.code for s in ALL_SPECS if s.allow_llm]
    assert allowed == ["ambient.calm"], allowed


def test_ambient_still_allows_generation():
    """`allow_llm` — единственное разрешение на генерацию во всём банке.
    Потеря флага при правке пула сделала бы ambient-тик немым, и заметили бы
    это только по тишине в гонке."""
    assert phrases.spec_for("ambient.calm").allow_llm is True


def test_ambient_variants_report_a_subject():
    """«Всё стабильно» / «Ситуация под контролем» — четыре способа ничего не
    сказать. Каждый вариант обязан НАЗЫВАТЬ предмет доклада: машина, темп,
    данные, стратегия, соперники, трасса. Тест грубый (подстроки), но ловит
    именно тот откат, который здесь уже случался — возврат к воде."""
    subjects = ("машин", "ритм", "темп", "данны", "стратег", "соперник", "трасс")
    for variant in phrases.spec_for("ambient.calm").variants:
        assert any(s in variant.lower() for s in subjects), variant


# ── Детерминированный выбор ──────────────────────────────────────────────────

def test_same_selector_key_always_gives_the_same_variant():
    first = phrases.render("battle.held", selector_key="dedupe:battle:norris")
    for _ in range(20):
        assert phrases.render(
            "battle.held", selector_key="dedupe:battle:norris") == first


def test_one_dedupe_key_keeps_one_variant_across_repeated_packets():
    """Повторный пакет телеметрии по той же ситуации не должен переписывать уже
    произнесённую формулировку."""
    key = "20260730:battle:norris:lap_18:near"
    picks = {phrases.render("battle.defend", {"rival": "Норрис"},
                            selector_key=key) for _ in range(30)}
    assert len(picks) == 1


def test_different_situations_get_different_variants():
    """Иначе вариативность существовала бы только на бумаге."""
    picked = {
        phrases.render("battle.held", selector_key=f"situation-{i}")
        for i in range(40)
    }
    assert len(picked) > 1


def test_selection_does_not_depend_on_the_process_hash_seed():
    """Встроенный `hash()` для строк солится по процессу — crc32 нет.
    Захардкоженное ожидание ловит подмену механизма обратно на `hash()`."""
    variants = ("a", "b", "c", "d")
    assert phrases.select_variant(variants, "stable-key") == \
        phrases.select_variant(variants, "stable-key")
    # Конкретное значение зафиксировано: crc32 стабилен между запусками и ОС.
    import zlib
    assert phrases.select_variant(variants, "stable-key") == \
        variants[zlib.crc32(b"stable-key") % 4]


def test_no_module_level_randomness_is_used():
    """Проверяем КОД, а не текст: в шапке модуля слово `random.choice` стоит
    законно — там объясняется, почему его здесь нет."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(phrases))

    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "random" not in imported
    assert not hasattr(phrases, "random")


def test_empty_variants_raise_rather_than_return_empty_string():
    with pytest.raises(PhraseError, match="no variants"):
        phrases.select_variant((), "k")


# ── Смысл вариантов ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.code)
def test_variants_share_one_action(spec):
    """Все варианты одной спеки описывают ОДНО действие. Тест сторожит
    структуру: действие объявлено на спеке, значит вариант физически не может
    нести другое."""
    assert isinstance(spec.action, str) and spec.action


def test_box_call_variants_never_contradict_each_other():
    """Ни один вариант команды в боксы не должен звучать как «останься»."""
    for code in ("box.call_1", "box.call_2", "box.call_3"):
        spec = phrases.spec_for(code)
        assert spec.action == "pit_now"
        for variant in spec.variants:
            lowered = variant.lower()
            assert "останься" not in lowered
            assert "не заходи" not in lowered
            assert "бокс" in lowered or "заходим" in lowered, variant


def test_spotter_side_variants_never_mention_the_other_side():
    """Главная защита от того, чтобы выбор варианта решал СТОРОНУ."""
    for variant in phrases.spec_for("spotter.left").variants:
        assert "справ" not in variant.lower(), variant
    for variant in phrases.spec_for("spotter.right").variants:
        assert "слев" not in variant.lower(), variant


# ── TTS-безопасность ─────────────────────────────────────────────────────────

# `_` допустим только внутри {токенов} (gap_behind, ers_clause).
_ALLOWED_CHARS = re.compile(r"^[А-Яа-яЁё0-9A-Za-z\s.,!?:—\-{}_]+$")


@_for_every_variant
def test_only_tts_safe_characters(spec, variant):
    assert _ALLOWED_CHARS.match(variant), f"{spec.code}: {variant!r}"


@_for_every_variant
def test_no_symbols_that_tts_reads_aloud(spec, variant):
    for bad in ('"', "'", "(", ")", "/", "\\", "…", ";", "*", "#", "&", "+", "%"):
        assert bad not in variant, f"{spec.code}: {bad!r} в {variant!r}"


@_for_every_variant
def test_variant_ends_with_terminal_punctuation(spec, variant):
    assert variant[-1] in ".!?", f"{spec.code}: {variant!r}"


@_for_every_variant
def test_no_double_spaces_or_stray_whitespace(spec, variant):
    assert "  " not in variant
    assert variant == variant.strip()


@_for_every_variant
def test_no_placeholder_debris(spec, variant):
    for junk in ("None", "%s", "%d", "{}", "—%", "N/A", "nan"):
        assert junk not in variant, f"{spec.code}: {junk!r} в {variant!r}"


@_for_every_variant
def test_no_unit_word_follows_a_numeric_token(spec, variant):
    """Русское согласование числительных нельзя оставлять в шаблоне: «через
    {minutes} минут» даёт «через 1 минут». Единицу приносит уже согласованное
    значение (см. конвенцию в шапке phrases.py)."""
    for unit in ("процент", "минут", "круг", "килограмм", "секунд"):
        assert not re.search(r"\{[a-z_]+\}\s+" + unit, variant), (
            f"{spec.code}: единица после токена в {variant!r}")


# ── Стиль (ТЗ §10) ───────────────────────────────────────────────────────────

@_for_every_variant
def test_no_bureaucratic_padding(spec, variant):
    lowered = variant.lower()
    for weed in ("мы хотели бы", "я хотел бы", "в данный момент", "пожалуйста",
                 "хотел бы проинформировать", "обращаем внимание",
                 "необходимо отметить", "таким образом", "в связи с тем",
                 "возможно, тебе стоит", "рассмотреть вариант",
                 "является достаточно", "составляет примерно"):
        assert weed not in lowered, f"{spec.code}: {weed!r} в {variant!r}"


@_for_every_variant
def test_one_variant_carries_at_most_two_sentences(spec, variant):
    sentences = [s for s in re.split(r"[.!?]+", variant) if s.strip()]
    assert len(sentences) <= 2, f"{spec.code}: {variant!r}"


def test_critical_variants_do_not_start_with_a_reason():
    """ТЗ §10: сначала команда, затем причина."""
    for spec in ALL_SPECS:
        if spec.urgency != policy.URGENCY_CRITICAL:
            continue
        for variant in spec.variants:
            lowered = variant.lower()
            for reason_first in ("потому что", "так как", "поскольку",
                                 "из-за того", "ввиду"):
                assert not lowered.startswith(reason_first), variant


def test_critical_variants_contain_no_hedging():
    """ТЗ §4: без неопределённых формулировок в critical-командах."""
    for spec in ALL_SPECS:
        if spec.urgency != policy.URGENCY_CRITICAL:
            continue
        for variant in spec.variants:
            lowered = variant.lower()
            for hedge in ("возможно", "наверное", "может быть", "если хочешь",
                          "попробуй", "как-нибудь", "вероятно"):
                assert hedge not in lowered, f"{spec.code}: {variant!r}"


# ── Подтверждения и «нет данных» ─────────────────────────────────────────────

def test_acknowledgements_are_short_and_varied():
    assert 4 <= len(phrases.ACKNOWLEDGEMENTS) <= 12
    assert len(set(phrases.ACKNOWLEDGEMENTS)) == len(phrases.ACKNOWLEDGEMENTS)
    for ack in phrases.ACKNOWLEDGEMENTS:
        assert phrases.word_count(ack) <= 5, ack
        assert ack[-1] in ".!?"


def test_no_data_answers_are_short():
    """ТЗ §12: не использовать длинные универсальные отказы."""
    assert phrases.NO_DATA_ANSWERS
    for answer in phrases.NO_DATA_ANSWERS:
        assert phrases.word_count(answer) <= 5, answer


# ── Терминология разрывов ────────────────────────────────────────────────────
# Две ошибки, найденные ревью пользователя: «отрыв» применялся к машине ВПЕРЕДИ
# (дефицит назывался словом для преимущества), и соседние фрагменты различались
# одной буквой («догоняем» / «догоняют»), что через TTS неразличимо.

_FRONT_CODES = ("gap.front_first", "gap.front_closing",
                "gap.front_growing", "gap.front_stable")
_BEHIND_CODES = ("gap.behind_first", "gap.behind_closing",
                 "gap.behind_growing", "gap.behind_stable")


@pytest.mark.parametrize("code", _FRONT_CODES)
def test_front_gap_never_called_otryv(code):
    """«Отрыв» — преимущество, которое пилот ДЕРЖИТ. До машины впереди у него
    отставание, и называть его отрывом значит перепутать два противоположных
    понятия."""
    for variant in phrases.spec_for(code).variants:
        assert "трыв" not in variant.lower(), f"{code}: {variant!r}"


@pytest.mark.parametrize("code", _BEHIND_CODES)
def test_behind_gap_never_called_otstavanie(code):
    """Симметрично: разрыв до преследователя — не отставание пилота."""
    for variant in phrases.spec_for(code).variants:
        assert "тставан" not in variant.lower(), f"{code}: {variant!r}"


def test_front_and_behind_fragments_are_not_near_homophones():
    """Фрагменты про машину впереди и про преследователя не должны различаться
    одной буквой: «догоняем» и «догоняют» означают противоположное, а на слух в
    кокпите неразличимы, и переспросить некого."""
    def words(codes):
        out = set()
        for code in codes:
            for variant in phrases.spec_for(code).variants:
                out |= {w.lower().strip(".,:!?") for w in variant.split()}
        return out

    front, behind = words(_FRONT_CODES), words(_BEHIND_CODES)
    collisions = [
        (a, b) for a in front for b in behind
        if a != b and len(a) == len(b) >= 6
        and sum(x != y for x, y in zip(a, b)) == 1
    ]
    assert not collisions, f"почти одинаковые на слух: {collisions}"


# ── Коуч пилотажа (фаза 1) ───────────────────────────────────────────────────

_COACH_CODES = [
    "coach.lockup_front_left", "coach.lockup_front_right",
    "coach.wheelspin", "coach.understeer", "coach.oversteer", "coach.offtrack",
]


@pytest.mark.parametrize("code", _COACH_CODES)
def test_coach_spec_exists(code):
    assert code in phrases.codes()


@pytest.mark.parametrize("code", _COACH_CODES)
def test_coach_spec_has_enough_variants(code):
    """Инвариант банка для небоевой спеки: подсказка звучит по многу раз за
    сессию, шесть вариантов — минимум, чтобы не приедаться."""
    assert len(phrases.spec_for(code).variants) >= 6


@pytest.mark.parametrize("code", _COACH_CODES)
def test_coach_spec_is_never_critical(code):
    """Подсказка по пилотажу не имеет права перебивать споттера или box-call."""
    assert phrases.spec_for(code).urgency != policy.URGENCY_CRITICAL


def test_lockup_sides_are_separate_specs_not_one_pool():
    """Сторона колеса — отдельная спека, а не вариант в общем пуле: «левое» и
    «правое» требуют разных действий, и выбор не должен делать колода."""
    left = phrases.spec_for("coach.lockup_front_left")
    right = phrases.spec_for("coach.lockup_front_right")
    assert left.action != right.action
    for variant in left.variants:
        assert "прав" not in variant.lower(), variant
    for variant in right.variants:
        assert "лев" not in variant.lower(), variant


# ── Коуч, фаза 2: отклонения от эталонного круга ─────────────────────────────

_COACH_REF_CODES = [
    "coach.ref_brake_early", "coach.ref_apex_slow",
    "coach.ref_throttle_late", "coach.ref_losing_time",
]


@pytest.mark.parametrize("code", _COACH_REF_CODES)
def test_coach_reference_spec_exists(code):
    assert code in phrases.codes()


@pytest.mark.parametrize("code", _COACH_REF_CODES)
def test_coach_reference_spec_has_enough_variants(code):
    assert len(phrases.spec_for(code).variants) >= 6


@pytest.mark.parametrize("code", _COACH_REF_CODES)
def test_coach_reference_spec_is_never_critical(code):
    assert phrases.spec_for(code).urgency != policy.URGENCY_CRITICAL


# ── Коуч, фаза 4: работа сессии ──────────────────────────────────────────────

_COACH_FOCUS_CODES = [
    "coach.focus_set", "coach.focus_progress", "coach.focus_fixed",
]


@pytest.mark.parametrize("code", _COACH_FOCUS_CODES)
def test_coach_focus_spec_exists(code):
    assert code in phrases.codes()


@pytest.mark.parametrize("code", _COACH_FOCUS_CODES)
def test_coach_focus_spec_is_never_critical(code):
    """Работа над ошибкой не имеет права перебивать споттера или box-call."""
    assert phrases.spec_for(code).urgency != policy.URGENCY_CRITICAL


@pytest.mark.parametrize("code", _COACH_FOCUS_CODES)
def test_coach_focus_spec_always_names_the_corner(code):
    """Работа без места — это не работа: пилот пойдёт искать её по всему кругу."""
    assert "corner_no" in phrases.spec_for(code).required_fields


def test_coach_focus_speaks_the_price_unlike_the_reference_hints():
    """Цена ЗВУЧИТ — и это не послабление к запрету на величину в coach.ref_*.

    Там запрещено отклонение («на двенадцать метров раньше»): его пилот в
    повороте не применит. Здесь звучит цена в секундах — она отвечает на вопрос
    «почему этим стоит заняться», без которого коуч остаётся набором верных по
    отдельности замечаний. Тест сторожит именно РАЗНИЦУ: если однажды исчезнет
    цена у focus_set или появится величина у ref_*, упадёт он.
    """
    assert "loss" in phrases.spec_for("coach.focus_set").required_fields
    assert "gain" in phrases.spec_for("coach.focus_progress").required_fields
    for code in _COACH_REF_CODES:
        assert phrases.spec_for(code).required_fields == frozenset({"corner_no"})


def test_coach_focus_closing_line_carries_no_number():
    """«Закрыли» — про факт, а не про величину: остаток по определению мал."""
    assert phrases.spec_for("coach.focus_fixed").required_fields == frozenset(
        {"corner_no"})


# ── Положение в поле по секторам ─────────────────────────────────────────────

_FIELD_CODES = ["field.sector_weak", "field.sector_strong"]


@pytest.mark.parametrize("code", _FIELD_CODES)
def test_field_spec_exists(code):
    assert code in phrases.codes()


@pytest.mark.parametrize("code", _FIELD_CODES)
def test_field_spec_is_never_critical(code):
    assert phrases.spec_for(code).urgency != policy.URGENCY_CRITICAL


@pytest.mark.parametrize("code", _FIELD_CODES)
def test_field_spec_always_names_the_sector_and_the_place(code):
    """Место без сектора и сектор без места по отдельности не значат ничего."""
    required = phrases.spec_for(code).required_fields
    assert "sector_no" in required
    assert "rank" in required


def test_field_specs_never_name_the_sector_leader():
    """Имя потребовало бы падежа, а падеж свободной строкой банк не выражает.

    На экране имя есть — там его читают глазами, а не слушают."""
    for code in _FIELD_CODES:
        assert "driver" not in phrases.spec_for(code).all_fields
        assert "rival" not in phrases.spec_for(code).all_fields


@pytest.mark.parametrize("code", _FIELD_CODES)
def test_field_line_renders_into_a_whole_sentence(code):
    spec = phrases.spec_for(code)
    available = {"sector_no": "третьем", "rank": "восемнадцатый",
                 "loss": "полсекунды"}
    fields = {k: v for k, v in available.items() if k in spec.required_fields}
    for selector in range(len(spec.variants) * 3):
        text = phrases.render(code, fields, selector_key=str(selector))
        assert "{" not in text and "}" not in text, text
        assert "в третьем секторе" in text.lower(), text


@pytest.mark.parametrize("code", _COACH_FOCUS_CODES)
def test_coach_focus_renders_into_a_whole_sentence(code):
    spec = phrases.spec_for(code)
    available = {"corner_no": "седьмом", "loss": "три десятых",
                 "gain": "две десятых"}
    fields = {k: v for k, v in available.items() if k in spec.required_fields}
    for selector in range(len(spec.variants) * 3):
        text = phrases.render(code, fields, selector_key=str(selector))
        assert "{" not in text and "}" not in text, text
        # Токен стоит только после предлога «в» — падеж у него один,
        # предложный (core/radio/corner_words.py). Регистр не в счёт: вариант
        # может начинаться этим предлогом.
        assert "в седьмом" in text.lower(), text


@pytest.mark.parametrize("code", _COACH_REF_CODES)
def test_coach_reference_spec_never_reads_out_a_magnitude(code):
    """Величину отклонения мы намеренно не зачитываем: «на двенадцать метров
    раньше» пилот в повороте не применит, ему нужно направление.

    Раньше этот тест требовал ОТСУТСТВИЯ полей вообще — и тем самым запрещал
    заодно назвать МЕСТО. Это оказалось не мелочью: сравнение с эталоном
    считается на пересечении линии старт/финиш, поэтому «здесь» и «в этом
    повороте» звучали на прямой и указывали в никуда. Место теперь обязательно,
    запрет на числа остался."""
    spec = phrases.spec_for(code)
    assert spec.required_fields == frozenset({"corner_no"}), (
        f"{code}: подсказка обязана называть поворот и ничего кроме")
    assert not spec.volatile_fields, f"{code}: величине здесь не место"


def test_corner_number_always_follows_the_preposition():
    """`{corner_no}` — предложный падеж, и это накладывает ограничение на место.

    `ordinal_prepositional` отдаёт «четвёртом»: такая форма ложится только
    после «в»/«во». Любая другая позиция даёт мусор вслух — «главная потеря
    круга — четвёртом поворот», — и никакой из существующих инвариантов её не
    ловит: токен на месте, поля совпадают, длина в норме, предложение с
    заглавной. Правило было неписаным, пока новые пулы персонажей его не
    нарушили двадцатью четырьмя фразами разом (2026-08-26).

    Предлог проверяется ПЕРЕД токеном и с учётом «во»: стык чинит
    `euphony.fix_prepositions`, но только если предлог там вообще есть.
    """
    offenders = []
    for spec in ALL_SPECS:
        pools = [spec.variants, *spec.character_variants.values()]
        for pool in pools:
            for variant in pool:
                for match in re.finditer(r"\{corner_no\}", variant):
                    before = variant[:match.start()].rstrip()
                    if not re.search(r"(?:^|[\s(—,:])[вВ]о?$", before):
                        offenders.append(f"{spec.code}: {variant!r}")
    assert not offenders, (
        "{corner_no} стоит не после «в» — вслух это будет мусор:\n  "
        + "\n  ".join(offenders))
