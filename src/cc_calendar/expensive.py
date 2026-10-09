"""The most expensive prompts across sessions, by the cost of the requests each one started."""

from __future__ import annotations

from collections.abc import Iterable

from .parser import SessionAcc

TEXT_LIMIT = 300


def expensive_requests(sessions: Iterable[SessionAcc], start: int, end: int, limit: int) -> dict:
    """The `limit` costliest prompts sent in [start, end), with how many there were in all."""
    rows = []
    for s in sessions:
        _, estimated = s.cost()
        for p in s.prompt_costs():
            if not start <= p["ts"] < end:
                continue
            rows.append(
                {
                    "session": s.session_id,
                    "ts": p["ts"],
                    "text": p["text"][:TEXT_LIMIT],
                    "kind": p["kind"],
                    "cost": round(p["cost"], 4),
                    "estimated": estimated,
                    "tokens": p["tokens"],
                    "requests": p["requests"],
                    "subagents": p["subagents"],
                }
            )
    rows.sort(key=lambda r: (-r["cost"], -r["tokens"], r["ts"]))
    return {
        "prompts": len(rows),
        "cost": round(sum(r["cost"] for r in rows), 4),
        "estimated": any(r["estimated"] for r in rows),
        "top": rows[:limit],
    }
