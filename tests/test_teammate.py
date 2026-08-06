"""Напарник по команде — вторая машина той же команды.

Идея подсмотрена у companion-приложений для F1 25 с Overtake.gg (в частности
head-to-head с напарником в «The Seat»): это единственный соперник на заведомо
равной технике, и в реальной Формуле-1 именно он служит точкой отсчёта. До
этого Spotter сравнивал только с соседями по позиции и с эталоном реальной F1.
"""
import pytest

from core.strategy_ai import teammate as tm


def _grid(*rows):
    return [{"vehicle_idx": idx, "team": team, "position": pos}
            for idx, team, pos in rows]


# ── Поиск напарника ───────────────────────────────────────────────────────────

def test_finds_the_other_car_of_the_same_team():
    grid = _grid((0, "McLaren", 1), (5, "Ferrari", 2), (7, "McLaren", 3))
    assert tm.find_teammate_idx(grid, 0) == 7
    assert tm.find_teammate_idx(grid, 7) == 0


def test_no_teammate_when_team_is_unique_on_grid():
    grid = _grid((0, "McLaren", 1), (5, "Ferrari", 2))
    assert tm.find_teammate_idx(grid, 0) is None


def test_empty_team_never_matches():
    """Иначе на гриде без метаданных «напарниками» стали бы все сразу."""
    grid = _grid((0, "", 1), (5, "", 2), (7, "", 3))
    assert tm.find_teammate_idx(grid, 0) is None


def test_whitespace_team_is_treated_as_empty():
    grid = _grid((0, "  ", 1), (5, "  ", 2))
    assert tm.find_teammate_idx(grid, 0) is None


def test_player_not_on_grid_yet():
    grid = _grid((5, "Ferrari", 1))
    assert tm.find_teammate_idx(grid, 0) is None
    assert tm.find_teammate_idx([], 0) is None


def test_unknown_player_index_is_safe():
    assert tm.find_teammate_idx(_grid((0, "McLaren", 1)), None) is None


def test_pick_is_stable_by_vehicle_idx_not_position():
    """Результат не должен прыгать между машинами при смене позиций."""
    grid = _grid((3, "Alpine", 9), (0, "Alpine", 4), (11, "Alpine", 1))
    assert tm.find_teammate_idx(grid, 0) == 3
    for row in grid:                       # позиции переставились
        row["position"] = 22 - row["position"]
    assert tm.find_teammate_idx(grid, 0) == 3


# ── Текст отчёта ──────────────────────────────────────────────────────────────

def test_report_says_how_many_positions_and_which_side():
    out = tm.build_report(mate_name="Норрис", player_pos=3, mate_pos=5)
    assert "P5" in out and "на 2 позиции позади тебя" in out


def test_report_singular_position_agreement():
    out = tm.build_report(mate_name="Норрис", player_pos=4, mate_pos=3)
    assert "на 1 позицию впереди тебя" in out


def test_report_many_positions_agreement():
    out = tm.build_report(mate_name="Норрис", player_pos=2, mate_pos=13)
    assert "на 11 позиций позади тебя" in out


def test_pace_comparison_names_the_faster_driver():
    faster = tm.build_report(mate_name="Норрис", player_pos=3, mate_pos=5,
                             player_best_ms=80100, mate_best_ms=80600)
    assert "ты быстрее на 0.5" in faster
    slower = tm.build_report(mate_name="Норрис", player_pos=5, mate_pos=3,
                             player_best_ms=80600, mate_best_ms=80100)
    assert "он быстрее на 0.5" in slower


def test_pace_within_noise_is_called_level_not_faster():
    out = tm.build_report(mate_name="Норрис", player_pos=3, mate_pos=5,
                          player_best_ms=80100, mate_best_ms=80150)
    assert "вровень" in out
    assert "быстрее" not in out


@pytest.mark.parametrize("compound, expected", [
    ("S", "Он на софте"),
    ("M", "Он на медиуме"),
    ("H", "Он на харде"),
    ("I", "Он на интермедиэйте"),
    ("W", "Он на дождевых"),
])
def test_compound_is_in_the_prepositional_case(compound, expected):
    """Первая версия склеивала форму по окончанию и выдавала «он на медиум»
    и «он на дождевую» — падеж хранится в словаре готовым."""
    out = tm.build_report(mate_name="Норрис", mate_pos=5, mate_compound=compound)
    assert expected in out


def test_tyre_age_agreement():
    one = tm.build_report(mate_name="Норрис", mate_pos=5, mate_compound="M",
                          mate_tyre_age=1)
    assert "1 круг." in one
    few = tm.build_report(mate_name="Норрис", mate_pos=5, mate_compound="M",
                          mate_tyre_age=23)
    assert "23 круга." in few
    many = tm.build_report(mate_name="Норрис", mate_pos=5, mate_compound="M",
                           mate_tyre_age=12)
    assert "12 кругов." in many


def test_unknown_compound_code_is_skipped_not_guessed():
    out = tm.build_report(mate_name="Норрис", mate_pos=5, mate_compound="?")
    assert "Он на" not in out


def test_missing_pieces_are_silently_omitted():
    out = tm.build_report(mate_name="Норрис", player_pos=3, mate_pos=5)
    assert "быстрее" not in out and "Он на" not in out
    assert out.endswith("позади тебя.")


def test_nothing_known_still_returns_usable_sentence():
    out = tm.build_report(mate_name="Норрис")
    assert "Норрис" in out and out.endswith(".")


def test_same_position_does_not_claim_a_gap():
    """Позиции ещё не разъехались (обе машины считаются на одной) — не врём."""
    out = tm.build_report(mate_name="Норрис", player_pos=5, mate_pos=5)
    assert "позади" not in out and "впереди" not in out


# ── Итог дуэли для послегоночной истории ──────────────────────────────────────

def test_race_result_beat_and_lost():
    assert tm.race_result(2, 7).startswith("обыграл напарника")
    assert tm.race_result(9, 4).startswith("проиграл напарнику")


def test_race_result_needs_both_positions():
    assert tm.race_result(None, 4) is None
    assert tm.race_result(4, None) is None
    assert tm.race_result(0, 4) is None


# ── Проводка: Voice Q&A ───────────────────────────────────────────────────────

def test_teammate_topic_recognised():
    from commentator.radio_answer import classify_topic
    for question in ("как там напарник", "что у напарника", "где тиммейт",
                     "как едет партнёр", "что делает второй пилот"):
        assert classify_topic(question) == "teammate", question


def test_teammate_wins_over_generic_data_words():
    """«какая позиция у напарника» не должно отвечать позицией ИГРОКА —
    поэтому тема стоит первой в словаре стемов."""
    from commentator.radio_answer import classify_topic
    assert classify_topic("какая позиция у напарника") == "teammate"
    assert classify_topic("на каких шинах напарник") == "teammate"
    assert classify_topic("какой отрыв до напарника") == "teammate"


def test_team_strategy_question_is_not_a_teammate_question():
    """Стем «команд» намеренно не взят — иначе сюда падали бы вопросы про
    стратегию команды вообще."""
    from commentator.radio_answer import classify_topic
    assert classify_topic("какая стратегия у команды") != "teammate"


def test_answer_uses_prepared_report():
    from commentator.radio_answer import answer_radio_question
    out = answer_radio_question(
        "как там напарник", weather=None, rain_forecast=None,
        gap_front_ms=None, gap_behind_ms=None, tyre_wear=None,
        teammate_report="Напарник Норрис идёт P5.")
    assert out == "Напарник Норрис идёт P5."


def test_answer_without_teammate_says_so_instead_of_off_topic():
    from commentator.radio_answer import answer_radio_question, OFF_TOPIC_ANSWER
    out = answer_radio_question(
        "как там напарник", weather=None, rain_forecast=None,
        gap_front_ms=None, gap_behind_ms=None, tyre_wear=None,
        teammate_report=None)
    assert out != OFF_TOPIC_ANSWER
    assert "напарник" in out.lower()


# ── Проводка: движок ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def engine():
    import core.engine as eng_mod
    orig = eng_mod.yc.load
    eng_mod.yc.load = lambda: None
    try:
        yield eng_mod.F1Engine({})
    finally:
        eng_mod.yc.load = orig


def _seed_grid(engine, player_idx=0):
    engine._player_car_index = player_idx
    engine._current_grid = [
        {"vehicle_idx": 0, "position": 3, "driver": "Игрок", "team": "McLaren"},
        {"vehicle_idx": 7, "position": 5, "driver": "Норрис", "team": "McLaren"},
        {"vehicle_idx": 5, "position": 1, "driver": "Ферстаппен", "team": "Red Bull"},
    ]
    engine._positions = {0: 3, 7: 5, 5: 1}
    engine._player_pos = 3


def test_engine_resolves_teammate_from_live_grid(engine):
    _seed_grid(engine)
    try:
        assert engine._teammate_idx() == 7
    finally:
        engine._current_grid = []
        engine._positions = {}
        engine._player_pos = None
        engine._player_car_index = 255


def test_engine_report_combines_position_pace_and_tyres(engine):
    _seed_grid(engine)
    engine._session_history = {
        0: {"best_lap_ms": 80100}, 7: {"best_lap_ms": 80700},
    }
    engine._grid_tyre_compounds = {7: "M"}
    try:
        report = engine._teammate_report()
        assert "P5" in report
        assert "ты быстрее на 0.6" in report
        assert "медиуме" in report
    finally:
        engine._session_history = {}
        engine._grid_tyre_compounds = {}
        engine._current_grid = []
        engine._positions = {}
        engine._player_pos = None
        engine._player_car_index = 255


def test_engine_report_is_none_without_teammate(engine):
    engine._player_car_index = 0
    engine._current_grid = [
        {"vehicle_idx": 0, "position": 3, "driver": "Игрок", "team": "McLaren"},
        {"vehicle_idx": 5, "position": 1, "driver": "Ферстаппен", "team": "Red Bull"},
    ]
    try:
        assert engine._teammate_report() is None
    finally:
        engine._current_grid = []
        engine._player_car_index = 255


def test_race_result_prefers_official_classification(engine):
    """Живой грид на CHQF может отставать — официальный packet 8 точнее."""
    _seed_grid(engine)
    engine._final_classification_grid = [{"vehicle_idx": 7, "position": 2}]
    try:
        # Игрок P4 по официальным данным, напарник P2 -> проиграл.
        assert engine._teammate_race_result(4).startswith("проиграл напарнику")
    finally:
        engine._final_classification_grid = []
        engine._current_grid = []
        engine._positions = {}
        engine._player_pos = None
        engine._player_car_index = 255


def test_race_result_falls_back_to_live_positions(engine):
    _seed_grid(engine)
    engine._final_classification_grid = []
    try:
        assert engine._teammate_race_result(3).startswith("обыграл напарника")
    finally:
        engine._current_grid = []
        engine._positions = {}
        engine._player_pos = None
        engine._player_car_index = 255


def test_story_facts_carry_teammate_result_only_for_races():
    from core.race_story import RaceStoryCollector
    collector = RaceStoryCollector()
    race = collector.facts(final_position=3, laps=[], teammate_result="обыграл напарника",
                           session_type="race")
    assert race["teammate_result"] == "обыграл напарника"
    quali = collector.facts(final_position=3, laps=[], teammate_result="обыграл напарника",
                            session_type="qualifying")
    assert quali["teammate_result"] is None


def test_story_prompt_mentions_teammate_duel():
    from commentator.story import build_prompt
    prompt = build_prompt({"teammate_result": "обыграл напарника (P2 против P7)"}, "tv")
    assert "Напарник по команде" in prompt
    assert "P2 против P7" in prompt
