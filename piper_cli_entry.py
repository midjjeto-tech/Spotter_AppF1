"""Точка входа для сборки piper.exe (см. PiperCLI.spec).

Это НЕ код Spotter App: собранный бинарник — отдельная программа, которая
распространяется на условиях GPL-3.0-or-later вместе с исходным кодом, включая
этот файл (см. NOTICE и installer/piper-README.txt). Файл нужен потому, что
PyInstaller не умеет замораживать `python -m piper` напрямую.

ЗАЧЕМ ЗДЕСЬ ВООБЩЕ ЕСТЬ КОД, кроме вызова main. Замороженный бутлоадер
PyInstaller подменяет обработку stdin, и русский текст приходил в программу
искажённым: «Бокс, бокс.» вместо 1.0 с звучало 5.4 с невнятицы. Ни
PYTHONIOENCODING, ни PYTHONUTF8 на это не влияют — проверено обоими. Ошибка
молчаливая: код возврата нулевой, файл создаётся, слышна только бессмыслица.
Поэтому кодировка задаётся здесь явно.

Логики Spotter App тут быть не должно — только это.
"""
import sys

from piper.__main__ import main

if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass
    main()
