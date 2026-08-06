import analytics.archive as archive


def test_season_result_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_SEASON", tmp_path / "season")
    archive.save_season_result({"track_id": 1, "classification": [{"driver": "Max", "points": 25}]})
    out = archive.list_season_results()
    assert len(out) == 1
    assert out[0]["classification"][0]["driver"] == "Max"


def test_season_results_newest_first_and_limited(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(archive, "_SEASON", tmp_path / "season")
    for i in range(3):
        archive.save_season_result({"track_id": i})
        time.sleep(0.01)  # distinct timestamped filenames
    out = archive.list_season_results(limit=2)
    assert [d["track_id"] for d in out] == [2, 1]  # newest-first, truncated


def test_list_season_results_empty_when_no_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_SEASON", tmp_path / "nope")
    assert archive.list_season_results() == []
