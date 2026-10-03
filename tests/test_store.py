import json
import os

from conftest import PROJECT, LogBuilder

from cc_calendar.store import Store


def test_scan(claude_dir):
    store = Store(claude_dir)
    store.scan()
    assert set(store.sessions) == {"s-basic", "s-sub", "s-prev", "s-next", "s-empty"}

    sub = store.sessions["s-sub"]
    assert set(sub.subagents) == {"a1"}  # the dangling symlink is skipped
    a1 = sub.subagents["a1"]
    assert a1.agent_type == "Explore"
    assert a1.tool_use_id == "t-agent"
    assert a1.status == "completed"
    assert len(a1.usages) == 2
    assert sub.tokens() > sum(u.total for u in sub.usages.values())

    assert store.continued_from() == {"s-next": "s-prev"}
    nxt = store.sessions["s-next"]
    assert [p["text"] for p in nxt.prompts] == ["Carry on"]
    assert nxt.state(None)[0] == "done"
    assert store.sessions["s-prev"].state(None)[0] == "interrupted"


def test_incremental_reads(claude_dir):
    store = Store(claude_dir)
    store.scan()
    path = claude_dir / "projects" / PROJECT / "s-basic.jsonl"
    b = LogBuilder("s-basic")
    b._n = 1000  # fresh uuids
    b.prompt(30, "Another request")
    line = json.dumps(b.records[0]) + "\n"

    # A partially written line is not consumed until it is complete.
    with open(path, "a") as f:
        f.write(line[:20])
    store.update_file(path)
    assert len(store.sessions["s-basic"].prompts) == 1
    with open(path, "a") as f:
        f.write(line[20:])
    assert store.update_file(path) == "s-basic"
    assert len(store.sessions["s-basic"].prompts) == 2


def test_rewritten_file_is_reparsed(claude_dir):
    store = Store(claude_dir)
    store.scan()
    path = claude_dir / "projects" / PROJECT / "s-sub.jsonl"
    b = LogBuilder("s-sub")
    b.prompt(0, "only")
    b.write(path)  # shorter than before
    store.update_file(path)
    s = store.sessions["s-sub"]
    assert [p["text"] for p in s.prompts] == ["only"]
    assert "a1" in s.subagents  # subagent data survives the rebuild


def test_live_sessions(claude_dir):
    sessions = claude_dir / "sessions"
    (sessions / "1.json").write_text(
        json.dumps({"pid": os.getpid(), "sessionId": "s-basic", "status": "busy"})
    )
    (sessions / "2.json").write_text(json.dumps({"pid": 2**22 + 12345, "sessionId": "s-sub"}))
    (sessions / "3.json").write_text("not json")
    live = Store(claude_dir).live_sessions()
    assert set(live) == {"s-basic"}


def test_missing_claude_dir(tmp_path):
    store = Store(tmp_path / "nope")
    store.scan()
    assert store.sessions == {}
    assert store.live_sessions() == {}
