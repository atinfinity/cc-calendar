import json
import os
import shutil

from conftest import PROJECT, LogBuilder

from cc_calendar import store as store_mod
from cc_calendar.store import ClaudeDir, Store


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


def two_dirs(claude_dir, laptop_dir):
    return [ClaudeDir("local", claude_dir), ClaudeDir("laptop", laptop_dir)]


def test_multiple_dirs(claude_dir, laptop_dir):
    store = Store(two_dirs(claude_dir, laptop_dir))
    store.scan()
    assert "s-laptop" in store.sessions and "s-sub" in store.sessions
    assert store.sessions["s-laptop"].source == "laptop"
    assert store.sessions["s-sub"].source == "local"
    assert store.sessions["s-laptop"].path.startswith(str(laptop_dir))


def test_duplicate_session_keeps_newest_copy(claude_dir, laptop_dir):
    store = Store(two_dirs(claude_dir, laptop_dir))
    store.scan()
    # The laptop copy of s-basic stops before the commit, so the local one is newer.
    assert store.sessions["s-basic"].source == "local"
    assert store.also_in("s-basic") == ["laptop"]
    assert store.also_in("s-laptop") == []

    # Once the laptop copy has later activity, it is shown instead.
    b = LogBuilder("s-basic")
    b._n = 1000
    b.prompt(30, "More work on the laptop")
    path = laptop_dir / "projects" / PROJECT / "s-basic.jsonl"
    with open(path, "a") as f:
        f.write(json.dumps(b.records[0]) + "\n")
    assert store.update_file(path) == "s-basic"
    assert store.sessions["s-basic"].source == "laptop"
    assert store.also_in("s-basic") == ["local"]


def test_duplicate_session_tie_goes_to_first_dir(claude_dir, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(claude_dir, copy, symlinks=True)
    store = Store([ClaudeDir("copy", copy), ClaudeDir("local", claude_dir)])
    store.scan()
    assert store.sessions["s-basic"].source == "copy"
    assert store.also_in("s-basic") == ["local"]


def test_live_sessions_across_dirs(claude_dir, laptop_dir):
    (laptop_dir / "sessions" / "1.json").write_text(
        json.dumps({"pid": os.getpid(), "sessionId": "s-laptop"})
    )
    live = Store(two_dirs(claude_dir, laptop_dir)).live_sessions()
    assert set(live) == {"s-laptop"}


def test_live_sessions_check_start_time(claude_dir, monkeypatch):
    monkeypatch.setattr(store_mod, "_proc_start", lambda pid: "Sun Oct  4 05:53:32 2026")
    sessions = claude_dir / "sessions"
    pid = os.getpid()
    for sid, start in [
        ("s-basic", "Sun Oct  4 05:53:32 2026"),  # same process
        ("s-sub", "Mon Sep 28 09:00:00 2026"),  # another process that had this PID
        ("s-prev", None),  # older Claude Code: PID check only
    ]:
        rec = {"pid": pid, "sessionId": sid, **({"procStart": start} if start else {})}
        (sessions / f"{sid}.json").write_text(json.dumps(rec))
    assert set(Store(claude_dir).live_sessions()) == {"s-basic", "s-prev"}


def test_live_sessions_without_ps(claude_dir, monkeypatch):
    monkeypatch.setattr(store_mod, "_proc_start", lambda pid: None)
    (claude_dir / "sessions" / "1.json").write_text(
        json.dumps({"pid": os.getpid(), "sessionId": "s-basic", "procStart": "whenever"})
    )
    assert set(Store(claude_dir).live_sessions()) == {"s-basic"}


def test_proc_start_of_this_process():
    start = store_mod._proc_start(os.getpid())
    assert start is None or len(start.split()) == 5  # e.g. "Sun Oct  4 05:53:32 2026"
