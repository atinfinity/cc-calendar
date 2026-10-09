import json

import pytest
from fastapi.testclient import TestClient

from cc_calendar.notes import Notes, NotesUnavailable
from cc_calendar.server import create_app


def test_set_get_and_file(tmp_path):
    path = tmp_path / "data" / "notes.json"
    notes = Notes(path)
    out = notes.set("s1", "  first line\r\nsecond  ", [" bug ", "Needs   review", "BUG", ""])
    assert out == {"note": "first line\nsecond", "tags": ["bug", "Needs review"], "outcome": None}
    data = json.loads(path.read_text())
    assert data["version"] == 1
    assert data["sessions"]["s1"]["tags"] == ["bug", "Needs review"]
    assert "updated" in data["sessions"]["s1"]
    assert Notes(path).get("s1") == out
    assert notes.get("missing") == {"note": "", "tags": [], "outcome": None}
    assert list(tmp_path.joinpath("data").iterdir()) == [path]  # no temporary file left


def test_tag_spelling_follows_other_sessions(tmp_path):
    notes = Notes(tmp_path / "notes.json")
    notes.set("s1", "", ["Failed"])
    assert notes.set("s2", "", ["failed", "pr review"])["tags"] == ["Failed", "pr review"]
    # The only session with a tag can change its case.
    assert notes.set("s2", "", ["PR review"])["tags"] == ["PR review"]
    assert notes.all_tags() == [{"tag": "Failed", "count": 1}, {"tag": "PR review", "count": 1}]
    notes.set("s3", "", ["failed"])
    assert notes.all_tags()[0] == {"tag": "Failed", "count": 2}


def test_empty_entry_is_removed(tmp_path):
    path = tmp_path / "notes.json"
    notes = Notes(path)
    notes.set("s1", "x", [])
    notes.set("s1", "  ", [])
    assert json.loads(path.read_text())["sessions"] == {}


def test_outcome(tmp_path):
    path = tmp_path / "notes.json"
    notes = Notes(path)
    # A rating alone keeps the entry.
    assert notes.set("s1", "", [], "failed")["outcome"] == "failed"
    assert json.loads(path.read_text())["sessions"]["s1"]["outcome"] == "failed"
    assert Notes(path).get("s1")["outcome"] == "failed"
    # Leaving it out keeps it; an empty string clears it.
    assert notes.set("s1", "retry", [])["outcome"] == "failed"
    assert notes.set("s1", "retry", [], "")["outcome"] is None
    assert "outcome" not in json.loads(path.read_text())["sessions"]["s1"]
    notes.set("s1", "", [], "")
    assert json.loads(path.read_text())["sessions"] == {}
    with pytest.raises(ValueError):
        notes.set("s1", "", [], "great")


def test_old_and_unknown_outcomes_load(tmp_path):
    path = tmp_path / "notes.json"
    sessions = {
        "old": {"note": "from v0.5", "tags": ["x"]},
        "rated": {"note": "", "tags": [], "outcome": "partial"},
        "newer": {"note": "y", "tags": [], "outcome": "superb"},
    }
    path.write_text(json.dumps({"version": 1, "sessions": sessions}))
    notes = Notes(path)
    assert notes.error is None
    assert notes.get("old") == {"note": "from v0.5", "tags": ["x"], "outcome": None}
    assert notes.get("rated")["outcome"] == "partial"
    assert notes.get("newer")["outcome"] is None


@pytest.mark.parametrize(
    ("note", "tags"),
    [("x" * 2001, []), ("", ["a,b"]), ("", ["x" * 41]), ("", [f"t{i}" for i in range(21)])],
)
def test_limits(tmp_path, note, tags):
    with pytest.raises(ValueError):
        Notes(tmp_path / "notes.json").set("s1", note, tags)


def test_unreadable_file_is_never_overwritten(tmp_path):
    path = tmp_path / "notes.json"
    path.write_text("{broken")
    notes = Notes(path)
    assert "could not be read" in notes.error
    with pytest.raises(NotesUnavailable):
        notes.set("s1", "x", [])
    assert path.read_text() == "{broken"


def test_reloads_when_the_file_changes(tmp_path):
    path = tmp_path / "notes.json"
    notes = Notes(path)
    notes.set("s1", "mine", [])
    other = Notes(path)  # e.g. another machine writing to a synced file
    other.set("s2", "theirs", ["x"])
    notes.refresh()
    assert notes.get("s2")["note"] == "theirs"
    notes.set("s1", "mine again", [])
    assert Notes(path).get("s2")["note"] == "theirs"  # a write keeps the other entries


@pytest.fixture
def client(claude_dir, tmp_path):
    app = create_app(claude_dir, watch=False, notes_path=tmp_path / "notes.json")
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


def test_api(client, tmp_path):
    res = client.put("/api/sessions/s-basic/notes", json={"note": "check later", "tags": ["todo"]})
    assert res.status_code == 200
    assert res.json() == {"note": "check later", "tags": ["todo"], "outcome": None}
    data = client.get("/api/sessions").json()
    basic = next(s for s in data["sessions"] if s["id"] == "s-basic")
    assert basic["note"] == "check later" and basic["tags"] == ["todo"]
    assert data["tags"] == [{"tag": "todo", "count": 1}]
    assert data["notes_error"] is None
    assert client.get("/api/sessions/s-basic").json()["tags"] == ["todo"]
    assert client.get("/api/sessions/s-sub").json()["note"] == ""


def test_api_outcome(client):
    url = "/api/sessions/s-basic/notes"
    res = client.put(url, json={"note": "", "tags": [], "outcome": "done"})
    assert res.status_code == 200 and res.json()["outcome"] == "done"
    basic = next(s for s in client.get("/api/sessions").json()["sessions"] if s["id"] == "s-basic")
    assert basic["outcome"] == "done"
    assert client.get("/api/sessions/s-sub").json()["outcome"] is None
    # A client that does not know about outcomes leaves the rating alone.
    assert client.put(url, json={"note": "x", "tags": []}).json()["outcome"] == "done"
    assert client.put(url, json={"note": "x", "outcome": ""}).json()["outcome"] is None
    assert client.put(url, json={"outcome": "great"}).status_code == 422


def test_api_errors(client):
    url = "/api/sessions/s-basic/notes"
    assert client.put("/api/sessions/nope/notes", json={"note": "x"}).status_code == 404
    assert client.put(url, json={"tags": ["a,b"]}).status_code == 422
    # A form post or a request from another site is refused.
    form = client.put(url, content='{"note": "x"}', headers={"Content-Type": "text/plain"})
    assert form.status_code == 415
    foreign = client.put(url, json={"note": "x"}, headers={"Origin": "https://evil.example"})
    assert foreign.status_code == 403
    same = client.put(url, json={"note": "x"}, headers={"Origin": "http://127.0.0.1:8000"})
    assert same.status_code == 200


def test_api_with_unreadable_file(claude_dir, tmp_path):
    path = tmp_path / "notes.json"
    path.write_text("[]")
    app = create_app(claude_dir, watch=False, notes_path=path)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert "could not be read" in c.get("/api/sessions").json()["notes_error"]
        assert c.put("/api/sessions/s-basic/notes", json={"note": "x"}).status_code == 409
    assert path.read_text() == "[]"


def test_default_path(monkeypatch, tmp_path):
    from cc_calendar import notes

    monkeypatch.setattr(notes.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert notes.default_path() == tmp_path / "cc-calendar" / "notes.json"
    monkeypatch.setattr(notes.sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows Path.home() ignores HOME
    assert notes.default_path() == tmp_path / "Library/Application Support/cc-calendar/notes.json"
    monkeypatch.setattr(notes.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert notes.default_path() == tmp_path / "Roaming" / "cc-calendar" / "notes.json"
