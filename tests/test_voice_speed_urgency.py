"""Темп речи зависит от срочности, а не только от персонажа.

До этой работы `voice_cast.resolve()` выдавал инженеру ОДНУ статичную скорость
на весь заезд, поэтому «Бокс! Бокс!» и «Идём по плану» произносились ровно
одинаково: срочность несли только слова, доставка её не несла. Премиальные
нейроголоса Yandex эмоций не поддерживают (см. шапку voice_cast.py), поэтому
темп — практически единственный доступный рычаг просодии.
"""
import pytest

from core.radio import policy, voice_cast


def test_more_urgent_means_faster():
    scale = voice_cast.speed_scale
    assert (scale(policy.URGENCY_CRITICAL) > scale(policy.URGENCY_HIGH)
            > scale(policy.URGENCY_NORMAL) > scale(policy.URGENCY_LOW))


def test_normal_urgency_is_exactly_neutral():
    """Ровно 1.0, а не «около»: на нормальной срочности темп обязан совпадать с
    настройкой персонажа, иначе выбор пользователя молча смещается. От этого же
    равенства зависит совместимость кэша TTS (см. tts.py::_voice_key)."""
    assert voice_cast.speed_scale(policy.URGENCY_NORMAL) == 1.0


def test_unknown_urgency_is_neutral():
    assert voice_cast.speed_scale(None) == 1.0
    assert voice_cast.speed_scale("нет такой") == 1.0


@pytest.mark.parametrize("urgency", [
    policy.URGENCY_CRITICAL, policy.URGENCY_HIGH,
    policy.URGENCY_NORMAL, policy.URGENCY_LOW,
])
def test_resulting_speed_stays_natural(urgency):
    """Множитель ложится ПОВЕРХ скорости персонажа (0.95–1.1). Итог обязан
    остаться в диапазоне, где нейроголос звучит как человек, а не как
    перемотка: за пределами примерно 0.85–1.25 речь слышно ломает."""
    scale = voice_cast.speed_scale(urgency)
    for character in voice_cast.CHARACTERS.values():
        result = character.speed * scale
        assert 0.85 <= result <= 1.25, (character.character_id, urgency, result)


def test_queue_item_keeps_the_urgency():
    """Раньше `urgency` участвовала только в расчёте ранга и на элементе не
    сохранялась. Синтез читает её именно оттуда — потеряется здесь, и темп
    молча вернётся к статичному."""
    from new_tts.queue_handler import TTSQueue

    q = TTSQueue(speak_fn=lambda text, persona: None)
    try:
        q.stop()
        q._put_locked(0, "текст", "engineer", "m1", None, None,
                      policy.URGENCY_CRITICAL)
        _rank, _seq, item = q._queue.get_nowait()
        assert item.urgency == policy.URGENCY_CRITICAL
    finally:
        q.stop()


def test_cache_key_separates_urgencies_but_keeps_the_neutral_one():
    """Два требования сразу, и оба ловят свою ошибку:

    - срочная и обычная реплики обязаны лечь под РАЗНЫЕ ключи, иначе одна
      озвучка подменит другую и темп начнёт зависеть от того, что синтезировали
      первым;
    - ключ нейтральной реплики обязан остаться ПРЕЖНИМ, иначе весь накопленный
      кэш обесценится разом, а синтез стоит денег.
    """
    from voice.tts import Voice

    voice = Voice.__new__(Voice)          # без инициализации звука и сети
    voice._yandex = type("Y", (), {"tts_version": "v3-grpc"})()
    voice._voice_overrides = {}

    neutral = voice._voice_key("engineer", 1.0)
    urgent = voice._voice_key("engineer", voice_cast.speed_scale(
        policy.URGENCY_CRITICAL))

    assert neutral != urgent
    assert neutral == voice._voice_key("engineer")


def test_every_urgency_level_is_covered():
    """Пропущенный уровень молча деградировал бы к 1.0 — то есть срочность
    просто перестала бы звучать, и заметили бы это только ухом."""
    for urgency in (policy.URGENCY_CRITICAL, policy.URGENCY_HIGH,
                    policy.URGENCY_NORMAL, policy.URGENCY_LOW):
        assert urgency in voice_cast.URGENCY_SPEED_SCALE
