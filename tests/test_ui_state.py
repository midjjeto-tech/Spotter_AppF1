from core.ui_state import OverlayTelemetry, UIStateProjection, initial_ui_state


def _projection(max_feed=2):
    return UIStateProjection(initial_ui_state(
        llm_engine="templates", tts_engine="piper", voice_status="ok",
        voice_available=True, persona="tv", yandex_ok=False,
    ), max_feed_items=max_feed)


def test_snapshot_is_deeply_isolated_from_projection():
    projection = _projection()
    projection.set_race({"leader": "—", "grid": [{"position": 1}]})

    snapshot = projection.snapshot()
    snapshot["race"]["grid"][0]["position"] = 99
    snapshot["feed"].append({"event_code": "FAKE"})

    fresh = projection.snapshot()
    assert fresh["race"]["grid"] == [{"position": 1}]
    assert fresh["feed"] == []


def test_feed_is_newest_first_capped_and_copied():
    projection = _projection(max_feed=2)
    item = {"event_code": "A", "details": {"lap": 1}}
    projection.append_feed(item)
    item["details"]["lap"] = 99
    projection.append_feed({"event_code": "B"})
    projection.append_feed({"event_code": "C"})

    assert [entry["event_code"] for entry in projection.snapshot()["feed"]] == ["C", "B"]


def test_session_reset_clears_public_session_results_and_strategy():
    projection = _projection()
    projection.set_race_story({"text": "old"})
    projection.set_f1_benchmark({"gap_ms": 1})
    projection.set_strategy({"action": "pit"})

    projection.reset_session_view()

    snapshot = projection.snapshot()
    assert snapshot["race_story"] is None
    assert snapshot["f1_benchmark"] is None
    assert snapshot["strategy_ai"]["action"] == "hold"


def test_overlay_uses_consistent_public_and_telemetry_snapshot():
    projection = _projection()
    projection.set_race({"leader": "Norris", "grid": []})
    projection.set_strategy({
        "action": "pit", "confidence": 0.9, "advice": "Box",
        "tyre_status": "critical",
    })

    overlay = projection.overlay(OverlayTelemetry(
        position=3, lap_current=10, lap_total=50, speed_kmh=300,
        drs_active=True, gap_leader_ms=1000, gap_front_ms=500,
        gap_behind_ms=800, tyre_compound="S", tyre_age=12, tyre_wear=70.0,
        radar=[], fuel_kg=28.4, ers_percent=73.0, ers_deploy_mode=2,
        last_lap_ms=82_345,
    ))

    assert overlay["leader"] == "Norris"
    assert overlay["strategy"]["action"] == "pit"
    assert overlay["tyre"]["status"] == "critical"
    assert overlay["car"]["fuel_kg"] == 28.4
    assert overlay["car"]["ers_percent"] == 73.0
    assert overlay["car"]["last_lap_str"] == "1:22.345"


def test_overlay_exposes_relative_rows_beyond_top5():
    projection = _projection()
    grid = [
        {"position": i, "driver": f"D{i}", "team": "T", "color": "#000",
         "gap_front_ms": 500}
        for i in range(1, 8)
    ]
    projection.set_race({"leader": "D1", "grid": grid})

    overlay = projection.overlay(OverlayTelemetry(
        position=6, lap_current=10, lap_total=50, speed_kmh=300,
        drs_active=True, gap_leader_ms=1000, gap_front_ms=500,
        gap_behind_ms=800, tyre_compound="S", tyre_age=12, tyre_wear=70.0,
        radar=[],
    ))

    # Игрок на P6 — вне топ-5 по позиции, но relative должен видеть его
    # соседей (P5/P7), значит build_overlay_state получил ПОЛНЫЙ grid, а не
    # обрезанный до 5 элементов до вызова.
    positions_in_relative = [row["position"] for row in overlay["relative"]]
    assert 5 in positions_in_relative
    assert 7 in positions_in_relative
    assert len(overlay["grid_top5"]) == 5


# ── Текстовая рация («System Message») ────────────────────────────────────────
# Идея из Grognaks Race Engineer App: если реплику не озвучили (авто-озвучка
# выключена, отвал TTS), инженер должен НАПИСАТЬ, а не исчезнуть. Раньше
# set_speaking() обнуляло now_speaking, и игровой HUD молчал вместе с голосом.

def test_radio_message_survives_an_unvoiced_phrase():
    projection = _projection()
    projection.set_speaking("Береги резину.", False)
    projection.set_radio_message("Береги резину.", voiced=False, now=100.0)

    snapshot = projection.snapshot()
    assert snapshot["now_speaking"] == ""          # старое поведение не тронуто
    assert snapshot["radio_message"] == {
        "text": "Береги резину.", "voiced": False, "ts": 100.0}


def test_radio_message_marks_voiced_phrases_too():
    projection = _projection()
    projection.set_radio_message("Бокс, бокс.", voiced=True, now=5.0)
    assert projection.snapshot()["radio_message"]["voiced"] is True


def test_empty_text_does_not_wipe_a_readable_message():
    """Иначе служебный вызов set_speaking('', False) стирал бы сообщение,
    которое игрок ещё не успел прочитать."""
    projection = _projection()
    projection.set_radio_message("Держи слева!", voiced=False, now=1.0)
    projection.set_radio_message("", voiced=False, now=2.0)
    assert projection.snapshot()["radio_message"]["text"] == "Держи слева!"


def test_clearing_the_feed_also_clears_the_hud_message():
    projection = _projection()
    projection.set_radio_message("Держи слева!", voiced=False, now=1.0)
    projection.clear_feed()
    assert projection.snapshot()["radio_message"]["text"] == ""


def test_radio_message_present_from_the_start():
    """Фронт читает поле без опциональных проверок на первом кадре."""
    assert _projection().snapshot()["radio_message"] == {
        "text": "", "voiced": False, "ts": 0.0}
