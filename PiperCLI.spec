# -*- mode: python ; coding: utf-8 -*-
#
# piper.exe — ОТДЕЛЬНАЯ ПРОГРАММА, не часть Spotter App.
#
# Piper распространяется под GPL-3.0-or-later. Вшивать его в закрытый
# SpotterApp.exe нельзя, поэтому здесь он собирается самостоятельным
# исполняемым файлом: Spotter запускает его как внешний процесс и общается
# через stdin и файлы (new_tts/piper_tts.py).
#
# Итог этой сборки распространяется НА УСЛОВИЯХ GPL-3.0-or-later. Установщик
# кладёт рядом с ним COPYING и ссылку на исходный код (installer/SpotterApp.iss,
# компонент «piper»). Код Piper мы не меняем — собираем как есть из пакета
# piper-tts, поэтому «соответствующий исходный код» — это официальный релиз
# проекта OHF-Voice/piper1-gpl той же версии.
#
# Сборка: pyinstaller --clean --noconfirm PiperCLI.spec
#
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ['piper', 'piper.__main__', 'onnxruntime', 'onnxruntime.capi']

# piper тянет с собой espeak-ng-data — без неё нет фонемизации русского.
for _pkg in ('piper', 'onnxruntime', 'numpy'):
    tmp_ret = collect_all(_pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Имя пакета фонемизатора менялось между версиями piper-tts; отсутствие любого
# из них не должно ронять сборку.
for _opt in ('piper_phonemize', 'espeakng_loader', 'espeak_phonemizer'):
    try:
        tmp_ret = collect_all(_opt)
        datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
    except Exception:
        pass


a = Analysis(
    ['piper_cli_entry.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['hooks/rthook_piper.py'],
    excludes=[
        # Ничего из Spotter App сюда попасть не должно: это чужая программа.
        'bottle', 'webview', 'aiohttp', 'pandas', 'fastf1', 'grpc',
        'yandexcloud', 'pyttsx3', 'comtypes', 'sounddevice', 'soundfile',
        'torch', 'transformers', 'matplotlib', 'PIL', 'scipy', 'sklearn',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='piper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Консольная программа: она читает stdin и пишет файлы. Окно консоли гасится
    # на стороне вызывающего (CREATE_NO_WINDOW в new_tts/piper_tts.py).
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
