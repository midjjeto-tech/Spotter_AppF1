"""Настройки пользователя. Это единственный файл, который обычно нужно менять."""

import os
import sys

# В PyInstaller onefile ресурсы распаковываются во временную папку _MEIPASS
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

# Папка для записи (рядом с EXE в frozen-режиме, корень проекта в dev)
DATA_DIR = (
    os.path.dirname(sys.executable)
    if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.abspath(__file__))
)

# --- Телеметрия ---
UDP_IP = "127.0.0.1"
UDP_PORT = 20777

# --- LLM ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = "claude-haiku-4-5-20251001"

# --- Комментатор ---
PERSONA = "tv"

# Минимальная пауза между фразами (сек)
MIN_COMMENT_GAP = 4.0

# Максимум событий в ленте UI
MAX_FEED_ITEMS = 30

# --- Метаданные F1 (Ergast API, как в Fast-F1) ---
F1_SEASON = "2025"
