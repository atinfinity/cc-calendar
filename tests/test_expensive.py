import pytest
from conftest import BASE, LogBuilder

from cc_calendar.expensive import expensive_requests
from cc_calendar.parser import SessionAcc
from cc_calendar.pricing import estimate_cost

T0 = int(BASE.timestamp() * 1000)
MIN = 60_000
USAGE = {"input_tokens": 100, "output_tokens": 10, "cache_read_input_tokens": 1000}


def feed(builder: LogBuilder) -> SessionAcc:
    s = SessionAcc(session_id=builder.sid, path="x.jsonl", project_dir="p")
    for r in builder.records:
        s.feed(r)
    return s


def usage(output_tokens: int) -> dict:
    return dict(USAGE, output_tokens=output_tokens)


def cost(output_tokens: int, model: str = "claude-sonnet-5-5") -> float:
    return estimate_cost(model, usage(output_tokens))


def session(sid: str = "s-cost", offset: float = 0) -> SessionAcc:
    """A big prompt that starts a subagent, then a small one and a slash command."""
    b = LogBuilder(sid)
    b.prompt(offset, "Refactor the whole module")
    b.assistant(offset + 1, [{"type": "text", "text": "Planning"}], msg_id="m1", output_tokens=5000)
    b.tool_use(offset + 2, "t-agent", "Agent", {"subagent_type": "Explore"}, msg_id="m2")
    b.tool_result(offset + 10, "t-agent", "found", {"agentId": "a1", "status": "completed"})
    b.assistant(
        offset + 11, [{"type": "text", "text": "Done"}], msg_id="m3", stop_reason="end_turn"
    )
    b.prompt(offset + 20, "Fix a typo")
    b.assistant(
        offset + 21, [{"type": "text", "text": "Fixed"}], msg_id="m4", stop_reason="end_turn"
    )
    b.command(offset + 30, "/compact")
    s = feed(b)
    agent = LogBuilder(sid)
    agent.assistant(offset + 3, [], msg_id="x1", model="claude-haiku-4-5", output_tokens=2000)
    agent.assistant(offset + 9, [], msg_id="x2", model="claude-haiku-4-5")
    for r in agent.records:
        s.feed_subagent("a1", "agent-a1.jsonl", r)
    return s


def test_prompt_costs_cover_requests_until_the_next_prompt_and_subagents():
    s = session()
    first, second, third = s.prompt_costs()
    sub = cost(2000, "claude-haiku-4-5") + cost(10, "claude-haiku-4-5")
    assert first["text"] == "Refactor the whole module" and first["ts"] == T0
    assert first["cost"] == pytest.approx(cost(5000) + cost(10) + cost(10) + sub)
    assert (first["requests"], first["subagents"]) == (3, 1)
    assert first["tokens"] == sum(u.total for u in s.all_usages()) - 1110  # all but m4
    assert second["cost"] == pytest.approx(cost(10))
    assert (second["requests"], second["subagents"], second["tokens"]) == (1, 0, 1110)
    # A slash command that no request followed costs nothing.
    assert third["kind"] == "command" and third["cost"] == 0 and third["requests"] == 0
    # Together they make up the session's estimated cost.
    total, estimated = s.cost()
    assert estimated and sum(p["cost"] for p in s.prompt_costs()) == pytest.approx(total)


def test_prompt_costs_scale_to_the_recorded_cost():
    s = session()
    estimated = [p["cost"] for p in s.prompt_costs()]
    s.feed({"type": "cost-state", "sessionId": s.session_id, "totalCostUSD": 3 * s.cost()[0]})
    assert s.cost()[1] is False
    assert [p["cost"] for p in s.prompt_costs()] == pytest.approx([3 * c for c in estimated])


def test_prompt_costs_skip_requests_before_the_first_prompt():
    b = LogBuilder("s-early")
    b.assistant(0, [{"type": "text", "text": "hello"}], msg_id="m0", output_tokens=900)
    b.prompt(1, "Go")
    b.assistant(2, [{"type": "text", "text": "ok"}], msg_id="m1")
    (p,) = feed(b).prompt_costs()
    assert p["cost"] == pytest.approx(cost(10)) and p["requests"] == 1


def test_expensive_requests_ranks_prompts_in_range():
    a = session("s-a")
    b = session("s-b", offset=24 * 60)  # the next day
    out = expensive_requests([a, b], T0, T0 + 24 * 60 * MIN, limit=2)
    assert out["prompts"] == 3  # s-b's prompts are outside the range
    assert [(r["session"], r["text"]) for r in out["top"]] == [
        ("s-a", "Refactor the whole module"),
        ("s-a", "Fix a typo"),
    ]
    top = out["top"][0]
    assert top["ts"] == T0 and top["estimated"] and top["subagents"] == 1
    assert out["cost"] == pytest.approx(a.cost()[0], abs=1e-3)

    both = expensive_requests([a, b], T0, T0 + 48 * 60 * MIN, limit=50)
    assert both["prompts"] == 6 and len(both["top"]) == 6
    assert expensive_requests([a], T0 + 60 * MIN, T0 + 120 * MIN, limit=5)["top"] == []
