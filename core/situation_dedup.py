"""
core/situation_dedup.py
========================
Семантическая дедупликация комментария по «ситуации», а не по коду события.

Проблема: во время затяжной погони игра шлёт OVTK/ATTACK/BATTLE каждые несколько
секунд, и LLM раз за разом пересказывает ОДНУ И ТУ ЖЕ ситуацию («до Албона 0.4,
догоняет» → «...темп стабильный» → «...держит темп»). Анти-повтор по тексту
(PhraseMemory) ловит только дословные дубли; SessionGuard кулдаунит по коду.
Ни то ни другое не видит, что это одна и та же погоня.

Решение: сводим событие к СИГНАТУРЕ ситуации = (сторона, сосед, band дистанции).
Та же сигнатура в пределах cooldown → молчим. Смена band (дистанция реально
изменилась) или смена соседа (обгон состоялся / новая цель) → это «материальное
изменение», комментируем снова.

band дистанции: <0.5с / 0.5–1с / 1–2с / >2с — переход через границу = повод
сказать заново; колебания внутри band — нет.
"""
from __future__ import annotations

# Коды событий, которые описывают позиционную близость к соседу (их и дедупим).
# Остальные коды (FTLP, PENA, RTMT, пит, повреждения, старт/финиш) — самостоятельные
# новости, их НЕ трогаем (signature → None → пропускаем без дедупа).
PROXIMITY_CODES: frozenset[str] = frozenset({
    "OVTK", "ATTACK", "BATTLE", "ATTACK_ZONE",
})

# Контакт — тоже «одна ситуация», но опознаётся он не дистанцией, а УЧАСТНИКАМИ.
# За гонку 2026-08-11 пришло 32 COLL, и один инцидент дал десяток пересказов.
#
# Важно понимать границу: вызывающий (core/engine.py) применяет этот дедуп
# только к некритическим событиям, а чужие аварии приходят критическими и сюда
# не попадают вовсе. Их дословные повторы ловит другой рубеж —
# `commentator/memory.py::PhraseMemory.is_repeat`. Здесь закрывается контакт
# игрока (COLL/COLL_LIGHT), который повторно приезжает той же телеметрией.
COLLISION_CODES: frozenset[str] = frozenset({
    "COLL", "COLL_LIGHT", "COLL_HEAVY",
})


def gap_band(gap_ms: int | None) -> str | None:
    """Дистанция (мс) → грубая полоса. None если дистанции нет."""
    if gap_ms is None or gap_ms <= 0:
        return None
    s = gap_ms / 1000.0
    if s < 0.5:
        return "vclose"
    if s < 1.0:
        return "close"
    if s < 2.0:
        return "near"
    return "far"


class SituationDedup:
    """Помнит последнюю озвученную «ситуацию» и душит её повторы в окне cooldown."""

    def __init__(self, cooldown: float = 20.0):
        self._cooldown = cooldown
        self._last_sig: tuple | None = None
        self._last_t: float = 0.0

    def signature(
        self,
        event: dict,
        *,
        gap_front_ms: int | None,
        gap_behind_ms: int | None,
        gap_leader_ms: int | None,
        ahead_name: str | None,
        behind_name: str | None,
        leader_name: str | None,
    ) -> tuple | None:
        """Сигнатура «ситуации» для proximity-события, иначе None.

        Берём ДОМИНИРУЮЩИЙ (ближайший) бой: машина впереди или сзади; если рядом
        никого — отрыв до лидера. Сигнатура = (сторона, сосед, band)."""
        code = event.get("event_code", "")

        # Контакт опознаётся участниками, а не дистанцией: отрыв в момент
        # столкновения ничего не говорит о том, ТОТ ЖЕ это инцидент или новый, а
        # пара «кто с кем» — говорит. Пару берём неупорядоченной: «Леклер задел
        # Хэмилтона» и «Хэмилтон задел Леклера» — один и тот же контакт.
        if code in COLLISION_CODES:
            pair = frozenset(
                str(event.get(key) or "").strip().lower()
                for key in ("driver", "target")
            ) - {""}
            if not pair:
                return None
            return ("collision", pair)

        if code not in PROXIMITY_CODES:
            return None

        candidates: list[tuple[str, str | None, int]] = []
        if gap_front_ms and gap_front_ms > 0:
            candidates.append(("front", ahead_name, gap_front_ms))
        if gap_behind_ms and gap_behind_ms > 0:
            candidates.append(("back", behind_name, gap_behind_ms))
        if not candidates and gap_leader_ms and gap_leader_ms > 0:
            candidates.append(("leader", leader_name, gap_leader_ms))
        if not candidates:
            return None

        side, name, gap = min(candidates, key=lambda c: c[2])
        return (side, name or "", gap_band(gap))

    def should_emit(self, signature: tuple | None, now: float) -> bool:
        """True = озвучить. False = та же ситуация недавно уже звучала.

        signature=None (не proximity-событие) → всегда True (дедуп не наш случай)."""
        if signature is None:
            return True
        if signature == self._last_sig and (now - self._last_t) < self._cooldown:
            return False
        self._last_sig = signature
        self._last_t = now
        return True

    def reset(self) -> None:
        """Забыть последнюю ситуацию (вызывать на флэшбеке / новой сессии)."""
        self._last_sig = None
        self._last_t = 0.0


class EngineerTopicDedup:
    """Одна новость — один раз, каким бы кодом инженера она ни пришла.

    Отличие от `SituationDedup` выше, из-за которого это отдельный класс, а не
    параметр. Тот дедупит поток КОММЕНТАТОРА по проксимити-кодам игры и знает
    только «та же ситуация или нет». Здесь задача другая: у инженера девять
    независимых трекеров (`core/race_engineer.py` — фасад над ними), каждый со
    своим кулдауном, и ни один не знает про остальных. Поэтому одну и ту же
    новость приносят РАЗНЫЕ коды, и решать приходится не только «повтор ли
    это», но и «какая из двух реплик про одно и то же ценнее».

    Ценность = ранг действенности из `policy.topic_for()`. Реплика, которая
    говорит пилоту ЧТО ДЕЛАТЬ, пробивает уже занятое окно и забирает его себе;
    равная или более информационная — молчит. Без этого правила выбор между
    «Отрыв впереди 0,9» и «DRS открыта, атакуй» решался бы тем, чей пакет
    телеметрии пришёл первым.

    Материальным изменением (то есть новой новостью, а не пересказом) считаются
    смена полосы дистанции и смена соседа — тот же принцип, что у
    `SituationDedup`, и намеренно те же полосы `gap_band`: два дедупа не имеют
    права считать «ту же ситуацию» по-разному.
    """

    def __init__(self, cooldown: float = 20.0):
        self._cooldown = cooldown
        #: тема -> (сосед, полоса, ранг занявшей реплики, когда)
        self._held: dict[str, tuple[str, str, int, float]] = {}

    def should_emit(self, topic: tuple[str, int] | None,
                    neighbour: str | None, band: str | None,
                    now: float) -> bool:
        """True = озвучить.

        `topic=None` — код вне таблицы тем, дедуп не наш случай: пропускаем
        всегда. `band=None` — дистанции нет (машины впереди попросту нет), и
        подавлять на основании неизвестного нельзя.
        """
        if topic is None or band is None:
            return True
        name, rank = topic
        held = self._held.get(name)
        if held is not None:
            prev_neighbour, prev_band, prev_rank, prev_t = held
            fresh = (now - prev_t) < self._cooldown
            same_news = prev_neighbour == (neighbour or "") and prev_band == band
            if fresh and same_news and rank <= prev_rank:
                return False
        self._held[name] = (neighbour or "", band, rank, now)
        return True

    def reset(self) -> None:
        """Забыть занятые темы (флэшбек / новая сессия)."""
        self._held.clear()
