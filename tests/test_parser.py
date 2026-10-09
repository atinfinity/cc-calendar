import pytest
from conftest import BASE, LogBuilder, basic_session

from cc_calendar.logview import build_entries, log_events
from cc_calendar.parser import (
    DENSITY_BUCKET_MS,
    SessionAcc,
    classify_user,
    command_text,
    extract_commit_subject,
    parse_ts,
)
from cc_calendar.pricing import estimate_cost, price_for

T0 = int(BASE.timestamp() * 1000)
MIN = 60_000


def feed(builder: LogBuilder) -> SessionAcc:
    s = SessionAcc(session_id=builder.sid, path="x.jsonl", project_dir="p")
    for r in builder.records:
        s.feed(r)
    return s


def test_parse_ts():
    assert parse_ts("2026-09-28T09:00:00Z") == T0
    assert parse_ts("2026-09-28T09:00:00.500Z") == T0 + 500
    assert parse_ts(None) is None
    assert parse_ts("garbage") is None


def test_classify_user():
    b = LogBuilder("s")
    assert classify_user(b.prompt(0, "hello")) == "prompt"
    assert classify_user(b.command(0, "/review", "42")) == "command"
    assert classify_user(b.interrupt(0)) == "interrupt"
    assert classify_user(b.tool_result(0, "t", "out")) == "tool_result"
    meta = b.prompt(0, "<local-command-stdout>hi</local-command-stdout>")
    assert classify_user(meta) == "meta"
    no_origin = b.prompt(0, "caveat")
    del no_origin["origin"]
    assert classify_user(no_origin) == "meta"
    note = b.prompt(0, "<task-notification><task-id>x</task-id></task-notification>")
    note["origin"] = {"kind": "task-notification"}
    assert classify_user(note) == "notification"
    compact = b.prompt(0, "summary")
    compact["isCompactSummary"] = True
    assert classify_user(compact) == "compact"


PASTED = (
    '\n\n<pasted_content id="ab12">\nhttps://example.com/a\n</pasted_content id="ab12">\n\n see'
)


def test_pasted_content_is_a_prompt():
    b = LogBuilder("s")
    b.prompt(0, PASTED)
    b.prompt(1, 'look at <pasted_content id="cd34">\nlog line\n</pasted_content id="cd34">')
    assert classify_user(b.records[0]) == "prompt"
    s = feed(b)
    texts = [p["text"] for p in s.prompts]
    assert texts == ["https://example.com/a\n\n\n see", "look at \nlog line"]
    assert s.title() == "https://example.com/a"
    # Claude Code's own wrappers stay meta even with a human origin.
    for text in ("<system-reminder>x</system-reminder>", "<bash-stdout>ok</bash-stdout>"):
        assert classify_user(b.prompt(2, text)) == "meta"
    # Pasted-looking text without a human origin is not a prompt.
    queued = b.prompt(3, PASTED)
    del queued["origin"]
    assert classify_user(queued) == "meta"


def desktop(b: LogBuilder, text: str, **extra) -> dict:
    rec = b.prompt(0, text)
    del rec["origin"]
    rec.update({"entrypoint": "claude-desktop", "promptSource": "sdk", **extra})
    return rec


def test_claude_desktop_prompts():
    b = LogBuilder("s")
    assert classify_user(desktop(b, "how do I build one package?")) == "prompt"
    assert classify_user(desktop(b, PASTED)) == "prompt"
    assert classify_user(desktop(b, "hi", promptSource="system")) == "meta"
    assert classify_user(desktop(b, "caveat", isMeta=True)) == "meta"
    assert classify_user(desktop(b, "<local-command-stdout>x</local-command-stdout>")) == "meta"
    result = desktop(b, "")
    result["message"]["content"] = [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]
    assert classify_user(result) == "tool_result"
    # A CLI record without `origin` is still synthetic.
    cli = desktop(b, "caveat", entrypoint="cli", promptSource=None)
    assert classify_user(cli) == "meta"


def test_command_text():
    text = "<command-name>/review</command-name>\n<command-args>42</command-args>"
    assert command_text(text) == "/review 42"
    assert (
        command_text("<command-name>/clear</command-name><command-args></command-args>") == "/clear"
    )


def test_extract_commit_subject():
    assert extract_commit_subject('git commit -m "Fix bug"') == "Fix bug"
    assert extract_commit_subject("git commit -m 'Single quoted'") == "Single quoted"
    heredoc = "git commit -m \"$(cat <<'EOF'\nAdd feature\n\nBody text\nEOF\n)\""
    assert extract_commit_subject(heredoc) == "Add feature"
    assert extract_commit_subject("git commit --amend --no-edit") is None


def test_basic_session():
    s = feed(basic_session())
    assert s.title() == "Write the README"
    assert [p["text"] for p in s.prompts] == ["Add a README"]
    assert s.cwd == "/work/demo" and s.git_branch == "main"
    # The split message m1 counts once, with the larger output figure.
    assert set(s.usages) == {"m1", "m2", "m3"}
    assert s.usages["m1"].usage["output_tokens"] == 50
    assert s.files["/work/demo/README.md"] == 1
    assert [(c["sha"], c["subject"]) for c in s.commits] == [("abc1234", "Add README")]
    status, checks = s.state(None)
    assert status == "done"
    assert checks == {"turn_ended": True, "no_background": True, "clean_exit": False}


def test_commit_without_hash_keeps_subject():
    b = LogBuilder("s")
    b.prompt(0, "commit")
    b.tool_use(1, "t1", "Bash", {"command": 'git commit -m "Quiet commit"'}, msg_id="m1")
    b.tool_result(2, "t1", "ok")  # output filtered: no "[branch sha]" line
    s = feed(b)
    assert s.commits[0]["sha"] is None
    assert s.commits[0]["subject"] == "Quiet commit"


def test_commit_from_git_operation_and_failed_commit():
    b = LogBuilder("s")
    b.tool_use(1, "t1", "Bash", {"command": "git commit -m x"}, msg_id="m1")
    b.tool_result(2, "t1", "", {"gitOperation": {"commit": {"sha": "deadbeef", "branch": "dev"}}})
    b.tool_use(3, "t2", "Bash", {"command": "git commit -m y"}, msg_id="m2")
    b.tool_result(4, "t2", "nothing to commit", is_error=True)
    s = feed(b)
    assert [(c["sha"], c["branch"], c["subject"]) for c in s.commits] == [("deadbeef", "dev", "x")]


def test_interrupted_session():
    b = LogBuilder("s")
    b.prompt(0, "go")
    b.tool_use(1, "t1", "Bash", {"command": "sleep 100"}, msg_id="m1")
    b.interrupt(2)
    status, checks = feed(b).state(None)
    assert status == "interrupted"
    assert checks["turn_ended"] is False


def test_unfinished_turn_is_interrupted_unless_live():
    b = LogBuilder("s")
    b.prompt(0, "go")
    b.tool_use(1, "t1", "Bash", {"command": "make"}, msg_id="m1")
    s = feed(b)
    assert s.state(None)[0] == "interrupted"
    assert s.state({"status": "busy"})[0] == "running"
    assert s.state({"status": "idle"})[0] == "waiting"


def test_background_tasks():
    b = LogBuilder("s")
    b.prompt(0, "serve")
    b.tool_use(
        1, "t1", "Bash", {"command": "npm run dev", "description": "Dev server"}, msg_id="m1"
    )
    b.tool_result(2, "t1", "started", {"backgroundTaskId": "bg1"})
    b.assistant(3, [{"type": "text", "text": "running"}], msg_id="m2", stop_reason="end_turn")
    b.turn_end(3)
    s = feed(b)
    assert s.background["bg1"] == {"id": "bg1", "status": "running", "description": "Dev server"}
    # Still running while the session is alive...
    assert s.state({"status": "idle"})[1]["no_background"] is False
    # ...but a dead session's leftover task was killed with it.
    assert s.state(None) == (
        "done",
        {"turn_ended": True, "no_background": True, "clean_exit": False},
    )

    note = (
        "<task-notification>\n<task-id>bg1</task-id>\n<status>failed</status>\n"
        "<summary>exit 1</summary>\n</task-notification>"
    )
    b.meta("attachment", uuid="att1", attachment={"type": "queued_command", "prompt": note})
    s = feed(b)
    assert s.background["bg1"]["status"] == "failed"
    assert s.background["bg1"]["summary"] == "exit 1"


def test_pending_background_agents_mean_interrupted():
    b = LogBuilder("s")
    b.prompt(0, "go")
    b.assistant(1, [{"type": "text", "text": "x"}], msg_id="m1", stop_reason="end_turn")
    b.turn_end(1, pending_background=2)
    assert feed(b).state(None)[0] == "interrupted"


def test_continued_copy_is_skipped():
    prev = LogBuilder("old")
    prev.prompt(0, "first")
    nxt = LogBuilder("new")
    nxt.records.extend(prev.records)
    nxt.prompt(10, "second")
    s = feed(nxt)
    assert [p["text"] for p in s.prompts] == ["second"]


def test_duplicate_uuids_are_ignored():
    b = LogBuilder("s")
    rec = b.prompt(0, "once")
    b.records.append(dict(rec))
    assert len(feed(b).prompts) == 1


def test_synthetic_messages_excluded():
    b = LogBuilder("s")
    b.assistant(0, [{"type": "text", "text": "API Error"}], msg_id="e1", model="<synthetic>")
    s = feed(b)
    assert s.usages == {} and s.activity == []


def test_segments_and_density():
    b = LogBuilder("s")
    for minute in (0, 5, 10, 60, 62):
        b.prompt(minute, f"p{minute}")
    s = feed(b)
    assert s.segments(15 * MIN) == [[T0, T0 + 10 * MIN], [T0 + 60 * MIN, T0 + 62 * MIN]]
    assert len(s.segments(5 * MIN)) == 2
    assert len(s.segments(1 * MIN)) == 5
    bucket = T0 // DENSITY_BUCKET_MS
    assert s.density() == {bucket: 2, bucket + 1: 1, bucket + 6: 2}


def test_cost_density_sums_to_estimate():
    s = feed(basic_session())
    density = s.cost_density()
    assert density and all(b == int(b) for b in density)
    assert sum(density.values()) == pytest.approx(s.cost()[0], abs=1e-5)


def test_title_fallbacks():
    b = LogBuilder("s")
    assert feed(b).title() == "(untitled session)"
    b.prompt(0, "first line\nsecond line")
    assert feed(b).title() == "first line"
    b.meta("agent-name", agentName="named")
    assert feed(b).title() == "named"


def test_cost_prefers_cost_state():
    b = basic_session()
    s = feed(b)
    cost, estimated = s.cost()
    assert estimated and cost > 0
    b.meta("cost-state", totalCostUSD=2.5)
    assert feed(b).cost() == (2.5, False)


def test_pricing():
    assert price_for("claude-sonnet-5-5").input == 2
    assert price_for("claude-opus-4-7[1m]").input == 5
    assert price_for("unknown-model") is None
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    assert estimate_cost("claude-haiku-4-5", usage) == 6.0
    assert estimate_cost(None, usage) == 0.0


def test_context_pct():
    b = LogBuilder("s")
    b.assistant(0, [], msg_id="m1", usage={"input_tokens": 0, "cache_read_input_tokens": 100_000})
    assert feed(b).context_pct() == 10.0  # 1M-token window


def test_project_is_launch_directory():
    b = LogBuilder("s")
    b.prompt(0, "start")
    b.prompt(1, "later")["cwd"] = "/work/demo/sub/dir"
    assert feed(b).cwd == "/work/demo"


def test_cache_stats():
    b = LogBuilder("s")
    usage = {
        "input_tokens": 100,
        "cache_creation_input_tokens": 100,
        "cache_read_input_tokens": 800,
    }
    b.assistant(0, [], msg_id="m1", model="claude-sonnet-5-5", usage=usage)
    hit, saved = feed(b).cache_stats()
    assert hit == 0.8
    # 800 reads at $2.00 - $0.20, minus 100 writes at the $0.50 premium, per million tokens.
    assert saved == pytest.approx((800 * 1.8 - 100 * 0.5) / 1e6)
    assert SessionAcc(session_id="e", path="x", project_dir="p").cache_stats() == (None, 0)


def test_marks():
    b = basic_session()
    b._base("system", 3, subtype="compact_boundary")
    b.assistant(4, [{"type": "text", "text": "API Error"}], msg_id="e1", model="<synthetic>")
    s = feed(b)
    kinds = [m[1] for m in s.marks()]
    assert kinds.count("prompt") == 1 and kinds.count("commit") == 1
    assert (T0 + 3 * MIN, "compact", {}) in s.marks()
    assert (T0 + 4 * MIN, "error") in s.marks()
    assert [m[0] for m in s.marks()] == sorted(m[0] for m in s.marks())


def test_log_events_match_marks(tmp_path):
    b = basic_session()
    b._base("system", 3, subtype="compact_boundary")
    b.assistant(4, [{"type": "text", "text": "API Error"}], msg_id="e1", model="<synthetic>")
    entries = build_entries(b.write(tmp_path / "s.jsonl"), b.sid)
    events = log_events(entries)
    assert sorted(k for _, _, k in events) == sorted(m[1] for m in feed(b).marks())
    for i, _, kind in events:
        assert entries[i]["event"] == kind
    commit = next(entries[i] for i, _, k in events if k == "commit")
    assert commit["kind"] == "tool_use" and commit["name"] == "Bash"


def test_effort_mix():
    b = basic_session()
    b.assistant(5, [{"type": "text", "text": "a"}], msg_id="x1", effort="low")
    b.assistant(5.1, [{"type": "text", "text": "a"}], msg_id="x1", effort="low")  # same request
    b.assistant(6, [{"type": "text", "text": "b"}], msg_id="x2", effort="high")
    b.assistant(7, [{"type": "text", "text": "c"}], msg_id="x3", effort="low")
    s = feed(b)
    assert s.effort_mix() == {"high": 1, "low": 2}
    assert s.effort() == "low"
    assert feed(basic_session()).effort() is None


def test_compaction_sizes(tmp_path):
    b = basic_session()
    meta = {"trigger": "auto", "preTokens": 167_000, "postTokens": 31_000}
    b._base("system", 3, subtype="compact_boundary", compactMetadata=meta)
    s = feed(b)
    info = {"trigger": "auto", "pre": 167_000, "post": 31_000}
    assert s.compactions == [{"ts": T0 + 3 * MIN, **info}]
    assert (T0 + 3 * MIN, "compact", info) in s.marks()
    entries = build_entries(b.write(tmp_path / "s.jsonl"), b.sid)
    compact = next(e for e in entries if e.get("event") == "compact")
    assert (compact["pre"], compact["post"], compact["trigger"]) == (167_000, 31_000, "auto")
