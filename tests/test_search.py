import json
import os
import shutil
import sqlite3

import pytest
from conftest import PROJECT, LogBuilder
from fastapi.testclient import TestClient

from cc_calendar.search import SearchIndex, fts_query, record_docs, snippet
from cc_calendar.server import create_app
from cc_calendar.store import ClaudeDir, Store


def indexed_store(dirs, path=None) -> Store:
    store = Store(dirs, SearchIndex(path))
    store.scan()
    assert store.index.wait_idle(10)
    return store


def hits(store: Store, query: str) -> dict:
    return {(h.session_id, h.agent_id): h for h in store.index.search(query)}


def test_record_docs():
    b = LogBuilder("s")
    b.prompt(0, "Fix the parser")
    b.assistant(1, [{"type": "thinking", "thinking": "secret plan"}], msg_id="m1")
    b.tool_use(2, "t1", "Edit", {"file_path": "/src/a.py", "old_string": "x"}, msg_id="m2")
    b.tool_result(3, "t1", "ValueError: bad input", is_error=True)
    docs = [record_docs(r) for r in b.records]
    assert docs[0] == [("prompt", None, "Fix the parser")]
    assert docs[1] == []  # thinking is not indexed
    assert docs[2] == [("tool_use", "Edit", "/src/a.py\nx")]
    assert docs[3] == [("tool_result", None, "ValueError: bad input")]


def test_query_and_snippet():
    assert fts_query("ab") is None
    assert fts_query('  say  "hi"  ') == '"say ""hi"""'
    s = snippet("x" * 100 + "Needle" + "y" * 100, "needle")
    assert s["match"] == "Needle"
    assert s["before"].startswith("…") and s["after"].endswith("…")


def test_search_scope(claude_dir):
    store = indexed_store(claude_dir)
    # Assistant text, tool input (a file path), tool output, and a subagent's reply.
    assert set(hits(store, "Writing it")) == {("s-basic", None)}
    assert set(hits(store, "README.md")) == {("s-basic", None)}
    assert set(hits(store, "abc1234")) == {("s-basic", None)}
    assert set(hits(store, "searching")) == {("s-sub", "a1")}
    assert hits(store, "plan") == {}  # thinking
    # Case and line breaks do not matter.
    assert set(hits(store, "1 FILE changed")) == {("s-basic", None)}
    # The continuation's copy of its predecessor is not indexed twice.
    assert set(hits(store, "Long task")) == {("s-prev", None)}
    h = hits(store, "README")[("s-basic", None)]
    assert h.count == 4 and h.kind == "prompt"


def test_search_japanese(claude_dir):
    b = LogBuilder("s-ja")
    b.prompt(0, "ビルドが失敗する原因を調べて")
    b.write(claude_dir / "projects" / PROJECT / "s-ja.jsonl")
    store = indexed_store(claude_dir)
    assert set(hits(store, "失敗する")) == {("s-ja", None)}


def test_index_persists_and_grows(claude_dir, tmp_path):
    db = tmp_path / "search.db"
    store = indexed_store(claude_dir, db)
    store.index.close()

    # A restart reads only the new lines.
    path = claude_dir / "projects" / PROJECT / "s-basic.jsonl"
    b = LogBuilder("s-basic")
    b._n = 1000
    b.prompt(30, "Now add a LICENSE file")
    with open(path, "a") as f:
        f.write(json.dumps(b.records[0]) + "\n")
    store = indexed_store(claude_dir, db)
    assert set(hits(store, "LICENSE")) == {("s-basic", None)}
    assert hits(store, "Writing it")[("s-basic", None)].count == 1

    # Live growth is picked up as the store reads it.
    b.prompt(31, "And a CHANGELOG")
    with open(path, "a") as f:
        f.write(json.dumps(b.records[1]) + "\n")
    store.update_file(path)
    assert store.index.wait_idle(10)
    assert set(hits(store, "CHANGELOG")) == {("s-basic", None)}
    store.index.close()

    # Two processes sharing the index do not duplicate rows.
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT count(*) FROM parts WHERE text LIKE '%LICENSE%'").fetchone()[0] == 1


def test_rewritten_and_deleted_files(claude_dir, tmp_path):
    db = tmp_path / "search.db"
    store = indexed_store(claude_dir, db)
    proj = claude_dir / "projects" / PROJECT
    b = LogBuilder("s-sub")
    b.prompt(0, "fresh start")
    b.write(proj / "s-sub.jsonl")  # shorter than before
    store.update_file(proj / "s-sub.jsonl")
    assert store.index.wait_idle(10)
    assert set(hits(store, "fresh start")) == {("s-sub", None)}
    assert ("s-sub", None) not in hits(store, "Research something")
    store.index.close()

    (proj / "s-basic.jsonl").unlink()
    store = indexed_store(claude_dir, db)
    assert hits(store, "Writing it") == {}
    store.index.close()


def test_corrupt_index_is_rebuilt(claude_dir, tmp_path):
    db = tmp_path / "search.db"
    db.write_bytes(b"not a database" * 100)
    store = indexed_store(claude_dir, db)
    assert set(hits(store, "Writing it")) == {("s-basic", None)}
    store.index.close()


@pytest.fixture
def client(claude_dir):
    with TestClient(create_app(claude_dir, watch=False), base_url="http://127.0.0.1") as c:
        assert c.app.state.store.index.wait_idle(10)
        yield c


def test_search_api(client):
    data = client.get("/api/search", params={"q": "abc1234"}).json()
    assert data["pending"] == 0
    hit = data["hits"]["s-basic"]
    assert hit["kind"] == "tool_result" and hit["agent"] is None
    assert hit["snippet"]["match"] == "abc1234"
    assert hit["ts"] is not None

    sub = client.get("/api/search", params={"q": "searching"}).json()["hits"]
    assert sub["s-sub"]["agent"] == "a1"
    assert client.get("/api/search", params={"q": "ab"}).json()["hits"] == {}
    assert client.get("/api/search", params={"q": "x" * 501}).status_code == 422


def test_search_shows_the_listed_copy(claude_dir, laptop_dir):
    # The laptop's copy of s-basic is older; the hit must come from the copy that is shown.
    dirs = [ClaudeDir("local", claude_dir), ClaudeDir("laptop", laptop_dir)]
    with TestClient(create_app(dirs, watch=False), base_url="http://127.0.0.1") as c:
        assert c.app.state.store.index.wait_idle(10)
        assert set(c.get("/api/search", params={"q": "README"}).json()["hits"]) == {"s-basic"}
        assert c.get("/api/search", params={"q": "README"}).json()["hits"]["s-basic"]["count"] == 4


def test_log_matches(client):
    data = client.get("/api/sessions/s-basic/log", params={"q": "abc1234"}).json()
    by_i = {e["i"]: e for e in data["entries"]}
    assert [by_i[i]["kind"] for i, _ in data["matches"]] == ["tool_result"]
    assert "matches" not in client.get("/api/sessions/s-basic/log").json()


def test_search_unavailable(claude_dir, monkeypatch):
    def broken(path):
        raise sqlite3.OperationalError("no such tokenizer: trigram")

    monkeypatch.setattr("cc_calendar.server.SearchIndex", broken)
    with TestClient(create_app(claude_dir, watch=False), base_url="http://127.0.0.1") as c:
        assert c.get("/api/search", params={"q": "README"}).status_code == 503
        assert c.get("/api/sessions").status_code == 200


def test_unreadable_index_path_falls_back_to_memory(claude_dir, tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root can write anywhere")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        app = create_app(claude_dir, watch=False, index_path=locked / "sub" / "search.db")
        with TestClient(app, base_url="http://127.0.0.1") as c:
            assert c.app.state.store.index.wait_idle(10)
            assert c.app.state.store.index.path is None
            assert "s-basic" in c.get("/api/search", params={"q": "README"}).json()["hits"]
    finally:
        locked.chmod(0o700)
        shutil.rmtree(locked)
