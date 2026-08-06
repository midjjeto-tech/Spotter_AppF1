"""
voice/voice_manager.py
======================
Reports the status of the voices used per persona.

When Yandex SpeechKit is attached and healthy → returns Yandex voices (filipp/ermil/alena/zahar).
When falling back to Piper → returns Piper voices (ruslan/denis/irina/dmitri).
"""
from __future__ import annotations

import os

from new_tts.piper_tts import PERSONA_VOICE, _PIPER_DIR


def _model_path(name: str) -> str:
    return os.path.join(str(_PIPER_DIR), f"ru_RU-{name}-medium.onnx")


def voice_status(yandex_attached: bool = False, yandex_healthy: bool = False,
                 overrides: dict | None = None) -> dict:
    """UI-friendly status dict for the /api/voices endpoint.

    When Yandex is attached and healthy, voices[] contains Yandex voice specs.
    Otherwise voices[] contains Piper fallback specs.
    piper_voices / yandex_voices are always present for the UI to reference both.

    `overrides` — действующий каст ролей (`Voice._voice_overrides`). Без него
    слоты `engineer`/`spotter` отдавались бы каталожными ДЕФОЛТАМИ, а звучал бы
    каст: выбери пользователь Грома — интерфейс продолжал бы показывать голос
    Волкова. Это тот же класс расхождения «показано одно, звучит другое», из-за
    которого с этого экрана уже убирали блок про «инженер всегда говорит
    голосом calm».

    `premium` в каждой записи — метка приемлемого качества
    (`yv.PREMIUM_VOICES`). Непремиальные голоса остаются в каталоге и валидны
    для SpeechKit, но звучат заметно «роботнее» под radio_fx.
    """
    from yandex_ai import voices as yv

    # Piper fallback voices — always computed (always bundled in the EXE)
    piper: dict[str, dict] = {}
    for persona, (name, length_scale) in PERSONA_VOICE.items():
        path = _model_path(name)
        found = os.path.isfile(path)
        size_mb = round(os.path.getsize(path) / (1024 * 1024), 1) if found else 0
        piper[persona] = {
            "voice": name,
            "filename": f"ru_RU-{name}-medium.onnx",
            "found": found,
            "size_mb": size_mb,
            "speed": "fast" if length_scale < 1 else ("slow" if length_scale > 1 else "normal"),
        }

    # Yandex voices — filled only when Yandex is attached
    yandex: dict[str, dict] = {}
    if yandex_attached:
        for persona in yv.DEFAULT_PERSONA_VOICE:
            # resolve(), а не сырой DEFAULT_PERSONA_VOICE: для слотов ролей
            # действующий голос задаётся кастом, и дефолт с ним расходится.
            spec = yv.resolve(persona, overrides)
            yandex[persona] = {
                "voice": spec["voice"],
                "display": yv.display_name(spec["voice"]),
                "emotion": spec["emotion"],
                "speed": spec["speed"],
                "premium": spec["voice"] in yv.PREMIUM_VOICES,
            }

    use_yandex = yandex_attached and yandex_healthy
    return {
        "engine": "Yandex SpeechKit" if use_yandex else "Piper (RU)",
        "yandex_attached": yandex_attached,
        "yandex_healthy": yandex_healthy,
        "voices_dir": str(_PIPER_DIR),
        "voices": yandex if use_yandex else piper,
        "piper_voices": piper,
        "yandex_voices": yandex,
    }
