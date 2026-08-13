"""RaceTimeline — скользящее окно памяти гонки для автономного ИИ-аналитика."""
from commentator.timeline import RaceTimeline


def test_empty_timeline_render():
    assert "не началась" in RaceTimeline().render().lower()


def test_render_includes_player_name_line_when_given():
    t = RaceTimeline()
    t.record_snapshot(lap=10, position=3, total_laps=58)
    out = t.render(player_name="Макс")
    assert "ПИЛОТ: Макс." in out


def test_render_omits_player_name_line_when_not_given():
    t = RaceTimeline()
    t.record_snapshot(lap=10, position=3, total_laps=58)
    out = t.render()
    assert "ПИЛОТ:" not in out


def test_snapshot_dedup_by_lap_and_neighbors():
    t = RaceTimeline()
    grid = [{"position": 2, "driver": "Норрис"},
            {"position": 3, "driver": "Хэмилтон"},
            {"position": 4, "driver": "Расселл"}]
    t.record_snapshot(lap=10, position=3, leader="Ферстаппен", grid=grid,
                      last_lap_ms=92000, fuel=40, total_laps=58)
    # тот же круг — обновляем, а не добавляем
    t.record_snapshot(lap=10, position=3, leader="Ферстаппен", grid=grid, last_lap_ms=91500)
    assert len(t._snapshots) == 1
    out = t.render()
    assert "круг 10/58" in out
    assert "P3" in out
    assert "впереди Норрис" in out and "позади Расселл" in out
    assert "лидер Ферстаппен" in out


def test_render_includes_name_declension_glossary():
    """Контекст для LLM содержит шпаргалку склонений (фикс коверканья имён)."""
    t = RaceTimeline()
    grid = [{"position": 2, "driver": "Алекс Албон"},
            {"position": 4, "driver": "Джордж Расселл"}]
    t.record_snapshot(lap=10, position=3, leader="Макс Ферстаппен", grid=grid,
                      total_laps=58)
    out = t.render()
    assert "СКЛОНЕНИЕ ИМЁН" in out
    assert "Албоном" in out      # творительный есть в шпаргалке → LLM не выдумает «албонам»


def test_pace_trend_and_position_trajectory():
    t = RaceTimeline()
    t.record_snapshot(lap=8, position=3, last_lap_ms=93000)
    t.record_snapshot(lap=9, position=4, last_lap_ms=92000)  # ускорился, потерял позицию
    out = t.render()
    assert "ускоряется" in out
    assert "P3→P4" in out


def test_events_and_trigger_in_render():
    t = RaceTimeline()
    t.record_snapshot(lap=5, position=3)
    t.record_event({"event_code": "OVTK", "driver": "Леклер",
                    "target": "Хэмилтон", "battle": True})
    out = t.render(trigger={"event_code": "PENA", "driver": "Расселл"})
    assert "OVTK" in out and "Леклер" in out and "Хэмилтон" in out
    assert "ТОЛЬКО ЧТО" in out and "PENA" in out and "Расселл" in out


def test_ambient_render_mentions_event_only_once():
    """Баг: после флэшбека (сбрасывает race_analyzer/situation_dedup, но не
    таймлайн) следующий ambient-тик LLM заново цепляется за старую новость
    (напр. RTMT — "кто выбыл") при каждом повторном тике. Фикс: ambient-режим
    (trigger=None) помечает событие как уже упомянутое и не включает его
    повторно."""
    t = RaceTimeline()
    t.record_snapshot(lap=5, position=3)
    t.record_event({"event_code": "RTMT", "driver": "Расселл"})

    first = t.render()  # ambient: trigger=None
    assert "RTMT" in first and "Расселл" in first

    second = t.render()  # тот же ambient-тик ещё раз — событие уже сказано
    assert "RTMT" not in second


def test_triggered_render_still_includes_previously_mentioned_event():
    """Событийный режим (trigger задан) не фильтруется ambient-меткой — там
    есть конкретный новый триггер, повторный контекст не проблема."""
    t = RaceTimeline()
    t.record_snapshot(lap=5, position=3)
    t.record_event({"event_code": "RTMT", "driver": "Расселл"})

    t.render()  # ambient-тик уже "озвучил" RTMT
    out = t.render(trigger={"event_code": "PENA", "driver": "Норрис"})
    assert "RTMT" in out and "Расселл" in out


def test_window_caps_snapshots():
    t = RaceTimeline(max_snapshots=3, max_events=3)
    for lap in range(1, 8):
        t.record_snapshot(lap=lap, position=lap)
    assert len(t._snapshots) == 3   # держим только последние 3 круга


# --------------------------------------------------------------------------- #
# Секция ОТРЫВЫ (gaps по времени)
# --------------------------------------------------------------------------- #

def test_render_gaps_section():
    t = RaceTimeline()
    t.record_snapshot(lap=12, position=3,
                      gap_leader_ms=15300, gap_front_ms=1800, gap_behind_ms=900)
    out = t.render()
    assert "ОТРЫВЫ:" in out
    assert "до лидера +15.3с" in out
    assert "до машины впереди +1.8с" in out
    assert "сзади в 0.9с" in out


def test_gap_leader_hidden_for_leader():
    """Лидеру (P1) строку «до лидера» не показываем, даже если поле не нулевое."""
    t = RaceTimeline()
    t.record_snapshot(lap=5, position=1, gap_leader_ms=5000)
    assert "до лидера" not in t.render()


def test_gap_front_trend_catching():
    t = RaceTimeline()
    t.record_snapshot(lap=10, position=4, gap_front_ms=2500)
    t.record_snapshot(lap=11, position=4, gap_front_ms=1800)  # сократился на 0.7с
    out = t.render()
    assert "ОТРЫВЫ:" in out
    assert "догоняет" in out


# --------------------------------------------------------------------------- #
# Секция ШИНЫ (компаунд / возраст / износ)
# --------------------------------------------------------------------------- #

def test_render_tyre_section():
    t = RaceTimeline()
    t.record_snapshot(lap=20, position=5,
                      tyre_compound="M", tyre_age=14, tyre_wear=37.0)
    out = t.render()
    assert "ШИНЫ:" in out
    assert "состав M" in out
    assert "возраст 14 кр." in out
    assert "износ ~37%" in out


def test_tyre_compound_unknown_hidden():
    """Неизвестный компаунд («?») не выводим, но возраст всё равно показываем."""
    t = RaceTimeline()
    t.record_snapshot(lap=3, position=8, tyre_compound="?", tyre_age=2)
    out = t.render()
    assert "состав" not in out
    assert "возраст 2 кр." in out


# --------------------------------------------------------------------------- #
# Секция ФАЗА (подсказка о стадии гонки)
# --------------------------------------------------------------------------- #

def test_phase_start():
    """Первые 15% дистанции → 'старт гонки'."""
    t = RaceTimeline()
    t.record_snapshot(lap=3, position=4, total_laps=58)
    assert "ФАЗА:" in t.render()
    assert "старт" in t.render()


def test_phase_middle():
    t = RaceTimeline()
    t.record_snapshot(lap=20, position=3, total_laps=58)
    assert "середина" in t.render()


def test_phase_final_laps():
    t = RaceTimeline()
    t.record_snapshot(lap=40, position=5, total_laps=58)
    assert "финальные" in t.render()


def test_phase_endgame():
    t = RaceTimeline()
    t.record_snapshot(lap=56, position=2, total_laps=58)
    assert "концовка" in t.render()


def test_phase_hidden_without_total_laps():
    """Без total_laps строку ФАЗА не рисуем — данных нет."""
    t = RaceTimeline()
    t.record_snapshot(lap=10, position=3)
    assert "ФАЗА:" not in t.render()


def test_practice_never_final_laps():
    """В практике total_laps приходит (напр. 20), но конец программы — НЕ финал
    гонки: ИИ не должен получать «финальные/последние круги»."""
    t = RaceTimeline()
    t.record_snapshot(lap=18, position=5, total_laps=20, session_type="practice")
    out = t.render()
    assert "практика" in out
    assert "финальные" not in out
    assert "последние круги" not in out


def test_qualifying_phase_label():
    t = RaceTimeline()
    t.record_snapshot(lap=3, position=5, total_laps=20, session_type="qualifying")
    out = t.render()
    assert "квалификация" in out
    assert "финальные" not in out


def test_race_phase_still_works_with_session_type():
    t = RaceTimeline()
    t.record_snapshot(lap=54, position=5, total_laps=58, session_type="race")  # 0.93 → концовка
    assert "концовка" in t.render()


# --------------------------------------------------------------------------- #
# Секция ПИТ-СТОП (pit_status live + pit_lap ретроспективно)
# --------------------------------------------------------------------------- #

def test_pace_trend_suppressed_when_last_lap_was_pit():
    t = RaceTimeline()
    t.record_snapshot(lap=8, position=3, last_lap_ms=93000)
    t.record_snapshot(lap=9, position=4, last_lap_ms=125000, pit_lap=True)
    out = t.render()
    assert "ТЕМП: круг 2:05" in out    # голое время всё же есть (125000мс = 2:05.000)
    assert "замедляется" not in out
    assert "рушится" not in out
    assert "ускоряется" not in out


def test_pace_trend_suppressed_when_prev_lap_was_pit():
    """Сравнение НЕ должно случиться и в обратную сторону — после пит-круга
    следующий обычный круг не должен показать ложное 'резкое ускорение'."""
    t = RaceTimeline()
    t.record_snapshot(lap=9, position=4, last_lap_ms=125000, pit_lap=True)
    t.record_snapshot(lap=10, position=3, last_lap_ms=91000, pit_lap=False)
    out = t.render()
    assert "ускоряется" not in out
    assert "замедляется" not in out


def test_pace_trend_normal_when_neither_lap_was_pit():
    t = RaceTimeline()
    t.record_snapshot(lap=8, position=3, last_lap_ms=93000, pit_lap=False)
    t.record_snapshot(lap=9, position=4, last_lap_ms=92000, pit_lap=False)
    out = t.render()
    assert "ускоряется" in out


def test_gaps_section_hidden_while_pit_status_active():
    t = RaceTimeline()
    t.record_snapshot(lap=12, position=3, pit_status=1,
                      gap_leader_ms=15300, gap_front_ms=1800, gap_behind_ms=900)
    out = t.render()
    assert "ОТРЫВЫ:" not in out


def test_gaps_section_shown_when_not_pitting():
    t = RaceTimeline()
    t.record_snapshot(lap=12, position=3, pit_status=0,
                      gap_leader_ms=15300, gap_front_ms=1800, gap_behind_ms=900)
    out = t.render()
    assert "ОТРЫВЫ:" in out


def test_pit_stop_phase_line_appears_when_pitting():
    t = RaceTimeline()
    t.record_snapshot(lap=12, position=3, total_laps=58, pit_status=1)
    out = t.render()
    assert "ФАЗА: ПИТ-СТОП" in out


def test_pit_stop_phase_line_absent_when_not_pitting():
    t = RaceTimeline()
    t.record_snapshot(lap=12, position=3, total_laps=58, pit_status=0)
    out = t.render()
    assert "ПИТ-СТОП" not in out


def test_pit_stop_phase_line_coexists_with_lap_ratio_phase():
    """Поздний пит-стоп — остаётся 'концовкой' И отдельно помечается пит-стопом."""
    t = RaceTimeline()
    t.record_snapshot(lap=56, position=2, total_laps=58, pit_status=2)
    out = t.render()
    assert "концовка" in out
    assert "ФАЗА: ПИТ-СТОП" in out


# --------------------------------------------------------------------------- #
# Личность игрока в контексте для LLM.
# Разбор живого заезда 2026-08-11: строка была «ПИЛОТ: Шарль.», рядом стояли
# «лидер Джордж Расселл» и события про «Леклера» — и модель весь заезд звала
# игрока Расселлом, вплоть до «Шарль Расселл борется за позицию».
# --------------------------------------------------------------------------- #

def _race_with_neighbours() -> RaceTimeline:
    t = RaceTimeline()
    t.record_snapshot(
        lap=12, position=5, total_laps=15, leader="Джордж Расселл",
        grid=[{"position": 1, "name": "Джордж Расселл"},
              {"position": 4, "name": "Оскар Пиастри"},
              {"position": 5, "name": "Шарль Леклер"},
              {"position": 6, "name": "Льюис Хэмилтон"}])
    t.record_event({"event_code": "OVTK", "driver": "Леклер", "target": "Пиастри"})
    return t


def test_player_line_links_first_name_to_surname():
    out = _race_with_neighbours().render(
        player_name="Шарль", player_full_name="Шарль Леклер")
    player_line = next(l for l in out.splitlines() if l.startswith("ПИЛОТ:"))
    assert "Шарль Леклер" in player_line
    assert "ИГРОК" in player_line
    assert "Леклер" in player_line     # под каким именем он в событиях
    assert "Шарль" in player_line      # как к нему обращаться


def test_player_surname_enters_declension_glossary():
    """Раньше фамилия игрока попадала в шпаргалку только случайно — если он
    оказывался соседом или участником события."""
    t = RaceTimeline()
    t.record_snapshot(lap=3, position=8, total_laps=15, leader="Джордж Расселл")
    out = t.render(player_name="Шарль", player_full_name="Шарль Леклер")
    gloss = out.split("СКЛОНЕНИЕ ИМЁН")[1]
    assert "Леклера" in gloss          # родительный падеж — значит имя разобрано
    assert gloss.strip().startswith("(бери фамилии ТОЛЬКО в этих формах):\nЛеклер")


def test_player_line_falls_back_for_single_word_name():
    """Кастомный пилот без фамилии — придумывать за игру нечего."""
    t = RaceTimeline()
    t.record_snapshot(lap=3, position=8, total_laps=15)
    out = t.render(player_name="Артём", player_full_name="Артём")
    assert "ПИЛОТ: Артём." in out
