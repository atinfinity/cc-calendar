import pytest
from conftest import BASE, PROJECT, LogBuilder, continuation, cost_totals, parse_minute, ts
from fastapi.testclient import TestClient

from cc_calendar.parser import SessionAcc, pr_create_args, pr_create_calls
from cc_calendar.prcosts import Attribution, pr_costs
from cc_calendar.server import create_app
from cc_calendar.store import Store

T0 = int(BASE.timestamp() * 1000)
MIN = 60_000
GAP = 15 * MIN
REPO = "https://github.com/o/demo"


def feed(builder: LogBuilder) -> SessionAcc:
    s = SessionAcc(session_id=builder.sid, path="x.jsonl", project_dir="p", cwd=None)
    for r in builder.records:
        s.feed(r)
    return s


def on_branch(b: LogBuilder, branch: str, since: float = 0) -> LogBuilder:
    """Record `branch` as the git branch from minute `since` on."""
    for r in b.records:
        m = parse_minute(r)
        if m is not None and m >= since:
            r["gitBranch"] = branch
    return b


def work(b: LogBuilder, minute: float, n: int, tag: str) -> None:
    """A prompt and `n` equally priced requests, one a minute after it."""
    b.prompt(minute, f"Work on {tag}")
    for i in range(n):
        b.assistant(minute + 1 + i, [{"type": "text", "text": "ok"}], msg_id=f"{tag}-{i}")


def open_pr(b: LogBuilder, minute: float, number: int, title: str, head: str | None = None) -> None:
    """`gh pr create` run at `minute`, as Claude Code records it, and the pr-link after it."""
    url = f"{REPO}/pull/{number}"
    cmd = f'git push -u origin HEAD && gh pr create --title "{title}" --body "Body"'
    if head:
        cmd += f" --head {head}"
    b.tool_use(minute, f"t-pr{number}", "Bash", {"command": cmd}, msg_id=f"pr-{number}")
    tur = {
        "stdout": url,
        "gitOperation": {"pr": {"action": "created", "number": number, "url": url}},
    }
    b.tool_result(minute + 0.5, f"t-pr{number}", url, tur)
    b.meta("pr-link", prNumber=number, prUrl=url, prRepository="o/demo", timestamp=ts(minute + 0.5))


def attribute(*sessions: SessionAcc, previous: dict | None = None) -> dict:
    attr = Attribution({s.session_id: s for s in sessions}, previous or {}, GAP)
    return pr_costs(attr, [s.session_id for s in sessions])


def by_number(out: dict) -> dict:
    return {p["number"]: p for p in out["prs"]}


def test_pr_create_args():
    assert pr_create_args('gh pr create --title "Fix it" --body x') == ("Fix it", None)
    assert pr_create_args("gh pr create -t 'Add it' -H me:feat") == ("Add it", "feat")
    assert pr_create_args("gh pr create --head=feat --fill") == (None, "feat")
    title = 'gh pr create --title "$(git log -1 --format=%s)"'
    assert pr_create_args(title) == (None, None)
    assert pr_create_args('git commit -m "--title x"') == (None, None)
    # Shell variables are not known from the command; single quotes keep a "$" as it is.
    assert pr_create_args('gh pr create --title "$t" --head "$br"') == (None, None)
    assert pr_create_args("gh pr create -t ${TITLE} -H $BRANCH") == (None, None)
    assert pr_create_args("gh pr create -t 'Costs in $' -H feat") == ("Costs in $", "feat")
    assert pr_create_args('gh pr create -t "Save $5 a month"') == (None, None)
    assert pr_create_args(r'gh pr create -t "Save \$5 a month"') == ("Save $5 a month", None)


def test_pr_create_calls():
    cmd = (
        'gh pr create -H one -t "First" -F a.md && '
        "u=$(gh pr create --head two --title 'Second'); echo $u"
    )
    assert pr_create_calls(cmd) == [("First", "one"), ("Second", "two")]
    assert pr_create_args(cmd) == (None, None)
    assert pr_create_calls("gh pr list") == []
    # A body that mentions the command, as text or in a here-document, is not a call.
    body = "gh pr create -t 'Doc' --body \"Use \\`gh pr create\\` to open one\""
    assert pr_create_calls(body) == [("Doc", None)]
    heredoc = "gh pr create -t 'Doc' -F - <<'EOF'\ngh pr create opens a PR\nEOF"
    assert pr_create_calls(heredoc) == [("Doc", None)]


def test_several_prs_in_one_command():
    """Claude Code's result names one of the PRs; the printed links pair with the calls."""
    b = LogBuilder("s1")
    work(b, 0, 2, "a")
    urls = [f"{REPO}/pull/{n}" for n in (21, 22)]
    cmd = 'gh pr create -H one -t "First" -F a.md && gh pr create -H two -t "Second" -F b.md'
    b.tool_use(5, "t-two", "Bash", {"command": cmd}, msg_id="pr-two")
    tur = {"gitOperation": {"pr": {"action": "created", "number": 22, "url": urls[1]}}}
    b.tool_result(5.5, "t-two", "\n".join(urls), tur)
    s = feed(b)
    assert [(s.prs[u]["number"], s.prs[u]["title"], s.prs[u]["head"]) for u in urls] == [
        (21, "First", "one"),
        (22, "Second", "two"),
    ]
    # Without one link per call, which call opened the PR is not known.
    c = LogBuilder("s2")
    c.tool_use(5, "t-x", "Bash", {"command": cmd}, msg_id="pr-x")
    c.tool_result(5.5, "t-x", urls[1], tur)
    pr = feed(c).prs[urls[1]]
    assert pr["title"] is None and pr["head"] is None and pr["created"] is not None
    # One call in a loop that opened both: neither is known.
    loop = LogBuilder("s3")
    cmd = 'for b in one two; do gh pr create -H "$b" -t "Same title"; done'
    loop.tool_use(5, "t-l", "Bash", {"command": cmd, "description": "x"}, msg_id="pr-l")
    loop.tool_result(5.5, "t-l", "\n".join(urls), tur)
    pr = feed(loop).prs[urls[1]]
    assert pr["title"] is None and pr["head"] is None


def test_parser_records_pr_creation():
    b = LogBuilder("s1")
    work(b, 0, 2, "a")
    open_pr(b, 5, 11, "Add the feature")
    on_branch(b, "feat", since=0)
    s = feed(b)
    pr = s.prs[f"{REPO}/pull/11"]
    assert pr["number"] == 11 and pr["repo"] == "o/demo"
    assert pr["created"] == T0 + 5 * MIN + 30_000
    assert pr["title"] == "Add the feature" and pr["head"] == "feat"
    assert s.branch_at(T0) == "feat"
    # PRs only merged or commented on in a session are not opened there.
    m = LogBuilder("s2")
    m.tool_use(0, "t-m", "Bash", {"command": "gh pr merge 11"}, msg_id="m1")
    tur = {"gitOperation": {"pr": {"action": "merged", "number": 11, "url": f"{REPO}/pull/11"}}}
    m.tool_result(1, "t-m", "merged", tur)
    assert "created" not in feed(m).prs[f"{REPO}/pull/11"]


def test_branch_changes():
    b = LogBuilder("s1")
    work(b, 0, 2, "a")
    work(b, 10, 2, "b")
    on_branch(b, "one", 0)
    on_branch(b, "two", 10)
    s = feed(b)
    assert s.branches == [[T0, "one"], [T0 + 10 * MIN, "two"]]
    assert [s.branch_at(T0 - MIN), s.branch_at(T0 + 9 * MIN), s.branch_at(T0 + 10 * MIN)] == [
        "one",
        "one",
        "two",
    ]


def test_one_session_several_prs():
    # Two requests, PR 1, three requests and the tool call, PR 2, then one more request.
    b = LogBuilder("s1")
    work(b, 0, 2, "a")
    open_pr(b, 3, 1, "First", head="feat-1")
    work(b, 10, 3, "b")
    open_pr(b, 14, 2, "Second", head="feat-2")
    work(b, 30, 1, "c")
    out = attribute(feed(b))
    prs = by_number(out)
    assert [p["number"] for p in out["prs"]] == [2, 1]  # newest first
    # Each `open_pr` adds its own request (the tool call) before the PR.
    assert prs[1]["requests"] == 3 and prs[2]["requests"] == 4
    assert prs[1]["title"] == "First" and prs[1]["head"] == "feat-1"
    assert prs[1]["sessions"] == [{"id": "s1", "cost": prs[1]["cost"]}]
    assert prs[1]["opened_in"] == "s1" and prs[1]["estimated"] is True
    # The request after the last PR is on "main", no PR's head: unattributed.
    assert out["unattributed"]["requests"] == 1 and out["unattributed"]["sessions"] == 1
    total = feed(b).cost()[0]
    assert prs[1]["cost"] + prs[2]["cost"] + out["unattributed"]["cost"] == pytest.approx(total)
    assert prs[2]["cost"] == pytest.approx(total * 4 / 8)
    # Active time: up to PR 1, then the gap before the next prompt and up to PR 2.
    assert prs[1]["active_ms"] == 3.5 * MIN
    assert prs[2]["active_ms"] == (6.5 + 4.5) * MIN


def test_review_fixes_on_the_head_branch():
    opener = LogBuilder("s-open")
    work(opener, 0, 2, "a")
    open_pr(opener, 3, 5, "Feature")
    on_branch(opener, "feat")
    # A later session on the PR's branch, with a commit: review fixes.
    fix = LogBuilder("s-fix")
    work(fix, 60, 2, "fix")
    fix.tool_use(63, "t-c", "Bash", {"command": 'git commit -m "Address review"'}, msg_id="c1")
    fix.tool_result(63.5, "t-c", "[feat abc1234] Address review")
    on_branch(fix, "feat")
    # Another session on another branch.
    other = LogBuilder("s-other")
    work(other, 120, 2, "other")
    on_branch(other, "something-else")
    # A session that worked on the branch before the PR was opened is not a review fix.
    before = LogBuilder("s-before")
    work(before, -60, 1, "early")
    on_branch(before, "feat")
    sessions = [feed(x) for x in (opener, fix, other, before)]
    for s in sessions:
        s.cwd = "/work/demo"  # not a repository: matched by directory
    out = attribute(*sessions)
    pr = by_number(out)[5]
    assert [s["id"] for s in pr["sessions"]] == ["s-open", "s-fix"]
    assert pr["requests"] == 3 + 3
    assert pr["commits"] == 1
    assert out["unattributed"]["sessions"] == 2
    # Another repository's branch of the same name is not this PR's.
    sessions[1].cwd = "/elsewhere"
    assert [s["id"] for s in by_number(attribute(*sessions))[5]["sessions"]] == ["s-open"]


def test_review_fixes_then_a_new_pr():
    opener = LogBuilder("s-open")
    work(opener, 0, 1, "a")
    open_pr(opener, 2, 5, "Feature")
    on_branch(opener, "feat")
    # Fixes for PR 5 on its branch, then a new branch and PR 6 in the same session.
    nxt = LogBuilder("s-next")
    work(nxt, 60, 2, "fix")
    work(nxt, 70, 1, "new")
    open_pr(nxt, 72, 6, "Follow-up")
    on_branch(nxt, "feat")
    on_branch(nxt, "follow-up", since=70)
    prs = by_number(attribute(feed(opener), feed(nxt)))
    assert prs[5]["requests"] == 2 + 2
    assert prs[6]["requests"] == 2
    assert prs[6]["head"] == "follow-up"


def test_branch_reused_for_a_new_pr():
    first = LogBuilder("s-1")
    work(first, 0, 1, "a")
    open_pr(first, 2, 1, "Old")
    on_branch(first, "fix")
    # Days later, the same branch name again: the work leads up to the new PR.
    second = LogBuilder("s-2")
    work(second, 3000, 3, "b")
    open_pr(second, 3004, 2, "New")
    on_branch(second, "fix")
    prs = by_number(attribute(feed(first), feed(second)))
    assert prs[1]["requests"] == 2 and prs[2]["requests"] == 4


def test_own_earlier_pr_gives_way_to_the_next():
    # The session stays on one branch while opening PRs from other worktrees (--head).
    b = LogBuilder("s1")
    work(b, 0, 1, "a")
    open_pr(b, 2, 1, "One")
    work(b, 10, 2, "b")
    open_pr(b, 13, 2, "Two", head="other")
    work(b, 20, 1, "c")
    on_branch(b, "one")
    prs = by_number(attribute(feed(b)))
    assert prs[1]["head"] == "one" and prs[2]["head"] == "other"
    # Work between the two goes to PR 2; after the last one, on PR 1's branch, to PR 1.
    assert prs[2]["requests"] == 3
    assert prs[1]["requests"] == 2 + 1


def test_subagents_count_and_work_for_their_own_pr():
    b = LogBuilder("s1")
    b.prompt(0, "Open two PRs in parallel")
    b.assistant(1, [], msg_id="m1")
    url = f"{REPO}/pull/{{}}"
    # Both subagents report back; the main log links both PRs.
    b.meta("pr-link", prNumber=21, prUrl=url.format(21), prRepository="o/demo", timestamp=ts(8))
    b.meta("pr-link", prNumber=22, prUrl=url.format(22), prRepository="o/demo", timestamp=ts(9))
    b.assistant(30, [], msg_id="m2")
    s = feed(b)
    # Agent a1 opens #22 at minute 9 and agent a2 #21 at minute 8, both working until then.
    for aid, number, end in (("a1", 22, 9), ("a2", 21, 8)):
        agent = LogBuilder("s1")
        for m in range(2, end):
            agent.assistant(m, [], msg_id=f"{aid}-{m}")
        cmd = f'gh pr create --title "Agent {aid}" --head {aid}-branch'
        agent.tool_use(end - 0.5, f"t-{aid}", "Bash", {"command": cmd}, msg_id=f"{aid}-pr")
        tur = {
            "gitOperation": {
                "pr": {"action": "created", "number": number, "url": url.format(number)}
            }
        }
        agent.tool_result(end, f"t-{aid}", url.format(number), tur)
        for r in agent.records:
            s.feed_subagent(aid, f"agent-{aid}.jsonl", r)
    assert s.prs[url.format(22)]["agent"] == "a1"
    assert (
        s.prs[url.format(22)]["title"] == "Agent a1"
        and s.prs[url.format(22)]["head"] == "a1-branch"
    )
    out = attribute(s)
    prs = by_number(out)
    # a1: minutes 2..8 plus its tool call; a2: minutes 2..7 plus its tool call; the main
    # thread's first request goes to the first PR, its last one to none.
    assert prs[22]["requests"] == 8
    assert prs[21]["requests"] == 7 + 1
    assert out["unattributed"]["requests"] == 1


def test_cost_record_is_split():
    b = LogBuilder("s1")
    work(b, 0, 3, "a")
    open_pr(b, 4, 1, "One")
    work(b, 10, 4, "b")
    on_branch(b, "feat")
    on_branch(b, "other", since=10)
    recorded = round(feed(b).estimate() * 1.5, 4)
    b.meta("cost-state", **cost_totals(recorded, 1, 1))
    out = attribute(feed(b))
    # Claude Code's record, split by the estimates: four requests each.
    assert out["prs"][0]["cost"] == pytest.approx(recorded / 2, abs=1e-4)
    assert out["prs"][0]["estimated"] is False
    assert out["unattributed"]["cost"] == pytest.approx(recorded / 2, abs=1e-4)


def test_only_prs_of_the_given_sessions():
    a = LogBuilder("s-a")
    work(a, 0, 1, "a")
    open_pr(a, 2, 1, "A", head="a")
    b = LogBuilder("s-b")
    work(b, 0, 1, "b")
    open_pr(b, 2, 2, "B", head="b")
    sessions = {"s-a": feed(a), "s-b": feed(b)}
    attr = Attribution(sessions, {}, GAP)
    assert [p["number"] for p in pr_costs(attr, ["s-b", "nope"])["prs"]] == [2]
    assert pr_costs(attr, [])["prs"] == []


@pytest.fixture
def pr_dir(tmp_path):
    """Three sessions on disk: one continued in another, which opens a PR, and a review fix."""
    root = tmp_path / ".claude"
    proj = root / "projects" / PROJECT
    prev = LogBuilder("s-prev")
    work(prev, 0, 3, "start")
    prev.turn_end(4)
    prev.meta("continued-in", continuedInSessionId="s-cont")
    on_branch(prev, "feat")
    prev.write(proj / "s-prev.jsonl")
    cont = continuation(prev, "s-cont")
    work(cont, 30, 2, "more")
    open_pr(cont, 33, 9, "Continued work")
    on_branch(cont, "feat")
    cont.write(proj / "s-cont.jsonl")
    fix = LogBuilder("s-fix")
    work(fix, 120, 1, "fix")
    on_branch(fix, "feat")
    fix.write(proj / "s-fix.jsonl")
    lone = LogBuilder("s-lone")
    work(lone, 200, 2, "lone")
    lone.write(proj / "s-lone.jsonl")
    (root / "sessions").mkdir()
    return root


def test_continued_session_and_api(pr_dir):
    store = Store(pr_dir)
    store.scan()
    assert store.continued_from() == {"s-cont": "s-prev"}
    with TestClient(create_app(pr_dir, watch=False), base_url="http://127.0.0.1") as client:
        res = client.post("/api/prs", json={"sessions": ["s-prev"], "gap": 15})
        assert res.status_code == 200
        data = res.json()
        [pr] = data["prs"]
        assert pr["number"] == 9 and pr["repo"] == "o/demo" and pr["title"] == "Continued work"
        assert pr["opened_in"] == "s-cont"
        # The predecessor's work leads up to the PR its continuation opened; the copy of it
        # at the start of the continuation is not counted twice.
        assert [s["id"] for s in pr["sessions"]] == ["s-cont", "s-prev", "s-fix"]
        assert pr["requests"] == 3 + 3 + 1
        assert data["unattributed"]["sessions"] == 0
        lone = client.post("/api/prs", json={"sessions": ["s-lone"]}).json()
        assert lone["prs"] == [] and lone["unattributed"]["requests"] == 2
        assert lone["unattributed"]["active_ms"] == 2 * MIN
        assert client.post("/api/prs", json={"sessions": [], "gap": 0}).status_code == 422
