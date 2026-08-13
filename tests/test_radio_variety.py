"""Анти-повтор: инженер не произносит одну и ту же формулировку подряд.

Зачем это существует. Банк закрепляет вариант за СИТУАЦИЕЙ через crc32, и это
правильно: повторный пакет телеметрии по той же ситуации обязан дать ту же
строку, а не переписать уже произнесённую. Но crc32 закрепляет за КЛЮЧОМ, а
между разными ключами сталкивается. Замер на живом банке до этой работы: из
двадцати срабатываний `drs.in_range` три ПОДРЯД давали «Оставайся в секунде
для DRS».

Оба свойства должны сохраниться одновременно, и тесты стерегут именно это:
закрепление за ситуацией — и отсутствие повтора между ситуациями.
"""
import pytest

from core.radio import phrases, variety


@pytest.fixture(autouse=True)
def _clean():
    variety.reset()
    yield
    variety.reset()


def test_same_situation_always_gives_the_same_wording():
    """Главное свойство банка, которое анти-повтор НЕ имеет права сломать:
    повторный пакет по той же ситуации не переписывает уже произнесённое."""
    first = phrases.render("drs.in_range", selector_key="sit-42")
    for _ in range(5):
        assert phrases.render("drs.in_range", selector_key="sit-42") == first


def test_same_situation_survives_other_situations_in_between():
    """Закрепление обязано пережить чужие ситуации между вызовами — иначе
    реплика, уже стоящая в очереди на озвучку, перерисуется под другой текст."""
    first = phrases.render("drs.in_range", selector_key="sit-A")
    for i in range(10):
        phrases.render("drs.in_range", selector_key=f"noise-{i}")
    assert phrases.render("drs.in_range", selector_key="sit-A") == first


def test_consecutive_situations_never_repeat_the_wording():
    said = [phrases.render("drs.in_range", selector_key=f"lap-{i}")
            for i in range(30)]
    adjacent = [(a, b) for a, b in zip(said, said[1:]) if a == b]
    assert not adjacent, adjacent


@pytest.mark.parametrize("code", [
    "drs.in_range", "tyres.wear", "gap.front_closing", "strategy.push_pace",
])
def test_no_spec_repeats_itself_back_to_back(code):
    said = [phrases.render(code, selector_key=f"{code}:{i}") for i in range(30)]
    assert not [1 for a, b in zip(said, said[1:]) if a == b], code


def test_character_pools_get_the_same_protection():
    """Пул персонажа — второй источник текста и такой же кандидат на повтор."""
    said = [phrases.render("tyres.wear", selector_key=f"k{i}", character="grom")
            for i in range(30)]
    assert not [1 for a, b in zip(said, said[1:]) if a == b]


def test_a_wording_cannot_return_until_others_have_been_used():
    """Памяти в один шаг мало: она убирает соседние повторы, но на пуле из
    шести crc32 всё равно выдавал одну строку трижды за восемь реплик. Окно —
    половина пула, значит на пуле из шести строка не возвращается раньше, чем
    через три другие."""
    said = [phrases.render("drs.in_range", selector_key=f"lap-{i}")
            for i in range(24)]
    distances = []
    for wording in set(said):
        positions = [i for i, s in enumerate(said) if s == wording]
        distances += [b - a for a, b in zip(positions, positions[1:])]
    assert distances, "ни одна строка не повторилась — тест ничего не проверил"
    assert min(distances) >= 4, min(distances)


def test_the_whole_pool_stays_in_rotation():
    """Анти-повтор не должен схлопнуть выбор до пары «любимых» строк."""
    said = {phrases.render("drs.in_range", selector_key=f"k-{i}")
            for i in range(24)}
    assert len(said) == len(phrases.spec_for("drs.in_range").variants)


def test_reset_forgets_history():
    before = phrases.render("drs.in_range", selector_key="same-key")
    variety.reset()
    assert phrases.render("drs.in_range", selector_key="same-key") == before


def test_single_variant_pool_does_not_loop_forever():
    """Пул из одной строки повтор исключить не может — важно, что он не виснет
    и не падает, а честно возвращает единственный вариант."""
    assert variety.index_for("x.single", "k1", 0, 1) == 0
    assert variety.index_for("x.single", "k2", 0, 1) == 0


def test_shortest_mode_stays_short():
    """Режим «коротко» обещает лаконичность, а не одну строку на весь заезд.

    Раньше здесь стоял обратный контракт: `shortest=True` возвращал строго
    минимальный вариант и селектор игнорировал. Обещание он выполнял, но ценой,
    которую никто не выбирал: пул из шести формулировок схлопывался в ОДНУ на
    всю гонку, и «Коротко» само по себе воспроизводило ту же жалобу, ради
    которой чинился селектор (см. tests/test_engine_phrase_variety.py).

    Замер по банку на момент правки: экономия строгого минимума — 1,05 слова из
    5,0 средних, разброс длин внутри пула невелик (медиана 2 слова). Поэтому
    режим выбирает из ОКНА самых коротких, а не из одной строки: платим
    полсловом, получаем ~4 варианта вместо одного в 155 пулах из 161.
    """
    said = {phrases.render("drs.in_range", selector_key=f"s{i}", shortest=True)
            for i in range(8)}
    assert len(said) > 1, said

    pool = phrases.variants_for(phrases.spec_for("drs.in_range"), None)
    limit = min(len(v.split()) for v in pool) + phrases.SHORTEST_WINDOW_WORDS
    assert all(len(v.split()) <= limit for v in said), said


def test_shortest_mode_never_picks_the_long_wording():
    """Обещание лаконичности проверяем на самой длинной строке пула поимённо:
    окно её пускать не должно ни при каком ключе."""
    pool = phrases.variants_for(phrases.spec_for("box.exit"), "volkov")
    longest = max(pool, key=lambda v: len(v.split()))
    said = {phrases.render("box.exit", selector_key=f"k{i}",
                           shortest=True, character="volkov")
            for i in range(12)}
    assert longest not in said, longest


def test_shortest_mode_keeps_the_situation_pinned():
    """Закрепление за ситуацией «коротко» не отменяет: повторная телеметрия по
    той же ситуации обязана дать ту же строку в любом режиме."""
    first = phrases.render("drs.in_range", selector_key="sit-7", shortest=True)
    for _ in range(5):
        assert phrases.render(
            "drs.in_range", selector_key="sit-7", shortest=True) == first


def test_memory_is_bounded():
    """Ключи ситуаций не должны копиться до бесконечности: движок живёт часами,
    и утечка здесь — это утечка на весь заезд."""
    for i in range(variety.MAX_PINNED * 3):
        variety.index_for("x.bounded", f"k{i}", 0, 6)
    assert variety.pinned_count() <= variety.MAX_PINNED
