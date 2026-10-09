"""Cost, time and commits per pull request, from the sessions that worked on it.

Each request (and each stretch of active time, and each commit) of a session goes to at most
one PR:

- Work up to a PR the session opens goes to that PR: a session that opens several PRs gives
  each the work since the previous one. A continued session counts as part of the session it
  continues, so work before a `continued-in` goes to the next PR either of them opens.
- Work on a branch that is the head of an earlier PR in the same repository goes to that PR
  (review fixes, also in later sessions). It takes precedence over the rule above, except for
  the session's own earlier PRs and for a new PR from the same branch.
- A subagent that opened PRs worked for those PRs only.
- Anything else stays unattributed.

A PR is opened where its earliest `pr-link` record or `gh pr create` result is. Costs are the
sessions' costs (Claude Code's record when there is one) split by the requests' estimates.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from collections.abc import Iterable

from . import gitinfo
from .parser import SessionAcc
from .pricing import estimate_cost

PR_URL_RE = re.compile(r"^(https?://[^/]+/[^/]+/[^/]+)/pull/(\d+)")


def chain_roots(sessions: dict[str, SessionAcc], previous: dict[str, str]) -> dict[str, str]:
    """The first session of each session's chain of continuations."""
    out = {}
    for sid in sessions:
        root, seen = sid, {sid}
        while (p := previous.get(root)) is not None and p in sessions and p not in seen:
            root = p
            seen.add(p)
        out[sid] = root
    return out


def pr_repo(url: str, repo: str | None) -> tuple[str | None, str | None]:
    """(web URL of the repository, owner/name) of a PR."""
    m = PR_URL_RE.match(url)
    base = m.group(1) if m else None
    name = repo or ("/".join(base.split("/")[-2:]) if base else None)
    return base, name


class Attribution:
    """Who did the work in `sessions`: per PR and per session, see the module docstring."""

    def __init__(
        self, sessions: dict[str, SessionAcc], previous: dict[str, str], gap_ms: int
    ) -> None:
        self.sessions = sessions
        self.gap_ms = gap_ms
        self.roots = chain_roots(sessions, previous)
        self.prs: dict[str, dict] = {}
        for sid, s in sessions.items():
            for url, pr in s.prs.items():
                if pr.get("created") is None:
                    continue  # merged, edited or commented on here, not opened
                known = self.prs.get(url)
                if known is None or pr["created"] < known["created"]:
                    base, name = pr_repo(url, pr.get("repo"))
                    self.prs[url] = {
                        "url": url,
                        "number": pr.get("number"),
                        "repo": name,
                        "repo_url": base,
                        "title": pr.get("title"),
                        "head": pr.get("head"),
                        "created": pr["created"],
                        "session": sid,
                    }
                for k in ("title", "head", "number"):
                    if self.prs[url].get(k) is None:
                        self.prs[url][k] = pr.get(k)
        self.opened: dict[str, list[dict]] = {}  # chain root -> PRs opened there, oldest first
        self.by_head: dict[str, list[dict]] = {}  # head branch -> PRs, oldest first
        for pr in sorted(self.prs.values(), key=lambda p: p["created"]):
            self.opened.setdefault(self.roots.get(pr["session"], pr["session"]), []).append(pr)
            if pr["head"]:
                self.by_head.setdefault(pr["head"], []).append(pr)
        self._repo: dict[str, str | None] = {}
        self.totals = {url: self._empty() for url in self.prs}
        self.unattributed = {sid: self._empty() for sid in sessions}
        for sid, s in sessions.items():
            self._attribute(sid, s)

    @staticmethod
    def _empty() -> dict:
        return {"cost": 0.0, "requests": 0, "tokens": 0, "active_ms": 0, "commits": set(),
                "sessions": {}, "estimated": False}  # fmt: skip

    def _same_repo(self, s: SessionAcc, pr: dict) -> bool:
        """Whether the session works in the PR's repository: by its origin remote, or when that
        is gone (a removed worktree), by its directory being that of the session that opened
        the PR."""
        if s.cwd not in self._repo:
            self._repo[s.cwd] = gitinfo.repo_url(s.cwd)
        url = self._repo[s.cwd]
        if url and pr["repo_url"]:
            return url.lower() == pr["repo_url"].lower()
        opener = self.sessions.get(pr["session"])
        return opener is not None and opener.cwd == s.cwd

    def owner(self, sid: str, s: SessionAcc, ts: int | None) -> dict | None:
        """The PR the session's work at `ts` goes to, or None."""
        if ts is None:
            return None
        root = self.roots[sid]
        opened = self.opened.get(root, [])
        i = bisect_left(opened, ts, key=lambda p: p["created"])
        nxt = opened[i] if i < len(opened) else None
        branch = s.branch_at(ts)
        if nxt is not None and nxt["head"] == branch:
            return nxt
        # Before the session opens another PR, its own earlier ones give way to that one: the
        # branch it records may stay put while it works in another worktree.
        earlier = [
            pr
            for pr in self.by_head.get(branch, [])
            if pr["created"] <= ts
            and (nxt is None or self.roots.get(pr["session"]) != root)
            and self._same_repo(s, pr)
        ]
        return earlier[-1] if earlier else nxt

    def _attribute(self, sid: str, s: SessionAcc) -> None:
        # (ts, estimated cost, tokens, the PR when a subagent that opened PRs sent it)
        requests: list[tuple[int | None, float, int, dict | None]] = [
            (u.ts, estimate_cost(u.model, u.usage), u.total, None)
            for mid, u in s.usages.items()
            if mid not in s.prior_usage_ids
        ]
        for aid, sa in s.subagents.items():
            # A subagent that opened PRs worked for them, also while others ran side by side:
            # each takes its requests up to it, the last one also those after it.
            mine = sorted(
                (self.prs[p["url"]] for p in s.prs.values() if p.get("agent") == aid),
                key=lambda p: p["created"],
            )
            for u in sa.usages.values():
                pr = None
                if mine:
                    i = bisect_left(mine, u.ts or 0, key=lambda p: p["created"])
                    pr = mine[min(i, len(mine) - 1)]
                requests.append((u.ts, estimate_cost(u.model, u.usage), u.total, pr))
        cost, estimated = s.cost()
        est = sum(r[1] for r in requests)
        # Split the session's cost (Claude Code's record when there is one) by the estimates.
        share = (lambda c: cost * c / est) if est > 0 else (lambda c: cost / len(requests))

        def acc_for(ts: int | None, pr: dict | None = None) -> dict:
            pr = pr or self.owner(sid, s, ts)
            acc = self.totals[pr["url"]] if pr else self.unattributed[sid]
            acc["sessions"].setdefault(sid, 0.0)
            acc["estimated"] |= estimated
            return acc

        for ts, c, tokens, pr in requests:
            acc = acc_for(ts, pr)
            acc["cost"] += share(c)
            acc["sessions"][sid] += share(c)
            acc["requests"] += 1
            acc["tokens"] += tokens
        # Active time as the calendar draws it: gaps up to gap_ms between activity.
        times = sorted(s.activity)
        for a, b in zip(times, times[1:], strict=False):
            if b - a <= self.gap_ms:
                acc_for(b)["active_ms"] += b - a
        for c in s.commits:
            acc_for(c.get("ts"))["commits"].add(c.get("sha") or (c.get("subject"), c.get("ts")))
        if requests or times:
            # The session that opened a PR always counts among its sessions.
            for pr in s.prs.values():
                url = pr["url"]
                if url in self.totals and self.prs[url]["session"] == sid:
                    self.totals[url]["sessions"].setdefault(sid, 0.0)


def pr_costs(attr: Attribution, ids: Iterable[str]) -> dict:
    """PRs that any of the sessions `ids` worked on, with their totals over all sessions, and
    what those sessions did that no PR took."""
    picked = {i for i in ids if i in attr.sessions}
    prs = []
    for url, t in attr.totals.items():
        if not picked & t["sessions"].keys():
            continue
        pr = attr.prs[url]
        prs.append(
            {
                **{k: pr[k] for k in ("url", "number", "repo", "title", "head", "created")},
                "opened_in": pr["session"],
                "cost": round(t["cost"], 4),
                "estimated": t["estimated"],
                "requests": t["requests"],
                "tokens": t["tokens"],
                "active_ms": t["active_ms"],
                "commits": len(t["commits"]),
                # Cost per session, the opener first, then by when each session started.
                "sessions": [
                    {"id": sid, "cost": round(c, 4)}
                    for sid, c in sorted(
                        t["sessions"].items(),
                        key=lambda kv: (
                            kv[0] != pr["session"],
                            attr.sessions[kv[0]].start or 0,
                        ),
                    )
                ],
            }
        )
    prs.sort(key=lambda p: -p["created"])
    rest = [attr.unattributed[sid] for sid in sorted(picked)]
    worked = [sid for sid, u in zip(sorted(picked), rest, strict=True) if u["sessions"]]
    return {
        "prs": prs,
        "unattributed": {
            "cost": round(sum(u["cost"] for u in rest), 4),
            "estimated": any(u["estimated"] for u in rest),
            "requests": sum(u["requests"] for u in rest),
            "tokens": sum(u["tokens"] for u in rest),
            "active_ms": sum(u["active_ms"] for u in rest),
            "commits": sum(len(u["commits"]) for u in rest),
            "sessions": len(worked),
        },
    }
