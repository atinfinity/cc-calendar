"""Incremental parsing of Claude Code session transcripts (~/.claude/projects/**/*.jsonl)."""

from __future__ import annotations

import re
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
from typing import Any

from .pricing import (
    TOKEN_TYPES,
    cache_hit_rate,
    cache_savings,
    context_window,
    cost_parts,
    estimate_cost,
    recache_cost,
)

INTERRUPT_PREFIX = "[Request interrupted"
GIT_COMMIT_RE = re.compile(r"\bgit\b(?:\s+-[cC]\s+\S+)*[^|;&\n]*?\bcommit\b")
EFFORT_ORDER = ["max", "xhigh", "high", "medium", "low"]


def compact_info(rec: dict) -> dict:
    """Trigger and context size before/after a compaction, from its compact_boundary record."""
    meta = rec.get("compactMetadata")
    meta = meta if isinstance(meta, dict) else {}
    pre, post, trigger = meta.get("preTokens"), meta.get("postTokens"), meta.get("trigger")
    return {
        "trigger": trigger if isinstance(trigger, str) else None,
        "pre": pre if isinstance(pre, int) else None,
        "post": post if isinstance(post, int) else None,
    }


def is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def as_count(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def compact_extra(c: dict) -> dict:
    return {k: c[k] for k in ("trigger", "pre", "post") if c.get(k) is not None}


def effort_mix(levels) -> dict[str, int]:
    counts = Counter(levels)
    rank = {e: i for i, e in enumerate(EFFORT_ORDER)}
    return dict(sorted(counts.items(), key=lambda kv: (rank.get(kv[0], len(rank)), kv[0])))


COMMIT_OUTPUT_RE = re.compile(r"^\[([^\]\s]+)(?: \([^)]*\))? ([0-9a-f]{7,40})\] (.*)$", re.M)
COMMIT_MSG_HEREDOC_RE = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?\n(.*?)\n\s*\1", re.S)
COMMIT_MSG_RE = re.compile(r"""(?:-m|--message)(?:=|\s+)(?:"((?:[^"\\]|\\.)*)"|'([^']*)'|(\S+))""")
# Title and head branch given to `gh pr create`.
PR_TITLE_RE = re.compile(
    r"""(?<!\S)(?:-t|--title)(?:=|\s+)(?:"((?:[^"\\]|\\.)*)"|'([^']*)'|(\S+))"""
)
PR_HEAD_RE = re.compile(r"""(?<!\S)(?:-H|--head)(?:=|\s+)["']?([^\s"']+)""")
TASK_ID_RE = re.compile(r"<task-id>(.*?)</task-id>", re.S)
TASK_STATUS_RE = re.compile(r"<status>(.*?)</status>", re.S)
TASK_SUMMARY_RE = re.compile(r"<summary>(.*?)</summary>", re.S)
COMMAND_NAME_RE = re.compile(r"<command-name>(.*?)</command-name>", re.S)
COMMAND_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
# Text pasted into the prompt box is wrapped as <pasted_content id="..">..</pasted_content id="..">.
PASTED_TAG = "<pasted_content"
PASTED_TAG_RE = re.compile(r"</?pasted_content\b[^>]*>")
DENSITY_BUCKET_MS = 10 * 60 * 1000
# Totals in a cost record that a continuation carries over from its predecessor.
CUMULATIVE_COST_KEYS = ("totalCostUSD", "totalLinesAdded", "totalLinesRemoved", "totalAPIDuration")
# A cost record this far above the session's own token estimate is taken to be cumulative: a
# continuation that names no predecessor. Real records stay below twice the estimate, while a
# continuation's full record is many times its own share.
CUMULATIVE_RATIO = 3
CUMULATIVE_MARGIN_USD = 1.0
# Totals in a cost record that cover only the Claude Code process that wrote it. A resumed
# session's last record starts again from zero, so these say nothing about its earlier runs.
RUN_COST_KEYS = (*CUMULATIVE_COST_KEYS, "totalDuration")
# Prompt cache lifetimes. A request's usage says which one its cache writes got; without that,
# the API's default of 5 minutes is assumed.
CACHE_TTL_5M_MS = 5 * 60 * 1000
CACHE_TTL_1H_MS = 60 * 60 * 1000

# A session ran on a bloated context when at least BLOAT_REQUESTS of its requests each resent
# more than BLOAT_TOKENS. Sessions on a 200k-token window compact on their own before that, so
# only a larger window lets the context grow past it, and every request then costs a few times
# as much as one on a compacted context.
BLOAT_TOKENS = 200_000
BLOAT_REQUESTS = 20
CONTEXT_POINTS = 400  # most points in the detail pane's context chart


def parse_ts(value: Any) -> int | None:
    """ISO-8601 timestamp -> epoch milliseconds."""
    if not isinstance(value, str):
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def tool_result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    parts.append(b.get("text", ""))
                elif b.get("type") == "image":
                    parts.append("[image]")
        return "\n".join(parts)
    return ""


def prompt_text(content: Any) -> str:
    """Text of a human prompt, with the pasted-content wrapper tags removed."""
    return PASTED_TAG_RE.sub("", content_text(content)).strip()


def _from_human(rec: dict, kind: str | None) -> bool:
    if kind is not None:
        return kind == "human"
    # The Claude desktop app writes typed prompts without `origin`. Records the
    # app generates itself (scheduled runs and the like) carry promptSource=system.
    return rec.get("entrypoint") == "claude-desktop" and rec.get("promptSource") != "system"


def classify_user(rec: dict) -> str:
    """Classify a `type=user` record.

    Returns one of: prompt, command, tool_result, interrupt, notification, compact, meta.
    A prompt is text the user wrote: `origin.kind == "human"` (or a desktop-app record,
    which has no `origin`) whose text is not one of Claude Code's own `<tag>` wrappers.
    Pasted text is the exception: it starts with `<pasted_content>` but is still a prompt.
    """
    content = rec.get("message", {}).get("content")
    if rec.get("toolUseResult") is not None or (
        isinstance(content, list)
        and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
    ):
        return "tool_result"
    if rec.get("isCompactSummary"):
        return "compact"
    text = content_text(content).lstrip()
    if text.startswith(INTERRUPT_PREFIX):
        return "interrupt"
    origin = rec.get("origin")
    kind = origin.get("kind") if isinstance(origin, dict) else None
    if kind == "task-notification" or text.startswith("<task-notification>"):
        return "notification"
    if rec.get("isMeta") or not _from_human(rec, kind):
        return "meta"
    if text.startswith("<command-message>") or text.startswith("<command-name>"):
        return "command"
    if text.startswith("<") and not text.startswith(PASTED_TAG):
        return "meta"
    return "prompt"


def command_text(text: str) -> str:
    name = COMMAND_NAME_RE.search(text)
    args = COMMAND_ARGS_RE.search(text)
    out = name.group(1).strip() if name else "/command"
    if args and args.group(1).strip():
        out += " " + args.group(1).strip()
    return out


def pr_create_args(command: str) -> tuple[str | None, str | None]:
    """(title, head branch) given to `gh pr create` in a shell command; None when not given."""
    if "pr create" not in command:
        return None, None
    title = None
    if m := PR_TITLE_RE.search(command):
        title = next(g for g in m.groups() if g is not None).replace('\\"', '"').strip()
        # A title read from a command substitution is not known from the command alone.
        if not title or title.startswith("$("):
            title = None
    head = None
    if m := PR_HEAD_RE.search(command):
        head = m.group(1).rsplit(":", 1)[-1]  # owner:branch for a branch on a fork
    return title, head


def extract_commit_subject(command: str) -> str | None:
    m = COMMIT_MSG_HEREDOC_RE.search(command)
    if m:
        body = m.group(2).strip()
        return body.splitlines()[0].strip() if body else None
    m = COMMIT_MSG_RE.search(command)
    if m:
        msg = next(g for g in m.groups() if g is not None)
        msg = msg.replace('\\"', '"')
        return msg.splitlines()[0].strip() if msg.strip() else None
    return None


class CopiedHead:
    """Spots the copy of an earlier session that a continued session's log starts with.

    Older Claude Code versions keep the earlier session's ID on the copied records, which tells
    them apart. Newer ones rewrite it to the new session's, and give every copied user record
    the prompt ID of the new session's first turn. A user record never shares the prompt ID of a
    turn that has already ended, so a user record under the log's first prompt ID that follows a
    `turn_duration` record shows that everything up to that turn end was copied. A copy whose
    last turn did not end cleanly is not recognised.

    Feed it a log's records in order, leaving out those under another session's ID.
    """

    def __init__(self) -> None:
        self.prompt_id: str | None = None
        self.open = True  # still among the records under the log's first prompt ID
        self.seen = 0  # records fed
        self.turn_end: int | None = None  # records fed up to the last turn end among them
        self.copied = 0  # leading records known to be copied
        self.uuids: set[str] = set()  # repeated records tell nothing new

    def feed(self, rec: dict) -> bool:
        """Note the next record; True when it shows that more of the log was copied."""
        self.seen += 1
        if not self.open:
            return False
        uuid = rec.get("uuid")
        if uuid:
            if uuid in self.uuids:
                return False
            self.uuids.add(uuid)
        rtype = rec.get("type")
        if rtype == "user" and uuid:
            pid = rec.get("promptId")
            if self.prompt_id is None and isinstance(pid, str):
                self.prompt_id = pid
            elif pid != self.prompt_id or pid is None:
                self.open, self.uuids = False, set()
            elif self.turn_end is not None:
                self.copied, self.turn_end = self.turn_end, None
                return True
        elif rtype == "system" and rec.get("subtype") == "turn_duration" and self.prompt_id:
            self.turn_end = self.seen
        return False


def clip_spans(spans: list[list[int]], segments: list[list[int]]) -> list[list[int]]:
    """The parts of `spans` (sorted, not overlapping) inside `segments`, adjoining ones merged."""
    out: list[list[int]] = []
    i = 0
    for a, b in spans:
        while i < len(segments) and segments[i][1] < a:
            i += 1
        j = i
        while j < len(segments) and segments[j][0] < b:
            lo, hi = max(a, segments[j][0]), min(b, segments[j][1])
            if hi > lo:
                if out and out[-1][1] >= lo:
                    out[-1][1] = max(out[-1][1], hi)
                else:
                    out.append([lo, hi])
            j += 1
    return out


def copied_head_length(records: list[dict]) -> int:
    """How many of `records` (one log's, in order) were copied from the session it continues."""
    head = CopiedHead()
    for rec in records:
        head.feed(rec)
        if not head.open:
            break
    return head.copied


@dataclass
class Usage:
    model: str | None
    usage: dict
    ts: int | None

    @property
    def total(self) -> int:
        u = self.usage
        return (
            u.get("input_tokens", 0)
            + u.get("output_tokens", 0)
            + u.get("cache_creation_input_tokens", 0)
            + u.get("cache_read_input_tokens", 0)
        )

    @property
    def context(self) -> int:
        u = self.usage
        return (
            u.get("input_tokens", 0)
            + u.get("cache_creation_input_tokens", 0)
            + u.get("cache_read_input_tokens", 0)
        )


def cache_ttl_ms(usage: dict) -> int | None:
    """Lifetime of the cache entries a request wrote, or None when it wrote none or says not."""
    cc = usage.get("cache_creation")
    if not isinstance(cc, dict):
        return None
    if cc.get("ephemeral_1h_input_tokens"):
        return CACHE_TTL_1H_MS
    if cc.get("ephemeral_5m_input_tokens"):
        return CACHE_TTL_5M_MS
    return None


def idle_recaches(usages: list[Usage], resets: list[int] | tuple = ()) -> list[list]:
    """Requests of one thread (the main session or one subagent) that rewrote the cache after
    it expired: [ts, tokens, estimated USD] each, oldest first.

    A request counts when it came more than the cache lifetime after the thread's previous
    request on the same model, with no compaction (`resets`) in between. Only the part of its
    cache write that the previous request's cache covered counts, and only what writing it cost
    over reading it, which is what a warm cache would have charged.
    """
    out: list[list] = []
    ttl = CACHE_TTL_5M_MS
    prev: Usage | None = None
    for u in sorted((u for u in usages if u.ts is not None), key=lambda u: u.ts):
        if (
            prev is not None
            and u.model == prev.model
            and u.ts - prev.ts > ttl
            and not any(prev.ts < r <= u.ts for r in resets)
        ):
            cached = prev.usage.get("cache_read_input_tokens", 0) + prev.usage.get(
                "cache_creation_input_tokens", 0
            )
            tokens = min(
                u.usage.get("cache_creation_input_tokens", 0),
                max(0, cached - u.usage.get("cache_read_input_tokens", 0)),
            )
            if tokens > 0:
                out.append([u.ts, tokens, recache_cost(u.model, tokens)])
        ttl = cache_ttl_ms(u.usage) or ttl
        prev = u
    return out


@dataclass
class SubagentAcc:
    agent_id: str
    path: str | None = None
    agent_type: str | None = None
    description: str | None = None
    model: str | None = None
    tool_use_id: str | None = None
    status: str | None = None
    first_ts: int | None = None
    last_ts: int | None = None
    usages: dict[str, Usage] = field(default_factory=dict)

    def tokens(self) -> int:
        return sum(u.total for u in self.usages.values())

    def cost(self) -> float:
        return sum(estimate_cost(u.model, u.usage) for u in self.usages.values())

    def to_dict(self) -> dict:
        models = Counter(u.model for u in self.usages.values() if u.model)
        return {
            "id": self.agent_id,
            "type": self.agent_type,
            "description": self.description,
            "model": self.model or (models.most_common(1)[0][0] if models else None),
            "status": self.status,
            "start": self.first_ts,
            "end": self.last_ts,
            "tokens": self.tokens(),
            "cost": round(self.cost(), 4),
            "has_log": self.path is not None,
            "tool_use_id": self.tool_use_id,
        }


@dataclass
class SessionAcc:
    """Accumulates everything the viewer needs about one session."""

    session_id: str
    path: str
    project_dir: str
    source: str = ""  # name of the Claude config directory the log was read from
    cwd: str | None = None
    git_branch: str | None = None
    seen_uuids: set[str] = field(default_factory=set)
    activity: list[int] = field(default_factory=list)
    density_events: list[int] = field(default_factory=list)
    usages: dict[str, Usage] = field(default_factory=dict)
    prompts: list[dict] = field(default_factory=list)
    ai_title: str | None = None
    agent_name: str | None = None
    last_prompt: str | None = None
    cost_state: dict | None = None
    continued_in: str | None = None
    copied_from: str | None = None  # session whose records this log starts with a copy of
    # Leading records copied under this session's own ID (see CopiedHead); not counted.
    copied_head: int = 0
    head: CopiedHead = field(default_factory=CopiedHead, repr=False)
    head_tail: list[dict] = field(default_factory=list, repr=False)  # fed since head.turn_end
    # Set by the store: the session this one continues (also when its log is gone) and that
    # session's last cost record, whose totals this session's record starts from.
    predecessor: str | None = None
    prior_cost_state: dict | None = None
    # API message IDs of the predecessor: a continuation's log may start with copies of them.
    prior_usage_ids: frozenset[str] = frozenset()
    permission_mode: str | None = None
    last_stop_reason: str | None = None
    last_assistant_ts: int | None = None
    last_main_usage: Usage | None = None
    last_turn_end_ts: int | None = None
    last_prompt_ts: int | None = None
    last_interrupt_ts: int | None = None
    interrupts: int = 0  # times the user stopped Claude with Esc
    queued_prompts: int = 0  # prompts typed while Claude was working, read mid-turn
    pending_background: int = 0
    # Main-thread turns, ended: [start, end, opener] each, oldest first (see work_spans).
    turns: list[list] = field(default_factory=list)
    open_turn: list | None = None  # [start, last activity, opener] of a turn not ended yet
    compactions: list[dict] = field(default_factory=list)  # {ts, trigger, pre, post}
    efforts: dict[str, str] = field(default_factory=dict)  # API request id -> effort level
    api_errors: list[int] = field(default_factory=list)
    commits: list[dict] = field(default_factory=list)
    files: Counter = field(default_factory=Counter)
    # url -> {number, url, repo}, plus `created` (ms), `head` and `title` for PRs opened here.
    prs: dict[str, dict] = field(default_factory=dict)
    branches: list[list] = field(default_factory=list)  # [ts, git branch] at each change
    pending_sub_prs: dict[str, str] = field(default_factory=dict)  # tool_use id -> command
    subagents: dict[str, SubagentAcc] = field(default_factory=dict)
    background: dict[str, dict] = field(default_factory=dict)
    pending_tools: dict[str, dict] = field(default_factory=dict)
    # Every tool call, including subagents': [ts, name, is_error, agent_id or None].
    tool_calls: list[list] = field(default_factory=list)
    pending_sub_calls: dict[str, int] = field(default_factory=dict)  # tool_use id -> index
    version: str | None = None

    # ------------------------------------------------------------------ feeding

    def feed(self, rec: dict) -> None:
        sid = rec.get("sessionId")
        # A continued session may begin with a verbatim copy of its predecessor.
        if sid is not None and sid != self.session_id:
            self.copied_from = sid
            return
        head = self.head
        if head.open:
            if head.feed(rec):
                self._drop_copied_head()
            if head.turn_end == head.seen:
                self.head_tail = []
            elif head.open and head.turn_end is not None:
                self.head_tail.append(rec)
            else:
                self.head_tail = []
        self._feed(rec)

    # Kept when a copied head is dropped: they describe the session rather than count its work.
    HEAD_KEEP = (
        "cwd",
        "git_branch",
        "version",
        "seen_uuids",
        "ai_title",
        "agent_name",
        "last_prompt",
        "cost_state",
        "continued_in",
        "copied_from",
        "predecessor",
        "prior_cost_state",
        "prior_usage_ids",
        "permission_mode",
        "head",
    )

    def _drop_copied_head(self) -> None:
        """Forget what the records before the head's tail added: they were copied from the
        session this one continues. Then feed the tail again."""
        tail = self.head_tail
        fresh = SessionAcc(self.session_id, self.path, self.project_dir, self.source)
        for name in fresh.__dataclass_fields__:
            if name not in self.HEAD_KEEP and name != "subagents":
                setattr(self, name, getattr(fresh, name))
        # Subagents with a log of their own in this session's directory stay.
        self.subagents = {k: sa for k, sa in self.subagents.items() if sa.path is not None}
        self.copied_head = self.head.copied
        for rec in tail:
            self.seen_uuids.discard(rec.get("uuid"))
        for rec in tail:
            self._feed(rec)

    def _feed(self, rec: dict) -> None:
        uuid = rec.get("uuid")
        if uuid:
            if uuid in self.seen_uuids:
                return
            self.seen_uuids.add(uuid)

        rtype = rec.get("type")
        ts = parse_ts(rec.get("timestamp"))
        # The launch directory identifies the project; later `cd`s inside it do not.
        if rec.get("cwd") and self.cwd is None:
            self.cwd = rec["cwd"]
        if rec.get("gitBranch"):
            self.git_branch = rec["gitBranch"]
            if ts is not None and (not self.branches or self.branches[-1][1] != self.git_branch):
                self.branches.append([ts, self.git_branch])
        if rec.get("version"):
            self.version = rec["version"]

        if ts is not None and not rec.get("isSidechain"):
            self._track_turn(rec, rtype, ts)
        if rtype == "user":
            self._feed_user(rec, ts)
        elif rtype == "assistant":
            self._feed_assistant(rec, ts)
        elif rtype == "system":
            if rec.get("subtype") == "turn_duration":
                self.last_turn_end_ts = ts
                self.pending_background = rec.get("pendingBackgroundAgentCount") or 0
            elif rec.get("subtype") == "compact_boundary" and ts is not None:
                self.compactions.append({"ts": ts, **compact_info(rec)})
        elif rtype == "attachment":
            # Notifications that arrive mid-turn are queued as attachments, not user records.
            att = rec.get("attachment") or {}
            prompt = att.get("prompt")
            if att.get("type") == "queued_command" and isinstance(prompt, str):
                if "<task-notification>" in prompt:
                    self._feed_notification(prompt)
                elif att.get("commandMode") == "prompt" and isinstance(att.get("origin"), dict):
                    # A prompt typed while Claude was working, which it read before its turn ended.
                    if att["origin"].get("kind") == "human":
                        self.queued_prompts += 1
        elif rtype == "ai-title":
            self.ai_title = rec.get("aiTitle") or self.ai_title
        elif rtype == "agent-name":
            self.agent_name = rec.get("agentName") or self.agent_name
        elif rtype == "last-prompt":
            self.last_prompt = rec.get("lastPrompt") or self.last_prompt
        elif rtype == "cost-state":
            self.cost_state = rec
        elif rtype == "continued-in":
            # A copy of the predecessor's record rewritten to this session's ID names itself.
            if rec.get("continuedInSessionId") != self.session_id:
                self.continued_in = rec.get("continuedInSessionId")
        elif rtype == "permission-mode":
            self.permission_mode = rec.get("permissionMode")
        elif rtype == "pr-link" and rec.get("prUrl"):
            # Written when a PR is opened, also by a subagent, and again later on.
            self.note_pr(
                rec["prUrl"],
                rec.get("prNumber"),
                rec.get("prRepository"),
                created=ts if ts is not None else self.end,
            )

    def _track_turn(self, rec: dict, rtype: str | None, ts: int) -> None:
        """Follow the main thread's turns, from what started each to its end.

        A turn ends at its `turn_duration` record, whose durationMs says when it started (that
        also covers turns started by a prompt queued mid-turn, which leaves no prompt record), or
        at an interrupt. A turn that ends neither way (a local command such as /model, a killed
        process) ends at its last record before the next turn starts. The opener says what
        started it: "human" (a prompt or command), "notification" (a background task finished)
        or None (unknown).
        """
        t = self.open_turn
        if rtype == "system" and rec.get("subtype") == "turn_duration":
            dur = rec.get("durationMs")
            start = ts - dur if is_number(dur) and dur >= 0 else (t[0] if t else None)
            if start is not None:
                self._end_turn(start, ts, t[2] if t else None)
            self.open_turn = None
            return
        if rtype == "user":
            kind = classify_user(rec)
            if kind in ("prompt", "command", "notification"):
                if t is not None:
                    self._end_turn(t[0], t[1], t[2])
                self.open_turn = [ts, ts, "notification" if kind == "notification" else "human"]
                return
            if kind == "interrupt" and t is not None:
                self._end_turn(t[0], ts, t[2])
                self.open_turn = None
                return
        if t is not None and rtype in ("user", "assistant"):
            t[1] = max(t[1], ts)

    def _end_turn(self, start: int, end: int, opener: str | None) -> None:
        # Turns do not overlap; a durationMs reaching back past the previous end is cut there.
        if self.turns:
            start = max(start, self.turns[-1][1])
        if end >= start:
            self.turns.append([start, end, opener])

    def _feed_user(self, rec: dict, ts: int | None) -> None:
        if ts is not None:
            self.activity.append(ts)
        kind = classify_user(rec)
        content = rec.get("message", {}).get("content")
        if rec.get("permissionMode"):
            self.permission_mode = rec["permissionMode"]
        if kind in ("prompt", "command"):
            if kind == "command":
                text = command_text(content_text(content))
            else:
                text = prompt_text(content)
            self.prompts.append({"uuid": rec.get("uuid"), "ts": ts, "text": text, "kind": kind})
            self.last_prompt_ts = ts
            if ts is not None:
                self.density_events.append(ts)
        elif kind == "interrupt":
            self.last_interrupt_ts = ts
            self.interrupts += 1
        elif kind == "notification":
            self._feed_notification(content_text(content))
        elif kind == "tool_result":
            self._feed_tool_results(rec, content, ts)

    def _feed_notification(self, text: str) -> None:
        tid = TASK_ID_RE.search(text)
        if not tid:
            return
        task_id = tid.group(1).strip()
        entry = self.background.setdefault(task_id, {"id": task_id, "description": None})
        st = TASK_STATUS_RE.search(text)
        if st:
            entry["status"] = st.group(1).strip()
        sm = TASK_SUMMARY_RE.search(text)
        if sm:
            entry["summary"] = sm.group(1).strip()[:300]
        if task_id in self.subagents and st:
            self.subagents[task_id].status = st.group(1).strip()

    def _feed_tool_results(self, rec: dict, content: Any, ts: int | None) -> None:
        tur = rec.get("toolUseResult")
        blocks = content if isinstance(content, list) else []
        command = ""
        for b in blocks:
            if not isinstance(b, dict) or b.get("type") != "tool_result":
                continue
            pending = self.pending_tools.pop(b.get("tool_use_id"), None)
            if pending is None:
                continue
            is_error = bool(b.get("is_error"))
            name = pending["name"]
            if name == "Bash":
                command = pending["input"].get("command", "")
            if is_error:
                self.tool_calls[pending["call"]][2] = True
            if name == "Bash":
                self._bash_result(pending, tur, tool_result_text(b.get("content")), is_error, ts)
            elif name in ("Agent", "Task") and isinstance(tur, dict):
                aid = tur.get("agentId")
                if aid:
                    sa = self.subagents.setdefault(aid, SubagentAcc(aid))
                    sa.tool_use_id = b.get("tool_use_id")
                    sa.description = sa.description or pending["input"].get("description")
                    sa.agent_type = sa.agent_type or pending["input"].get("subagent_type")
                    sa.model = sa.model or tur.get("resolvedModel")
                    sa.status = tur.get("status") or sa.status
            elif name in ("Edit", "Write", "MultiEdit", "NotebookEdit") and not is_error:
                path = pending["input"].get("file_path") or pending["input"].get("notebook_path")
                if path:
                    self.files[path] += 1
        if isinstance(tur, dict):
            git_op = tur.get("gitOperation")
            if isinstance(git_op, dict) and isinstance(git_op.get("pr"), dict):
                pr = git_op["pr"]
                if pr.get("url"):
                    self.note_pr(pr["url"], pr.get("number"))
                    if pr.get("action") == "created":
                        self.pr_created(pr["url"], ts, command, git_op, rec.get("gitBranch"))

    def note_pr(
        self, url: str, number: Any, repo: str | None = None, created: int | None = None
    ) -> dict:
        pr = self.prs.setdefault(url, {"number": number, "url": url, "repo": repo})
        pr["number"] = number if number is not None else pr["number"]
        pr["repo"] = repo or pr["repo"]
        if created is not None and (pr.get("created") is None or created < pr["created"]):
            pr["created"] = created
        return pr

    def pr_created(
        self,
        url: str,
        ts: int | None,
        command: str,
        git_op: dict,
        branch: str | None,
        agent: str | None = None,
    ) -> None:
        """A `gh pr create` that opened `url`: when, its title and its head branch, and the
        subagent that ran it, if one did.

        The head is the --head given, else the branch pushed with it, else the branch the
        command ran on.
        """
        pr = self.note_pr(url, None, created=ts)
        if agent:
            pr["agent"] = agent
        title, head = pr_create_args(command)
        push = git_op.get("push")
        pushed = push.get("branch") if isinstance(push, dict) else None
        head = head or (pushed if isinstance(pushed, str) else None) or branch or self.git_branch
        pr["title"] = pr.get("title") or title
        pr["head"] = pr.get("head") or head

    def _bash_result(
        self, pending: dict, tur: Any, output: str, is_error: bool, ts: int | None
    ) -> None:
        tur = tur if isinstance(tur, dict) else {}
        if tur.get("backgroundTaskId"):
            tid = tur["backgroundTaskId"]
            self.background.setdefault(tid, {"id": tid, "status": "running"})
            self.background[tid]["description"] = (
                pending["input"].get("description") or pending["input"].get("command", "")[:120]
            )
        if tur.get("bashEditDiff") and isinstance(tur["bashEditDiff"], dict):
            path = tur["bashEditDiff"].get("filePath")
            if path:
                self.files[path] += 1
        command = pending["input"].get("command", "")
        if not GIT_COMMIT_RE.search(command) or is_error or tur.get("interrupted"):
            return
        found: list[dict] = []
        git_op = tur.get("gitOperation")
        if isinstance(git_op, dict) and isinstance(git_op.get("commit"), dict):
            c = git_op["commit"]
            if c.get("sha"):
                found.append({"sha": c["sha"], "branch": c.get("branch"), "subject": None})
        if not found:
            for m in COMMIT_OUTPUT_RE.finditer(output):
                found.append({"branch": m.group(1), "sha": m.group(2), "subject": m.group(3)})
        subject = extract_commit_subject(command)
        if not found and subject:
            found.append({"sha": None, "branch": None, "subject": subject})
        for c in found:
            c["subject"] = c["subject"] or subject
            c["ts"] = ts
            c["cwd"] = self.cwd
            self.commits.append(c)

    def _feed_assistant(self, rec: dict, ts: int | None) -> None:
        msg = rec.get("message") or {}
        model = msg.get("model")
        if model == "<synthetic>" or rec.get("isApiErrorMessage"):
            if ts is not None:
                self.api_errors.append(ts)
            return
        if ts is not None:
            self.activity.append(ts)
        mid = msg.get("id") or rec.get("requestId") or rec.get("uuid")
        usage = msg.get("usage") or {}
        if isinstance(rec.get("effort"), str):
            self.efforts[mid] = rec["effort"]
        if mid not in self.usages and ts is not None:
            self.density_events.append(ts)
        prev = self.usages.get(mid)
        if prev is None or usage.get("output_tokens", 0) >= prev.usage.get("output_tokens", 0):
            u = Usage(model, usage, ts)
            self.usages[mid] = u
            self.last_main_usage = u
        if msg.get("stop_reason"):
            self.last_stop_reason = msg["stop_reason"]
        self.last_assistant_ts = ts
        for b in msg.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                self.pending_tools[b.get("id")] = {
                    "name": b.get("name"),
                    "input": b.get("input") if isinstance(b.get("input"), dict) else {},
                    "call": len(self.tool_calls),
                }
                self.tool_calls.append([ts, b.get("name") or "?", False, None])

    def feed_subagent(self, agent_id: str, path: str, rec: dict) -> None:
        sa = self.subagents.setdefault(agent_id, SubagentAcc(agent_id))
        sa.path = path
        msg = rec.get("message") or {}
        content = msg.get("content")
        if rec.get("type") == "user" and isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    i = self.pending_sub_calls.pop(b.get("tool_use_id"), None)
                    if i is not None and b.get("is_error"):
                        self.tool_calls[i][2] = True
                    command = self.pending_sub_prs.pop(b.get("tool_use_id"), "")
                    tur = rec.get("toolUseResult")
                    git_op = tur.get("gitOperation") if isinstance(tur, dict) else None
                    pr = git_op.get("pr") if isinstance(git_op, dict) else None
                    # A PR the subagent opened; the main log's pr-link names it as well.
                    if isinstance(pr, dict) and pr.get("url") and pr.get("action") == "created":
                        ts = parse_ts(rec.get("timestamp"))
                        branch = rec.get("gitBranch")
                        self.pr_created(pr["url"], ts, command, git_op, branch, agent_id)
        if rec.get("type") != "assistant" or msg.get("model") == "<synthetic>":
            return
        ts = parse_ts(rec.get("timestamp"))
        for b in content if isinstance(content, list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                self.pending_sub_calls[b.get("id")] = len(self.tool_calls)
                self.tool_calls.append([ts, b.get("name") or "?", False, agent_id])
                command = (b.get("input") or {}).get("command")
                if b.get("name") == "Bash" and isinstance(command, str) and "pr create" in command:
                    self.pending_sub_prs[b.get("id")] = command
        if ts is not None:
            sa.first_ts = ts if sa.first_ts is None else min(sa.first_ts, ts)
            sa.last_ts = ts if sa.last_ts is None else max(sa.last_ts, ts)
        mid = msg.get("id") or rec.get("requestId") or rec.get("uuid")
        usage = msg.get("usage") or {}
        prev = sa.usages.get(mid)
        if prev is None or usage.get("output_tokens", 0) >= prev.usage.get("output_tokens", 0):
            sa.usages[mid] = Usage(msg.get("model"), usage, ts)

    def apply_subagent_meta(self, agent_id: str, meta: dict) -> None:
        sa = self.subagents.setdefault(agent_id, SubagentAcc(agent_id))
        sa.agent_type = meta.get("agentType") or sa.agent_type
        sa.description = meta.get("description") or sa.description
        sa.model = meta.get("model") or sa.model
        sa.tool_use_id = meta.get("toolUseId") or sa.tool_use_id

    # ------------------------------------------------------------------ derived

    @property
    def start(self) -> int | None:
        return min(self.activity) if self.activity else None

    @property
    def end(self) -> int | None:
        return max(self.activity) if self.activity else None

    def branch_at(self, ts: int) -> str | None:
        """The git branch the session was on at `ts` (its first one before that)."""
        if not self.branches:
            return self.git_branch
        i = bisect_right(self.branches, ts, key=lambda b: b[0]) - 1
        return self.branches[max(i, 0)][1]

    def title(self) -> str:
        if self.ai_title:
            return self.ai_title
        if self.agent_name:
            return self.agent_name
        for p in self.prompts:
            if p["text"]:
                return p["text"].splitlines()[0][:120]
        return self.last_prompt or "(untitled session)"

    def segments(self, gap_ms: int) -> list[list[int]]:
        if not self.activity:
            return []
        times = sorted(self.activity)
        segs = [[times[0], times[0]]]
        for t in times[1:]:
            if t - segs[-1][1] > gap_ms:
                segs.append([t, t])
            else:
                segs[-1][1] = t
        return segs

    def work_spans(self, gap_ms: int) -> dict:
        """When Claude worked and when it waited for you, as [start, end] spans, oldest first.

        Working: the main thread's turns, cut to the activity segments so it never exceeds the
        active time (a long silent tool call is not counted, as in segments). The gap before a
        turn that a finished background task started counts as working too: the session was
        busy with its own background work. Waiting: the gap between the end of a turn
        (finished or interrupted) and your next prompt or command. Gaps longer than `gap_ms`
        count as neither, as active time splits there. Subagents run inside their parent's turn
        and are not counted again. A turn still running counts up to its latest record.
        """
        turns = [*self.turns, *([self.open_turn] if self.open_turn else [])]
        working: list[list[int]] = []
        waiting: list[list[int]] = []
        for i, (start, end, opener) in enumerate(turns):
            prev = turns[i - 1][1] if i else None
            if prev is not None and 0 < start - prev <= gap_ms:
                if opener == "human":
                    waiting.append([prev, start])
                elif opener == "notification":
                    working.append([prev, start])
            if end > start:
                working.append([start, end])
        return {"working": clip_spans(sorted(working), self.segments(gap_ms)), "waiting": waiting}

    def work_stats(self, gap_ms: int) -> dict:
        """work_spans and their totals, with the median time you took to reply."""
        spans = self.work_spans(gap_ms)
        replies = [b - a for a, b in spans["waiting"]]
        return {
            **spans,
            "working_ms": sum(b - a for a, b in spans["working"]),
            "waiting_ms": sum(replies),
            "reply_median_ms": round(median(replies)) if replies else None,
        }

    def marks(self) -> list[tuple]:
        """Timestamped events drawn on the calendar bars, oldest first.

        Compactions carry a third element with their trigger and token counts.
        """
        out: list[tuple] = [(p["ts"], "prompt") for p in self.prompts if p["ts"] is not None]
        out += [(c["ts"], "commit") for c in self.commits if c.get("ts") is not None]
        out += [(c["ts"], "compact", compact_extra(c)) for c in self.compactions]
        out += [(t, "error") for t in self.api_errors]
        return sorted(out, key=lambda m: (m[0], m[1]))

    def friction(self) -> dict[str, int]:
        """Signs that the session went badly, counted side by side.

        Tool calls and errors are the main session's: a subagent's failures are its own retries,
        which the user does not see. `total` adds up the events, as a sort key.
        """
        calls = [c for c in self.tool_calls if c[3] is None]
        out = {
            "interrupts": self.interrupts,
            "api_errors": len(self.api_errors),
            "queued_prompts": self.queued_prompts,
            "tool_calls": len(calls),
            "tool_errors": sum(1 for c in calls if c[2]),
        }
        out["total"] = (
            out["interrupts"] + out["api_errors"] + out["queued_prompts"] + out["tool_errors"]
        )
        return out

    def effort_mix(self) -> dict[str, int]:
        """API requests per effort level, highest level first."""
        return effort_mix(self.efforts.values())

    def effort(self) -> str | None:
        """The effort level most requests ran at."""
        mix = self.effort_mix()
        return max(mix, key=mix.get) if mix else None

    def density(self) -> dict[int, int]:
        out: Counter = Counter()
        for t in self.density_events:
            out[t // DENSITY_BUCKET_MS] += 1
        return dict(out)

    def cost_density(self) -> dict[int, float]:
        """Estimated cost per DENSITY_BUCKET_MS bucket, subagents included.

        Lets the UI split a session's cost across days; only the proportions are used. For a
        resumed session the run its cost record covers gets the record's cost and the earlier
        runs their estimate, so earlier days do not take a share of the record.
        """
        out: Counter = Counter()
        if self.cost_basis() == "resumed":
            start = self.cost_state["startTime"]
            for u in self.earlier_usages():
                out[u.ts // DENSITY_BUCKET_MS] += estimate_cost(u.model, u.usage)
            run: Counter = Counter()
            for u in self.all_usages():
                if u.ts is not None and u.ts >= start:
                    run[u.ts // DENSITY_BUCKET_MS] += estimate_cost(u.model, u.usage)
            recorded = float(self.cost_state["totalCostUSD"])
            total = sum(run.values())
            if total > 0:
                for b, c in run.items():
                    out[b] += recorded * c / total
            else:
                out[start // DENSITY_BUCKET_MS] += recorded
        else:
            for u in self.all_usages():
                if u.ts is not None:
                    out[u.ts // DENSITY_BUCKET_MS] += estimate_cost(u.model, u.usage)
        return {b: round(c, 6) for b, c in out.items() if c}

    def cost_breakdown(self) -> dict[int, dict[str, list[float]]]:
        """Tokens and estimated cost per DENSITY_BUCKET_MS bucket and model, subagents included.

        Each entry is [input, output, cache write, cache read] tokens followed by their costs,
        so subagent requests count under the model they ran on.
        """
        out: dict[int, dict[str, list[float]]] = {}
        for u in self.all_usages():
            if u.ts is None:
                continue
            row = out.setdefault(u.ts // DENSITY_BUCKET_MS, {}).setdefault(
                u.model or "unknown", [0] * 8
            )
            for i, k in enumerate(TOKEN_TYPES):
                row[i] += u.usage.get(k, 0)
            for i, c in enumerate(cost_parts(u.model, u.usage)):
                row[4 + i] += c
        return out

    def prompt_costs(self) -> list[dict]:
        """Cost and tokens of each timestamped prompt, oldest first.

        A prompt owns the requests from it until the next prompt, plus the subagents started in
        that span. With Claude Code's own cost record, the estimates are scaled to add up to it
        (requests before the first prompt keep their share), like the per-day split in the UI.
        """
        prompts = sorted((p for p in self.prompts if p["ts"] is not None), key=lambda p: p["ts"])
        starts = [p["ts"] for p in prompts]
        out = [dict(p, cost=0.0, tokens=0, requests=0, subagents=0) for p in prompts]

        def owner(ts: int | None) -> dict | None:
            i = bisect_right(starts, ts) - 1 if ts is not None else -1
            return out[i] if i >= 0 else None

        estimated = 0.0
        for u in self.usages.values():
            cost = estimate_cost(u.model, u.usage)
            estimated += cost
            if (row := owner(u.ts)) is not None:
                row["cost"] += cost
                row["tokens"] += u.total
                row["requests"] += 1
        for sa in self.subagents.values():
            cost = sa.cost()
            estimated += cost
            if (row := owner(sa.first_ts)) is not None:
                row["cost"] += cost
                row["tokens"] += sa.tokens()
                row["subagents"] += 1
        total, _ = self.cost()
        scale = total / estimated if estimated else 1.0
        for row in out:
            row["cost"] *= scale
        return out

    def all_usages(self) -> list[Usage]:
        """API usage of the session and its subagents."""
        out = [*self.usages.values()]
        for sa in self.subagents.values():
            out.extend(sa.usages.values())
        return out

    def cache_stats(self) -> tuple[float | None, float]:
        """(cache hit rate, estimated USD saved by caching), subagents included."""
        usages = self.all_usages()
        saved = sum(cache_savings(u.model, u.usage) for u in usages)
        return cache_hit_rate([u.usage for u in usages]), saved

    def idle_recaches(self) -> list[list]:
        """Requests that rewrote an expired cache, subagents included: [ts, tokens, USD]."""
        resets = [c["ts"] for c in self.compactions]
        out = idle_recaches(list(self.usages.values()), resets)
        for sa in self.subagents.values():
            out += idle_recaches(list(sa.usages.values()))
        return sorted(out)

    def idle_recache_cost(self) -> float:
        """Estimated USD lost to re-caching after idle gaps (see idle_recaches)."""
        return sum(c for _, _, c in self.idle_recaches())

    def tokens(self) -> int:
        return sum(u.total for u in self.usages.values()) + sum(
            s.tokens() for s in self.subagents.values()
        )

    def own_cost_state(self) -> dict | None:
        """The cost record with its cumulative totals cut down to this session's own share.

        A continuation's record starts from its predecessor's final totals, so those are
        subtracted. Totals that cannot be told that way (the predecessor's record is gone, the
        cost is below its, or the record is cumulative with no known predecessor) are None, as
        are a resumed session's run totals, which cover only its last run.
        """
        cs = self.cost_state
        if cs is None:
            return None
        basis = self.cost_basis()
        if basis == "resumed":
            return {**cs, **dict.fromkeys(RUN_COST_KEYS)}
        if self.predecessor is None:
            if basis in ("cumulative", "no_previous"):
                return {**cs, **dict.fromkeys(CUMULATIVE_COST_KEYS)}
            return cs
        prior = self.prior_cost_state or {}
        out = dict(cs)
        for k in CUMULATIVE_COST_KEYS:
            v, p = cs.get(k), prior.get(k)
            out[k] = v - p if is_number(v) and is_number(p) and v >= p else None
        if out["totalCostUSD"] is None:
            out.update(dict.fromkeys(CUMULATIVE_COST_KEYS))
        return out

    def earlier_usages(self) -> list[Usage]:
        """API usage, subagents included, from before the run the cost record covers.

        The record's startTime is when the Claude Code process that wrote it started; a session
        resumed with `claude --resume` keeps its log, so its earlier runs come before that.
        Copies of the predecessor's messages at the start of a continuation are left out.
        """
        cs = self.cost_state or {}
        start = cs.get("startTime")
        if not is_number(start):
            return []
        out = [
            u
            for mid, u in self.usages.items()
            if u.ts is not None and u.ts < start and mid not in self.prior_usage_ids
        ]
        for sa in self.subagents.values():
            out.extend(u for u in sa.usages.values() if u.ts is not None and u.ts < start)
        return out

    def resumed(self) -> bool:
        """True when the cost record covers only the last of several runs of this session.

        A resumed run starts its totals from zero, so the record sits close to the token
        estimate of its own run. A record far above that estimate already counts the earlier
        runs (or a predecessor's), and is left to the other rules.
        """
        cs = self.cost_state
        if not cs or not is_number(cs.get("totalCostUSD")) or not self.earlier_usages():
            return False
        start = cs["startTime"]
        run = sum(
            estimate_cost(u.model, u.usage)
            for u in self.all_usages()
            if u.ts is not None and u.ts >= start
        )
        return cs["totalCostUSD"] <= max(run * CUMULATIVE_RATIO, run + CUMULATIVE_MARGIN_USD)

    def cost_basis(self) -> str:
        """Where cost() comes from.

        "record": Claude Code's cost record; "continued": this continuation's share of its
        cumulative record. Estimated from tokens: "estimate" (no record), "no_previous" (the
        predecessor's log or record is gone) or "negative" (the record is below the
        predecessor's) or "cumulative" (the record is far above the session's own token usage,
        as when it continues a session nothing names and whose copy went unrecognised). Partly
        estimated: "resumed" (the record covers only the last run of a resumed session; earlier
        runs are estimated).
        """
        cs = self.cost_state
        if not cs or not is_number(cs.get("totalCostUSD")):
            return "estimate"
        if self.resumed():
            # Its own process started from zero, so no predecessor totals are in the record.
            return "resumed"
        if self.predecessor is None:
            # Newer continuations rewrite the copied records' session IDs, so nothing in the
            # log names the predecessor once its own log is gone. The copy may still show.
            if self.copied_head:
                return "no_previous"
            est = self.estimate()
            if cs["totalCostUSD"] > max(est * CUMULATIVE_RATIO, est + CUMULATIVE_MARGIN_USD):
                return "cumulative"
            return "record"
        prior = self.prior_cost_state
        if not prior or not is_number(prior.get("totalCostUSD")):
            return "no_previous"
        return "negative" if cs["totalCostUSD"] < prior["totalCostUSD"] else "continued"

    def own_lines(self) -> tuple[int | None, int | None]:
        """(lines added, lines removed) in this session, from its own share of the cost
        record; None when unknown."""
        cs = self.own_cost_state() or {}
        return as_count(cs.get("totalLinesAdded")), as_count(cs.get("totalLinesRemoved"))

    def cost(self) -> tuple[float, bool]:
        """(cost USD, estimated?)"""
        basis = self.cost_basis()
        if basis in ("record", "continued"):
            return float(self.own_cost_state()["totalCostUSD"]), False
        if basis == "resumed":
            earlier = sum(estimate_cost(u.model, u.usage) for u in self.earlier_usages())
            return float(self.cost_state["totalCostUSD"]) + earlier, True
        return self.estimate(), True

    def estimate(self) -> float:
        """Cost USD estimated from token usage, subagents included."""
        est = sum(estimate_cost(u.model, u.usage) for u in self.usages.values())
        return est + sum(s.cost() for s in self.subagents.values())

    def lines_changed(self) -> dict[str, int | None]:
        """Lines added / removed in this session; None when unknown."""
        added, removed = self.own_lines()
        return {"lines_added": added, "lines_removed": removed}

    def models(self) -> list[str]:
        c = Counter(u.model for u in self.usages.values() if u.model)
        return [m for m, _ in c.most_common()]

    def context_pct(self) -> float | None:
        u = self.last_main_usage
        if u is None:
            return None
        return round(100 * u.context / context_window(u.model), 1)

    def context_requests(self) -> list[Usage]:
        """Main-thread requests that sent context, oldest first.

        Copies of the predecessor's messages at the start of a continuation are left out.
        """
        out = [
            u
            for mid, u in self.usages.items()
            if u.ts is not None and u.context > 0 and mid not in self.prior_usage_ids
        ]
        return sorted(out, key=lambda u: u.ts)

    def context_stats(self) -> dict:
        """Average and peak context per request, and whether the session ran bloated."""
        sizes = [u.context for u in self.context_requests()]
        over = sum(1 for n in sizes if n > BLOAT_TOKENS)
        return {
            "context_avg": round(sum(sizes) / len(sizes)) if sizes else None,
            "context_peak": max(sizes) if sizes else None,
            "context_over": over,
            "context_bloated": over >= BLOAT_REQUESTS,
        }

    def context_chart(self) -> dict:
        """Context size per main-thread request for the detail pane's chart.

        Points are [request index, ts, tokens]. A long session is cut down to CONTEXT_POINTS
        points, keeping the smallest and largest request of each stretch, so peaks and the drop
        after a compaction stay visible. `compactions` holds the index of the first request
        after each compaction, in the order of `self.compactions`.
        """
        reqs = self.context_requests()
        n = len(reqs)
        points = [[i, u.ts, u.context] for i, u in enumerate(reqs)]
        if n > CONTEXT_POINTS:
            buckets = CONTEXT_POINTS // 2
            picked = []
            for b in range(buckets):
                chunk = points[b * n // buckets : (b + 1) * n // buckets]
                lo = min(chunk, key=lambda p: p[2])
                hi = max(chunk, key=lambda p: p[2])
                picked += sorted({lo[0]: lo, hi[0]: hi}.values())
            points = picked
        times = [u.ts for u in reqs]
        last = self.last_main_usage
        return {
            "points": points,
            "requests": n,
            "limit": context_window(last.model) if last else None,
            "bloat_tokens": BLOAT_TOKENS,
            "compactions": [min(bisect_right(times, c["ts"]), n) for c in self.compactions],
        }

    def state(self, live: dict | None) -> tuple[str, dict]:
        """Status label plus the individual checks shown in the detail pane."""
        turn_ended = self.last_stop_reason == "end_turn" or (
            self.last_turn_end_ts is not None
            and (self.last_prompt_ts is None or self.last_turn_end_ts >= self.last_prompt_ts)
        )
        interrupted = self.last_interrupt_ts is not None and (
            self.last_prompt_ts is None or self.last_interrupt_ts >= self.last_prompt_ts
        )
        # Tasks still marked running in a dead session were killed with it; only the
        # count Claude Code recorded at the end of the last turn says work was left over.
        bg_running = self.pending_background > 0 or (
            live is not None and any(b.get("status") == "running" for b in self.background.values())
        )
        checks = {
            "turn_ended": turn_ended and not interrupted,
            "no_background": not bg_running,
            "clean_exit": self.cost_state is not None,
        }
        if live is not None:
            status = "running" if live.get("status") == "busy" else "waiting"
        elif interrupted or not turn_ended or bg_running:
            status = "interrupted"
        else:
            status = "done"
        return status, checks
