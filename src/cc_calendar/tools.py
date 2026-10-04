"""Tool usage across sessions: most used tools, error rates, MCP servers and subagents."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable

from .parser import SessionAcc


def mcp_server(name: str) -> str | None:
    """'mcp__github__create_issue' -> 'github'."""
    parts = name.split("__")
    return parts[1] if len(parts) >= 3 and parts[0] == "mcp" and parts[1] else None


def tool_usage(sessions: Iterable[SessionAcc], start: int, end: int) -> dict:
    """Tool calls made in [start, end), main session and subagents together."""
    calls: Counter = Counter()
    errors: Counter = Counter()
    sub_calls: Counter = Counter()
    tool_sessions: dict[str, set] = defaultdict(set)
    agent_calls: Counter = Counter()  # agent id -> tool calls
    agents: dict[str, dict] = {}
    used = set()
    for s in sessions:
        for ts, name, is_error, agent in s.tool_calls:
            if ts is None or not start <= ts < end:
                continue
            calls[name] += 1
            errors[name] += is_error
            tool_sessions[name].add(s.session_id)
            used.add(s.session_id)
            if agent:
                sub_calls[name] += 1
                agent_calls[agent] += 1
        for sa in s.subagents.values():
            if sa.first_ts is None or not start <= sa.first_ts < end:
                continue
            row = agents.setdefault(
                sa.agent_type or "general-purpose",
                {
                    "type": sa.agent_type or "general-purpose",
                    "runs": 0,
                    "calls": 0,
                    "tokens": 0,
                    "cost": 0.0,
                    "ids": [],
                },
            )
            row["runs"] += 1
            row["tokens"] += sa.tokens()
            row["cost"] += sa.cost()
            row["ids"].append(sa.agent_id)

    tools = [
        {
            "name": name,
            "calls": n,
            "errors": errors[name],
            "subagent_calls": sub_calls[name],
            "sessions": len(tool_sessions[name]),
            "mcp_server": mcp_server(name),
        }
        for name, n in calls.most_common()
    ]
    servers: dict[str, dict] = {}
    for t in tools:
        if not t["mcp_server"]:
            continue
        srv = servers.setdefault(
            t["mcp_server"], {"server": t["mcp_server"], "calls": 0, "errors": 0, "tools": 0}
        )
        srv["calls"] += t["calls"]
        srv["errors"] += t["errors"]
        srv["tools"] += 1
    for row in agents.values():
        row["calls"] = sum(agent_calls[i] for i in row.pop("ids"))
        row["cost"] = round(row["cost"], 4)
    return {
        "calls": sum(calls.values()),
        "errors": sum(errors.values()),
        "sessions": len(used),
        "tools": tools,
        "mcp": sorted(servers.values(), key=lambda r: -r["calls"]),
        "subagents": sorted(agents.values(), key=lambda r: (-r["runs"], -r["cost"])),
    }
