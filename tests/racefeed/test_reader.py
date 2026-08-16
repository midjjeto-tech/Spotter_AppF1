import pytest

from core.racefeed import reader, storage
from core.racefeed.models import Post


def _session(tmp_path, session_id="20260726_202326", post_id="p1"):
    path = str(tmp_path / f"{session_id}.sqlite3")
    storage.init_db(path)
    storage.save_post(path, Post(
        id=post_id, session_id=session_id, story_id="st",
        reporter_id="race_control", category="incident", text="Контакт в первом повороте.",
        created_at=1.0, published_at=2.0, driver="Норрис", is_player_story=False,
    ))
    return path


# --- валидация пути ---------------------------------------------------------
# session_id приходит из браузера — единственное место, где фронт решает, в
# какой файл писать.

@pytest.mark.parametrize("session_id", [
    "../../settings",
    "..\\..\\settings",
    "/etc/passwd",
    "C:\\Windows\\System32\\config",
    "20260726_202326/../../evil",
    "20260726",
    "2026072_202326",
    "20260726_20232",
    "20260726_202326.sqlite3",
    "",
    None,
])
def test_session_file_rejects_anything_that_is_not_a_timestamp(tmp_path, session_id):
    with pytest.raises(reader.ReaderError):
        reader.session_file(str(tmp_path), session_id)


def test_session_file_rejects_a_valid_id_with_no_file(tmp_path):
    with pytest.raises(reader.ReaderError):
        reader.session_file(str(tmp_path), "20260726_202326")


def test_session_file_accepts_an_existing_session(tmp_path):
    _session(tmp_path)
    assert reader.session_file(str(tmp_path), "20260726_202326").name == \
        "20260726_202326.sqlite3"


def test_a_rejected_session_id_writes_nothing(tmp_path):
    _session(tmp_path)
    outside = tmp_path.parent / "outside.sqlite3"

    with pytest.raises(reader.ReaderError):
        reader.react(str(tmp_path), "../outside", "p1", "🔥")

    assert not outside.exists()


# --- реакции и голос --------------------------------------------------------

def test_reaction_is_persisted_on_the_post(tmp_path):
    path = _session(tmp_path)
    reader.react(str(tmp_path), "20260726_202326", "p1", "🔥")

    assert storage.get_posts(path)[0]["reader"]["reaction"] == "🔥"


def test_reaction_can_be_cleared(tmp_path):
    path = _session(tmp_path)
    reader.react(str(tmp_path), "20260726_202326", "p1", "🔥")
    reader.react(str(tmp_path), "20260726_202326", "p1", "")

    assert storage.get_posts(path)[0]["reader"] == {}


def test_vote_is_persisted(tmp_path):
    path = _session(tmp_path)
    reader.vote(str(tmp_path), "20260726_202326", "p1", "Алонсо")

    assert storage.get_posts(path)[0]["reader"]["vote"] == "Алонсо"


def test_action_without_a_post_id_is_rejected(tmp_path):
    _session(tmp_path)
    with pytest.raises(reader.ReaderError):
        reader.react(str(tmp_path), "20260726_202326", "", "🔥")


# --- реплика читателя -------------------------------------------------------

def test_comment_is_stored_and_returned_for_immediate_display(tmp_path):
    path = _session(tmp_path)

    saved = reader.add_comment(str(tmp_path), "20260726_202326", "p1",
                               "Это был чистый манёвр")

    assert saved["author_id"] == "player"
    assert saved["text"] == "Это был чистый манёвр"
    stored = storage.get_posts(path)[0]["comments"]
    assert [c["text"] for c in stored] == ["Это был чистый манёвр"]


def test_empty_comment_is_rejected(tmp_path):
    _session(tmp_path)
    for text in ("", "   ", "\n", None):
        with pytest.raises(reader.ReaderError):
            reader.add_comment(str(tmp_path), "20260726_202326", "p1", text)


def test_long_comment_is_truncated_not_refused(tmp_path):
    _session(tmp_path)
    saved = reader.add_comment(str(tmp_path), "20260726_202326", "p1", "я" * 900)

    assert len(saved["text"]) == reader.MAX_COMMENT_CHARS


def test_reader_comment_survives_on_an_archived_race(tmp_path):
    """Смысл хранения в БД, а не в localStorage: действие остаётся в файле той
    гонки и видно, когда она уже уехала в архив."""
    path = _session(tmp_path, session_id="20260701_120000")
    reader.add_comment(str(tmp_path), "20260701_120000", "p1", "до сих пор обидно")
    reader.react(str(tmp_path), "20260701_120000", "p1", "😢")

    post = storage.get_posts(path)[0]
    assert post["reader"]["reaction"] == "😢"
    assert post["comments"][0]["author_name"] == "Ты"


def test_thread_of_returns_post_text_and_existing_comments(tmp_path):
    _session(tmp_path)
    reader.add_comment(str(tmp_path), "20260726_202326", "p1", "моя реплика")

    text, comments = reader.thread_of(str(tmp_path), "20260726_202326", "p1")

    assert text == "Контакт в первом повороте."
    assert [c["text"] for c in comments] == ["моя реплика"]


def test_thread_of_unknown_post_is_rejected(tmp_path):
    _session(tmp_path)
    with pytest.raises(reader.ReaderError):
        reader.thread_of(str(tmp_path), "20260726_202326", "нет-такого")


# --- поведение движка при выключенном репортаже ------------------------------

class _StubEngine:
    """Минимальный носитель методов F1Engine, которые дёргают роуты."""

    def __init__(self, race_feed=None):
        self._race_feed = race_feed

    racefeed_reader_action = None  # заполняется ниже


def test_actions_report_disabled_instead_of_crashing():
    """Тумблер репортажа выключен — фронт должен получить внятный отказ, а не 500."""
    from core.engine import F1Engine
    stub = _StubEngine()
    result = F1Engine.racefeed_reader_action(stub, "reaction", "20260726_202326",
                                             "p1", "🔥")
    assert result == {"ok": False, "reason": "disabled"}

    result = F1Engine.racefeed_reader_comment(stub, "20260726_202326", "p1", "x")
    assert result == {"ok": False, "reason": "disabled"}


def test_unknown_action_kind_is_refused(tmp_path):
    from core.engine import F1Engine

    class _Feed:
        def data_dir(self):
            return str(tmp_path)

    result = F1Engine.racefeed_reader_action(_StubEngine(_Feed()), "delete_everything",
                                             "20260726_202326", "p1", "x")
    assert result == {"ok": False, "reason": "unknown_action"}


def test_bad_session_id_is_reported_not_raised(tmp_path):
    from core.engine import F1Engine

    class _Feed:
        def data_dir(self):
            return str(tmp_path)

    result = F1Engine.racefeed_reader_action(_StubEngine(_Feed()), "reaction",
                                             "../../evil", "p1", "🔥")
    assert result["ok"] is False
    assert "session" in result["reason"]
