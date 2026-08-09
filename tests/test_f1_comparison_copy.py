from analytics.context import build_qwen_context


def test_negative_gap_is_presented_as_a_recorded_time_difference():
    """Гэп обязан читаться как записанная разница времён, а не как приговор.

    Формулировки переписаны 2026-08-08 вместе со сменой источника эталона:
    сравнение с РЕАЛЬНЫМ Гран-при удалено (Jolpica/OpenF1 несовместимы с
    продаваемой сборкой, см. NOTICE), осталось сравнение внутри игры. Поэтому
    ушло «игровое время» против реального и оговорка «не сопоставимы»: физика и
    регламент теперь одни и те же, расходятся только условия заезда.

    Что НЕ изменилось и проверяется здесь же — запрет на «опережение»: меньшее
    время не делает пилота лучше, и текст не должен это утверждать."""
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
    assert "твоё время" in text.lower()
    assert "условия заездов различаются" in text.lower()
