"""Resolve commits made during a session against the repository's git history."""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

CACHE_TTL = 30.0
MATCH_WINDOW_S = 15 * 60

Entry = tuple[str, str, int]  # (sha, subject, commit_time_s)

_log_cache: dict[str, tuple[float, LogIndex]] = {}
_remote_cache: dict[str, tuple[float, str | None]] = {}


def _git(cwd: str, *args: str) -> str | None:
    if not cwd or not Path(cwd).is_dir():
        return None
    try:
        out = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


class LogIndex:
    """Commits of a repository, looked up by SHA prefix or by subject."""

    def __init__(self, entries: list[Entry]):
        self.by_short: dict[str, list[Entry]] = {}
        self.by_subject: dict[str, list[Entry]] = {}
        for e in entries:
            self.by_short.setdefault(e[0][:7], []).append(e)
            self.by_subject.setdefault(e[1], []).append(e)

    def find_sha(self, sha: str) -> Entry | None:
        return next((e for e in self.by_short.get(sha[:7], []) if e[0].startswith(sha)), None)

    def find_subject(self, subject: str, ts_s: float) -> Entry | None:
        """The commit with this subject closest in time, within MATCH_WINDOW_S."""
        candidates = [
            e for e in self.by_subject.get(subject, []) if abs(e[2] - ts_s) <= MATCH_WINDOW_S
        ]
        return min(candidates, key=lambda e: abs(e[2] - ts_s)) if candidates else None


_EMPTY = LogIndex([])


def _log(cwd: str) -> LogIndex:
    """Commits across all refs, cached briefly."""
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
    index = LogIndex(entries)
    _log_cache[cwd] = (now, index)
    return index


def resolve_commits(commits: list[dict]) -> list[dict]:
    """Fill in missing SHAs by matching subject + time, and subjects for SHA-only entries."""
    resolved = []
    for c in commits:
        c = dict(c)
        index = _log(c["cwd"]) if c.get("cwd") else _EMPTY
        if c.get("sha"):
            match = index.find_sha(c["sha"])
            if match:
                c["sha"], c["subject"] = match[0], c.get("subject") or match[1]
        elif c.get("subject") and c.get("ts"):
            match = index.find_subject(c["subject"], c["ts"] / 1000)
            if match:
                c["sha"] = match[0]
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
