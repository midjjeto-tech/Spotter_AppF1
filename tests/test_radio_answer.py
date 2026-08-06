from commentator import radio_answer


def _answer(question, weather=None, rain_forecast=None,
            gap_front_ms=None, gap_behind_ms=None, tyre_wear=None,
            ahead_name=None, behind_name=None,
            position=None, penalty_count=0, penalty_seconds=0,
            damage=None, fuel_kg=None,
            ers_percent=None, ers_deploy_mode=None,
            laps_remaining=None, tyre_age=None, tyre_compound=None,
            tyre_sets_available=None):
    return radio_answer.answer_radio_question(
        question, weather=weather, rain_forecast=rain_forecast,
        gap_front_ms=gap_front_ms, gap_behind_ms=gap_behind_ms, tyre_wear=tyre_wear,
        ahead_name=ahead_name, behind_name=behind_name,
        position=position, penalty_count=penalty_count, penalty_seconds=penalty_seconds,
        damage=damage, fuel_kg=fuel_kg,
        ers_percent=ers_percent, ers_deploy_mode=ers_deploy_mode,
        laps_remaining=laps_remaining, tyre_age=tyre_age, tyre_compound=tyre_compound,
        tyre_sets_available=tyre_sets_available)


def test_classify_weather_topic():
    assert radio_answer.classify_topic("какая погода") == "weather"
    assert radio_answer.classify_topic("Будет дождь?") == "weather"
    assert radio_answer.classify_topic("сухо сейчас на трассе?") == "weather"


def test_classify_gap_topic():
    assert radio_answer.classify_topic("какой гэп до лидера") == "gap"
    assert radio_answer.classify_topic("что там впереди") == "gap"
    assert radio_answer.classify_topic("сзади кто-то есть?") == "gap"


def test_classify_tyres_topic():
    assert radio_answer.classify_topic("как шины") == "tyres"
    assert radio_answer.classify_topic("какой износ резины") == "tyres"
    assert radio_answer.classify_topic("покрышки ещё живы?") == "tyres"


def test_classify_unknown_topic_returns_none():
    assert radio_answer.classify_topic("какая тут музыка играет") is None


def test_classify_empty_question_returns_none():
    assert radio_answer.classify_topic("") is None
    assert radio_answer.classify_topic("   ") is None


def test_weather_answer_no_rain_in_forecast():
    weather = {"weather": 0, "track_temp": 30, "air_temp": 22}
    answer = _answer("какая погода", weather=weather)
    assert answer == "Ясно, 30° на трассе. Дождя не ожидается."


def test_weather_answer_rain_in_forecast():
    weather = {"weather": 1, "track_temp": 28, "air_temp": 20}
    rain_forecast = {"minutes": 15, "rain_pct": 60, "weather": 3}
    answer = _answer("будет дождь?", weather=weather, rain_forecast=rain_forecast)
    assert answer == "Облачно, 28° на трассе. Дождь через 15 минут, вероятность 60%."


def test_weather_answer_no_data():
    answer = _answer("какая погода", weather=None)
    assert answer == "Данные о погоде пока недоступны."


def test_weather_answer_rain_minute_pluralization():
    weather = {"weather": 0, "track_temp": 25, "air_temp": 18}
    rain_forecast = {"minutes": 1, "rain_pct": 40, "weather": 3}
    answer = _answer("погода?", weather=weather, rain_forecast=rain_forecast)
    assert "через 1 минуту" in answer


def test_gap_answer_front_and_behind():
    answer = _answer("какой гэп", gap_front_ms=1200, gap_behind_ms=2500)
    assert answer == "До машины впереди 1.2. Отрыв сзади 2.5."


def test_gap_answer_front_only():
    answer = _answer("что впереди", gap_front_ms=800, gap_behind_ms=None)
    assert answer == "До машины впереди 0.8."


def test_gap_answer_behind_only():
    answer = _answer("кто сзади", gap_front_ms=None, gap_behind_ms=3000)
    assert answer == "Отрыв сзади 3.0."


# --- гэп + имя (фолд "кто сзади/впереди" в существующую тему gap, а не
# отдельная тема — см. docs/superpowers/plans/2026-07-19-voice-qa-expansion.md) ---

def test_gap_answer_includes_ahead_and_behind_names():
    answer = _answer("какой гэп", gap_front_ms=1200, gap_behind_ms=2500,
                      ahead_name="Норрис", behind_name="Ферстаппен")
    assert answer == ("До машины впереди 1.2 — это Норрис. "
                       "Отрыв сзади 2.5 — это Ферстаппен.")


def test_gap_answer_behind_name_without_ahead():
    answer = _answer("кто сзади", gap_front_ms=None, gap_behind_ms=3000,
                      behind_name="Ферстаппен")
    assert answer == "Отрыв сзади 3.0 — это Ферстаппен."


def test_gap_answer_no_name_omits_name_clause():
    answer = _answer("что впереди", gap_front_ms=800, gap_behind_ms=None,
                      ahead_name=None)
    assert answer == "До машины впереди 0.8."


def test_gap_answer_leader_when_no_gaps():
    answer = _answer("какой гэп", gap_front_ms=None, gap_behind_ms=None)
    assert answer == "Вы лидируете."


def test_gap_answer_leader_when_gaps_zero():
    answer = _answer("какой гэп", gap_front_ms=0, gap_behind_ms=0)
    assert answer == "Вы лидируете."


def test_tyres_answer_with_data():
    answer = _answer("как шины", tyre_wear=42.3)
    assert answer == "Износ шин 42%."


def test_tyres_answer_no_data():
    answer = _answer("какой износ", tyre_wear=None)
    assert answer == "Данные по износу пока недоступны."


def test_off_topic_question_returns_fixed_phrase():
    answer = _answer("какая тут музыка играет")
    assert answer == radio_answer.OFF_TOPIC_ANSWER


def test_empty_question_returns_fixed_phrase():
    assert _answer("") == radio_answer.OFF_TOPIC_ANSWER
    assert _answer("   ") == radio_answer.OFF_TOPIC_ANSWER


# --------------------------------------------------------------------------- #
# Voice Q&A expansion (3 -> 8 topics + voice commands). См. docs/superpowers/
# plans/2026-07-19-voice-qa-expansion.md.
# --------------------------------------------------------------------------- #

def test_classify_position_topic():
    assert radio_answer.classify_topic("на каком я месте") == "position"
    assert radio_answer.classify_topic("какая у меня позиция") == "position"


def test_position_answer_with_data():
    assert _answer("какая позиция", position=5) == "Ты на 5-м месте из 22."


def test_position_answer_no_data():
    assert _answer("какая позиция", position=None) == "Позиция пока не определена."


def test_classify_penalties_topic():
    assert radio_answer.classify_topic("у меня есть штрафы") == "penalties"
    assert radio_answer.classify_topic("сколько штрафных секунд") == "penalties"


def test_penalties_answer_none():
    assert _answer("штрафы есть", penalty_count=0, penalty_seconds=0) == "Штрафов пока нет."


def test_penalties_answer_singular():
    assert _answer("штрафы есть", penalty_count=1, penalty_seconds=5) == "У тебя 1 штраф, 5 секунд."


def test_penalties_answer_plural():
    assert _answer("штрафы есть", penalty_count=2, penalty_seconds=10) == "У тебя 2 штрафа, 10 секунд."


def test_classify_damage_topic():
    assert radio_answer.classify_topic("какие повреждения") == "damage"
    assert radio_answer.classify_topic("большой ущерб у болида") == "damage"


def test_damage_answer_no_data():
    assert _answer("повреждения есть", damage=None) == "Машина цела, серьёзных повреждений нет."


def test_damage_answer_all_below_threshold():
    damage = {"wing_damage": 5, "floor_damage": 0, "gearbox_damage": 0, "engine_damage": 10}
    assert _answer("повреждения есть", damage=damage) == "Машина цела, серьёзных повреждений нет."


def test_damage_answer_single_category():
    damage = {"wing_damage": 45, "floor_damage": 0, "gearbox_damage": 0, "engine_damage": 0}
    assert _answer("повреждения есть", damage=damage) == "Повреждено: крыло 45%."


def test_damage_answer_multiple_categories_in_fixed_order():
    damage = {"wing_damage": 45, "floor_damage": 30, "gearbox_damage": 0, "engine_damage": 25}
    assert _answer("повреждения есть", damage=damage) == \
        "Повреждено: крыло 45%, пол 30%, двигатель 25%."


def test_classify_fuel_topic():
    assert radio_answer.classify_topic("сколько топлива осталось") == "fuel"
    assert radio_answer.classify_topic("хватит бензина") == "fuel"


def test_fuel_answer_with_data():
    assert _answer("сколько топлива", fuel_kg=25.44) == "Топлива 25.4 кг."


def test_fuel_answer_no_data():
    assert _answer("сколько топлива", fuel_kg=None) == "Данные о топливе пока недоступны."


def test_classify_ers_topic():
    assert radio_answer.classify_topic("сколько заряда ERS") == "ers"
    assert radio_answer.classify_topic("какой заряд батареи") == "ers"


def test_ers_answer_with_data():
    answer = _answer("сколько эрс", ers_percent=65.2, ers_deploy_mode=1)
    assert answer == "Заряд ERS 65%, режим — средний."


def test_ers_answer_unknown_mode_label():
    answer = _answer("сколько эрс", ers_percent=50.0, ers_deploy_mode=9)
    assert answer == "Заряд ERS 50%, режим — неизвестно."


def test_ers_answer_no_data():
    assert _answer("сколько эрс", ers_percent=None) == "Данные по ERS пока недоступны."


def test_classify_laps_remaining_topic():
    assert radio_answer.classify_topic("сколько кругов осталось") == "laps_remaining"
    assert radio_answer.classify_topic("сколько кругов до финиша") == "laps_remaining"


def test_laps_remaining_answer_plural_forms():
    assert _answer("сколько кругов", laps_remaining=1) == "Осталось 1 круг."
    assert _answer("сколько кругов", laps_remaining=3) == "Осталось 3 круга."
    assert _answer("сколько кругов", laps_remaining=5) == "Осталось 5 кругов."


def test_laps_remaining_answer_last_lap():
    assert _answer("сколько кругов", laps_remaining=0) == "Это последний круг."


def test_laps_remaining_answer_no_data():
    assert _answer("сколько кругов", laps_remaining=None) == \
        "Пока не известно, сколько кругов осталось."


def test_classify_pit_window_topic():
    assert radio_answer.classify_topic("когда мне в питы") == "pit_window"
    assert radio_answer.classify_topic("скоро пит-стоп") == "pit_window"
    assert radio_answer.classify_topic("пора в боксы") == "pit_window"


def test_pit_window_answer_open():
    # Известные входные данные из tests/test_strategy_ai.py — detect_pit_window
    # возвращает open=True.
    answer = _answer("когда мне в питы", tyre_age=35, tyre_wear=65.0, laps_remaining=15)
    assert answer == "Окно пит-стопа открыто — заезжай в этом круге."


def test_pit_window_answer_laps_estimate():
    # Тот же источник — detect_pit_window возвращает open=False, laps_to_pit=21.
    answer = _answer("когда мне в питы", tyre_age=8, tyre_wear=25.0, laps_remaining=40)
    assert answer == "Ещё примерно 21 круг до пит-стопа."


def test_pit_window_answer_too_early():
    answer = _answer("когда мне в питы", tyre_age=None, tyre_wear=None, laps_remaining=None)
    assert answer == "Пока рано думать про пит-стоп."


# --- classify_command — голосовые команды поверх существующих хоткеев ---

def test_classify_command_mute():
    assert radio_answer.classify_command("замолчи") == "toggle_commentary"
    assert radio_answer.classify_command("хватит болтать") == "toggle_commentary"
    assert radio_answer.classify_command("потише пожалуйста") == "toggle_commentary"


def test_classify_command_next_persona():
    assert radio_answer.classify_command("смени персону") == "next_persona"
    assert radio_answer.classify_command("смени голос") == "next_persona"
    assert radio_answer.classify_command("поменяй голос") == "next_persona"


def test_classify_command_unrelated_returns_none():
    assert radio_answer.classify_command("какая погода") is None
    assert radio_answer.classify_command("") is None


def test_command_stems_do_not_collide_with_topic_stems():
    for question in ("замолчи", "хватит болтать", "потише пожалуйста",
                      "смени персону", "смени голос", "поменяй голос"):
        assert radio_answer.classify_topic(question) is None


# --------------------------------------------------------------------------- #
# Tyre Sets (item 5, packet 12). См. docs/superpowers/plans/2026-07-19-
# tyre-sets-final-classification.md.
# --------------------------------------------------------------------------- #

def test_classify_tyre_sets_topic():
    assert radio_answer.classify_topic("сколько у меня комплектов") == "tyre_sets"
    assert radio_answer.classify_topic("остались ли ещё комплекты") == "tyre_sets"


def test_tyre_sets_answer_with_data():
    answer = _answer("комплекты", tyre_sets_available={"M": 2, "H": 1})
    assert answer == "Доступно: 2 медиум, 1 хард."


def test_tyre_sets_answer_fixed_order_regardless_of_dict_order():
    answer = _answer("комплекты", tyre_sets_available={"W": 1, "S": 3, "H": 1})
    assert answer == "Доступно: 3 софт, 1 хард, 1 дождевые."


def test_tyre_sets_answer_no_data():
    assert _answer("комплекты", tyre_sets_available=None) == \
        "Данные о комплектах пока недоступны."


def test_tyre_sets_answer_none_left():
    assert _answer("комплекты", tyre_sets_available={}) == \
        "Свободных комплектов не осталось."
