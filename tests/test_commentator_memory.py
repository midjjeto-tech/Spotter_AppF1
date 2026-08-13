"""Жёсткий фильтр дословных повторов комментатора (PhraseMemory.is_repeat).

Разбор живого заезда 2026-08-11: одна и та же реплика про столкновение
прозвучала четырежды — 15:05:05, 15:06:37, 15:07:04, 15:07:12, слово в слово.
Анти-повтор существовал, но работал ПОДСКАЗКОЙ в промпте («НЕДАВНО СКАЗАНО»),
то есть просьбой к модели, а модель её проигнорировала. Просьба осталась,
последнее слово теперь за проверкой факта.
"""
import time

from commentator.memory import PhraseMemory, normalize


def test_exact_repeat_is_caught():
    m = PhraseMemory()
    m.clear()
    m.append("Катастрофа на прямой! Леклер и Хэмилтон столкнулись!", "COLL")
    assert m.is_repeat("Катастрофа на прямой! Леклер и Хэмилтон столкнулись!")


def test_new_phrase_passes():
    m = PhraseMemory()
    m.clear()
    m.append("Катастрофа на прямой! Леклер и Хэмилтон столкнулись!", "COLL")
    assert not m.is_repeat("Расселл уверенно догоняет Пиастри.")


def test_case_punctuation_and_yo_do_not_make_it_a_new_phrase():
    """Модель печатает то «ё», то «е», то с восклицанием, то без."""
    m = PhraseMemory()
    m.clear()
    m.append("Всё решено, борьба окончена!", "AMBIENT")
    assert m.is_repeat("ВСЕ РЕШЕНО   борьба окончена")


def test_repeat_outside_the_window_is_allowed(monkeypatch):
    """Тот же оборот через полчаса — нормальная речь, а не поломка.

    Часы двигаем явно: на Windows `time.time()` дискретен (~15 мс), и запись с
    проверкой попадали в один тик — тест то проходил, то нет.
    """
    import commentator.memory as mem
    m = PhraseMemory()
    m.clear()
    m.append("Отличный темп на этом отрезке.", "AMBIENT")
    later = time.time() + 1800.0
    monkeypatch.setattr(mem.time, "time", lambda: later)
    assert not m.is_repeat("Отличный темп на этом отрезке.")
    # А внутри окна та же фраза всё ещё повтор.
    assert m.is_repeat("Отличный темп на этом отрезке.", window_sec=3600.0)


def test_empty_phrase_is_never_a_repeat():
    m = PhraseMemory()
    m.clear()
    m.append("Что-то сказано.", "AMBIENT")
    assert not m.is_repeat("")
    assert not m.is_repeat("   ")


def test_normalize_keeps_words_and_drops_the_rest():
    assert normalize("  Ох, ЁЛКИ! Вот это да...  ") == "ох елки вот это да"
