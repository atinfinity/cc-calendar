from conftest import BASE, LogBuilder, basic_session

from cc_calendar.parser import SessionAcc
from cc_calendar.tools import mcp_server, tool_usage

T0 = int(BASE.timestamp() * 1000)
MIN = 60_000


def feed(builder: LogBuilder) -> SessionAcc:
    s = SessionAcc(session_id=builder.sid, path="x.jsonl", project_dir="p")
    for r in builder.records:
        s.feed(r)
    return s


def test_mcp_server():
    assert mcp_server("mcp__github__create_issue") == "github"
    assert mcp_server("mcp__claude_ai_Docs__read") == "claude_ai_Docs"
    assert mcp_server("Bash") is None
    assert mcp_server("mcp__broken") is None


def session_with_errors_and_subagent() -> SessionAcc:
    b = LogBuilder("s-tools")
    b.prompt(0, "Do things")
    b.tool_use(1, "t1", "Bash", {"command": "ls"}, msg_id="m1")
    b.tool_result(2, "t1", "ok")
    b.tool_use(3, "t2", "Bash", {"command": "false"}, msg_id="m2")
    b.tool_result(4, "t2", "exit 1", is_error=True)
    b.tool_use(5, "t3", "mcp__github__create_issue", {"title": "x"}, msg_id="m3")
    b.tool_result(6, "t3", "created")
    b.tool_use(7, "t4", "Agent", {"subagent_type": "Explore", "prompt": "look"}, msg_id="m4")
    b.tool_result(30, "t4", "done", {"agentId": "a1", "status": "completed"})
    b.tool_use(120, "t5", "Bash", {"command": "late"}, msg_id="m5")
    s = feed(b)
    agent = LogBuilder("s-tools")
    agent.tool_use(8, "g1", "Grep", {"pattern": "x"}, msg_id="x1")
    agent.tool_result(9, "g1", "no such file", is_error=True)
    agent.tool_use(10, "g2", "Read", {"file_path": "/a"}, msg_id="x2")
    agent.tool_result(11, "g2", "contents")
    for r in agent.records:
        s.feed_subagent("a1", "agent-a1.jsonl", r)
    s.apply_subagent_meta("a1", {"agentType": "Explore"})
    return s


def test_tool_usage_counts_errors_mcp_and_subagents():
    s = session_with_errors_and_subagent()
    u = tool_usage([s], T0, T0 + 60 * MIN)
    by_name = {t["name"]: t for t in u["tools"]}
    # The Bash call at minute 120 is outside the range.
    assert by_name["Bash"] == {
        "name": "Bash",
        "calls": 2,
        "errors": 1,
        "subagent_calls": 0,
        "sessions": 1,
        "mcp_server": None,
    }
    assert by_name["Grep"]["errors"] == 1 and by_name["Grep"]["subagent_calls"] == 1
    assert by_name["Read"]["errors"] == 0
    assert u["calls"] == 6 and u["errors"] == 2 and u["sessions"] == 1
    assert u["mcp"] == [{"server": "github", "calls": 1, "errors": 0, "tools": 1}]
    assert [(a["type"], a["runs"], a["calls"]) for a in u["subagents"]] == [("Explore", 1, 2)]


def test_tool_usage_outside_range_is_empty():
    s = session_with_errors_and_subagent()
    u = tool_usage([s], T0 + 200 * MIN, T0 + 300 * MIN)
    assert u["calls"] == 0 and u["tools"] == [] and u["subagents"] == []


def test_tool_usage_counts_split_assistant_records_once():
    s = feed(basic_session())
    u = tool_usage([s], T0, T0 + 60 * MIN)
    assert {t["name"]: t["calls"] for t in u["tools"]} == {"Write": 1, "Bash": 1}
