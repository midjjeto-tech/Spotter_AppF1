"""Russian surname declension for spoken commentary (core/ru_names.py)."""
import pytest

from core.ru_names import decline, surname_of, glossary, first_name_of
from commentator.templates import render


def test_full_name_declines_to_surname_cases():
    # The user's example: "Ферстаппен обогнал Леклера"
    assert decline("Макс Ферстаппен", "nom") == "Ферстаппен"
    assert decline("Шарль Леклер", "acc") == "Леклера"
    assert decline("Шарль Леклер", "gen") == "Леклера"
    assert decline("Шарль Леклер", "dat") == "Леклеру"


def test_surname_input_also_declines():
    assert decline("Леклер", "acc") == "Леклера"
    assert decline("Расселл", "gen") == "Расселла"
    assert decline("Хэмилтон", "dat") == "Хэмилтону"


@pytest.mark.parametrize("name", ["Алонсо", "Гасли", "Пиастри", "Антонелли", "Бортолето"])
def test_indeclinable_surnames_unchanged(name):
    for case in ("nom", "gen", "dat", "acc", "ins"):
        assert decline(name, case) == name


def test_instrumental_case():
    # «за Албоном», «перед Ферстаппеном» — творительный падеж (был пропущен → "за албонам")
    assert decline("Албон", "ins") == "Албоном"
    assert decline("Макс Ферстаппен", "ins") == "Ферстаппеном"
    assert decline("Расселл", "ins") == "Расселлом"
    assert decline("Юки Цунода", "ins") == "Цунодой"
    assert decline("соперник", "ins") == "соперником"


def test_tsunoda_feminine_declension():
    assert decline("Юки Цунода", "acc") == "Цуноду"
    assert decline("Юки Цунода", "gen") == "Цуноды"


def test_every_grid_driver_has_declension_or_is_indeclinable():
    from core.f1_metadata import F1_2025_BY_NUMBER, F1_2026_BY_NUMBER
    indeclinable = {"Алонсо", "Гасли", "Пиастри", "Антонелли", "Бортолето", "Колапинто"}
    for full, _team in {**F1_2025_BY_NUMBER, **F1_2026_BY_NUMBER}.values():
        sn = surname_of(full)
        acc = decline(full, "acc")
        if sn in indeclinable:
            assert acc == sn
        else:
            assert acc != sn, f"{sn} should decline in accusative"


def test_generic_labels_decline():
    assert decline("соперник", "acc") == "соперника"
    assert decline("оппонент", "gen") == "оппонента"


def test_unknown_custom_name_falls_back_undeclined():
    assert decline("Кастомов", "acc") == "Кастомов"   # unknown → surname undeclined
    assert decline("", "acc") == ""


def test_first_name_of_real_full_name():
    """Имя игрока для радио-обращения ("Макс, ...") — см. commentator/personas.py, calm."""
    assert first_name_of("Макс Ферстаппен") == "Макс"
    assert first_name_of("Шарль Леклер") == "Шарль"


def test_first_name_of_placeholder_labels_returns_none():
    """Служебные метки (нет данных / кастомный пилот) — LLM не должна выдумывать имя."""
    for label in ("", None, "player", "—", "оппонент", "соперник", "гонщик", "пилот"):
        assert first_name_of(label) is None


def test_first_name_of_case_insensitive_placeholder():
    assert first_name_of("Player") is None
    assert first_name_of("ПИЛОТ") is None


def test_glossary_lists_all_cases_for_declinable():
    g = glossary(["Албон"])
    assert "Албоном" in g          # тв. — форма, которую LLM коверкал в «албонам»
    assert "Албона" in g           # род./вин.
    assert "Албону" in g           # дат.
    assert "тв." in g and "им." in g


def test_glossary_marks_indeclinable():
    g = glossary(["Пьер Гасли"])
    assert "не склоняется" in g


def test_glossary_dedups_and_skips_service_labels():
    g = glossary(["Макс Ферстаппен", "Ферстаппен", "player", "соперник", "", "#12"])
    assert g.count("Ферстаппен:") == 1     # полное имя и фамилия → одна запись
    assert "player" not in g
    assert "соперник" not in g             # служебная метка не нужна в шпаргалке


def test_glossary_empty_for_no_real_names():
    assert glossary([]) == ""
    assert glossary(["player", "", "#5"]) == ""


def test_render_produces_correct_case_in_sentence():
    """End-to-end: an OVTK event with full names reads grammatically."""
    evt = {"event_code": "OVTK", "driver": "Макс Ферстаппен", "target": "Шарль Леклер"}
    # Force the deterministic first template via repeated draws is flaky; instead
    # assert the declined object form appears and the nominative subject appears.
    results = {render(evt, persona="tv") for _ in range(30)}
    joined = " ".join(results)
    assert "Ферстаппен" in joined
    assert "Леклера" in joined  # accusative/genitive object form somewhere
    assert "{" not in joined
