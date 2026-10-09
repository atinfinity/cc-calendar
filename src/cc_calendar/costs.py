"""Cost across sessions by model and token type: input, output, cache write, cache read."""

from __future__ import annotations

from collections.abc import Iterable

from .parser import DENSITY_BUCKET_MS, SessionAcc
from .pricing import PRICES, TOKEN_TYPES, cost_parts


def cost_breakdown(sessions: Iterable[SessionAcc], bounds: list[tuple[int, int]]) -> dict:
    """Tokens and cost per model and per [start, end) period in `bounds`.

    A bucket counts in the period its start falls in, as the Summary splits cost. Sessions
    with Claude Code's own cost record keep that total, split by the estimate's proportions.
    `idle_recache` adds up the requests in the periods that rewrote an expired cache.

    `usage` splits the whole range by model and by main thread or subagent, for re-pricing
    with another model: `scaled` is tokens times the session's recorded/estimate ratio, so
    scaled tokens times another model's rates compare with `cost` on the same footing.
    """
    models: dict[str, list[float]] = {}
    usage: dict[tuple[str, bool], list[float]] = {}
    days = [[0.0] * 8 for _ in bounds]
    used = set()
    recorded = 0
    estimated = False
    idle = {"cost": 0.0, "tokens": 0, "requests": 0, "sessions": 0}  # re-caching after idle gaps
    for s in sessions:
        buckets = s.cost_breakdown()
        cost, is_estimate = s.cost()
        est = sum(sum(row[4:]) for by_model in buckets.values() for row in by_model.values())
        scale = cost / est if not is_estimate and est > 0 else 1.0
        seen = False
        for bucket, by_model in buckets.items():
            t = bucket * DENSITY_BUCKET_MS
            day = next((i for i, (a, b) in enumerate(bounds) if a <= t < b), None)
            if day is None:
                continue
            seen = True
            for model, row in by_model.items():
                acc = models.setdefault(model, [0.0] * 8)
                for i, v in enumerate(row):
                    v = v * scale if i >= 4 else v
                    acc[i] += v
                    days[day][i] += v
        for agent, u in thread_usages(s):
            t = u.ts // DENSITY_BUCKET_MS * DENSITY_BUCKET_MS if u.ts is not None else None
            if t is None or not any(a <= t < b for a, b in bounds):
                continue
            acc = usage.setdefault((u.model or "unknown", agent), [0.0] * 9)
            for i, k in enumerate(TOKEN_TYPES):
                acc[i] += u.usage.get(k, 0)
                acc[4 + i] += u.usage.get(k, 0) * scale
            acc[8] += sum(cost_parts(u.model, u.usage)) * scale
        if seen:
            used.add(s.session_id)
            recorded += not is_estimate
            estimated |= is_estimate
        # Always an estimate: not scaled to a cost record.
        recaches = [r for r in s.idle_recaches() if any(a <= r[0] < b for a, b in bounds)]
        if recaches:
            idle["sessions"] += 1
            idle["requests"] += len(recaches)
            idle["tokens"] += sum(n for _, n, _ in recaches)
            idle["cost"] += sum(c for _, _, c in recaches)

    def split(row: list[float]) -> dict:
        return {"tokens": [int(n) for n in row[:4]], "cost": [round(c, 4) for c in row[4:]]}

    rows = [{"model": m, **split(row)} for m, row in models.items()]
    rows.sort(key=lambda r: (-sum(r["cost"]), -sum(r["tokens"])))
    return {
        "sessions": len(used),
        "recorded": recorded,  # sessions whose cost Claude Code recorded
        "estimated": estimated,
        "models": rows,
        "days": [split(row) for row in days],
        "idle_recache": {**idle, "cost": round(idle["cost"], 4)},
        "usage": [
            {
                "model": m,
                "agent": agent,
                "tokens": [int(n) for n in row[:4]],
                "scaled": [round(n, 2) for n in row[4:8]],
                "cost": round(row[8], 4),
            }
            for (m, agent), row in usage.items()
        ],
        # USD per million tokens in TOKEN_TYPES order, for the models a what-if can switch to.
        "prices": [
            {"model": m, "rates": [p.input, p.output, p.cache_write, p.cache_read_rate]}
            for m, p in PRICES
        ],
    }


def thread_usages(s: SessionAcc):
    """(ran in a subagent?, usage) for each API request of the session."""
    for u in s.usages.values():
        yield False, u
    for sa in s.subagents.values():
        for u in sa.usages.values():
            yield True, u
