"""
voice/cache.py
==============
Дисковый кэш сгенерированных WAV-файлов TTS.
Кэш-файл — это и есть файл воспроизведения: никакого отдельного шага
"сгенерировать во временный файл и удалить после игры" для повторных фраз.
"""

from __future__ import annotations

import hashlib
import os
import re

_CACHE_NAME_RE = re.compile(r'^[0-9a-f]{40}\.wav$')


class TTSCache:
    def __init__(self, cache_dir: str, max_files: int = 3000, max_mb: int = 300,
                 version: str = ""):
        self.cache_dir = cache_dir
        self.max_files = max_files
        self.max_bytes = max_mb * 1024 * 1024
        # version namespaces the key so switching TTS engines invalidates old
        # cache (otherwise old broken audio would be served on a key collision)
        self.version = version
        os.makedirs(self.cache_dir, exist_ok=True)

    def path_for(self, text: str, speaker: str) -> str:
        key = hashlib.sha1(f"{self.version}|{text}|{speaker}".encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, f"{key}.wav")

    def evict_if_needed(self) -> None:
        """Удаляет самые старые (по mtime) файлы, если превышены лимиты."""
        try:
            entries = [
                (e.path, e.stat().st_mtime, e.stat().st_size)
                for e in os.scandir(self.cache_dir)
                if e.is_file() and _CACHE_NAME_RE.match(e.name)
            ]
        except OSError:
            return

        total_bytes = sum(size for _, _, size in entries)
        count = len(entries)
        if count <= self.max_files and total_bytes <= self.max_bytes:
            return

        entries.sort(key=lambda e: e[1])  # старые сначала
        for path, _, size in entries:
            if count <= self.max_files and total_bytes <= self.max_bytes:
                break
            try:
                os.remove(path)
            except OSError:
                continue
            count -= 1
            total_bytes -= size

    def cleanup_tmp(self) -> int:
        """Remove stale .wav.tmp files left by interrupted writes. Returns count removed."""
        removed = 0
        try:
            for e in os.scandir(self.cache_dir):
                if e.is_file() and e.name.endswith(".tmp"):
                    try:
                        os.remove(e.path)
                        removed += 1
                    except OSError:
                        pass
        except OSError:
            pass
        return removed
