from core.session_recorder import SessionRecorder


def test_laps_accessor_returns_copy():
    r = SessionRecorder()
    r.on_lap_complete(1, 95000, 30000, 33000, 32000)
    laps = r.laps()
    assert laps == [{"lap": 1, "last_lap_ms": 95000,
                     "s1_ms": 30000, "s2_ms": 33000, "s3_ms": 32000,
                     "pit_lap": False}]
    laps.append({"x": 1})            # мутация копии не трогает внутренний список
    assert len(r.laps()) == 1


def test_on_lap_complete_records_pit_lap_flag():
    r = SessionRecorder()
    r.on_lap_complete(1, 95000, 30000, 33000, 32000, pit_lap=True)
    assert r.laps()[0]["pit_lap"] is True
