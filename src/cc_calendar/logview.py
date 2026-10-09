"""Flatten a transcript file into display entries for the log viewer."""

from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .parser import (
    GIT_COMMIT_RE,
    classify_user,
    command_text,
    compact_extra,
    compact_info,
    content_text,
    parse_ts,
    prompt_text,
    tool_result_text,
)
from .search import normalize

MAX_TEXT = 20_000
MAX_INPUT = 4_000
_cache: OrderedDict[tuple[str, float, int], list[dict]] = OrderedDict()
CACHE_SIZE = 4


def _clip(text: str, limit: int = MAX_TEXT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… ({len(text) - limit:,} more characters)"


def _input_summary(name: str, inp: dict) -> str:
    for key in ("command", "file_path", "pattern", "url", "description", "prompt", "query"):
        if isinstance(inp.get(key), str):
            return inp[key].splitlines()[0][:200] if inp[key] else ""
    return ""


def iter_records(path: Path, session_id: str | None) -> Iterator[dict]:
    """Records of one transcript, skipping copied predecessors and duplicate uuids."""
    seen: set[str] = set()
    with open(path, "rb") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            if session_id and rec.get("sessionId") not in (None, session_id):
                continue
            uuid = rec.get("uuid")
            if uuid:
                if uuid in seen:
                    continue
                seen.add(uuid)
            yield rec


def build_entries(path: Path, session_id: str | None) -> list[dict]:
    st = path.stat()
    key = (str(path), st.st_mtime, st.st_size)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    entries: list[dict] = []
    tool_names: dict[str, str] = {}
    commit_calls: set[str] = set()
    for rec in iter_records(path, session_id):
        entries.extend(_entries_for(rec, tool_names, commit_calls))
    for i, e in enumerate(entries):
        e["i"] = i
    _tag_commits(entries, commit_calls)
    _cache[key] = entries
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return entries


def _tag_commits(entries: list[dict], commit_calls: set[str]) -> None:
    """Mark git commit calls that succeeded, matching the commits drawn on the calendar."""
    calls = {e["id"]: e for e in entries if e["kind"] == "tool_use" and e["id"] in commit_calls}
    for e in entries:
        call = calls.get(e.get("tool_use_id")) if e["kind"] == "tool_result" else None
        if call and not e["is_error"] and not e.get("interrupted"):
            call["event"] = "commit"


# Entry kinds full-text search covers, and the fields it looks in.
SEARCHED = {
    "user": ("text",),
    "assistant": ("text",),
    "tool_use": ("summary", "input"),
    "tool_result": ("text",),
    "error": ("text",),
    "notification": ("text",),
}


def find_entries(entries: list[dict], query: str) -> list[tuple[int, int | None]]:
    """(index, ts) of the entries containing `query`, ignoring case and whitespace."""
    q = normalize(query).casefold()
    if not q:
        return []
    out = []
    for e in entries:
        fields = SEARCHED.get(e["kind"], ())
        if any(q in normalize(e.get(f) or "").casefold() for f in fields):
            out.append((e["i"], e["ts"]))
    return out


def log_events(entries: list[dict]) -> list[tuple[int, int | None, str]]:
    """(index, ts, kind) of the entries that correspond to the calendar's event marks."""
    return [(e["i"], e["ts"], e["event"]) for e in entries if "event" in e]


def _entries_for(rec: dict, tool_names: dict[str, str], commit_calls: set[str]) -> list[dict]:
    rtype = rec.get("type")
    ts = parse_ts(rec.get("timestamp"))
    msg = rec.get("message") or {}
    content: Any = msg.get("content")
    if rtype == "user":
        kind = classify_user(rec)
        if kind == "tool_result":
            tur = rec.get("toolUseResult")
            interrupted = isinstance(tur, dict) and bool(tur.get("interrupted"))
            out = []
            for b in content if isinstance(content, list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    tid = b.get("tool_use_id")
                    out.append(
                        {
                            "kind": "tool_result",
                            "ts": ts,
                            "tool_use_id": tid,
                            "name": tool_names.get(tid, ""),
                            "is_error": bool(b.get("is_error")),
                            "interrupted": interrupted,
                            "text": _clip(tool_result_text(b.get("content"))),
                        }
                    )
            return out
        text = content_text(content)
        if kind == "prompt":
            text = prompt_text(content)
            return [{"kind": "user", "ts": ts, "text": _clip(text), "event": "prompt"}]
        if kind == "command":
            text = command_text(text)
            return [{"kind": "user", "ts": ts, "text": text, "command": True, "event": "prompt"}]
        if kind == "interrupt":
            return [{"kind": "interrupt", "ts": ts, "text": text.strip()}]
        if kind == "compact":
            return [{"kind": "compact", "ts": ts, "text": _clip(text)}]
        if kind == "notification":
            return [{"kind": "notification", "ts": ts, "text": _clip(text, 2000)}]
        return [{"kind": "meta", "ts": ts, "text": _clip(text, 4000)}]
    if rtype == "assistant":
        if msg.get("model") == "<synthetic>" or rec.get("isApiErrorMessage"):
            text = _clip(content_text(content), 2000)
            return [{"kind": "error", "ts": ts, "text": text, "event": "error"}]
        out = []
        for b in content if isinstance(content, list) else []:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt == "text" and b.get("text", "").strip():
                out.append({"kind": "assistant", "ts": ts, "text": _clip(b["text"])})
            elif bt == "thinking" and b.get("thinking", "").strip():
                out.append({"kind": "thinking", "ts": ts, "text": _clip(b["thinking"])})
            elif bt == "tool_use":
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                name = b.get("name", "")
                tool_names[b.get("id")] = name
                if name == "Bash" and GIT_COMMIT_RE.search(str(inp.get("command", ""))):
                    commit_calls.add(b.get("id"))
                entry = {
                    "kind": "tool_use",
                    "ts": ts,
                    "id": b.get("id"),
                    "name": name,
                    "summary": _input_summary(name, inp),
                    "input": _clip(json.dumps(inp, ensure_ascii=False, indent=2), MAX_INPUT),
                }
                out.append(entry)
        return out
    if rtype == "attachment":
        att = rec.get("attachment") or {}
        prompt = att.get("prompt")
        if isinstance(prompt, str) and "<task-notification>" in prompt:
            return [{"kind": "notification", "ts": ts, "text": _clip(prompt, 2000)}]
        return [{"kind": "attachment", "ts": ts, "text": att.get("type", "attachment")}]
    if rtype == "system":
        sub = rec.get("subtype")
        if sub == "compact_boundary":
            text = "— context compacted —"
            entry = {"kind": "compact", "ts": ts, "text": text, "event": "compact"}
            return [{**entry, **compact_extra(compact_info(rec))}]
        if sub in ("turn_duration", None):
            return []
        return [{"kind": "system", "ts": ts, "text": f"{sub}: {rec.get('content', '')}"[:2000]}]
    return []
