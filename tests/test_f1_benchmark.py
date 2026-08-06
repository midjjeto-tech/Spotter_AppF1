from core.f1_benchmark import F1Benchmark


class _Client:
    def __init__(self, fl=None, pole=None):
        self._fl, self._pole = fl, pole
        self.fl_calls, self.pole_calls = [], []

    def get_circuit_fastest_lap(self, year, circuit):
        self.fl_calls.append((year, circuit))
        return self._fl

    def get_circuit_pole(self, year, circuit):
        self.pole_calls.append((year, circuit))
        return self._pole


_UNSET = object()   # отличаем «sectors не передан» (→ дефолт) от явного sectors=None (→ None)


class _OpenF1:
    def __init__(self, session_key=9161, sectors=_UNSET, blocked_by_live_session=False):
        self._session_key = session_key
        self._sectors = {1: 27000, 2: 38000, 3: 26000} if sectors is _UNSET else sectors
        self.blocked_by_live_session = blocked_by_live_session
        self.session_calls, self.sector_calls = [], []

    def get_session_key(self, year, circuit):
        self.session_calls.append((year, circuit))
        return self._session_key

    def get_best_sectors(self, session_key):
        self.sector_calls.append(session_key)
        return self._sectors


def test_load_reference_from_fastest_lap_maps_latin_to_ru():
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1())
    assert b.load(11, 2025) is True               # Monza
    assert b.ready
    assert b.reference["driver"] == "Ферстаппен"  # латиница → кириллица
    assert b.reference["source"] == "fastest_lap"
    assert b.reference["event"] == "Italian Grand Prix"


def test_load_falls_back_to_pole_after_trying_both_years():
    c = _Client(fl=None, pole={"driver": "Leclerc", "time_ms": 79800})
    b = F1Benchmark(client=c, openf1_client=_OpenF1())
    assert b.load(11, 2025) is True
    assert b.reference["source"] == "pole"
    assert b.reference["driver"] == "Леклер"
    assert c.fl_calls == [(2025, "monza"), (2024, "monza")]   # fastest пробован за оба года


def test_load_unknown_track_returns_false():
    b = F1Benchmark(client=_Client(fl={"driver": "X", "time_ms": 1}), openf1_client=_OpenF1())
    assert b.load(999, 2025) is False
    assert not b.ready


# --- Regulation era boundary: 2026 (new regs) must never fall back to 2025 (old regs) ---

def test_load_2026_never_falls_back_to_2025_different_era():
    c = _Client(fl=None, pole={"driver": "Leclerc", "time_ms": 79800})
    b = F1Benchmark(client=c, openf1_client=_OpenF1())
    b.load(11, 2026)   # Monza; no fastest-lap data yet for the new season
    assert c.fl_calls == [(2026, "monza")]     # NOT [(2026, ...), (2025, ...)]
    assert c.pole_calls == [(2026, "monza")]


def test_load_2025_still_falls_back_to_2024_same_era():
    c = _Client(fl=None, pole={"driver": "Leclerc", "time_ms": 79800})
    b = F1Benchmark(client=c, openf1_client=_OpenF1())
    b.load(11, 2025)
    assert c.fl_calls == [(2025, "monza"), (2024, "monza")]


def test_load_fetches_sectors_after_finding_reference():
    """load() дополнительно тянет OpenF1-секторы после нахождения эталона."""
    openf1 = _OpenF1(session_key=9161, sectors={1: 27000, 2: 38000, 3: 26000})
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=openf1)
    b.load(11, 2025)
    assert b.reference["sector_ms"] == {1: 27000, 2: 38000, 3: 26000}
    assert openf1.session_calls == [(2025, "monza")]
    assert openf1.sector_calls == [9161]


def test_load_sectors_none_does_not_fail_load(monkeypatch):
    """OpenF1 не находит данные -> sector_ms=None, но load() всё равно True
    (полный-круга-эталон не зависит от OpenF1). monza (track_id=11) теперь ЕСТЬ
    в SECTOR_SEED (наполнен 2026-07-08) — тест про случай "совсем нет данных"
    временно убирает его сидовую запись, чтобы проверять именно это."""
    import core.f1_benchmark as f1b_mod
    monkeypatch.delitem(f1b_mod.SECTOR_SEED, "monza", raising=False)
    openf1 = _OpenF1(session_key=None, sectors=None)
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=openf1)
    assert b.load(11, 2025) is True
    assert b.reference["sector_ms"] is None


def test_compare_computes_gap():
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1())
    b.load(11, 2025)
    cmp = b.compare([{"lap": 5, "last_lap_ms": 81346}, {"lap": 6, "last_lap_ms": 0}])
    assert cmp["gap_ms"] == 1500
    assert cmp["player_best_ms"] == 81346
    assert cmp["f1_driver"] == "Ферстаппен"


def test_compare_none_when_not_ready_or_no_laps():
    b = F1Benchmark(client=_Client(fl={"driver": "X", "time_ms": 1}), openf1_client=_OpenF1())
    assert b.compare([{"last_lap_ms": 1000}]) is None      # не загружен
    b.load(11, 2025)
    assert b.compare([]) is None
    assert b.compare([{"last_lap_ms": 0}]) is None


def test_compare_always_has_sectors_key():
    """compare() ВСЕГДА возвращает ключ "sectors" (словарь либо None) — контракт
    для HUD/Voice/Story, без hasattr-проверок у потребителей."""
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1(sectors=None))
    b.load(11, 2025)
    cmp = b.compare([{"lap": 5, "last_lap_ms": 81346}])
    assert "sectors" in cmp
    assert cmp["sectors"] is None


def test_compare_always_has_sectors_source_and_blocked_keys():
    """Тот же контракт «всегда присутствует», что у "sectors" — для UI (race.tsx),
    которому нужно отличить «идёт live-сессия F1» от «просто нет данных»."""
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1(sectors={1: 27000, 2: 38000, 3: 26000}))
    b.load(11, 2025)
    cmp = b.compare([{"lap": 5, "last_lap_ms": 81346}])
    assert cmp["sectors_source"] == "api"
    assert cmp["sectors_blocked"] is False


def test_compare_reports_blocked_by_live_session(monkeypatch):
    """monza (track_id=11) теперь есть в SECTOR_SEED — убираем на время теста,
    чтобы проверить путь "заблокировано и нет сида", а не "заблокировано, но
    сид спас"."""
    import core.f1_benchmark as f1b_mod
    monkeypatch.delitem(f1b_mod.SECTOR_SEED, "monza", raising=False)
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1(sectors=None, blocked_by_live_session=True))
    b.load(11, 2025)
    cmp = b.compare([{"lap": 5, "last_lap_ms": 81346}])
    assert cmp["sectors"] is None
    assert cmp["sectors_source"] is None
    assert cmp["sectors_blocked"] is True


def test_compare_falls_back_to_seed_when_no_live_or_cached_sectors(monkeypatch):
    """Холодный старт: ни живых, ни кэшированных секторов нет, но для трассы есть
    статический сид (core/openf1_seed.py) — используем его, помечаем источник."""
    import core.f1_benchmark as f1b_mod
    monkeypatch.setitem(f1b_mod.SECTOR_SEED, "monza",
                        {"year": 2024, "event": "Italian Grand Prix",
                         "sectors": {1: 26500, 2: 38657, 3: 25900}})
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1(sectors=None))
    b.load(11, 2025)   # 11 -> "monza" (см. TRACK_ID_TO_CIRCUIT)
    cmp = b.compare([{"lap": 5, "last_lap_ms": 81346,
                      "s1_ms": 26900, "s2_ms": 39000, "s3_ms": 26200}])
    assert cmp["sectors_source"] == "seed"
    assert cmp["sectors"] is not None
    assert cmp["sectors"][1]["gap_ms"] == 26900 - 26500


def test_compare_no_seed_and_no_live_data_leaves_sectors_none(monkeypatch):
    """monza (track_id=11) наполнен в SECTOR_SEED 2026-07-08 — убираем на время
    теста, чтобы проверить именно случай "совсем нет данных", как и раньше."""
    import core.f1_benchmark as f1b_mod
    monkeypatch.delitem(f1b_mod.SECTOR_SEED, "monza", raising=False)
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1(sectors=None))
    b.load(11, 2025)   # monza — временно без сида (см. monkeypatch выше)
    cmp = b.compare([{"lap": 5, "last_lap_ms": 81346}])
    assert cmp["sectors"] is None
    assert cmp["sectors_source"] is None


def test_compare_sectors_gap_uses_player_best_lap():
    """Секторный гэп берётся из ТОГО ЖЕ круга, что дал player_best_ms."""
    openf1 = _OpenF1(sectors={1: 27000, 2: 38000, 3: 26000})
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=openf1)
    b.load(11, 2025)
    cmp = b.compare([
        {"lap": 5, "last_lap_ms": 81346, "s1_ms": 27200, "s2_ms": 37800, "s3_ms": 26346},
        {"lap": 6, "last_lap_ms": 90000, "s1_ms": 30000, "s2_ms": 40000, "s3_ms": 20000},
    ])
    assert cmp["player_best_lap"] == 5
    assert cmp["sectors"] == {
        1: {"player_ms": 27200, "gap_ms": 200},
        2: {"player_ms": 37800, "gap_ms": -200},
        3: {"player_ms": 26346, "gap_ms": 346},
    }


def test_compare_sectors_none_when_best_lap_missing_sector_data():
    """Лучший круг без валидных s1/s2/s3 (например, из телеметрии с 0) -> sectors=None,
    полный-круга-гэп при этом считается как обычно."""
    openf1 = _OpenF1(sectors={1: 27000, 2: 38000, 3: 26000})
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=openf1)
    b.load(11, 2025)
    cmp = b.compare([{"lap": 5, "last_lap_ms": 81346, "s1_ms": 0, "s2_ms": 0, "s3_ms": 0}])
    assert cmp["gap_ms"] == 1500
    assert cmp["sectors"] is None


def test_lines_use_genitive_and_source_word():
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1())
    b.load(11, 2025)
    cmp = b.compare([{"lap": 5, "last_lap_ms": 81346}])
    assert "Ферстаппена" in b.context_line(cmp) and "быстрейший круг" in b.context_line(cmp)
    assert "Ферстаппена" in b.pb_line(cmp) and "рекорд" in b.pb_line(cmp).lower()


def test_pb_line_describes_time_difference_without_claiming_driver_is_faster():
    """Game and real GP conditions are not normalized, so a negative gap may
    describe only the recorded times, never the user's skill versus a driver."""
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1())
    b.load(11, 2025)
    slower = b.compare([{"lap": 5, "last_lap_ms": 81346}])
    assert "игровое время" in b.pb_line(slower).lower()
    faster = b.compare([{"lap": 5, "last_lap_ms": 79000}])
    line = b.pb_line(faster)
    assert "ты быстрее" not in line.lower()
    assert "игровое время" in line.lower()
    assert "условия" in line.lower()


def test_pb_line_genitive_pole_wording():
    b = F1Benchmark(client=_Client(fl=None, pole={"driver": "Leclerc", "time_ms": 79800}),
                    openf1_client=_OpenF1())
    b.load(11, 2025)
    cmp = b.compare([{"lap": 3, "last_lap_ms": 80000}])
    assert "Ориентир — поул Леклера" in b.pb_line(cmp)


def test_pb_line_avoids_third_person_when_player_is_the_reference_driver():
    """Если игрок в игре управляет машиной того же пилота, что и реальный
    эталон (например, выбрал Ферстаппена), нельзя говорить "ты быстрее
    Ферстаппена на 0.3" — это звучит как обращение к другому человеку, хотя
    игрок и есть Ферстаппен."""
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1())
    b.load(11, 2025)
    faster = b.compare([{"lap": 5, "last_lap_ms": 79000}])
    line = b.pb_line(faster, player_name="Макс Ферстаппен")
    assert "Ферстаппена" not in line
    assert "твой же" in line

    slower = b.compare([{"lap": 5, "last_lap_ms": 81346}])
    line2 = b.pb_line(slower, player_name="Макс Ферстаппен")
    assert "Ферстаппена" not in line2
    assert "твой же" in line2


def test_pb_line_still_names_driver_when_player_is_someone_else():
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1())
    b.load(11, 2025)
    cmp = b.compare([{"lap": 5, "last_lap_ms": 81346}])
    line = b.pb_line(cmp, player_name="Льюис Хэмилтон")
    assert "Ферстаппена" in line


def test_context_line_avoids_third_person_when_player_is_the_reference_driver():
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1())
    b.load(11, 2025)
    cmp = b.compare([{"lap": 5, "last_lap_ms": 81346}])
    line = b.context_line(cmp, player_name="Макс Ферстаппен")
    assert "Ферстаппена" not in line
    assert "твой же" in line


def test_pole_source_changes_wording():
    b = F1Benchmark(client=_Client(fl=None, pole={"driver": "Leclerc", "time_ms": 79800}),
                    openf1_client=_OpenF1())
    b.load(11, 2025)
    cmp = b.compare([{"lap": 3, "last_lap_ms": 80000}])
    assert "поул" in b.context_line(cmp)


def test_reset_clears():
    b = F1Benchmark(client=_Client(fl={"driver": "X", "time_ms": 1}), openf1_client=_OpenF1())
    b.load(11, 2025)
    b.reset()
    assert not b.ready


def test_sector_pb_line_faster_than_reference():
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1())
    b.load(11, 2025)
    line = b.sector_pb_line(2, {"player_ms": 37800, "gap_ms": -200})
    assert "Сектор 2" in line
    assert "ты быстрее" not in line.lower()
    assert "игровое время" in line.lower()


def test_sector_pb_line_slower_than_reference():
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1())
    b.load(11, 2025)
    line = b.sector_pb_line(1, {"player_ms": 27200, "gap_ms": 200})
    assert "Сектор 1" in line and "игровое время" in line.lower()


def test_race_weak_sector_picks_largest_average_gap():
    openf1 = _OpenF1(sectors={1: 27000, 2: 38000, 3: 26000})
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=openf1)
    b.load(11, 2025)
    laps = [
        {"s1_ms": 27100, "s2_ms": 39500, "s3_ms": 26050},   # s2 гэп +1500
        {"s1_ms": 27050, "s2_ms": 39000, "s3_ms": 26100},   # s2 гэп +1000
    ]
    assert b.race_weak_sector(laps) == 2


def test_race_weak_sector_ignores_pit_laps():
    """Пит-круг с огромным (искажённым) гэпом не должен ложно назначить сектор
    слабым — он исключается из усреднения целиком."""
    openf1 = _OpenF1(sectors={1: 27000, 2: 38000, 3: 26000})
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=openf1)
    b.load(11, 2025)
    laps = [
        {"s1_ms": 27100, "s2_ms": 38100, "s3_ms": 26050},                  # обычный круг, s1 гэп +100 (наибольший из "чистых")
        {"s1_ms": 27050, "s2_ms": 38900, "s3_ms": 91000, "pit_lap": True}, # пит-круг: искажённый s3, огромный гэп
    ]
    # Без исключения пит-круга s3 дал бы гэп +65000 и "выиграл" бы как самый слабый —
    # с исключением побеждает s1 (+100 среди оставшегося одного чистого круга).
    assert b.race_weak_sector(laps) == 1


def test_race_weak_sector_none_without_reference_sectors(monkeypatch):
    """monza (track_id=11) теперь есть в SECTOR_SEED — убираем на время теста,
    чтобы проверить путь "нет секторного эталона вообще"."""
    import core.f1_benchmark as f1b_mod
    monkeypatch.delitem(f1b_mod.SECTOR_SEED, "monza", raising=False)
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1(sectors=None))
    b.load(11, 2025)
    assert b.race_weak_sector([{"s1_ms": 27000, "s2_ms": 38000, "s3_ms": 26000}]) is None


def test_race_weak_sector_none_without_valid_laps():
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=_OpenF1())
    b.load(11, 2025)
    assert b.race_weak_sector([{"s1_ms": 0, "s2_ms": 0, "s3_ms": 0}]) is None


def test_race_weak_sector_ties_resolve_to_lowest_number():
    """При равенстве средних гэпов между секторами -> наименьший номер сектора."""
    openf1 = _OpenF1(sectors={1: 27000, 2: 38000, 3: 26000})
    b = F1Benchmark(client=_Client(fl={"driver": "Verstappen", "time_ms": 79846}),
                    openf1_client=openf1)
    b.load(11, 2025)
    laps = [
        {"s1_ms": 28000, "s2_ms": 39000, "s3_ms": 26000},   # s1 гэп +1000, s2 гэп +1000, s3 гэп 0
    ]
    assert b.race_weak_sector(laps) == 1   # s1 и s2 равны (+1000) -> наименьший номер (1)


def test_ru_driver_transliterates_names_outside_latin_to_ru_dict():
    from core.f1_benchmark import _ru_driver
    # "Magnussen" is genuinely NOT a key in _LATIN_TO_RU (confirmed: the dict
    # has 24 curated entries, this isn't one of them) — this proves the
    # fallback actually executes, unlike "Bearman", which IS in the dict and
    # would pass this assertion even with the fallback deleted entirely.
    assert _ru_driver("Magnussen") == "Магнуссен"


def test_ru_driver_still_prefers_curated_dict_entry():
    from core.f1_benchmark import _ru_driver
    # "Verstappen" IS a key in _LATIN_TO_RU ("Ферстаппен") — the curated
    # dict must still win over the transliteration fallback, since the
    # algorithm alone would produce "Верстаппен" (see
    # tests/test_transliterate.py::test_verstappen_mismatches_static_dict_this_is_expected).
    assert _ru_driver("Verstappen") == "Ферстаппен"


def test_ru_driver_handles_none_and_empty():
    from core.f1_benchmark import _ru_driver
    assert _ru_driver(None) == ""
    assert _ru_driver("") == ""
