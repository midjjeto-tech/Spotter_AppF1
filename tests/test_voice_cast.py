"""Раздача голосов по ролям: комментатор / инженер / споттер."""
import itertools

import pytest

from core.radio import voice_cast
from yandex_ai import voices


#: Живой источник, а не копия: перебор обязан расширяться сам при добавлении
#: новой персоны — иначе он тихо перестанет быть исчерпывающим, и главный
#: инвариант останется зелёным на устаревшем наборе. Слоты ролей исключены
#: явно: они лежат в том же DEFAULT_PERSONA_VOICE, но слот роли — не персона
#: комментатора, и подавать его в resolve() как персону бессмысленно.
ALL_PERSONAS = tuple(
    p for p in voices.DEFAULT_PERSONA_VOICE
    if p not in (voice_cast.SLOT_ENGINEER, voice_cast.SLOT_SPOTTER)
)


@pytest.mark.parametrize("persona,character",
                         list(itertools.product(ALL_PERSONAS, voice_cast.CHARACTERS)))
def test_three_roles_never_share_a_voice(persona, character):
    """Главный инвариант: ни при каком сочетании настроек два канала не звучат
    одним голосом. 4 персоны x 3 персонажа = 12 сочетаний, перебираются все."""
    cast = voice_cast.resolve(persona, character)
    commentator = voices.resolve(persona)["voice"]
    engineer = cast[voice_cast.SLOT_ENGINEER]["voice"]
    spotter = cast[voice_cast.SLOT_SPOTTER]["voice"]
    assert len({commentator, engineer, spotter}) == 3


def test_character_keeps_its_preferred_voice_when_free():
    """Персона toxic занимает kirill — alexander свободен, Волков его получает."""
    cast = voice_cast.resolve("toxic", "volkov")
    assert cast[voice_cast.SLOT_ENGINEER]["voice"] == "alexander"


def test_character_yields_when_commentator_took_its_voice():
    """persona=tv занимает alexander — Волков уходит на запасной kirill."""
    cast = voice_cast.resolve("tv", "volkov")
    assert cast[voice_cast.SLOT_ENGINEER]["voice"] == "kirill"


def test_spotter_needs_its_third_preference():
    """persona=hype берёт anton, Гром уходит на kirill — споттеру остаётся
    только третий пункт списка. Тест фиксирует, что два пункта у споттера НЕ
    сработали бы: это не запас на всякий случай."""
    cast = voice_cast.resolve("hype", "grom")
    assert cast[voice_cast.SLOT_SPOTTER]["voice"] == "alexander"


def test_unknown_character_falls_back_to_default():
    assert voice_cast.character("нет такого").character_id == voice_cast.DEFAULT_CHARACTER
    assert voice_cast.character(None).character_id == voice_cast.DEFAULT_CHARACTER


def test_first_free_fails_loudly_when_no_voice_is_available():
    """Раньше здесь возвращался последний голос — то есть ЗАНЯТЫЙ. Модуль,
    существующий ради запрета коллизий, молча их производил. Теперь отказ
    явный: тихая коллизия хуже громкой ошибки."""
    with pytest.raises(voice_cast.VoiceCastError):
        voice_cast._first_free(("alexander", "kirill"), {"alexander", "kirill"})


def test_engineer_preferences_have_at_least_two_unique_voices():
    """Инженер разрешается вторым — до него занят один голос. Длины мало:
    список из двух ОДИНАКОВЫХ голосов формально проходит проверку длины, а
    фактически оставляет инженера без запасного."""
    for character in voice_cast.CHARACTERS.values():
        assert len(set(character.voices)) >= 2, character.character_id


def test_spotter_preferences_have_at_least_three_unique_voices():
    """Споттер разрешается третьим — до него занято два голоса."""
    assert len(set(voice_cast.SPOTTER_VOICES)) >= 3


def test_resolve_shape_matches_voice_overrides_contract():
    """Формат обязан совпадать с тем, что принимает Voice.set_voice_overrides()
    и yandex_ai.voices.resolve(persona, overrides) — иначе оверрайд молча
    проигнорируется (voices.resolve отбрасывает неизвестные ключи)."""
    cast = voice_cast.resolve("tv", "volkov")
    for slot in (voice_cast.SLOT_ENGINEER, voice_cast.SLOT_SPOTTER):
        assert set(cast[slot]) == {"voice", "emotion", "speed"}


def test_every_character_voice_exists_in_the_catalogue():
    """Опечатка в имени голоса даёт 400 от SpeechKit и МОЛЧАЛИВЫЙ уход на
    Piper — ловим её тестом, а не ушами в гонке."""
    for character in voice_cast.CHARACTERS.values():
        for voice in character.voices:
            assert voice in voices.AVAILABLE_VOICES
    for voice in voice_cast.SPOTTER_VOICES:
        assert voice in voices.AVAILABLE_VOICES


def test_emotion_is_supported_by_every_voice():
    """Неподдерживаемая эмоция даёт 400 от SpeechKit и МОЛЧАЛИВЫЙ уход на
    Piper. Аналогично проверке в test_voices.py::test_default_emotions_supported
    — гарантируем, что voice_cast._EMOTION входит в список эмоций, поддержанных
    каждым голосом в наборе."""
    emotion = voice_cast._EMOTION
    for character in voice_cast.CHARACTERS.values():
        for voice in character.voices:
            supported = voices.AVAILABLE_VOICES.get(voice, [])
            assert emotion in supported, (
                f"{character.character_id}: эмоция '{emotion}' не поддержана "
                f"голосом '{voice}' (доступно: {supported})")
    for voice in voice_cast.SPOTTER_VOICES:
        supported = voices.AVAILABLE_VOICES.get(voice, [])
        assert emotion in supported, (
            f"spotter: эмоция '{emotion}' не поддержана голосом '{voice}' "
            f"(доступно: {supported})")


def test_role_slots_exist_in_both_catalogues():
    """Слот роли обязан быть в ОБОИХ каталогах. Пропуск в Piper не заметен по
    основному пути, но при отказе Yandex озвучка уходит на фолбэк, и там
    отсутствующий ключ молча свалится в дефолтный голос — то есть роли
    схлопнутся в одну ровно в тот момент, когда сеть легла."""
    from new_tts.piper_tts import PERSONA_VOICE

    for slot in (voice_cast.SLOT_ENGINEER, voice_cast.SLOT_SPOTTER):
        assert slot in voices.DEFAULT_PERSONA_VOICE
        assert slot in PERSONA_VOICE


def test_piper_role_slots_differ_from_each_other():
    """В models/piper/ лежат ровно ЧЕТЫРЕ модели (ruslan, denis, irina,
    dmitri), и все четыре уже розданы персонам комментатора. Свободной модели
    под роль нет, а путь Piper не умеет оверрайды (PERSONA_VOICE.get(persona)
    статичен) — то есть динамически уступать голос, как это делает
    voice_cast.resolve() для Yandex, фолбэк не может.

    Поэтому здесь гарантия СЛАБЕЕ и это осознанно: инженер и споттер обязаны
    отличаться друг от друга, но могут совпасть с комментатором при одной из
    персон. Полная гарантия живёт в основном пути (Yandex); Piper — аварийный
    фолбэк, и в проекте он намеренно не развивается."""
    from new_tts.piper_tts import PERSONA_VOICE

    engineer = PERSONA_VOICE[voice_cast.SLOT_ENGINEER][0]
    spotter = PERSONA_VOICE[voice_cast.SLOT_SPOTTER][0]
    assert engineer != spotter


def test_piper_role_models_exist_on_disk():
    """Несуществующее имя модели даёт found:false в UI и тишину вместо голоса —
    ловим тестом, а не в гонке."""
    import os

    from new_tts.piper_tts import PERSONA_VOICE, _voice_dir

    for slot in (voice_cast.SLOT_ENGINEER, voice_cast.SLOT_SPOTTER):
        name = PERSONA_VOICE[slot][0]
        assert os.path.isfile(
            os.path.join(str(_voice_dir()), f"ru_RU-{name}-medium.onnx")), name


def test_commentator_persona_list_matches_the_prompt_catalogue():
    """`voice/tts.py::_COMMENTATOR_PERSONAS` — четвёртая копия списка персон
    (есть ещё в voices.DEFAULT_PERSONA_VOICE, piper_tts.PERSONA_VOICE и
    commentator/personas.py). Копия нужна, чтобы voice/ не зависел от
    core.radio, но рассинхрон был бы МОЛЧАЛИВЫМ: забытая здесь новая персона не
    упадёт, а тихо озвучится голосом "tv"."""
    from commentator.personas import PERSONAS
    from voice.tts import _COMMENTATOR_PERSONAS

    assert _COMMENTATOR_PERSONAS == frozenset(PERSONAS)


def test_set_persona_ignores_role_slots_without_losing_the_users_choice():
    """Тест намеренно стартует с "hype", а не с "tv": прежняя реализация
    сбрасывала персону на "tv" при любом чужом значении, и стартовавший с "tv"
    тест этого не видел."""
    from voice.tts import Voice

    v = Voice.__new__(Voice)
    v._current_persona = "hype"

    v.set_persona(voice_cast.SLOT_ENGINEER)
    assert v._current_persona == "hype"
    v.set_persona("нет такой персоны")
    assert v._current_persona == "hype"

    v.set_persona("calm")
    assert v._current_persona == "calm"


def test_policy_voice_slots_match_the_cast_constants():
    """policy.py и speakers.py держат имена слотов ЛИТЕРАЛАМИ — именно потому,
    что policy по контракту ни от чего не зависит. Цена — рассинхрон при
    переименовании константы был бы молчаливым: voices.resolve() не найдёт
    ключ, отдаст дефолт 'tv', и роль заговорит голосом комментатора."""
    from core.radio import policy, speakers

    assert policy.voice_persona_for(policy.CHANNEL_ENGINEER) == voice_cast.SLOT_ENGINEER
    assert policy.voice_persona_for(policy.CHANNEL_SPOTTER) == voice_cast.SLOT_SPOTTER
    assert policy.voice_persona_for(policy.CHANNEL_COMMENTATOR) is None
    assert speakers.RACE_ENGINEER.voice_persona == voice_cast.SLOT_ENGINEER
    assert speakers.SPOTTER.voice_persona == voice_cast.SLOT_SPOTTER


def test_settings_default_character_matches_the_module():
    """settings.py не импортирует voice_cast (лишняя зависимость на старте),
    поэтому дефолт продублирован строкой. Тест держит копии синхронными."""
    from core.settings import DEFAULTS

    assert DEFAULTS["engineer_character"] == voice_cast.DEFAULT_CHARACTER
    assert DEFAULTS["engineer_character"] in voice_cast.CHARACTERS


def test_cache_key_follows_the_resolved_voice_not_the_slot_name():
    """Ключ кэша строится из слота ("engineer"), и если бы он зависел только
    от ИМЕНИ слота, то после смены персонажа проигрывались бы WAV, озвученные
    прежним голосом, — молча и до очистки кэша.

    Спасает то, что `_voice_key` резолвит слот через `voices.resolve(slot,
    overrides)` и кладёт в ключ РЕАЛЬНЫЕ параметры синтеза. Тест фиксирует
    свойство, чтобы будущая «оптимизация» ключа его не потеряла."""
    import types

    from voice.tts import Voice

    v = Voice.__new__(Voice)
    v._yandex = types.SimpleNamespace(tts_version="v3")

    v._voice_overrides = voice_cast.resolve("calm", "volkov")
    key_volkov = v._voice_key(voice_cast.SLOT_ENGINEER)

    v._voice_overrides = voice_cast.resolve("calm", "grom")
    key_grom = v._voice_key(voice_cast.SLOT_ENGINEER)

    assert key_volkov != key_grom


def test_radio_effect_applies_only_to_radio_slots():
    """Комментатор звучит чисто, инженер и споттер — через рацию. Глобальный
    тумблер radio_fx при этом главнее: выключен — молчат все эффекты."""
    from voice.tts import Voice

    v = Voice.__new__(Voice)
    v._current_persona = "tv"
    v._radio_enabled = True

    assert v._radio_for(voice_cast.SLOT_ENGINEER) is True
    assert v._radio_for(voice_cast.SLOT_SPOTTER) is True
    assert v._radio_for("tv") is False
    assert v._radio_for(None) is False       # None -> текущая персона (tv)

    v._radio_enabled = False
    assert v._radio_for(voice_cast.SLOT_ENGINEER) is False


def test_settings_normalises_an_unknown_engineer_character(tmp_path, monkeypatch):
    """Неизвестный id не должен доживать до UI: иначе интерфейс не подсветит
    ничего, а озвучка пойдёт дефолтным персонажем — показанное разойдётся со
    звучащим. Нормализация внутри voice_cast.character() этого не решает: она
    чинит звук, но не то, что настройки хранят и отдают клиенту."""
    import json

    import core.settings as s

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"engineer_character": "нет такого"}),
                    encoding="utf-8")
    monkeypatch.setattr(s, "_PATH", path)

    assert s.load()["engineer_character"] == voice_cast.DEFAULT_CHARACTER


def test_settings_keeps_a_valid_engineer_character(tmp_path, monkeypatch):
    """Нормализация не имеет права трогать корректное значение."""
    import json

    import core.settings as s

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"engineer_character": "grom"}), encoding="utf-8")
    monkeypatch.setattr(s, "_PATH", path)

    assert s.load()["engineer_character"] == "grom"


def test_settings_character_whitelist_matches_the_cast():
    """Белый список в settings.py — копия ключей voice_cast.CHARACTERS.
    Рассинхрон означал бы, что валидный персонаж молча сбрасывается на дефолт."""
    from core.settings import _ENGINEER_CHARACTERS

    assert _ENGINEER_CHARACTERS == frozenset(voice_cast.CHARACTERS)


def test_cast_uses_only_premium_voices():
    """Решение пользователя (2026-08-02): каст живёт на премиальных голосах.
    Непремиальные остаются в каталоге и валидны для SpeechKit, но под radio_fx
    звучат заметно «роботнее» — в проекте из-за этого уже меняли дефолты.
    Тест не даёт протащить такой голос в роль незаметно; расширять набор
    полагается только после живого прослушивания."""
    for character in voice_cast.CHARACTERS.values():
        for voice in character.voices:
            assert voice in voices.PREMIUM_VOICES, (
                f"{character.character_id}: {voice} не премиальный")
    for voice in voice_cast.SPOTTER_VOICES:
        assert voice in voices.PREMIUM_VOICES, f"споттер: {voice} не премиальный"


def test_voice_status_reports_the_actual_cast_not_catalogue_defaults():
    """UI обязан показывать то, что ЗВУЧИТ. Без передачи каста слоты ролей
    отдавались бы дефолтами каталога: выбери пользователь Грома — интерфейс
    продолжал бы показывать голос Волкова."""
    from voice.voice_manager import voice_status

    grom = voice_cast.resolve("calm", "grom")
    reported = voice_status(True, True, grom)["voices"]

    assert reported[voice_cast.SLOT_ENGINEER]["voice"] == "anton"
    assert reported[voice_cast.SLOT_ENGINEER]["premium"] is True


def test_voice_status_shows_the_substituted_voice_for_sokolova():
    """Известная слабость каста: при persona=calm марина занята комментатором,
    и Соколова звучит мужским запасным. Интерфейс обязан это показывать, иначе
    пользователь выбирает одного инженера, а слышит другого без объяснений."""
    from voice.voice_manager import voice_status

    cast = voice_cast.resolve("calm", "sokolova")
    reported = voice_status(True, True, cast)["voices"]

    assert reported[voice_cast.SLOT_ENGINEER]["voice"] == "alexander"
    assert reported["calm"]["voice"] == "marina"
