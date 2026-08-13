"""
core/radio/speakers.py
======================
Кто говорит: имя, роль, портрет и акцент радио-канала.

Почему отдельный модуль, а не константы в `policy.py`. Канал — это решение
конвейера («чей это голос и с каким приоритетом»), а профиль — презентация
(«как подписать карточку в кадре»). Смешивать их значит заставить политику
знать про портреты и HEX-цвета, то есть протащить UI в слой, который решает,
прерывать ли звучащую фразу.

Главное правило, которое легко потерять (ТЗ §15): выбранная пользователем
персона комментатора влияет ТОЛЬКО на профиль комментатора. Инженер и споттер —
фиксированные персонажи с фиксированной ролью. Иначе «токсичный напарник»
однажды объявит критический box-call, и игрок не поймёт, шутка это или команда.

Имена персонажей — оригинальные и вымышленные. Реальных людей, реальных
инженеров F1 и персонажей сторонних модов здесь быть не должно.

Портрет — ИМЯ ФАЙЛА, а не картинка. Файла может не быть: карточка обязана
рисоваться и без него (ТЗ §5), поэтому `portrait_url` спокойно отдаёт ссылку на
несуществующий файл, а фронт падает на инициалы по `onError`. Проверять наличие
файла здесь нельзя — модуль импортируется в тестах без рабочего каталога.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from core.radio.policy import (
    CHANNEL_COMMENTATOR,
    CHANNEL_ENGINEER,
    CHANNEL_SPOTTER,
)

#: Канал реплики пилота. В `policy` его нет намеренно: пилот ничего не
#: озвучивает, он существует только как строка истории и как подпись под
#: распознанным PTT-запросом (ТЗ §4).
CHANNEL_DRIVER = "driver"

#: URL-префикс отдачи портретов (`web_server.py`). Файлы лежат в `assets/radio/`.
PORTRAIT_URL_PREFIX = "/assets/radio"


@dataclass(frozen=True, slots=True)
class SpeakerProfile:
    """Презентация говорящего. Неизменяема: профиль — это конфигурация."""

    speaker_id: str
    #: Имя в кадре, uppercase (ТЗ §6: имя капсом, роль мельче и тусклее).
    display_name: str
    #: Роль латиницей — телевизионная подпись, а не перевод канала.
    role: str
    #: Короткая русская подпись канала. Существующий контракт
    #: `RadioMessage.speaker`, его читают «Рация» и лента. Не менять.
    short_label: str
    #: Имя файла в `assets/radio/`, либо None если портрета у роли нет.
    portrait: str | None
    accent: str
    voice_persona: str | None
    allowed_channels: frozenset[str]
    #: Пол персонажа: "m" | "f". Здесь он потому, что задаёт его ИМЯ в кадре, а
    #: имя живёт здесь. Голос обязан совпадать — сверку держит тест
    #: (tests/test_voice_cast.py): подпись «ЛЕВ ТИХОНОВ» женским голосом
    #: доезжала до живой гонки, потому что имя и голос лежат в разных файлах и
    #: по отдельности оба выглядят верными.
    gender: str = "m"

    @property
    def portrait_url(self) -> str | None:
        if not self.portrait:
            return None
        return f"{PORTRAIT_URL_PREFIX}/{self.portrait}"

    @property
    def initials(self) -> str:
        """Фолбэк вместо портрета.

        Два слова дают две буквы («ИГОРЬ ВОЛКОВ» → «ИВ»), одно — одну:
        «СП» из «СПОТТЕР» читается как обрезанное слово, а не как монограмма."""
        words = [word for word in self.display_name.split() if word]
        if not words:
            return "?"
        if len(words) == 1:
            return words[0][0].upper()
        return (words[0][0] + words[1][0]).upper()


# ── Фиксированные роли ───────────────────────────────────────────────────────
# `voice_persona` дублирует `policy._VOICE_PERSONA` дословно — на это стоит
# тест (tests/test_radio_projection.py). Значения — слоты голоса из
# core/radio/voice_cast.py, а не персоны комментатора: см.
# docs/superpowers/specs/2026-08-01-voice-cast-design.md.

RACE_ENGINEER = SpeakerProfile(
    speaker_id="race_engineer",
    display_name="ИГОРЬ ВОЛКОВ",
    role="RACE ENGINEER",
    short_label="Инженер",
    portrait="engineer.webp",
    accent="#e32636",
    voice_persona="engineer",
    allowed_channels=frozenset({CHANNEL_ENGINEER}),
)

SPOTTER = SpeakerProfile(
    speaker_id="spotter",
    display_name="СПОТТЕР",
    role="TRACKSIDE SPOTTER",
    short_label="Споттер",
    portrait="spotter.webp",
    accent="#f4b942",
    voice_persona="spotter",
    allowed_channels=frozenset({CHANNEL_SPOTTER}),
)

DRIVER = SpeakerProfile(
    speaker_id="driver",
    display_name="ПИЛОТ",
    role="DRIVER",
    short_label="Пилот",
    portrait=None,
    accent="#c8ced6",
    voice_persona=None,
    allowed_channels=frozenset({CHANNEL_DRIVER}),
)


# ── Комментатор: профиль на каждую персону ───────────────────────────────────
# id персон совпадают с `config.PERSONA` и списком в
# `NewSpotterUI/lib/spotter-data.ts::personas`. Роль у всех одна — аналитик:
# меняется голос и характер, а не должность.

def _analyst(speaker_id: str, display_name: str,
             gender: str = "m") -> SpeakerProfile:
    return SpeakerProfile(
        speaker_id=speaker_id,
        display_name=display_name,
        gender=gender,
        role="RACE ANALYST",
        short_label="Комментатор",
        portrait=f"{speaker_id}.webp",
        accent="#39c5d4",
        # None = говорить персоной, которую выбрал пользователь. Отдельного
        # голоса у комментатора нет и не заводится (ТЗ §15: не создавать
        # четыре новых TTS-движка).
        voice_persona=None,
        allowed_channels=frozenset({CHANNEL_COMMENTATOR}),
    )


_ANALYSTS: dict[str, SpeakerProfile] = {
    "tv": _analyst("analyst_tv", "АНДРЕЙ КОРШУНОВ"),
    "hype": _analyst("analyst_hype", "ГЛЕБ ЯРЦЕВ"),
    "calm": _analyst("analyst_calm", "ЛЕВ ТИХОНОВ"),
    "toxic": _analyst("analyst_toxic", "МАРК ЗУБОВ"),
}

#: Персона, которой подписан комментатор, если выбранная неизвестна. "tv" —
#: тот же дефолт, что и `config.PERSONA`.
_DEFAULT_PERSONA = "tv"

_BY_CHANNEL: dict[str, SpeakerProfile] = {
    CHANNEL_ENGINEER: RACE_ENGINEER,
    CHANNEL_SPOTTER: SPOTTER,
    CHANNEL_DRIVER: DRIVER,
}

#: Все профили по speaker_id — для истории, где персона могла смениться уже
#: после того, как реплика прозвучала.
ALL: MappingProxyType[str, SpeakerProfile] = MappingProxyType({
    profile.speaker_id: profile
    for profile in (RACE_ENGINEER, SPOTTER, DRIVER, *_ANALYSTS.values())
})


def profile_for(channel: str, persona: str | None = None) -> SpeakerProfile:
    """Профиль говорящего по каналу.

    `persona` учитывается ТОЛЬКО для канала комментатора. Для инженера и
    споттера аргумент игнорируется полностью — это и есть гарантия ТЗ §15, и
    на неё стоит отдельный тест."""
    fixed = _BY_CHANNEL.get(channel)
    if fixed is not None:
        return fixed
    if channel == CHANNEL_COMMENTATOR:
        return _ANALYSTS.get(persona or _DEFAULT_PERSONA,
                             _ANALYSTS[_DEFAULT_PERSONA])
    # Неизвестный канал не должен ронять проекцию: подпись поедет, но карточка
    # нарисуется. Тот же принцип, что у `policy.speaker_label_for`.
    return _ANALYSTS[_DEFAULT_PERSONA]


def profile_by_id(speaker_id: str) -> SpeakerProfile | None:
    return ALL.get(speaker_id)
