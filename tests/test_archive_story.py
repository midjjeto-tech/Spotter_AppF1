from analytics import archive


def test_attach_story_adds_key(tmp_path):
    p = tmp_path / "sess.json"
    archive._atomic_write(p, {"track_name": "Монца", "player_laps": []})
    archive.attach_story(p, "Отличная гонка.")
    data = archive._load(p)
    assert data["story"] == "Отличная гонка."
    assert data["track_name"] == "Монца"          # существующие поля целы


def test_attach_story_missing_file_is_safe(tmp_path):
    archive.attach_story(tmp_path / "nope.json", "x")   # без исключений
