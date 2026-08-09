"""Приглушение игры на время реплики (core/audio_ducking.py).

Главное свойство, ради которого написана половина этих тестов: **игра никогда
не должна остаться тихой**. Любой сбой обязан заканчиваться восстановлением
громкости, а не молчаливым выключением звука у пользователя.
"""
import pytest

from core.audio_ducking import GameDucker


class _Session:
    def __init__(self, name: str, volume: float = 1.0):
        self.process_name = name
        self.volume = volume


class _Backend:
    """Подставной микшер. `fail_on` заставляет его падать на N-м обращении."""

    def __init__(self, *sessions, fail_after: int | None = None):
        self._sessions = list(sessions)
        self.calls = 0
        self.fail_after = fail_after

    def sessions(self):
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise OSError("mixer gone")
        return list(self._sessions)


def _ducker(*sessions, level=0.4, **kw):
    return GameDucker(backend=_Backend(*sessions, **kw), level=level)


def test_ducks_only_the_game_session():
    game, other = _Session("F1_25.exe", 1.0), _Session("Discord.exe", 0.8)
    d = _ducker(game, other)

    d.set_busy(True)

    assert game.volume == pytest.approx(0.4)
    assert other.volume == pytest.approx(0.8)


def test_restores_the_original_volume():
    game = _Session("F1_25.exe", 0.9)
    d = _ducker(game)

    d.set_busy(True)
    d.set_busy(False)

    assert game.volume == pytest.approx(0.9)


def test_ducking_is_relative_to_the_users_own_level():
    """Пользователь уже поставил игре 50% — приглушать надо от этого, а не до
    абсолютной величины."""
    game = _Session("F1_25.exe", 0.5)
    d = _ducker(game, level=0.4)

    d.set_busy(True)

    assert game.volume == pytest.approx(0.2)


def test_second_duck_does_not_compound():
    """Повторный вызов не должен приглушать уже приглушённое: иначе серия
    реплик уводит игру в ноль."""
    game = _Session("F1_25.exe", 1.0)
    d = _ducker(game)

    d.set_busy(True)
    d.set_busy(True)

    assert game.volume == pytest.approx(0.4)
    d.set_busy(False)
    assert game.volume == pytest.approx(1.0)


def test_restore_without_duck_is_a_noop():
    game = _Session("F1_25.exe", 1.0)
    d = _ducker(game)

    d.set_busy(False)

    assert game.volume == pytest.approx(1.0)


def test_no_game_session_is_not_an_error():
    d = _ducker(_Session("Discord.exe", 0.8))
    d.set_busy(True)
    d.set_busy(False)
    assert d.active is False


class _DyingSession:
    """Сессия, которая перестаёт принимать громкость — так выглядит закрытая
    игра или перезапуск аудиоустройства. Восстановление НЕ перечисляет сессии
    заново, поэтому отказ приходит именно отсюда, а не из микшера."""

    def __init__(self, name: str, volume: float, die_after: int):
        self.process_name = name
        self._volume = volume
        self._sets = 0
        self._die_after = die_after

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, value: float) -> None:
        self._sets += 1
        if self._sets > self._die_after:
            raise OSError("session gone")
        self._volume = value


def test_session_failure_on_restore_disables_ducking():
    """Если вернуть громкость не удалось — больше не трогаем звук вообще.
    Лучше без приглушения, чем ещё один заход на уже сломанную сессию."""
    game = _DyingSession("F1_25.exe", 1.0, die_after=1)
    d = GameDucker(backend=_Backend(game), level=0.4)

    d.set_busy(True)
    assert game.volume == pytest.approx(0.4)

    d.set_busy(False)         # попытка вернуть падает
    assert d.disabled is True

    before = game.volume
    d.set_busy(True)          # после отказа не трогаем ничего
    assert game.volume == pytest.approx(before)


def test_one_dead_session_does_not_strand_the_others():
    """Главный инвариант при частичном отказе.

    Пропуск в покрытии, найденный предрелизным ревью: тест на ОДНУ умирающую
    сессию был, тест на ДВЕ живые был, а на «одна упала, вторая обязана
    вернуться» — нет. `try` стоял вокруг всего цикла, поэтому вторая сессия
    оставалась на приглушённой громкости, а следом `disabled = True` запрещал
    любой новый заход: вернуть её было уже некому. Пользователь получал тихую
    игру навсегда и шёл искать причину в настройках игры."""
    dying = _DyingSession("F1_25.exe", 1.0, die_after=1)   # переживёт только duck
    alive = _Session("F1_25.exe", 1.0)
    d = GameDucker(backend=_Backend(dying, alive), level=0.4)

    d.set_busy(True)
    assert (dying.volume, alive.volume) == (pytest.approx(0.4), pytest.approx(0.4))

    d.set_busy(False)

    assert alive.volume == pytest.approx(1.0), "живая сессия осталась приглушённой"
    assert d.disabled is True   # отказ всё ещё выключает фичу целиком


def test_a_dead_session_first_in_the_list_does_not_block_the_rest():
    """Порядок не должен решать. Тот же случай, но падающая сессия идёт ВТОРОЙ —
    иначе тест выше проходил бы и на реализации, которая просто ловит исключение
    после последнего элемента."""
    alive = _Session("F1_25.exe", 1.0)
    dying = _DyingSession("F1_25.exe", 1.0, die_after=1)
    d = GameDucker(backend=_Backend(alive, dying), level=0.4)

    d.set_busy(True)
    d.set_busy(False)

    assert alive.volume == pytest.approx(1.0)
    assert d.disabled is True


def test_mixer_enumeration_failure_disables_ducking():
    d = GameDucker(backend=_Backend(_Session("F1_25.exe", 1.0), fail_after=0),
                   level=0.4)
    d.set_busy(True)
    assert d.disabled is True


def test_failure_while_ducking_leaves_volume_untouched():
    d = GameDucker(backend=_Backend(_Session("F1_25.exe", 1.0), fail_after=0),
                   level=0.4)
    d.set_busy(True)
    assert d.disabled is True
    assert d.active is False


def test_user_changed_volume_while_ducked_is_not_overwritten():
    """Пользователь сам подвинул ползунок, пока инженер говорил — вернуть
    старое значение поверх его выбора значит спорить с ним."""
    game = _Session("F1_25.exe", 1.0)
    d = _ducker(game)

    d.set_busy(True)
    game.volume = 0.15        # игрок сам убавил
    d.set_busy(False)

    assert game.volume == pytest.approx(0.15)


def test_custom_process_name_is_matched():
    game = _Session("iRacingSim64DX11.exe", 1.0)
    d = GameDucker(backend=_Backend(game), level=0.5,
                   process_names=("iracingsim64dx11.exe",))

    d.set_busy(True)

    assert game.volume == pytest.approx(0.5)


def test_matching_is_case_insensitive():
    game = _Session("f1_25.EXE", 1.0)
    d = _ducker(game)
    d.set_busy(True)
    assert game.volume == pytest.approx(0.4)


def test_multiple_game_sessions_are_all_ducked_and_restored():
    a, b = _Session("F1_25.exe", 1.0), _Session("F1_25.exe", 0.6)
    d = _ducker(a, b)

    d.set_busy(True)
    assert (a.volume, b.volume) == (pytest.approx(0.4), pytest.approx(0.24))

    d.set_busy(False)
    assert (a.volume, b.volume) == (pytest.approx(1.0), pytest.approx(0.6))


def test_shutdown_restores_a_ducked_game():
    game = _Session("F1_25.exe", 1.0)
    d = _ducker(game)
    d.set_busy(True)

    d.shutdown()

    assert game.volume == pytest.approx(1.0)
