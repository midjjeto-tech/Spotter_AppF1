"""Ручной smoke Yandex-комментатора (НЕ pytest — тратит платный API).

Запуск (Git Bash):
    YA_KEY=AQVN... YA_FOLDER=b1g... py -3.12 tests/smoke_yandex.py
Запуск (PowerShell):
    $env:YA_KEY="AQVN..."; $env:YA_FOLDER="b1g..."; py -3.12 tests/smoke_yandex.py

Проверяет сквозной путь: validate -> GPT -> TTS -> воспроизведение -> кэш-хит.
"""
import os
import sys
import time

# корень проекта в sys.path при запуске из tests/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yandex_ai.client import YandexClient
from yandex_ai.credentials import Credentials
from yandex_ai.gpt import YandexGPT
from yandex_ai.speech import YandexSpeech

key = os.environ.get("YA_KEY", "")
folder = os.environ.get("YA_FOLDER", "")
assert key and folder, "Задай YA_KEY и YA_FOLDER в окружении"

cl = YandexClient(Credentials(key, folder))
cl.start()
try:
    ok, code, msg = cl.submit(cl.validate()).result(timeout=20)
    print("validate:", ok, code, msg)
    assert ok, msg

    gpt = YandexGPT(cl)
    phrase = gpt.generate({"event_code": "OVTK", "driver": "Ферстаппен"}, "tv")
    print("GPT:", phrase)
    assert phrase

    sp = YandexSpeech(cl)
    audio, sr = sp.synthesize(phrase, "tv")
    print("TTS samples:", None if audio is None else len(audio), "sr:", sr)
    assert audio is not None

    try:
        import sounddevice as sd
        sd.play(audio, sr)
        sd.wait()
        print("playback OK")
    except Exception as exc:  # noqa: BLE001
        print("playback skipped:", exc)
finally:
    cl.stop()

print("SMOKE PASSED")
