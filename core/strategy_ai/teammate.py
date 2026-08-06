"""
core/strategy_ai/teammate.py
=============================
Напарник по команде — вторая машина той же команды, что и у игрока.

Это единственный соперник, у которого ЗАВЕДОМО такая же техника: в реальной
Формуле-1 именно с ним сравнивают пилота, и именно про него инженер говорит
без спроса. У Spotter'а до сих пор были только «соседи по позиции» (ближайшие
впереди/сзади) и «эталон реальной F1» — сравнения с равной машиной не было
вообще.

Модуль чистый: получает уже собранное состояние (грид, шины, история кругов) и
возвращает готовый текст либо None. Никакой телеметрии и потоков.
"""
from __future__ import annotations

from core.num_to_words import ru_plural

# Ниже этой разницы лучших кругов говорить «быстрее/медленнее» бессмысленно —
# это шум замера, а не темп. Тот же порядок, что TREND_THRESHOLD_MS у гэпов.
PACE_NOISE_MS = 100

# Сразу в предложном падеже («он НА чём»): собирать форму из именительного
# по окончанию не выйдет — «медиум»/«хард» и «дождевые» склоняются по-разному,
# а первая попытка так и выдала «он на медиум» и «он на дождевую».
# Слова — те же, что уже приняты в commentator/radio_answer.py и personas.py
# (софт/медиум/хард/интермедиэйт/дождевые), новую терминологию не вводим.
_COMPOUND_RU_ON = {
    "S": "софте", "M": "медиуме", "H": "харде",
    "I": "интермедиэйте", "W": "дождевых",
}


def find_teammate_idx(grid: list[dict], player_idx: int | None) -> int | None:
    """car_idx напарника, либо None.

    Напарник — единственная другая машина с той же командой. Пустая/неизвестная
    команда не считается совпадением: иначе на неполном гриде «напарниками»
    оказались бы все машины без метаданных сразу. Порядок обхода — по
    vehicle_idx, чтобы результат не зависел от текущих позиций."""
    if player_idx is None:
        return None
    rows = {row.get("vehicle_idx"): row for row in grid}
    player_row = rows.get(player_idx)
    if player_row is None:
        return None
    team = (player_row.get("team") or "").strip()
    if not team:
        return None
    for idx in sorted(i for i in rows if isinstance(i, int)):
        if idx == player_idx:
            continue
        if (rows[idx].get("team") or "").strip() == team:
            return idx
    return None


def _position_clause(player_pos: int | None, mate_pos: int | None,
                     mate_name: str) -> str | None:
    if not mate_pos:
        return None
    if not player_pos:
        return f"Напарник {mate_name} идёт P{mate_pos}."
    delta = mate_pos - player_pos
    if delta == 0:                       # позиции ещё не разъехались
        return f"Напарник {mate_name} идёт P{mate_pos}."
    where = "позади" if delta > 0 else "впереди"
    count = abs(delta)
    word = ru_plural(count, "позицию", "позиции", "позиций")
    return (f"Напарник {mate_name} идёт P{mate_pos}, "
            f"это на {count} {word} {where} тебя.")


def _pace_clause(player_best_ms: int | None, mate_best_ms: int | None) -> str | None:
    """Сравнение ЛУЧШИХ кругов сессии — единственная честная оценка темпа на
    равной машине. Разницу меньше PACE_NOISE_MS не озвучиваем."""
    if not player_best_ms or not mate_best_ms:
        return None
    delta = player_best_ms - mate_best_ms
    if abs(delta) < PACE_NOISE_MS:
        return "По лучшему кругу вы идёте вровень."
    seconds = abs(delta) / 1000.0
    if delta < 0:
        return f"По лучшему кругу ты быстрее на {seconds:.1f}."
    return f"По лучшему кругу он быстрее на {seconds:.1f}."


def _tyre_clause(mate_compound: str | None, mate_age: int | None) -> str | None:
    name = _COMPOUND_RU_ON.get(mate_compound or "")
    if name is None:
        return None
    if mate_age is None:
        return f"Он на {name}."
    word = ru_plural(mate_age, "круг", "круга", "кругов")
    return f"Он на {name}, {mate_age} {word}."


def build_report(
    *,
    mate_name: str,
    player_pos: int | None = None,
    mate_pos: int | None = None,
    player_best_ms: int | None = None,
    mate_best_ms: int | None = None,
    mate_compound: str | None = None,
    mate_tyre_age: int | None = None,
) -> str:
    """Готовый ответ инженера про напарника. Собирается только из того, что
    реально известно — недостающие куски молча опускаются, как в gap_digest."""
    parts = [
        _position_clause(player_pos, mate_pos, mate_name),
        _pace_clause(player_best_ms, mate_best_ms),
        _tyre_clause(mate_compound, mate_tyre_age),
    ]
    said = [part for part in parts if part]
    if not said:
        return f"Напарник {mate_name} на трассе, данных по нему пока нет."
    return " ".join(said)


def race_result(player_pos: int | None, mate_pos: int | None) -> str | None:
    """Итог дуэли с напарником для послегоночной истории. None — сравнивать
    нечего (нет напарника или кто-то не классифицирован)."""
    if not player_pos or not mate_pos:
        return None
    if player_pos < mate_pos:
        return f"обыграл напарника (P{player_pos} против P{mate_pos})"
    if player_pos > mate_pos:
        return f"проиграл напарнику (P{player_pos} против P{mate_pos})"
    return None          # одинаковых позиций в классификации не бывает
