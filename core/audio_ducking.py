"""
core/audio_ducking.py
======================
Приглушение звука ИГРЫ на время реплики — то, что в настоящей F1 делает
радиоканал: он прибивает всё остальное, и поэтому его слышно.

До этого голос микшировался поверх ревущего двигателя на равных, и разборчивость
зависела от того, насколько громко у пользователя выкручена игра.

**Главный инвариант: игра никогда не должна остаться тихой.** Любой сбой
микшера заканчивается восстановлением громкости и полным отключением фичи —
лучше без приглушения, чем с навсегда убавленным звуком, причину которого
пользователь будет искать в настройках игры.

Собственного потока здесь нет. Приглушение включает и снимает воркер очереди
TTS (`new_tts/queue_handler.py`), у которого и так есть цикл с таймаутом: он
знает и когда речь началась, и когда очередь опустела. Заводить ради этого ещё
один аудио-поток в проекте, у которого уже была гонка на нативном PortAudio,
не стоит.
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

#: Исполняемые файлы, которые считаем «игрой». Список, а не одно имя: F1 меняет
#: имя файла каждый сезон, а проект поддерживает ещё и iRacing.
DEFAULT_PROCESS_NAMES: tuple[str, ...] = (
    "f1_25.exe", "f1_24.exe", "f1_23.exe", "f1_22.exe",
    "iracingsim64dx11.exe",
)

#: До какой доли от ТЕКУЩЕЙ громкости игры приглушаем. Доля, а не абсолютная
#: величина: пользователь мог уже поставить игре 50%, и «выставить 0.35»
#: означало бы сделать ГРОМЧЕ.
DEFAULT_LEVEL = 0.35


class GameDucker:
    """Один экземпляр на приложение. Потокобезопасность обеспечивает вызывающий:
    `set_busy` зовётся только из воркера очереди TTS."""

    def __init__(self, backend=None, level: float = DEFAULT_LEVEL,
                 process_names: tuple[str, ...] = DEFAULT_PROCESS_NAMES,
                 field=None) -> None:
        self._backend = backend
        self._level = max(0.0, min(1.0, level))
        self._names = tuple(n.lower() for n in process_names)
        #: сессия -> громкость, которую мы у неё застали
        self._ducked: list[tuple[object, float]] = []
        self.disabled = False
        #: Полевой журнал (core/field_log.py) или None. Приглушение — фича, у
        #: которой отказ выглядит как «ничего не произошло»: игра просто не
        #: становится тише. Без записи, КАКИЕ сессии микшера нашлись, отличить
        #: «не нашли процесс игры» от «нашли, но не сработало» невозможно.
        self._field = field

    @property
    def active(self) -> bool:
        return bool(self._ducked)

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, level))

    def set_busy(self, busy: bool) -> None:
        """True — началась речь, False — очередь опустела."""
        if self.disabled:
            return
        if busy:
            self._duck()
        else:
            self._restore()

    def shutdown(self) -> None:
        """Снять приглушение при остановке приложения. Зовётся из владельца
        очереди: процесс не должен умереть, оставив игру тихой."""
        self._restore()

    # ------------------------------------------------------------------ #

    def _duck(self) -> None:
        if self._ducked:
            # Повторный вызов не должен приглушать уже приглушённое — иначе
            # серия реплик уводит игру в ноль.
            return
        try:
            sessions = self._sessions()
            targets = [s for s in sessions
                       if str(getattr(s, "process_name", "")).lower() in self._names]
            if self._field is not None:
                # Список ВСЕХ процессов микшера, а не только совпавших: если игра
                # не приглушилась, первый вопрос — под каким именем она вообще
                # видна системе (F1 меняет имя файла каждый сезон).
                self._field.record(
                    "duck", matched=[getattr(s, "process_name", "?") for s in targets],
                    all_sessions=[getattr(s, "process_name", "?") for s in sessions],
                    looking_for=list(self._names), level=self._level)
            for session in targets:
                original = float(session.volume)
                self._ducked.append((session, original))
                session.volume = original * self._level
        except Exception:  # noqa: BLE001
            _log.warning("ducking: микшер недоступен, приглушение отключено",
                         exc_info=True)
            if self._field is not None:
                self._field.record("duck_failed", stage="enumerate_or_set")
            self._fail()

    def _restore(self) -> None:
        if not self._ducked:
            return
        ducked, self._ducked = self._ducked, []
        failed = False
        for session, original in ducked:
            # try ВОКРУГ ОДНОЙ сессии, а не вокруг всего цикла. Раньше падение
            # на первой бросало все остальные приглушёнными, а следом
            # `disabled = True` запрещал любой новый заход — вернуть их было уже
            # некому, и игра оставалась тихой навсегда. Ровно то, что этот
            # модуль обязан не допускать; см. `_fail`, где приём тот же.
            try:
                # Если пользователь сам подвинул ползунок, пока инженер говорил,
                # возвращать своё значение поверх его выбора значит спорить с
                # ним. Сверяем с тем, что оставили мы.
                expected = original * self._level
                if abs(float(session.volume) - expected) > 1e-3:
                    continue
                session.volume = original
            except Exception:  # noqa: BLE001
                failed = True
                _log.warning("ducking: не удалось вернуть громкость сессии %r",
                             getattr(session, "process_name", "?"), exc_info=True)
        # Отключаемся ПОСЛЕ прохода по всем: отказ одной сессии — повод больше не
        # трогать звук, но не повод бросить остальные приглушёнными.
        if failed:
            self.disabled = True

    def _fail(self) -> None:
        """Отказ микшера: вернуть всё, что успели тронуть, и больше не лезть."""
        for session, original in self._ducked:
            try:
                session.volume = original
            except Exception:  # noqa: BLE001
                pass
        self._ducked = []
        self.disabled = True

    def _sessions(self):
        if self._backend is None:
            self._backend = _PycawBackend()
        return self._backend.sessions()


class _PycawBackend:
    """Сессии микшера Windows через pycaw.

    Импорт ленивый и внутри метода: pycaw тянет COM, а он не нужен ни в тестах,
    ни при выключенной фиче. Любая ошибка здесь поднимается наверх и там
    отключает приглушение целиком."""

    def sessions(self):
        from pycaw.pycaw import AudioUtilities  # локально: COM только по нужде

        out = []
        for session in AudioUtilities.GetAllSessions():
            if session.Process is None:
                continue
            out.append(_PycawSession(session))
        return out


class _PycawSession:
    """Одна сессия микшера с громкостью как обычным атрибутом — так подставной
    микшер в тестах и настоящий выглядят одинаково для GameDucker."""

    __slots__ = ("_session", "process_name")

    def __init__(self, session):
        self._session = session
        self.process_name = session.Process.name()

    @property
    def volume(self) -> float:
        return self._session.SimpleAudioVolume.GetMasterVolume()

    @volume.setter
    def volume(self, value: float) -> None:
        self._session.SimpleAudioVolume.SetMasterVolume(
            max(0.0, min(1.0, value)), None)
