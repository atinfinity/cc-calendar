"""Resolve commits made during a session against the repository's git history."""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

CACHE_TTL = 30.0
MATCH_WINDOW_S = 15 * 60

_log_cache: dict[str, tuple[float, list[tuple[str, str, int]]]] = {}
_remote_cache: dict[str, tuple[float, str | None]] = {}


def _git(cwd: str, *args: str) -> str | None:
    if not cwd or not Path(cwd).is_dir():
        return None
    try:
        out = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def _log(cwd: str) -> list[tuple[str, str, int]]:
    """[(sha, subject, commit_time_s)] across all refs, cached briefly."""
    now = time.monotonic()
    cached = _log_cache.get(cwd)
    if cached and now - cached[0] < CACHE_TTL:
        return cached[1]
    out = _git(cwd, "log", "--all", "--reflog", "--format=%H%x1f%s%x1f%ct", "-n", "5000")
    entries = []
    for line in (out or "").splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3 and parts[2].isdigit():
            entries.append((parts[0], parts[1], int(parts[2])))
    _log_cache[cwd] = (now, entries)
    return entries


def resolve_commits(commits: list[dict]) -> list[dict]:
    """Fill in missing SHAs by matching subject + time, and subjects for SHA-only entries."""
    resolved = []
    for c in commits:
        c = dict(c)
        entries = _log(c["cwd"]) if c.get("cwd") else []
        if c.get("sha"):
            match = next((e for e in entries if e[0].startswith(c["sha"])), None)
            if match:
                c["sha"], c["subject"] = match[0], c.get("subject") or match[1]
        elif c.get("subject") and c.get("ts"):
            ts_s = c["ts"] / 1000
            candidates = [
                e for e in entries if e[1] == c["subject"] and abs(e[2] - ts_s) <= MATCH_WINDOW_S
            ]
            if candidates:
                best = min(candidates, key=lambda e: abs(e[2] - ts_s))
                c["sha"] = best[0]
        resolved.append(c)
    # Drop duplicates (e.g. both gitOperation and regex picked up the same commit).
    seen, out = set(), []
    for c in resolved:
        key = c.get("sha") or (c.get("subject"), c.get("ts"))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def web_url(remote: str) -> str | None:
    """Browser URL of a git remote: git@host:o/r.git and https://host/o/r.git -> https://host/o/r."""
    remote = remote.strip()
    m = re.match(r"^(?:ssh://)?git@([^:/]+)[:/](.+?)(?:\.git)?/?$", remote)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"
    m = re.match(r"^https?://(?:[^@/]+@)?([^/]+)/(.+?)(?:\.git)?/?$", remote)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"
    return None


def repo_url(cwd: str | None) -> str | None:
    """Web URL of the origin remote of the repository at cwd, cached briefly."""
    if not cwd:
        return None
    now = time.monotonic()
    cached = _remote_cache.get(cwd)
    if cached and now - cached[0] < CACHE_TTL:
        return cached[1]
    out = _git(cwd, "remote", "get-url", "origin")
    url = web_url(out) if out else None
    _remote_cache[cwd] = (now, url)
    return url


def working_tree_clean(cwd: str | None) -> bool | None:
    """True/False for a git work tree, None if not a repository."""
    if not cwd:
        return None
    out = _git(cwd, "status", "--porcelain")
    if out is None:
        return None
    return out.strip() == ""
