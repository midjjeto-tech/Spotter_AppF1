"""core/settings.py — persistent JSON settings store.

Three functions: load / save / reset. No class.

Future additions (volume, cooldown, persona_voices) belong in DEFAULTS here.
Boot errors (corrupt JSON, permissions) silently return DEFAULTS — the app
must always start.
"""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path

import config

_log = logging.getLogger(__name__)

DEFAULTS: dict = {
    "commentary_enabled":      True,
    "autovoice_enabled":       True,
    "critical_events_enabled": True,
    "ambient_enabled":         True,
    "radio_fx":                True,
    "commentator_position":    "auto",
    "persona":                 config.PERSONA,
    # Персонаж инженера: "volkov" | "sokolova" | "grom". Ось, НЕЗАВИСИМАЯ от
    # persona (та — характер КОММЕНТАТОРА). Строка продублирована из
    # core.radio.voice_cast.DEFAULT_CHARACTER намеренно: settings загружается
    # на старте раньше радио-конвейера, тянуть сюда его импорт незачем.
    # Синхронность копий держит тест test_voice_cast.py.
    "engineer_character":      "volkov",
    "min_comment_gap":         config.MIN_COMMENT_GAP,
    "broadcast_mode_enabled":  False,
    "volume":                  80,
    "volume_tv":               80,
    "volume_hype":             90,
    "volume_calm":             75,
    "volume_toxic":            80,
    # Громкость РОЛЕЙ — отдельные ключи, а не персона комментатора. Раньше
    # инженер озвучивался персоной "calm", и его громкостью управлял
    # volume_calm; после развода каналов по ролям (core/radio/voice_cast.py)
    # тот ключ остался только у комментатора. Перенос прежнего значения — в
    # load().
    "volume_engineer":         75,
    "volume_spotter":          75,
    # v3 = современный нейро-рендер (живая интонация, поддержка role-хинтов) —
    # дефолт с 2026-07-01 (жалоба «звучит как робот» на v1+filipp). speech.py
    # гарантирует per-phrase фолбэк v3→v1 при любом сбое — деградация безопасна.
    "yandex_tts_version":      "v3",
    # live/calm/story — темп и стиль повествования, НЕЗАВИСИМАЯ ось от persona
    # (persona = характер голоса, commentary_mode = как часто/подробно говорит).
    # См. docs/superpowers/specs/2026-07-07-commentary-mode-design.md.
    "commentary_mode":         "live",
    "engineer_chatter_enabled": True,
    # Стиль радио — сколько говорит ИНЖЕНЕР. Независимая ось от
    # commentary_mode (тот про темп КОММЕНТАТОРА), см. config.RADIO_STYLE_PROFILE.
    # Меняет порог важности, разрешённость аналитики и минимальный интервал
    # сразу — это не таймер «раз в N секунд». Critical и споттер не отключает.
    "radio_style":              config.RADIO_STYLE_DEFAULT,
    # "short" — из каждой ситуации выбирается самый короткий вариант банка
    # (core/radio/phrases.py). Режима длинных монологов нет намеренно (ТЗ §17).
    "phrase_length":            "standard",
    # Субтитр инженера на игровом HUD: показывать ли и сколько секунд.
    # Раньше время было захардкожено в оверлее (RADIO_TEXT_TTL_S = 12).
    "subtitles_enabled":        True,
    "subtitle_seconds":         12,
    # Размер субтитра и текста карточки: "s" | "m" | "l". Отдельно от
    # `radio_card_scale` — масштаб тянет карточку целиком вместе с портретом,
    # а этот ключ меняет только кегль для тех, кому мелко на 1440p.
    "subtitle_size":            "m",

    # ── Представление радио-карточки (ТЗ §18) ────────────────────────────────
    # ВСЕ ключи ниже управляют ТОЛЬКО показом. Ни один из них не отключает
    # озвучку и не трогает safety-логику: споттера и критическую реплику
    # инженера можно спрятать с экрана, но они всё равно прозвучат. Смешивать
    # «показывать» и «озвучивать» в одном переключателе прямо запрещено —
    # игрок, убравший карточку с глаз, не должен молча лишиться предупреждения
    # о машине рядом.
    "show_broadcast_radio_card": True,
    "show_spotter_card":         True,
    "show_commentary_card":      True,
    "show_portraits":            True,
    #: Множитель габаритов карточки, 0.8–1.4. Клипуется на фронте.
    "radio_card_scale":          1.0,
    #: Множитель времени показа после завершения реплики, 0.5–2.0. Базовые
    #: длительности по каналам живут в `NewSpotterUI/lib/radio-ui.ts`.
    "radio_card_duration":       1.0,
    #: Запоминать перетащенную позицию карточки между запусками. False —
    #: карточка каждый раз возвращается на дефолтное место снизу по центру.
    "remember_overlay_position": True,
    # Визуальный язык оверлея: "broadcast" | "cockpit" | "radio". Меняет только
    # оформление — ни один виджет не появляется и не исчезает, габариты окон из
    # core/overlay_window.py::HUD_WIDGETS остаются прежними. Дефолт "broadcast"
    # намеренно: это вид, который у пользователей уже стоит, и обновление не
    # должно перекрашивать HUD без спроса. Наборы токенов —
    # NewSpotterUI/lib/overlay-theme.ts.
    "overlay_theme":            "broadcast",
    # Имя выбранного устройства записи (из voice.listener.list_input_devices()),
    # None = системное устройство по умолчанию. См.
    # docs/superpowers/specs/2026-07-12-mic-device-setting-design.md.
    "mic_device":               None,
    # Push-to-talk хоткей (глобальный, работает пока F1 25 в фокусе) — может быть
    # одной обычной клавишей без модификаторов либо сочетанием Ctrl/Alt/Shift,
    # см.
    # core/hotkeys.py::GlobalHotkeyManager и docs/superpowers/specs/
    # 2026-07-14-ptt-hotkey-radio-beep-design.md. Смена применяется после
    # перезапуска Spotter App (регистрация хоткеев — один раз при старте потока).
    "ptt_hotkey": {"ctrl": True, "alt": True, "shift": False, "key": "V"},
    # Источник телеметрии: "f1" (UDP, дефолт) | "iracing" (shared memory,
    # core/iracing_telemetry.py + core/iracing_packets.py). Читается один раз
    # при F1Engine.start() — смена применяется после перезапуска (та же
    # модель, что и ptt_hotkey выше). См. план peaceful-humming-teacup.md.
    "telemetry_source":         "f1",
    # RaceFeed: AI paddock feed (core/racefeed/). Off by default — it's an AI
    # content-generation subsystem (LLM calls, background worker thread), not a
    # telemetry feature; see docs/superpowers/specs/2026-07-20-racefeed-phase1-design.md.
    "racefeed_enabled":         False,
    # Визард первого запуска пройден или пропущен. False = показать его при
    # старте. Отдельный флаг, а НЕ «существует ли settings.json»: файл создаётся
    # первым же сохранением любой галочки, и по нему визард исчезал бы у
    # пользователя, который до него не дошёл. См. views/onboarding.tsx.
    "onboarding_done":          False,
}

#: Допустимые персонажи инженера. Дублирует ключи
#: core.radio.voice_cast.CHARACTERS намеренно — settings загружается на старте
#: раньше радио-конвейера. Синхронность держит тест в test_voice_cast.py.
_ENGINEER_CHARACTERS: frozenset[str] = frozenset({"volkov", "sokolova", "grom"})

#: Допустимые визуальные языки оверлея. Дублирует ключи THEMES из
#: NewSpotterUI/lib/overlay-theme.ts — граница процесса, общего модуля нет.
_OVERLAY_THEMES: frozenset[str] = frozenset({"broadcast", "cockpit", "radio"})

_PATH = Path(config.DATA_DIR) / "settings.json"


def load() -> dict:
    """Return settings dict. Missing keys filled from DEFAULTS; unknown keys dropped.

    deepcopy (not dict()) — DEFAULTS now has a nested-dict value (ptt_hotkey);
    a shallow copy would alias that nested dict across every load()/reset()
    call, so in-place mutation of a caller's settings["ptt_hotkey"] would
    silently corrupt the process-wide DEFAULTS for the rest of the run."""
    result = copy.deepcopy(DEFAULTS)
    saved: dict = {}
    try:
        if _PATH.exists():
            saved = json.loads(_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                result.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except Exception:  # noqa: BLE001
        pass

    # Разовый перенос: до развода каналов по ролям громкостью инженера
    # управлял ползунок, писавший в volume_calm. Если пользователь его крутил,
    # а нового ключа в файле ещё нет — переносим значение, иначе настройка
    # молча сбросится на дефолт и инженер станет громче без объяснений.
    if isinstance(saved, dict) and "volume_engineer" not in saved \
            and "volume_calm" in saved:
        result["volume_engineer"] = result["volume_calm"]

    # Неизвестный персонаж инженера нормализуется здесь, а не только внутри
    # voice_cast.character(): иначе настройки хранят и отдают в UI id, которого
    # нет, интерфейс не подсвечивает ничего, а озвучка идёт дефолтным
    # персонажем — показанное расходится со звучащим.
    if result["engineer_character"] not in _ENGINEER_CHARACTERS:
        result["engineer_character"] = DEFAULTS["engineer_character"]

    # По той же причине нормализуется тема оверлея: восемь окон виджетов читают
    # этот ключ независимо, и неизвестное значение оставило бы HUD без стилей
    # вместо того, чтобы откатить его на привычный вид.
    if result["overlay_theme"] not in _OVERLAY_THEMES:
        result["overlay_theme"] = DEFAULTS["overlay_theme"]

    return result


def save(settings: dict) -> None:
    """Persist only known keys. Logs a warning on I/O errors."""
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(
            json.dumps(
                {k: settings[k] for k in DEFAULTS if k in settings},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        _log.warning("settings.save failed", exc_info=True)


def reset() -> dict:
    """Overwrite disk with DEFAULTS, return a copy."""
    save(DEFAULTS)
    return copy.deepcopy(DEFAULTS)
