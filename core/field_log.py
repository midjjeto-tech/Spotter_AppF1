"""
core/field_log.py
==================
Полевой журнал живого заезда — то, по чему МОЖНО РАЗОБРАТЬ заезд после него.

Обычный `spotter.log` отвечает на вопрос «что произошло». Он бесполезен там, где
вопрос звучит иначе: **почему НЕ произошло**. Коуч промолчал весь заезд — пороги
завышены вдвое или сигнал вообще не тот? По событийному логу это неотличимо:
там просто нет строк.

Поэтому здесь пишутся не только события, но и РАСПРЕДЕЛЕНИЯ сигналов: сколько
кадров, какой минимум и максимум, сколько раз перешагнули порог. Заезд, в
котором ничего не сработало, остаётся полностью разбираемым — видно, на сколько
именно сигнал не дотянул.

Формат — JSONL: одна строка на запись, читается построчно и не портится, если
приложение убили посреди сессии.

**Выключен по умолчанию.** Включается на время проверки:
  * переменной окружения `SPOTTER_DIAG=1` — дерево разработки;
  * ключом `"field_diagnostics": true` в `settings.json` — собранное приложение,
    где переменную окружения выставить неоткуда.

Стоимость на горячем пути — обновление словаря на кадр; на диск уходит один раз
за круг. Отдельного потока нет: заводить ещё один в проекте, где уже была гонка
на нативном PortAudio, ради диагностики не стоит.

Модуль НЕ ИМЕЕТ ПРАВА уронить движок: любая ошибка внутри гасится. Диагностика,
которая ломает заезд, стоит дороже, чем отсутствие диагностики.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime

import config

_log = logging.getLogger(__name__)

#: Ключи, которые принадлежат самой записи и не могут быть заняты полем.
_RESERVED_KEYS = frozenset({"t", "kind"})


def _enabled_by_env() -> bool:
    return os.environ.get("SPOTTER_DIAG") == "1"


class FieldLog:
    """Один экземпляр на приложение. Потокобезопасен: пишут и поток телеметрии,
    и воркер очереди TTS."""

    def __init__(self, enabled: bool = False, path: str | None = None) -> None:
        self.enabled = bool(enabled)
        self._lock = threading.Lock()
        self._file = None
        self._path = path
        #: канал -> {count, min, max, sum, over: {порог: сколько раз}}
        self._stats: dict[str, dict] = {}

    # ── жизненный цикл ───────────────────────────────────────────────────── #

    def start(self, **environment) -> None:
        """Открыть файл и записать снимок окружения.

        Снимок первым делом и целиком: разбирая лог через неделю, невозможно
        вспомнить, какая была версия, какие настройки и был ли вообще включён
        коуч. Половина вопросов «почему не сработало» закрывается этой строкой."""
        if not self.enabled or self._file is not None:
            return
        try:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._path = self._path or os.path.join(
                config.DATA_DIR, f"field-diag-{stamp}.jsonl")
            self._file = open(self._path, "a", encoding="utf-8")
            self.record("session_start", **environment)
            _log.info("Field diagnostics ON -> %s", self._path)
        except Exception:  # noqa: BLE001 — диагностика не роняет запуск
            _log.warning("Field diagnostics could not start", exc_info=True)
            self.enabled = False
            self._file = None

    def stop(self) -> None:
        if self._file is None:
            return
        try:
            self.flush_stats(reason="shutdown")
            self.record("session_end")
        except Exception:  # noqa: BLE001
            pass
        try:
            self._file.close()
        except Exception:  # noqa: BLE001
            pass
        self._file = None

    @property
    def path(self) -> str | None:
        return self._path

    # ── события ──────────────────────────────────────────────────────────── #

    def record(self, event: str, /, **fields) -> None:
        """Одно событие. `event` — что случилось, остальное произвольно.

        Параметр ПОЗИЦИОННЫЙ (`/`) намеренно: у записываемых объектов бывают
        поля с любыми именами, и `record("coach_mistake", kind=...)` иначе
        падает с «got multiple values for argument». Диагностика, которая роняет
        движок именем поля, не имеет смысла — так и случилось на первом же
        прогоне."""
        if not self.enabled or self._file is None:
            return
        line = {"t": round(time.time(), 3), "kind": event}
        for key, value in fields.items():
            # Служебные ключи не перезаписываются. `line.update(fields)` было
            # хуже падения: поле с именем `kind` МОЛЧА подменяло имя события, и
            # запись про ошибку коуча уезжала в лог под именем "lockup". Здесь
            # выигрывает служебный ключ, а значение поля сохраняется рядом —
            # терять данные диагностика тоже не имеет права.
            if key in _RESERVED_KEYS:
                key = f"{key}_"
            line[key] = value
        try:
            with self._lock:
                # default=str: в поля попадают dataclass'ы и Path, и падать из-за
                # несериализуемого значения диагностика права не имеет.
                self._file.write(json.dumps(line, ensure_ascii=False,
                                            default=str) + "\n")
                self._file.flush()
        except Exception:  # noqa: BLE001
            pass

    # ── распределения ────────────────────────────────────────────────────── #

    def observe(self, channel: str, value: float,
                thresholds: tuple[float, ...] = ()) -> None:
        """Значение сигнала на кадре.

        `thresholds` — пороги, по которым считаются превышения. Именно они
        отвечают на вопрос «на сколько не дотянуло»: без счётчика превышений
        максимум сам по себе не говорит, был ли это одиночный выброс."""
        if not self.enabled:
            return
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
        with self._lock:
            stat = self._stats.get(channel)
            if stat is None:
                stat = {"count": 0, "min": value, "max": value, "sum": 0.0,
                        "over": {}}
                self._stats[channel] = stat
            stat["count"] += 1
            stat["sum"] += value
            if value < stat["min"]:
                stat["min"] = value
            if value > stat["max"]:
                stat["max"] = value
            for threshold in thresholds:
                key = str(threshold)
                hit = value >= threshold if threshold >= 0 else value <= threshold
                if hit:
                    stat["over"][key] = stat["over"].get(key, 0) + 1

    def flush_stats(self, **context) -> None:
        """Сводка по всем каналам одной строкой и сброс счётчиков. Зовётся раз в
        круг: чаще — мусор, реже — потеряется привязка к кругу."""
        if not self.enabled or self._file is None:
            return
        with self._lock:
            stats, self._stats = self._stats, {}
        if not stats:
            return
        summary = {
            name: {
                "n": s["count"],
                "min": round(s["min"], 4),
                "max": round(s["max"], 4),
                "avg": round(s["sum"] / s["count"], 4) if s["count"] else None,
                "over": s["over"],
            }
            for name, s in stats.items()
        }
        self.record("signals", **context, channels=summary)


#: Заглушка на случай выключенной диагностики: вызывающим не нужно проверять
#: `if field_log is not None` на каждом кадре.
DISABLED = FieldLog(enabled=False)


def create(settings: dict | None = None) -> FieldLog:
    """Журнал по настройкам. Два переключателя намеренно: в дереве разработки
    удобна переменная окружения, а в собранном приложении её выставить
    неоткуда — там ключ в settings.json."""
    by_setting = bool((settings or {}).get("field_diagnostics", False))
    return FieldLog(enabled=_enabled_by_env() or by_setting)
