import json
import os
import shutil

import pytest
from conftest import BASE, PROJECT, LogBuilder, basic_session, continuation, cost_totals

from cc_calendar import store as store_mod
from cc_calendar.parser import SessionAcc
from cc_calendar.pricing import estimate_cost
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


def continued_chain(proj, totals: list[tuple[float, int, int]]) -> list[str]:
    """Write sessions c0 -> c1 -> ..., each with the given cumulative cost-state totals.

    Each log starts with a copy of its predecessor's, as Claude Code writes them.
    """
    sids = [f"c{i}" for i in range(len(totals))]
    copied: list[dict] = []
    for i, (sid, (cost, added, removed)) in enumerate(zip(sids, totals, strict=True)):
        b = LogBuilder(sid)
        b.records.extend(json.loads(json.dumps(r)) for r in copied)
        b.prompt(400 + 10 * i, f"step {i}")
        b.assistant(401 + 10 * i, [], msg_id=f"{sid}-m", stop_reason="end_turn")
        b.meta("cost-state", **cost_totals(cost, added, removed))
        if i + 1 < len(sids):
            b.meta("continued-in", continuedInSessionId=sids[i + 1])
        b.write(proj / f"{sid}.jsonl")
        copied = b.records
    return sids


def own(store: Store, sid: str) -> tuple:
    s = store.sessions[sid]
    return round(s.cost()[0], 4), s.cost_basis(), s.own_lines()


def test_continued_cost_is_own_share(claude_dir):
    store = Store(claude_dir)
    store.scan()
    assert own(store, "s-prev") == (0.75, "record", (2, 0))
    assert own(store, "s-next") == (1.25, "continued", (3, 1))
    assert store.sessions["s-next"].own_cost_state()["totalDuration"] == 1000  # per session


def test_continued_chain(claude_dir):
    proj = claude_dir / "projects" / PROJECT
    continued_chain(proj, [(1.0, 10, 2), (3.5, 15, 2), (4.0, 15, 7)])
    store = Store(claude_dir)
    store.scan()
    assert own(store, "c0") == (1.0, "record", (10, 2))
    assert own(store, "c1") == (2.5, "continued", (5, 0))
    assert own(store, "c2") == (0.5, "continued", (0, 5))


def test_continued_from_deleted_log(claude_dir):
    proj = claude_dir / "projects" / PROJECT
    continued_chain(proj, [(1.0, 10, 2), (3.5, 15, 2), (4.0, 15, 7)])
    (proj / "c0.jsonl").unlink()
    (proj / "s-prev.jsonl").unlink()
    store = Store(claude_dir)
    store.scan()
    # The copied records still tell that these continue a session; their share is estimated.
    nxt = store.sessions["s-next"]
    assert nxt.predecessor == "s-prev"
    cost, estimated = nxt.cost()
    assert estimated and 0 < cost < 1.25
    assert nxt.cost_basis() == "no_previous" and nxt.own_lines() == (None, None)
    assert store.sessions["c1"].cost_basis() == "no_previous"
    assert own(store, "c2") == (0.5, "continued", (0, 5))


def test_continued_from_deleted_log_with_rewritten_ids(claude_dir):
    # Newer continuations copy their predecessor's records under their own session ID, so
    # once the predecessor's log is gone only the size of the record gives it away.
    proj = claude_dir / "projects" / PROJECT
    continued_chain(proj, [(30.0, 500, 20), (31.0, 510, 20)])
    c1 = proj / "c1.jsonl"
    recs = [json.loads(line) for line in c1.read_text().splitlines()]
    c1.write_text("".join(json.dumps({**r, "sessionId": "c1"}) + "\n" for r in recs))
    (proj / "c0.jsonl").unlink()
    store = Store(claude_dir)
    store.scan()
    s = store.sessions["c1"]
    assert s.predecessor is None and s.copied_from is None
    assert s.cost_basis() == "cumulative" and s.cost()[1] and s.own_lines() == (None, None)


def test_continued_cost_below_predecessor(claude_dir):
    proj = claude_dir / "projects" / PROJECT
    continued_chain(proj, [(2.0, 10, 2), (1.5, 12, 2)])
    store = Store(claude_dir)
    store.scan()
    s = store.sessions["c1"]
    assert s.cost_basis() == "negative" and s.cost()[1] is True
    assert s.own_lines() == (None, None)


@pytest.mark.parametrize("rewritten", [False, True])
def test_continuation_later_resumed(claude_dir, rewritten):
    # c1 continues c0, exits, and is resumed later: its last record is that run's alone.
    proj = claude_dir / "projects" / PROJECT
    continued_chain(proj, [(1.0, 10, 2), (3.5, 15, 2)])
    c1 = proj / "c1.jsonl"
    recs = [json.loads(line) for line in c1.read_text().splitlines()]
    if rewritten:  # newer continuations copy their predecessor's records under their own ID
        recs = [{**r, "sessionId": "c1"} for r in recs]
    resumed = LogBuilder("c1")
    resumed.prompt(2000, "Resume")
    resumed.assistant(2001, [], msg_id="c1-r", stop_reason="end_turn")
    start = int(BASE.timestamp() * 1000) + 1999 * 60_000
    resumed.meta("cost-state", **cost_totals(0.25, 4, 0), startTime=start)
    c1.write_text("".join(json.dumps(r) + "\n" for r in [*recs, *resumed.records]))
    store = Store(claude_dir)
    store.scan()
    s = store.sessions["c1"]
    assert s.predecessor == "c0" and s.cost_basis() == "resumed"
    # The resumed run's record plus c1's first run, not the copy of c0's request.
    first_run = s.usages["c1-m"]
    assert s.earlier_usages() == [first_run]
    assert s.cost() == (pytest.approx(0.25 + estimate_cost(first_run.model, first_run.usage)), True)
    assert s.own_lines() == (None, None)
    assert own(store, "c0") == (1.0, "record", (10, 2))


@pytest.mark.parametrize("first", ["c1", "c0"])
def test_continued_cost_follows_either_log(claude_dir, first):
    proj = claude_dir / "projects" / PROJECT
    continued_chain(proj, [(1.0, 10, 2), (3.5, 15, 2)])
    store = Store(claude_dir)
    # Read the continuation before or after its predecessor.
    for sid in (first, {"c0": "c1", "c1": "c0"}[first]):
        store.update_file(proj / f"{sid}.jsonl")
    assert own(store, "c1") == (2.5, "continued", (5, 0))

    # The predecessor writes a later cost record (e.g. resumed once more): the share shrinks.
    b = LogBuilder("c0")
    b.meta("cost-state", **cost_totals(1.5, 12, 2))
    with open(proj / "c0.jsonl", "a") as f:
        f.write(json.dumps(b.records[0]) + "\n")
    store.update_file(proj / "c0.jsonl")
    assert own(store, "c1") == (2.0, "continued", (3, 0))

    # The continuation's own record grows.
    b = LogBuilder("c1")
    b.meta("cost-state", **cost_totals(5.0, 20, 2))
    with open(proj / "c1.jsonl", "a") as f:
        f.write(json.dumps(b.records[0]) + "\n")
    store.update_file(proj / "c1.jsonl")
    assert own(store, "c1") == (3.5, "continued", (8, 0))


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


def continued_with_copy(proj) -> tuple[LogBuilder, LogBuilder]:
    """n0 continued in n1 the newer way: n1's copy of n0 is under n1's own session ID."""
    prev = basic_session("n0")
    prev.meta("cost-state", **cost_totals(1.0, 10, 2))
    prev.meta("continued-in", continuedInSessionId="n1")
    prev.write(proj / "n0.jsonl")
    nxt = continuation(prev, "n1")
    nxt.prompt(30, "Now the changelog")
    nxt.assistant(31, [{"type": "text", "text": "ok"}], msg_id="n1-m", stop_reason="end_turn")
    nxt.turn_end(31)
    nxt.meta("cost-state", **cost_totals(1.5, 14, 3))
    nxt.write(proj / "n1.jsonl")
    alone = LogBuilder("n1")
    alone.records = nxt.records[len(nxt.records) - 4 :]
    return nxt, alone


def test_continued_with_copy_counts_own_work(claude_dir):
    proj = claude_dir / "projects" / PROJECT
    _, alone = continued_with_copy(proj)
    store = Store(claude_dir)
    store.scan()
    s = store.sessions["n1"]
    assert own(store, "n1") == (0.5, "continued", (4, 1))
    assert [p["text"] for p in s.prompts] == ["Now the changelog"]
    assert s.commits == [] and s.copied_head == 8
    assert s.estimate() == pytest.approx(estimate(alone))
    assert s.marks() == [(s.prompts[0]["ts"], "prompt")]
    assert len(store.sessions["n0"].commits) == 1


def test_continued_with_copy_from_deleted_log(claude_dir):
    # The copy still shows the session continues another, whose totals its record includes.
    proj = claude_dir / "projects" / PROJECT
    _, alone = continued_with_copy(proj)
    (proj / "n0.jsonl").unlink()
    store = Store(claude_dir)
    store.scan()
    s = store.sessions["n1"]
    assert s.predecessor is None
    assert s.cost_basis() == "no_previous" and s.own_lines() == (None, None)
    assert s.cost() == (pytest.approx(estimate(alone)), True)
    assert [p["text"] for p in s.prompts] == ["Now the changelog"]


def estimate(b: LogBuilder) -> float:
    s = SessionAcc(b.sid, "x", "p")
    for r in b.records:
        s.feed(r)
    return s.estimate()
