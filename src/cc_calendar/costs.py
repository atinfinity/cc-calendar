"""Cost across sessions by model and token type: input, output, cache write, cache read."""

from __future__ import annotations

from collections.abc import Iterable

from .parser import DENSITY_BUCKET_MS, SessionAcc


def cost_breakdown(sessions: Iterable[SessionAcc], bounds: list[tuple[int, int]]) -> dict:
    """Tokens and cost per model and per [start, end) period in `bounds`.

    A bucket counts in the period its start falls in, as the Summary splits cost. Sessions
    with Claude Code's own cost record keep that total, split by the estimate's proportions.
    `idle_recache` adds up the requests in the periods that rewrote an expired cache.
    """
    models: dict[str, list[float]] = {}
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
    }
