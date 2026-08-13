"""
commentator/timeline.py
========================
Скользящее окно памяти гонки («Race Timeline») для автономного ИИ-аналитика.

Вместо одного изолированного события ИИ получает ДИНАМИКУ: как менялись круг,
позиция игрока, темп (времена кругов) и соседи по сетке за последние ~3-5 кругов,
плюс ленту последних событий. Это позволяет говорить «шли третьими, Леклер догонял,
заехали на пит — выехали шестыми», а не реагировать на сухой триггер.

Модуль самодостаточен: принимает простые данные (числа/строки/list[dict] из
state.race и state.telemetry), не зависит от engine. Износ шин в телеметрии F1 25
не парсится (см. core/packets.py) — деградацию отражает ТЕМП (дельта времён кругов).
"""
from __future__ import annotations

from collections import deque

from core.ru_names import glossary as _name_glossary, surname_of


def _fmt_laptime(ms: int | None) -> str | None:
    """Время круга в мс -> «1:32.456» / «58.4с». None/0 -> None."""
    if not ms or ms <= 0:
        return None
    total = ms / 1000.0
    minutes = int(total // 60)
    seconds = total - minutes * 60
    return f"{minutes}:{seconds:06.3f}" if minutes else f"{seconds:.1f}с"


def _fmt_gap(ms: int | None) -> str | None:
    """Отрыв в мс -> «1.8с». None/0 -> None (0 = нет машины / сам лидер)."""
    if not ms or ms <= 0:
        return None
    return f"{ms / 1000.0:.1f}с"


def _player_line(first_name: str, full_name: str | None) -> str:
    """Строка ПИЛОТ: кто такой игрок и под каким именем он в остальном контексте.

    Одного имени мало: в ленте событий игрок назван ФАМИЛИЕЙ, соседи и лидер —
    полными именами, и модель, которой дали только «Шарль», берёт фамилию у
    ближайшего названного гонщика. Поэтому здесь обе формы и обе роли явно.
    Фамилии нет (кастомный пилот в одно слово) — остаётся прежняя короткая
    строка, придумывать за игру нечего.
    """
    surname = surname_of(full_name) if full_name else None
    if not surname or surname == first_name:
        return f"ПИЛОТ: {first_name}."
    return (f"ПИЛОТ: {full_name} — это ИГРОК, вся телеметрия ниже про него. "
            f"В событиях он «{surname}»; обращаться к нему — «{first_name}».")


class RaceTimeline:
    """Память гонки: посекундные снимки (дедуп по кругу) + лента событий."""

    def __init__(self, max_snapshots: int = 15, max_events: int = 15):
        self._snapshots: deque[dict] = deque(maxlen=max_snapshots)
        self._events: deque[dict] = deque(maxlen=max_events)

    # ------------------------------------------------------------------ #
    # Запись
    # ------------------------------------------------------------------ #

    def record_snapshot(self, *, lap: int | None, position: int | None,
                        leader: str | None = None, grid: list[dict] | None = None,
                        last_lap_ms: int | None = None, fuel=None,
                        total_laps: int | None = None,
                        gap_leader_ms: int | None = None,
                        gap_front_ms: int | None = None,
                        gap_behind_ms: int | None = None,
                        tyre_compound: str | None = None,
                        tyre_age: int | None = None,
                        tyre_wear: float | None = None,
                        session_type: str | None = None,
                        pit_status: int | None = None,
                        pit_lap: bool | None = None) -> None:
        """Снимок ситуации: позиция, соседи, темп, ОТРЫВЫ по времени (мс) и ШИНЫ
        (компаунд/возраст/износ). Соседи (имена) — из grid по позиции. Снимки
        дедуплицируются по кругу: тот же круг — обновляем последний, иначе новый.

        pit_status — ЖИВОЙ статус на момент снимка (0/1/2); используется для
        подавления ОТРЫВОВ и фаза-тэга "ПИТ-СТОП" (эти значения искажены, только
        пока машина реально в боксах СЕЙЧАС).
        pit_lap — было ли пит-событие в ходе круга, чьё last_lap_ms несёт этот
        снимок (РЕТРОСПЕКТИВНО — круг мог завершиться уже после выезда из боксов,
        когда pit_status снова 0); используется для подавления ТЕМП-тренда."""
        ahead = behind = None
        if grid and position:
            by_pos = {g.get("position"): g.get("driver")
                      for g in grid if g.get("position")}
            ahead = by_pos.get(position - 1)
            behind = by_pos.get(position + 1)

        snap = {
            "lap": lap,
            "position": position,
            "leader": leader,
            "ahead": ahead,
            "behind": behind,
            "last_lap_ms": last_lap_ms,
            "fuel": fuel,
            "total_laps": total_laps,
            "gap_leader_ms": gap_leader_ms,
            "gap_front_ms": gap_front_ms,
            "gap_behind_ms": gap_behind_ms,
            "tyre_compound": tyre_compound,
            "tyre_age": tyre_age,
            "tyre_wear": tyre_wear,
            "session_type": session_type,
            "pit_status": pit_status,
            "pit_lap": pit_lap,
        }
        if self._snapshots and self._snapshots[-1].get("lap") == lap and lap is not None:
            # тот же круг — обновляем непустыми полями (темп/отрывы/шины уточняются)
            self._snapshots[-1].update({k: v for k, v in snap.items() if v is not None})
        else:
            self._snapshots.append(snap)

    def record_event(self, event: dict) -> None:
        """Лента событий: код + участники + круг (для «истории» в контексте ИИ)."""
        self._events.append({
            "code": event.get("event_code"),
            "driver": event.get("driver"),
            "target": event.get("target"),
            "battle": event.get("battle", False),
            "lap": self._current_lap(),
            "ambient_mentioned": False,
        })

    def reset(self) -> None:
        self._snapshots.clear()
        self._events.clear()

    # ------------------------------------------------------------------ #
    # Запросы
    # ------------------------------------------------------------------ #

    def _current_lap(self) -> int | None:
        return self._snapshots[-1].get("lap") if self._snapshots else None

    def _pace_trend(self) -> str | None:
        """Тренд темпа по последним временам кругов: ускоряется/замедляется/ровно.
        None, если хотя бы один из двух сравниваемых кругов был пит-кругом —
        искажённое пит-стопом время не показатель темпа на трассе (ни в форме
        'замедлился', ни в форме ложного 'резко ускорился' сразу после боксов)."""
        entries = [(s["last_lap_ms"], s.get("pit_lap", False))
                  for s in self._snapshots if s.get("last_lap_ms")]
        if len(entries) < 2:
            return None
        (prev, prev_pit), (last, last_pit) = entries[-2], entries[-1]
        if prev_pit or last_pit:
            return None
        delta = last - prev
        sign = "+" if delta >= 0 else "−"
        tag = "замедляется" if delta > 250 else ("ускоряется" if delta < -250 else "ровно")
        return f"{tag} ({sign}{abs(delta) / 1000:.1f}с к прошлому кругу)"

    def _gap_front_trend(self) -> str | None:
        """Тренд отрыва к машине впереди: догоняет / отрыв растёт / держится."""
        gaps = [s["gap_front_ms"] for s in self._snapshots if s.get("gap_front_ms")]
        if len(gaps) < 2:
            return None
        delta = gaps[-1] - gaps[-2]          # <0 = отрыв сократился (догоняет)
        if delta < -100:
            return f"догоняет {abs(delta) / 1000:.1f}с/кр"
        if delta > 100:
            return f"отрыв растёт {delta / 1000:.1f}с/кр"
        return "держится"

    def _position_trajectory(self) -> str | None:
        """Траектория позиции по снимкам: «P3→P4→P6» (только смены)."""
        seq: list[int] = []
        for s in self._snapshots:
            p = s.get("position")
            if p and (not seq or seq[-1] != p):
                seq.append(p)
        if len(seq) < 2:
            return None
        return "→".join(f"P{p}" for p in seq[-5:])

    def render(self, trigger: dict | None = None, player_name: str | None = None,
               player_full_name: str | None = None) -> str:
        """Компактный текстовый контекст для LLM: ситуация + динамика + события.

        trigger — событие, спровоцировавшее запрос (для событийного режима); в
        ambient-режиме None. player_name — имя игрока (core.ru_names.first_name_of),
        None если неизвестно — тогда строки ПИЛОТ не будет, и персона "calm" не
        должна ничего придумывать (см. commentator/personas.py). Пустой таймлайн ->
        минимальный контекст «нет данных».

        player_full_name — полное имя того же человека. Без него строка была
        «ПИЛОТ: Шарль.», а рядом стояли «лидер Джордж Расселл» полным именем и
        события, где игрок назван «Леклер»; связать одно с другим модели нечем,
        и разбор живого заезда 2026-08-11 показал результат: игрока весь заезд
        звали Расселлом, вплоть до «Шарль Расселл борется за позицию». Имя и
        фамилия нужны обе и в РАЗНЫХ ролях: фамилией о нём говорят, именем к
        нему обращаются."""
        if not self._snapshots and not self._events:
            return "Гонка ещё не началась — данных телеметрии нет."

        lines: list[str] = []
        cur = self._snapshots[-1] if self._snapshots else {}

        if player_name:
            lines.append(_player_line(player_name, player_full_name))

        # --- Текущая ситуация ---
        lap = cur.get("lap")
        total = cur.get("total_laps")
        situ: list[str] = []
        if lap:
            situ.append(f"круг {lap}" + (f"/{total}" if total else ""))
        if cur.get("position"):
            situ.append(f"игрок P{cur['position']}")
        if cur.get("leader"):
            situ.append(f"лидер {cur['leader']}")
        if situ:
            lines.append("СИТУАЦИЯ: " + ", ".join(situ) + ".")

        # --- Фаза сессии (подсказка ИИ: адаптируй стиль и срочность к моменту) ---
        # Логика «финальных кругов» — ТОЛЬКО для гонки. В практике/квалификации
        # total_laps тоже приходит (напр. 20-круговая программа практики), но её
        # конец — НЕ финал гонки; иначе ИИ начинает кричать про «последний круг»
        # на свободных заездах. session_type=None в юнит-снимках → как гонка.
        st = cur.get("session_type")
        if st == "practice":
            lines.append("ФАЗА: практика — свободные заезды, не гонка"
                         + (f" (круг {lap})" if lap else "") + ".")
        elif st == "qualifying":
            lines.append("ФАЗА: квалификация — важен один быстрый круг, не дистанция"
                         + (f" (круг {lap})" if lap else "") + ".")
        elif lap and total and total > 0:
            ratio = lap / total
            if ratio <= 0.15:
                phase = "старт гонки"
            elif ratio <= 0.50:
                phase = "середина гонки"
            elif ratio <= 0.85:
                phase = "финальные круги"
            else:
                phase = "концовка, последние круги"
            lines.append(f"ФАЗА: {phase} ({lap}/{total}).")

        # Пит-стоп — отдельная строка, НЕ замена лап-based фазы выше (поздний
        # пит-стоп остаётся одновременно и "концовкой", и "пит-стопом").
        if cur.get("pit_status"):
            lines.append("ФАЗА: ПИТ-СТОП — трасса не в счёт, не считай это потерей темпа.")

        neigh: list[str] = []
        if cur.get("ahead"):
            neigh.append(f"впереди {cur['ahead']}")
        if cur.get("behind"):
            neigh.append(f"позади {cur['behind']}")
        if neigh:
            lines.append("СОСЕДИ: " + ", ".join(neigh) + ".")

        pace = _fmt_laptime(cur.get("last_lap_ms"))
        trend = self._pace_trend()
        if pace:
            lines.append(f"ТЕМП: круг {pace}" + (f", {trend}" if trend else "") + ".")

        # --- Отрывы по времени (подавляем во время пит-стопа — отрыв искусственно
        # растёт, пока машина стоит в боксах, это не потеря темпа на трассе) ---
        if not cur.get("pit_status"):
            pos = cur.get("position")
            gaps: list[str] = []
            gl = _fmt_gap(cur.get("gap_leader_ms"))
            if gl and pos and pos > 1:
                gaps.append(f"до лидера +{gl}")
            gf = _fmt_gap(cur.get("gap_front_ms"))
            if gf:
                ftrend = self._gap_front_trend()
                gaps.append(f"до машины впереди +{gf}" + (f" ({ftrend})" if ftrend else ""))
            gb = _fmt_gap(cur.get("gap_behind_ms"))
            if gb:
                gaps.append(f"сзади в {gb}")
            if gaps:
                lines.append("ОТРЫВЫ: " + ", ".join(gaps) + ".")

        # --- Шины ---
        tyre: list[str] = []
        if cur.get("tyre_compound") and cur["tyre_compound"] != "?":
            tyre.append(f"состав {cur['tyre_compound']}")
        if cur.get("tyre_age") is not None:
            tyre.append(f"возраст {cur['tyre_age']} кр.")
        if cur.get("tyre_wear") is not None:
            tyre.append(f"износ ~{cur['tyre_wear']:.0f}%")
        if tyre:
            lines.append("ШИНЫ: " + ", ".join(tyre) + ".")

        if cur.get("fuel") is not None:
            lines.append(f"ТОПЛИВО: {cur['fuel']} кг.")

        # --- Динамика ---
        traj = self._position_trajectory()
        if traj:
            lines.append(f"ДИНАМИКА ПОЗИЦИИ: {traj}.")

        # --- Лента событий ---
        # Ambient-режим (trigger=None) помечает событие как уже упомянутое и
        # больше не включает его повторно: иначе после флэшбека (когда
        # "свежие" сигналы race_ai сброшены, а таймлайн — нет) LLM на каждом
        # следующем ambient-тике заново цепляется за старую новость (напр.
        # RTMT — «кто выбыл») вместо того чтобы промолчать. Событийный режим
        # (trigger задан) не фильтруется — там есть конкретный новый триггер.
        if self._events:
            is_ambient = trigger is None
            candidates = [e for e in self._events
                         if not (is_ambient and e.get("ambient_mentioned"))]
            ev_lines = []
            for e in candidates[-8:]:
                who = e.get("driver") or ""
                tgt = f" → {e['target']}" if e.get("target") else ""
                lp = f" (круг {e['lap']})" if e.get("lap") else ""
                battle = " [борьба]" if e.get("battle") else ""
                ev_lines.append(f"{e.get('code')}: {who}{tgt}{battle}{lp}".strip())
                if is_ambient:
                    e["ambient_mentioned"] = True
            if ev_lines:
                lines.append("ПОСЛЕДНИЕ СОБЫТИЯ:\n- " + "\n- ".join(ev_lines))

        # --- Триггер ---
        if trigger is not None:
            who = trigger.get("driver") or ""
            tgt = f" → {trigger['target']}" if trigger.get("target") else ""
            lines.append(f"ТОЛЬКО ЧТО: {trigger.get('event_code')} {who}{tgt}".strip())

        # --- Склонение имён (шпаргалка для LLM: копируй формы, не угадывай) ---
        gloss = _name_glossary(
            self._context_names(cur, trigger, player_full_name))
        if gloss:
            lines.append(
                "СКЛОНЕНИЕ ИМЁН (бери фамилии ТОЛЬКО в этих формах):\n" + gloss
            )

        return "\n".join(lines)

    def _context_names(self, cur: dict, trigger: dict | None,
                       player_full_name: str | None = None) -> list[str]:
        """Имена пилотов, упомянутых в текущем контексте — для шпаргалки склонений."""
        names: list[str] = []
        # Игрок — первым. Раньше его фамилия попадала в шпаргалку только
        # случайно (если он оказывался соседом или участником события), и
        # склонять её модель была вынуждена наугад — при том что говорит она
        # про игрока чаще, чем про кого-либо ещё.
        if player_full_name:
            names.append(player_full_name)
        for key in ("leader", "ahead", "behind"):
            if cur.get(key):
                names.append(cur[key])
        for e in self._events:
            for key in ("driver", "target"):
                if e.get(key):
                    names.append(e[key])
        if trigger is not None:
            for key in ("driver", "target"):
                if trigger.get(key):
                    names.append(trigger[key])
        return names
