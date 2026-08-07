# -*- mode: python ; coding: utf-8 -*-
#
# Spotter App build spec.
#
# Commentator stack:
#   - Text:  GigaChat / YandexGPT over REST via aiohttp.
#   - Voice: Yandex SpeechKit (cloud, REST via aiohttp) as PRIMARY.
#            Piper — OFFLINE FALLBACK, НО НЕ ЗДЕСЬ: он под GPL-3.0-or-later и
#            в закрытый EXE не вшивается. Его ставит отдельный компонент
#            установщика (installer/SpotterApp.iss), собирает PiperCLI.spec, а
#            приложение запускает его отдельным процессом (new_tts/piper_tts.py).
#            Вместе с Piper отсюда ушёл onnxruntime — его больше никто не звал.
#   - No torch / MOSS / Qwen / transformers (removed).
#
# NOTE: build must run under an interpreter that has the FULL runtime stack
# installed (bottle, pywebview, pywin32, sounddevice, soundfile, piper-tts,
# onnxruntime, numpy, psutil, aiohttp, pandas/fastf1) + pyinstaller.
# See build.ps1 for the dependency gate.
#
from PyInstaller.utils.hooks import collect_all


datas = [
    # Python source packages
    ('voice',        'voice'),
    ('core',         'core'),
    ('tracks',       'tracks'),         # Track Intelligence JSON (24 F1 25 circuits)
    ('commentator',  'commentator'),
    ('new_tts',      'new_tts'),
    ('analytics',    'analytics'),
    ('yandex_ai',    'yandex_ai'),
    # Голосов Piper здесь нет намеренно: их (242 МБ) кладёт компонент
    # установщика в PIPER_VOICES_DIR рядом с приложением.
    # Static UI — статический экспорт Next.js (NewSpotterUI -> webui/, см. build.ps1)
    ('webui',        'webui'),
    # Портреты говорящих для карточки рации (web_server: /assets/radio/<file>).
    # Только эта подпапка: `assets/voices` — мёртвый остаток voice cloning.
    # Отсутствие файла не ломает карточку (фолбэк на инициалы), но без этой
    # строки портретов не было бы ТОЛЬКО в EXE — то есть баг увидел бы
    # пользователь, а не разработчик.
    ('assets/radio', 'assets/radio'),
    ('config.py',    '.'),
    ('app.pyw',      '.'),
    ('web_server.py', '.'),
]

binaries = []

hiddenimports = [
    'webview',
    'webview.platforms.winforms',
    'webview.platforms',
    'webview.servers',
    'webview.http',
    'bottle',
    'psutil',
    'psutil._pswindows',
    'psutil._psutil_windows',
    # Async networking — Yandex GPT/SpeechKit over REST
    'aiohttp',
    'multidict',
    'yarl',
    'frozenlist',
    'aiosignal',
    'attr',
    'attrs',
    'numpy',
    # audio I/O
    'sounddevice',
    'soundfile',
    # global hotkeys (pywin32) — used by core/hotkeys.py via app.pyw
    'win32gui',
    'win32con',
    'win32api',
    'win32process',
    # pyttsx3's SAPI5 driver (last-resort TTS fallback) uses comtypes + the
    # pywin32 pythoncom module (NOT win32com — confirmed by reading
    # pyttsx3/drivers/sapi5.py source), loaded dynamically by name via
    # importlib — invisible to PyInstaller's static import analysis.
    'pythoncom',
    'pywintypes',
    'pyttsx3.drivers',
    'pyttsx3.drivers.sapi5',
    'comtypes.client',
    'comtypes.gen',
    'comtypes.stream',
    # analytics (lazy-imported — PyInstaller static analysis misses these)
    'fastf1',
    'fastf1.exceptions',
    'fastf1.core',
    'pandas',
    'requests',
]

# pywebview — GUI framework
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# bottle — HTTP API
tmp_ret = collect_all('bottle')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# psutil — native .pyd files
tmp_ret = collect_all('psutil')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# aiohttp + async deps (Yandex GPT/TTS over REST)
for _pkg in ('aiohttp', 'multidict', 'yarl', 'frozenlist', 'aiosignal'):
    tmp_ret = collect_all(_pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# pyttsx3 (last-resort offline fallback, used only if BOTH Yandex and Piper
# fail — see voice/tts.py::_init_pyttsx3). Its SAPI5 driver (pyttsx3/drivers/
# sapi5.py) is loaded by name via importlib, invisible to PyInstaller's static
# analysis, AND drives SAPI through `comtypes` (not win32com — confirmed by
# reading the driver source), generating comtypes.gen.SpeechLib at runtime on
# first use. Both packages must be collected in full.
tmp_ret = collect_all('pyttsx3')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('comtypes')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# audio
tmp_ret = collect_all('sounddevice')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

tmp_ret = collect_all('soundfile')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# pandas — fastf1 analytics
tmp_ret = collect_all('pandas')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# gRPC — SpeechKit v3 Synthesizer (yandex_ai/client.py). Native extension
# (_cygrpc) — collect_all alone has previously NOT been sufficient for native
# extensions in this project (see torch DLL lesson in CONTEXT.md); confirmed
# working WITHOUT an explicit collect_dynamic_libs('grpc') as of the 2026-07-09
# build (PyInstaller auto-detected grpc._cython._cygrpc). Mandatory, not
# optional (build.ps1's dependency gate already requires both packages) — uses
# collect_all like aiohttp above, not _safe_collect, so a future collection
# failure fails loudly at build time instead of silently at runtime.
for _pkg in ('grpc', 'yandexcloud'):
    tmp_ret = collect_all(_pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app.pyw'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=['hooks'],
    hooksconfig={},
    # rthook_piper больше не нужен: espeak-ng-data живёт внутри piper.exe,
    # который собирается отдельно (PiperCLI.spec) и не делит с нами _MEIPASS.
    runtime_hooks=[],
    excludes=[
        # Piper и его ONNX-движок — ТОЛЬКО в отдельном piper.exe.
        # Здесь они запрещены явно: GPL-код не должен попасть в закрытый EXE
        # транзитивным импортом, и молча это заметить было бы невозможно.
        'piper', 'onnxruntime',
        # PyTorch full stack (system Python has CUDA torch — must not enter the EXE)
        'torch', 'torch.distributed', 'torch.cuda', 'torch.backends',
        'torchvision', 'torchaudio',
        # ML / NLP tools not needed at runtime
        'transformers', 'accelerate', 'diffusers', 'sentencepiece',
        'sklearn', 'scipy',
        # Visualisation / notebook
        'matplotlib', 'PIL', 'IPython', 'cv2',
        # Removed API clients
        'anthropic',
        # Legacy TTS engines (pyttsx3 is NOT excluded — see collect_all/hiddenimports
        # above, it's the last-resort offline fallback in voice/tts.py)
        'silero',
        # Dev-only web frameworks installed in this environment
        'gradio', 'fastapi', 'uvicorn', 'starlette',
        # Audio dev packages not needed in the frozen app
        'librosa', 'pydub',
        # Qt backends from .venv (not used by this app)
        'PyQt5', 'PySide6',
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
    name='SpotterApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
