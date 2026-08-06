# Runtime hook: resolve espeak-ng data path for piper-tts in a frozen PyInstaller app.
# piper_phonemize looks for espeak-ng-data/ relative to its package directory.
# In a onefile EXE, all packages land under sys._MEIPASS, so we point env vars there.
import os
import sys

_base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))

# piper_phonemize (piper-tts 1.x) checks PHONEMIZER_ESPEAK_PATH / ESPEAK_DATA_PATH
_piper_dir = os.path.join(_base, 'piper')
_esp_data = os.path.join(_piper_dir, 'espeak-ng-data')
if os.path.isdir(_esp_data):
    os.environ.setdefault('PHONEMIZER_ESPEAK_PATH', _piper_dir)
    os.environ.setdefault('ESPEAK_DATA_PATH', _esp_data)

# Some versions ship the data directly under piper_phonemize package directory
_ph_dir = os.path.join(_base, 'piper_phonemize')
_ph_esp = os.path.join(_ph_dir, 'espeak-ng-data')
if os.path.isdir(_ph_esp):
    os.environ.setdefault('PHONEMIZER_ESPEAK_PATH', _ph_dir)
    os.environ.setdefault('ESPEAK_DATA_PATH', _ph_esp)
