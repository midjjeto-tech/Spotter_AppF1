"""
tools/diagnose.py
==================
Один отчёт по заезду — чтобы «пришлите диагностику» было действием на одно
сообщение, а не пересылкой мегабайта JSONL.

    ЗАПУСК (из корня проекта, после заезда с включённой диагностикой):

        .venv\\Scripts\\python.exe tools/diagnose.py

    Отчёт печатается в консоль и кладётся рядом файлом
    `spotter-diagnostic-<дата>.txt`. Его и надо прислать целиком.

    ЧТОБЫ ЖУРНАЛ ВЁЛСЯ, перед заездом нужно одно из двух:
      * `"field_diagnostics": true` в settings.json (работает и в собранном
        приложении), либо
      * переменная окружения `SPOTTER_DIAG=1` (дерево разработки).

Скрипт ничего не считает сам: разбор живёт в `core/diag_report.py` и покрыт
тестами. Здесь только чтение файлов и выбор, какой журнал брать.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.diag_report import build_report  # noqa: E402

#: Сколько последних строк spotter.log просматривать на ошибки. Лог растёт
#: неограниченно, а интересен хвост — тот заезд, про который спрашивают.
LOG_TAIL_LINES = 4000

#: Строки лога, которые считаем ошибкой. `Traceback` отдельно: у него сам текст
#: исключения приходит СЛЕДУЮЩЕЙ строкой, и без неё запись бесполезна.
_ERROR_RE = re.compile(r"\b(ERROR|CRITICAL|Traceback|Exception|Error:)\b")


def _data_dir() -> Path:
    try:
        import config
        return Path(config.DATA_DIR)
    except Exception:  # noqa: BLE001 — конфиг может не подняться вне приложения
        return Path(__file__).resolve().parents[1]


def newest_journal(explicit: str | None = None) -> Path | None:
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    candidates: list[Path] = []
    root = Path(__file__).resolve().parents[1]
    for folder in {_data_dir(), root, root / "dist"}:
        try:
            candidates.extend(folder.glob("field-diag-*.jsonl"))
        except Exception:  # noqa: BLE001
            continue
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_journal(path: Path) -> list[dict]:
    """Разобранные записи. Битая строка пропускается: журнал пишется на живом
    заезде и может оборваться на середине, если приложение убили."""
    records: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def read_log_errors() -> list[str]:
    for candidate in (_data_dir() / "spotter.log",
                      Path(__file__).resolve().parents[1] / "spotter.log"):
        if not candidate.exists():
            continue
        try:
            tail = candidate.read_text(encoding="utf-8",
                                       errors="replace").splitlines()[-LOG_TAIL_LINES:]
        except OSError:
            continue
        return [line for line in tail if _ERROR_RE.search(line)]
    return []


def _force_utf8_console() -> None:
    """Кириллица в консоли Windows — знакомый класс сбоев.

    Унаследованная консоль отдаёт cp866, и `print()` русского текста в ней
    падает с `UnicodeEncodeError` — то есть диагностика, ради которой всё
    делалось, обрывается на первой же строке. `errors="replace"` вместо отказа:
    испорченные символы в консоли терпимы, а файл отчёта всё равно пишется в
    UTF-8 и уходит целым."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def main() -> int:
    _force_utf8_console()
    parser = argparse.ArgumentParser(description="Отчёт по полевому журналу.")
    parser.add_argument("journal", nargs="?", help="путь к field-diag-*.jsonl")
    parser.add_argument("--no-file", action="store_true",
                        help="только печать, не сохранять отчёт")
    args = parser.parse_args()

    path = newest_journal(args.journal)
    if path is None:
        print("Журнал не найден.\n"
              "Перед заездом включите диагностику одним из двух способов:\n"
              '  * "field_diagnostics": true в settings.json\n'
              "  * переменная окружения SPOTTER_DIAG=1\n"
              "затем проедьте хотя бы несколько кругов и запустите снова.")
        return 1

    report = build_report(read_journal(path), read_log_errors(), path.name)
    text = report.to_text()
    print(text)

    if not args.no_file:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = Path(__file__).resolve().parents[1] / f"spotter-diagnostic-{stamp}.txt"
        try:
            out.write_text(text, encoding="utf-8")
            print(f"\nОтчёт сохранён: {out}")
        except OSError as exc:
            print(f"\nНе удалось сохранить отчёт: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
