"""Driver-name resolution: Russian-by-number priority + garble rejection.

Root cause of the "Рэйм" bug: UDP participant packets and Ergast give LATIN
names ("Verstappen"), which Russian Yandex TTS mispronounces into garble. The
curated Russian dict (F1_2025_BY_NUMBER) must win by race number for the real
2025 grid; custom/unknown drivers keep their UDP name.
"""
from core.f1_metadata import F1Metadata
from core.packets import _looks_like_name, _decode_name


class _OfflineClient:
    """Stand-in JolpicaClient that never touches the network (deterministic tests)."""
    def get_json(self, path):
        return None


def _meta_no_ergast() -> F1Metadata:
    m = F1Metadata(client=_OfflineClient())
    m._loaded = False   # force static-only path, deterministic offline
    return m


def test_russian_name_wins_over_latin_for_known_number():
    m = _meta_no_ergast()
    out = m.enrich_drivers({0: {"name": "Verstappen", "team": "Red Bull Racing", "number": 1}})
    assert out[0]["name"] == "Макс Ферстаппен"


def test_russian_name_wins_for_every_grid_number():
    m = _meta_no_ergast()
    out = m.enrich_drivers({
        0: {"name": "Norris", "team": "McLaren", "number": 4},
        1: {"name": "Leclerc", "team": "Ferrari", "number": 16},
        2: {"name": "Hamilton", "team": "Ferrari", "number": 44},
    })
    assert out[0]["name"] == "Ландо Норрис"
    assert out[1]["name"] == "Шарль Леклер"
    assert out[2]["name"] == "Льюис Хэмилтон"


def test_custom_driver_keeps_udp_name_for_unknown_number():
    m = _meta_no_ergast()
    out = m.enrich_drivers({0: {"name": "Кастомный Гонщик", "team": "X", "number": 99}})
    assert out[0]["name"] == "Кастомный Гонщик"


def test_team_preserved_from_participant_for_known_number():
    m = _meta_no_ergast()
    out = m.enrich_drivers({0: {"name": "Verstappen", "team": "Red Bull Racing", "number": 1}})
    assert out[0]["team"] == "Red Bull Racing"


# --- 2026 season: car numbers get reused (Verstappen 1->3, Norris ->1) ---

def test_2026_number_1_resolves_to_norris_not_verstappen():
    m = _meta_no_ergast()
    m.game_year = 2026
    out = m.enrich_drivers({0: {"name": "Norris", "team": "McLaren", "number": 1}})
    assert out[0]["name"] == "Ландо Норрис"


def test_2026_number_3_resolves_to_verstappen():
    m = _meta_no_ergast()
    m.game_year = 2026
    out = m.enrich_drivers({0: {"name": "Verstappen", "team": "Red Bull Racing", "number": 3}})
    assert out[0]["name"] == "Макс Ферстаппен"


def test_default_game_year_still_resolves_2025_grid():
    # game_year не проставлен (0) — поведение НЕ должно измениться (regression guard).
    m = _meta_no_ergast()
    out = m.enrich_drivers({0: {"name": "Verstappen", "team": "Red Bull Racing", "number": 1}})
    assert out[0]["name"] == "Макс Ферстаппен"


# --- name sanity (_looks_like_name / _decode_name) ---

def test_looks_like_name_accepts_real_names():
    assert _looks_like_name("Verstappen")
    assert _looks_like_name("Ферстаппен")
    assert _looks_like_name("Pérez")


def test_looks_like_name_rejects_garbage():
    assert not _looks_like_name("")
    assert not _looks_like_name("X")
    assert not _looks_like_name("\x01\x02\x03")
    assert not _looks_like_name("###@@@")


def test_decode_name_rejects_control_bytes():
    assert _decode_name(b"\x01\x02\x03\x00padding") == ""


def test_decode_name_keeps_valid_latin():
    assert _decode_name(b"Verstappen\x00\x00") == "Verstappen"


# --- transliteration fallback (Jolpica-resolved Latin name outside static dicts) ---

def test_jolpica_latin_name_outside_static_dict_gets_transliterated():
    """Number 99 is not in F1_2025_BY_NUMBER/F1_2026_BY_NUMBER. Simulate
    Jolpica resolving it to a Latin name that isn't in either static dict —
    the transliteration fallback should kick in rather than passing raw
    Latin through to TTS."""
    m = _meta_no_ergast()
    m._loaded = True
    m._by_number[99] = {"name": "Bearman", "code": "BEA", "number": 99,
                        "team": "Haas", "nationality": "British"}
    out = m.enrich_drivers({0: {"name": "Bearman", "team": "Haas", "number": 99}})
    assert out[0]["name"] == "Бирман"


def test_custom_driver_keeps_udp_name_for_unknown_number_still_works():
    """Regression: the new transliteration fallback must NOT affect drivers
    who never resolved through Jolpica at all (enrich_driver's result stays
    empty, so the caller keeps the original UDP name unchanged) — this test
    already existed before this plan; re-asserting it here as an explicit
    regression guard for this specific change."""
    m = _meta_no_ergast()
    out = m.enrich_drivers({0: {"name": "Кастомный Гонщик", "team": "X", "number": 99}})
    assert out[0]["name"] == "Кастомный Гонщик"


# --- KNOWN_SURNAMES whitelist fallback (Perez/Lindblad — raw UDP name, no
# Jolpica/static match at all): "PEREZ"/"LINDLAND"(typo of Lindblad) bug ---

def test_known_real_driver_raw_udp_name_gets_fixed_even_without_jolpica():
    """Perez (Cadillac #11) and Lindblad (Racing Bulls #41, rookie) are only
    in F1_2026_BY_NUMBER, not F1_2025_BY_NUMBER — and a rookie may be absent
    from Jolpica's driverStandings entirely (only scoring drivers listed).
    Without the whitelist, raw UDP name ("PEREZ", all-caps) went straight to
    TTS untouched."""
    m = _meta_no_ergast()
    out = m.enrich_drivers({0: {"name": "PEREZ", "team": "Cadillac", "number": 11}})
    assert out[0]["name"] == "Перес"


def test_jolpica_accented_perez_name_gets_fixed():
    """Jolpica spells Perez as ``Pérez``. The accent must not bypass the
    curated Russian full name and leak Latin text into SpeechKit."""
    m = _meta_no_ergast()
    m._loaded = True
    m._by_number[99] = {
        "name": "Sergio Pérez",
        "code": "PER",
        "number": 99,
        "team": "Cadillac",
        "nationality": "Mexican",
    }

    out = m.enrich_drivers({
        0: {"name": "Pérez", "team": "Cadillac", "number": 99},
    })

    assert out[0]["name"] == "Серхио Перес"


def test_known_real_driver_raw_udp_name_lindblad():
    m = _meta_no_ergast()
    out = m.enrich_drivers({0: {"name": "LINDBLAD", "team": "Racing Bulls", "number": 41}})
    assert out[0]["name"] == "Линдблад"


def test_known_real_driver_wins_over_generic_transliteration():
    """Verstappen under a car number outside both static dicts (e.g. UDP
    reports a number our roster doesn't cover for this game_year) must still
    resolve to "Ферстаппен" via the whitelist, not the documented-wrong
    "Верстаппен" the generic algorithm alone would produce."""
    m = _meta_no_ergast()
    out = m.enrich_drivers({0: {"name": "VERSTAPPEN", "team": "Red Bull Racing", "number": 199}})
    assert out[0]["name"] == "Ферстаппен"
