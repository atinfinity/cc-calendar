import pytest
from fastapi.testclient import TestClient

from cc_calendar import __version__
from cc_calendar.server import create_app
from cc_calendar.store import ClaudeDir


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


def test_content_security_policy(client):
    # Nothing from other hosts may load, e.g. an image linked in a transcript.
    for path in ("/", "/static/app.js", "/api/sessions"):
        csp = client.get(path).headers["content-security-policy"]
        assert "default-src 'self'" in csp and "img-src 'self' data:" in csp


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
    assert [(c["sha"], c["subject"]) for c in basic["commit_list"]] == [("abc1234", "Add README")]
    assert by_id["s-next"]["continued_from"] == "s-prev"
    assert by_id["s-prev"]["continued_in"] == "s-next"
    assert by_id["s-next"]["cost"] == 1.25 and by_id["s-next"]["cost_estimated"] is False
    assert "readme" in basic["search"].lower()
    assert basic["version"] == "2.1.0"  # Claude Code version from the log
    assert data["version"] == __version__
    assert basic["source"] == "local"
    # Output for cost per commit / PR / line.
    assert basic["files_changed"] == 1
    assert basic["pr_list"] == []
    assert basic["lines_added"] is None and basic["lines_removed"] is None
    nxt = by_id["s-next"]
    assert nxt["pr_list"] == [{"number": 7, "url": "https://github.com/o/demo/pull/7"}]
    assert (nxt["lines_added"], nxt["lines_removed"]) == (3, 1)
    assert nxt["files_changed"] == 0
    assert [d["name"] for d in data["claude_dirs"]] == ["local"]


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


def test_tools(client):
    sessions = client.get("/api/sessions").json()["sessions"]
    start = min(s["start"] for s in sessions)
    end = max(s["end"] for s in sessions) + 1
    res = client.post(
        "/api/tools", json={"start": start, "end": end, "sessions": ["s-sub", "missing"]}
    )
    data = res.json()
    assert [t["name"] for t in data["tools"]] == ["Agent"]
    assert [(a["type"], a["runs"]) for a in data["subagents"]] == [("Explore", 1)]


@pytest.fixture
def multi_client(claude_dir, laptop_dir):
    dirs = [ClaudeDir("local", claude_dir), ClaudeDir("laptop", laptop_dir)]
    with TestClient(create_app(dirs, watch=False), base_url="http://127.0.0.1") as c:
        yield c


def test_sessions_from_several_dirs(multi_client, claude_dir, laptop_dir):
    data = multi_client.get("/api/sessions").json()
    assert data["claude_dirs"] == [
        {"name": "local", "path": str(claude_dir)},
        {"name": "laptop", "path": str(laptop_dir)},
    ]
    by_id = {s["id"]: s for s in data["sessions"]}
    assert by_id["s-laptop"]["source"] == "laptop"
    assert by_id["s-basic"]["source"] == "local"  # the newer of the two copies

    d = multi_client.get("/api/sessions/s-laptop").json()
    assert d["source"] == "laptop" and d["also_in"] == []
    assert multi_client.get("/api/sessions/s-basic").json()["also_in"] == ["laptop"]
    log = multi_client.get("/api/sessions/s-laptop/log").json()
    assert log["entries"][0]["kind"] == "user"
    assert multi_client.get("/api/sessions/s-laptop/stats").json()["prompts"] == 1
