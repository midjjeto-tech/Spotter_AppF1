"""
core/radio/voice_cast.py
========================
Кто каким голосом говорит: раздача голосов Yandex по трём ролям.

Почему отдельный модуль. `policy.py` отвечает на вопрос «кто говорит» (канал),
`speakers.py` — «как подписать карточку в кадре», этот — «каким голосом».
Смешивать их нельзя: раздача голосов зависит от ДВУХ пользовательских настроек
сразу (персона комментатора и персонаж инженера), а `policy.py` по своему
контракту держит чистые таблицы решений без пользовательского состояния.

Причина существования модуля — арифметика. Премиальных нейроголосов четыре
(`yandex_ai/voices.py`), ролей три, и голос комментатора жёстко задан его
персоной. Значит инженер и споттер обязаны уметь уступать занятый голос.
Правило одно: «первый свободный из своего списка», роли разрешаются по порядку
комментатор → инженер → споттер.

Длина списка диктуется позицией в очереди: роли, разрешаемой N-й по счёту,
нужен список из N голосов — перед ней занято ровно N-1, поэтому N-й пункт
гарантированно свободен. Инженеру хватает двух, споттеру нужно три, и третий
пункт у споттера реально срабатывает (persona=hype + Виктор Гром), а не лежит
запасом. Если это правило всё же нарушено (список короче, чем нужно) —
`_first_free` поднимает `VoiceCastError`, а не молча возвращает последний
(занятый) голос: смысл модуля в запрете коллизий, и тихая коллизия хуже
громкой ошибки.

Споттеру выбор голоса НЕ даётся намеренно: safety-канал должен быть одинаково
узнаваем у всех пользователей.

Имена персонажей вымышленные — то же правило, что в `speakers.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from yandex_ai import voices

#: Слоты голоса. Совпадают с ключами `voices.DEFAULT_PERSONA_VOICE` и
#: `new_tts.piper_tts.PERSONA_VOICE`: движок передаёт слот туда, где раньше
#: передавал персону, поэтому вся цепочка синтеза и ключ кэша работают без
#: правок.
SLOT_ENGINEER = "engineer"
SLOT_SPOTTER = "spotter"


@dataclass(frozen=True, slots=True)
class EngineerCharacter:
    """Персонаж инженера: подпись, голоса по убыванию предпочтения, темп."""

    character_id: str
    display_name: str
    #: Минимум ДВА голоса — инженер разрешается вторым (см. шапку модуля).
    voices: tuple[str, ...]
    speed: float


VOLKOV = EngineerCharacter(
    character_id="volkov",
    display_name="ИГОРЬ ВОЛКОВ",
    voices=("alexander", "kirill"),
    speed=1.0,
)
SOKOLOVA = EngineerCharacter(
    character_id="sokolova",
    display_name="МАРИНА СОКОЛОВА",
    voices=("marina", "alexander"),
    speed=0.95,
)
GROM = EngineerCharacter(
    character_id="grom",
    display_name="ВИКТОР ГРОМ",
    voices=("anton", "kirill"),
    speed=1.1,
)

CHARACTERS: MappingProxyType[str, EngineerCharacter] = MappingProxyType({
    c.character_id: c for c in (VOLKOV, SOKOLOVA, GROM)
})

#: Дефолт — действующий персонаж карточки инженера (`speakers.RACE_ENGINEER`).
DEFAULT_CHARACTER = VOLKOV.character_id

#: Споттер: три голоса — необходимость, а не запас (см. шапку).
SPOTTER_VOICES: tuple[str, ...] = ("kirill", "anton", "alexander")
SPOTTER_SPEED = 1.1

#: Роли говорят ровно нейтрально: «характер» несёт ТЕКСТ и темп, не legacy-роль
#: SpeechKit. Премиальные нейроголоса эмоции всё равно не поддерживают
#: (см. комментарий над `voices.DEFAULT_PERSONA_VOICE`).
_EMOTION = "neutral"


def character(character_id: str | None) -> EngineerCharacter:
    """Персонаж по id. Неизвестный или None -> дефолтный."""
    return CHARACTERS.get(character_id or "", VOLKOV)


class VoiceCastError(RuntimeError):
    """Раздать голоса невозможно: список предпочтений исчерпан.

    Отдельный тип, потому что это ошибка КОНФИГУРАЦИИ модуля (константы ниже),
    а не рантайма: входы у `_first_free` — статические списки плюс голос
    комментатора, поэтому исчерпать список можно только неудачной правкой кода.
    Молча вернуть занятый голос нельзя: смысл модуля именно в том, чтобы
    коллизий не было, и тихая коллизия хуже громкой ошибки."""


def _first_free(preferences: tuple[str, ...], taken: set[str]) -> str:
    for voice in preferences:
        if voice not in taken:
            return voice
    raise VoiceCastError(
        f"свободного голоса нет: preferences={preferences!r}, taken={taken!r}")


def resolve(persona: str, character_id: str | None = None) -> dict[str, dict]:
    """Оверрайды голосов для слотов инженера и споттера.

    Формат совпадает с контрактом `voice.Voice.set_voice_overrides()` и
    `yandex_ai.voices.resolve()`: {слот: {voice, emotion, speed}}. Комментатора
    в результате НЕТ намеренно: его голос задан персоной и не смещается — он
    первый в очереди и всегда получает своё.
    """
    commentator_voice = voices.resolve(persona)["voice"]
    taken = {commentator_voice}

    engineer = character(character_id)
    engineer_voice = _first_free(engineer.voices, taken)
    taken.add(engineer_voice)

    spotter_voice = _first_free(SPOTTER_VOICES, taken)

    return {
        SLOT_ENGINEER: {
            "voice": engineer_voice, "emotion": _EMOTION, "speed": engineer.speed,
        },
        SLOT_SPOTTER: {
            "voice": spotter_voice, "emotion": _EMOTION, "speed": SPOTTER_SPEED,
        },
    }
