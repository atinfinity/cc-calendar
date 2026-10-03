"""Incremental parsing of Claude Code session transcripts (~/.claude/projects/**/*.jsonl)."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .pricing import context_window, estimate_cost

INTERRUPT_PREFIX = "[Request interrupted"
GIT_COMMIT_RE = re.compile(r"\bgit\b(?:\s+-[cC]\s+\S+)*[^|;&\n]*?\bcommit\b")
COMMIT_OUTPUT_RE = re.compile(r"^\[([^\]\s]+)(?: \([^)]*\))? ([0-9a-f]{7,40})\] (.*)$", re.M)
COMMIT_MSG_HEREDOC_RE = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?\n(.*?)\n\s*\1", re.S)
COMMIT_MSG_RE = re.compile(r"""(?:-m|--message)(?:=|\s+)(?:"((?:[^"\\]|\\.)*)"|'([^']*)'|(\S+))""")
TASK_ID_RE = re.compile(r"<task-id>(.*?)</task-id>", re.S)
TASK_STATUS_RE = re.compile(r"<status>(.*?)</status>", re.S)
TASK_SUMMARY_RE = re.compile(r"<summary>(.*?)</summary>", re.S)
COMMAND_NAME_RE = re.compile(r"<command-name>(.*?)</command-name>", re.S)
COMMAND_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
DENSITY_BUCKET_MS = 10 * 60 * 1000


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


def classify_user(rec: dict) -> str:
    """Classify a `type=user` record.

    Returns one of: prompt, command, tool_result, interrupt, notification, compact, meta.
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
    if rec.get("isMeta") or kind != "human":
        return "meta"
    if text.startswith("<command-message>") or text.startswith("<command-name>"):
        return "command"
    if text.startswith("<"):
        return "meta"
    return "prompt"


def command_text(text: str) -> str:
    name = COMMAND_NAME_RE.search(text)
    args = COMMAND_ARGS_RE.search(text)
    out = name.group(1).strip() if name else "/command"
    if args and args.group(1).strip():
        out += " " + args.group(1).strip()
    return out


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
    permission_mode: str | None = None
    last_stop_reason: str | None = None
    last_assistant_ts: int | None = None
    last_main_usage: Usage | None = None
    last_turn_end_ts: int | None = None
    last_prompt_ts: int | None = None
    last_interrupt_ts: int | None = None
    pending_background: int = 0
    commits: list[dict] = field(default_factory=list)
    files: Counter = field(default_factory=Counter)
    prs: dict[str, dict] = field(default_factory=dict)
    subagents: dict[str, SubagentAcc] = field(default_factory=dict)
    background: dict[str, dict] = field(default_factory=dict)
    pending_tools: dict[str, dict] = field(default_factory=dict)
    version: str | None = None

    # ------------------------------------------------------------------ feeding

    def feed(self, rec: dict) -> None:
        sid = rec.get("sessionId")
        # A continued session may begin with a verbatim copy of its predecessor.
        if sid is not None and sid != self.session_id:
            return
        uuid = rec.get("uuid")
        if uuid:
            if uuid in self.seen_uuids:
                return
            self.seen_uuids.add(uuid)

        rtype = rec.get("type")
        ts = parse_ts(rec.get("timestamp"))
        if rec.get("cwd"):
            self.cwd = rec["cwd"]
        if rec.get("gitBranch"):
            self.git_branch = rec["gitBranch"]
        if rec.get("version"):
            self.version = rec["version"]

        if rtype == "user":
            self._feed_user(rec, ts)
        elif rtype == "assistant":
            self._feed_assistant(rec, ts)
        elif rtype == "system":
            if rec.get("subtype") == "turn_duration":
                self.last_turn_end_ts = ts
                self.pending_background = rec.get("pendingBackgroundAgentCount") or 0
        elif rtype == "attachment":
            # Notifications that arrive mid-turn are queued as attachments, not user records.
            att = rec.get("attachment") or {}
            prompt = att.get("prompt")
            if att.get("type") == "queued_command" and isinstance(prompt, str):
                if "<task-notification>" in prompt:
                    self._feed_notification(prompt)
        elif rtype == "ai-title":
            self.ai_title = rec.get("aiTitle") or self.ai_title
        elif rtype == "agent-name":
            self.agent_name = rec.get("agentName") or self.agent_name
        elif rtype == "last-prompt":
            self.last_prompt = rec.get("lastPrompt") or self.last_prompt
        elif rtype == "cost-state":
            self.cost_state = rec
        elif rtype == "continued-in":
            self.continued_in = rec.get("continuedInSessionId")
        elif rtype == "permission-mode":
            self.permission_mode = rec.get("permissionMode")
        elif rtype == "pr-link" and rec.get("prUrl"):
            self.prs[rec["prUrl"]] = {
                "number": rec.get("prNumber"),
                "url": rec["prUrl"],
                "repo": rec.get("prRepository"),
            }

    def _feed_user(self, rec: dict, ts: int | None) -> None:
        if ts is not None:
            self.activity.append(ts)
        kind = classify_user(rec)
        content = rec.get("message", {}).get("content")
        if rec.get("permissionMode"):
            self.permission_mode = rec["permissionMode"]
        if kind in ("prompt", "command"):
            text = content_text(content).strip()
            if kind == "command":
                text = command_text(text)
            self.prompts.append({"uuid": rec.get("uuid"), "ts": ts, "text": text, "kind": kind})
            self.last_prompt_ts = ts
            if ts is not None:
                self.density_events.append(ts)
        elif kind == "interrupt":
            self.last_interrupt_ts = ts
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
        for b in blocks:
            if not isinstance(b, dict) or b.get("type") != "tool_result":
                continue
            pending = self.pending_tools.pop(b.get("tool_use_id"), None)
            if pending is None:
                continue
            is_error = bool(b.get("is_error"))
            name = pending["name"]
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
                    self.prs.setdefault(
                        pr["url"], {"number": pr.get("number"), "url": pr["url"], "repo": None}
                    )

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
            return
        if ts is not None:
            self.activity.append(ts)
        mid = msg.get("id") or rec.get("requestId") or rec.get("uuid")
        usage = msg.get("usage") or {}
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
                }

    def feed_subagent(self, agent_id: str, path: str, rec: dict) -> None:
        sa = self.subagents.setdefault(agent_id, SubagentAcc(agent_id))
        sa.path = path
        if rec.get("type") != "assistant":
            return
        msg = rec.get("message") or {}
        if msg.get("model") == "<synthetic>":
            return
        ts = parse_ts(rec.get("timestamp"))
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

    def density(self) -> dict[int, int]:
        out: Counter = Counter()
        for t in self.density_events:
            out[t // DENSITY_BUCKET_MS] += 1
        return dict(out)

    def tokens(self) -> int:
        return sum(u.total for u in self.usages.values()) + sum(
            s.tokens() for s in self.subagents.values()
        )

    def cost(self) -> tuple[float, bool]:
        """(cost USD, estimated?)"""
        if self.cost_state and isinstance(self.cost_state.get("totalCostUSD"), (int, float)):
            return float(self.cost_state["totalCostUSD"]), False
        est = sum(estimate_cost(u.model, u.usage) for u in self.usages.values())
        est += sum(s.cost() for s in self.subagents.values())
        return est, True

    def models(self) -> list[str]:
        c = Counter(u.model for u in self.usages.values() if u.model)
        return [m for m, _ in c.most_common()]

    def context_pct(self) -> float | None:
        u = self.last_main_usage
        if u is None:
            return None
        return round(100 * u.context / context_window(u.model), 1)

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
