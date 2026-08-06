from analytics.context import build_qwen_context


def test_negative_gap_is_presented_as_non_normalized_time_difference():
    compare = {
        "source_coverage": {"player": "partial", "f1": "partial"},
        "player_best_lap_ms": 87_876,
        "player_best_lap_lap_number": 1,
        "f1_fastest_ms": 91_869,
        "f1_best_lap_driver": "NOR",
        "gap_ms": -3_993,
        "partial": True,
    }
    f1_meta = {
        "event": "Miami Grand Prix",
        "year": 2026,
        "results_top10": [{"driver": "ANT"}],
        "fastest_lap": {"lap": 35},
    }

    text = build_qwen_context(compare, f1_meta)

    assert "опережение" not in text.lower()
    assert "игровое время" in text.lower()
    assert "не сопоставим" in text.lower()
