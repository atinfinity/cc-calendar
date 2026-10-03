import pytest
from fastapi.testclient import TestClient

from cc_calendar.server import create_app


@pytest.fixture
def client(claude_dir):
    with TestClient(create_app(claude_dir, watch=False), base_url="http://127.0.0.1") as c:
        yield c


def test_rejects_foreign_host(client):
    assert client.get("/api/sessions", headers={"Host": "localhost:8000"}).status_code == 200
    assert client.get("/api/sessions", headers={"Host": "evil.example:8000"}).status_code == 400


def test_index_and_static(client):
    res = client.get("/")
    assert res.status_code == 200 and "cc-calendar" in res.text
    assert res.headers["cache-control"] == "no-cache"
    js = client.get("/static/app.js")
    assert js.status_code == 200
    assert js.headers["cache-control"] == "no-cache"


def test_sessions(client):
    data = client.get("/api/sessions", params={"gap": 15}).json()
    by_id = {s["id"]: s for s in data["sessions"]}
    # Sessions without any timestamped activity cannot be placed on the calendar.
    assert set(by_id) == {"s-basic", "s-sub", "s-prev", "s-next"}
    basic = by_id["s-basic"]
    assert basic["title"] == "Write the README"
    assert basic["project_name"] == "demo"
    assert basic["status"] == "done"
    assert basic["cost_estimated"] is True
    assert basic["prompt_count"] == 1
    assert len(basic["segments"]) == 1
    assert by_id["s-next"]["continued_from"] == "s-prev"
    assert by_id["s-prev"]["continued_in"] == "s-next"
    assert by_id["s-next"]["cost"] == 1.25 and by_id["s-next"]["cost_estimated"] is False
    assert "readme" in basic["search"].lower()


def test_session_detail(client):
    d = client.get("/api/sessions/s-basic").json()
    assert d["files"] == [{"path": "/work/demo/README.md", "count": 1}]
    assert d["commits"][0]["subject"] == "Add README"
    # Commits are attributed to the prompt that preceded them.
    assert d["prompts"][0]["commits"] == [d["commits"][0]["sha"] or "Add README"]
    assert d["checks"]["committed"] is None  # /work/demo is not a git repository here
    sub = client.get("/api/sessions/s-sub").json()
    assert [a["id"] for a in sub["subagents"]] == ["a1"]
    assert sub["subagents"][0]["has_log"] is True
    assert client.get("/api/sessions/nope").status_code == 404


def test_log(client):
    log = client.get("/api/sessions/s-basic/log").json()
    kinds = [e["kind"] for e in log["entries"]]
    assert kinds[0] == "user"
    assert "thinking" in kinds and "tool_use" in kinds and "tool_result" in kinds
    assert log["total"] == len(log["entries"])
    page = client.get("/api/sessions/s-basic/log", params={"offset": 1, "limit": 2}).json()
    assert [e["i"] for e in page["entries"]] == [1, 2]

    agent = client.get("/api/sessions/s-sub/log", params={"agent": "a1"}).json()
    assert [e["text"] for e in agent["entries"]] == ["searching", "found it"]
    assert client.get("/api/sessions/s-sub/log", params={"agent": "zzz"}).status_code == 404


def test_stats(client):
    st = client.get("/api/sessions/s-basic/stats").json()
    assert st["prompts"] == 1 and st["requests"] == 3
    assert {t["name"]: t["calls"] for t in st["tools"]} == {"Write": 1, "Bash": 1}
    assert st["tokens"]["output"] == 50 + 10 + 10  # the split message m1 counts once
    assert st["thinking_blocks"] == 1
    assert [m["model"] for m in st["models"]] == ["claude-sonnet-5-5"]
    assert st["end"] - st["start"] == 5 * 60_000 and st["active_ms"] == 5 * 60_000

    agent = client.get("/api/sessions/s-sub/stats", params={"agent": "a1"}).json()
    assert agent["requests"] == 2 and agent["models"][0]["model"] == "claude-haiku-4-5"
    assert client.get("/api/sessions/s-sub/stats", params={"agent": "zzz"}).status_code == 404
