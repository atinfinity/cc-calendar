"""Statistics for one transcript file (a session or a subagent), shown in the log viewer."""

from __future__ import annotations

import itertools
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any

from .logview import iter_records
from .parser import classify_user, parse_ts
from .pricing import cache_hit_rate, cache_savings, estimate_cost

IDLE_MS = 5 * 60_000  # gaps longer than this do not count as active time
TOKEN_KEYS = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_read": "cache_read_input_tokens",
    "cache_write": "cache_creation_input_tokens",
}
_cache: OrderedDict[tuple[str, float, int], dict] = OrderedDict()
CACHE_SIZE = 4


def log_stats(path: Path, session_id: str | None) -> dict:
    st = path.stat()
    key = (str(path), st.st_mtime, st.st_size)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    result = _compute(path, session_id)
    _cache[key] = result
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return result


def _compute(path: Path, session_id: str | None) -> dict:
    counts: Counter = Counter()
    times: list[int] = []
    # One API response can be written as several records; keep its largest usage.
    usages: dict[str, tuple[str | None, dict]] = {}
    tool_names: dict[str, str] = {}
    tool_calls: Counter = Counter()
    tool_errors: Counter = Counter()

    for rec in iter_records(path, session_id):
        rtype = rec.get("type")
        ts = parse_ts(rec.get("timestamp"))
        msg = rec.get("message") or {}
        content: Any = msg.get("content")
        if rtype == "user":
            kind = classify_user(rec)
            if kind == "tool_result":
                for b in content if isinstance(content, list) else []:
                    if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                        tool_errors[tool_names.get(b.get("tool_use_id"), "?")] += 1
                continue
            # A compaction writes both a boundary and a summary; count whichever exists.
            counts["compact_summary" if kind == "compact" else kind] += 1
            if kind in ("prompt", "command") and ts is not None:
                times.append(ts)
        elif rtype == "assistant":
            if msg.get("model") == "<synthetic>" or rec.get("isApiErrorMessage"):
                counts["api_error"] += 1
                continue
            if ts is not None:
                times.append(ts)
            mid = msg.get("id") or rec.get("requestId") or rec.get("uuid")
            usage = msg.get("usage") or {}
            prev = usages.get(mid)
            if prev is None or usage.get("output_tokens", 0) >= prev[1].get("output_tokens", 0):
                usages[mid] = (msg.get("model"), usage)
            for b in content if isinstance(content, list) else []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    name = b.get("name") or "?"
                    tool_names[b.get("id")] = name
                    tool_calls[name] += 1
                elif b.get("type") == "thinking":
                    counts["thinking"] += 1
        elif rtype == "system" and rec.get("subtype") == "compact_boundary":
            counts["compact"] += 1

    by_model: dict[str, dict] = {}
    for model, usage in usages.values():
        m = by_model.setdefault(
            model or "unknown", {"model": model or "unknown", "requests": 0, "cost": 0.0}
        )
        m["requests"] += 1
        for k, field in TOKEN_KEYS.items():
            m[k] = m.get(k, 0) + (usage.get(field) or 0)
        m["cost"] += estimate_cost(model, usage)
    models = sorted(by_model.values(), key=lambda m: -m["cost"])
    totals = {k: sum(m.get(k, 0) for m in models) for k in TOKEN_KEYS}
    for m in models:
        m["cost"] = round(m["cost"], 4)

    times.sort()
    active = sum(b - a for a, b in itertools.pairwise(times) if b - a <= IDLE_MS)
    return {
        "start": times[0] if times else None,
        "end": times[-1] if times else None,
        "active_ms": active,
        "idle_threshold_ms": IDLE_MS,
        "prompts": counts["prompt"],
        "commands": counts["command"],
        "interrupts": counts["interrupt"],
        "compactions": max(counts["compact"], counts["compact_summary"]),
        "notifications": counts["notification"],
        "thinking_blocks": counts["thinking"],
        "api_errors": counts["api_error"],
        "requests": len(usages),
        "tokens": totals,
        "cost": round(sum(m["cost"] for m in models), 4),
        "cache_hit": cache_hit_rate([u for _, u in usages.values()]),
        "cache_saved": round(sum(cache_savings(m, u) for m, u in usages.values()), 4),
        "models": models,
        "tools": [
            {"name": name, "calls": n, "errors": tool_errors.get(name, 0)}
            for name, n in tool_calls.most_common()
        ],
    }
