"""Synthetic Claude Code logs. Never commit real transcripts to this repo."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

BASE = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)
PROJECT = "-work-demo"
CWD = "/work/demo"


def ts(minutes: float) -> str:
    return (BASE + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


class LogBuilder:
    """Builds records for one session in the shape Claude Code writes them."""

    def __init__(self, session_id: str):
        self.sid = session_id
        self.records: list[dict] = []
        self._n = 0

    def _uuid(self) -> str:
        self._n += 1
        return f"{self.sid}-u{self._n}"

    def _base(self, rtype: str, minute: float, **extra) -> dict:
        rec = {
            "type": rtype,
            "uuid": self._uuid(),
            "sessionId": self.sid,
            "timestamp": ts(minute),
            "cwd": CWD,
            "gitBranch": "main",
            "version": "2.1.0",
        }
        rec.update(extra)
        self.records.append(rec)
        return rec

    def prompt(self, minute: float, text: str) -> dict:
        return self._base(
            "user", minute, origin={"kind": "human"}, message={"role": "user", "content": text}
        )

    def command(self, minute: float, name: str, args: str = "") -> dict:
        text = f"<command-name>{name}</command-name>\n<command-args>{args}</command-args>"
        return self._base(
            "user", minute, origin={"kind": "human"}, message={"role": "user", "content": text}
        )

    def interrupt(self, minute: float) -> dict:
        return self._base(
            "user",
            minute,
            message={
                "role": "user",
                "content": [{"type": "text", "text": "[Request interrupted by user]"}],
            },
        )

    def assistant(
        self,
        minute: float,
        blocks: list[dict],
        *,
        msg_id: str,
        model: str = "claude-sonnet-5-5",
        output_tokens: int = 10,
        stop_reason: str | None = None,
        usage: dict | None = None,
        effort: str | None = None,
    ) -> dict:
        u = {"input_tokens": 100, "output_tokens": output_tokens, "cache_read_input_tokens": 1000}
        u.update(usage or {})
        return self._base(
            "assistant",
            minute,
            requestId=f"req-{msg_id}",
            **({"effort": effort} if effort else {}),
            message={
                "id": msg_id,
                "role": "assistant",
                "model": model,
                "content": blocks,
                "stop_reason": stop_reason,
                "usage": u,
            },
        )

    def tool_use(self, minute: float, tool_id: str, name: str, inp: dict, msg_id: str) -> dict:
        return self.assistant(
            minute,
            [{"type": "tool_use", "id": tool_id, "name": name, "input": inp}],
            msg_id=msg_id,
            stop_reason="tool_use",
        )

    def tool_result(
        self, minute: float, tool_id: str, output: str, tur: dict | None = None, is_error=False
    ) -> dict:
        return self._base(
            "user",
            minute,
            message={
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": output,
                        "is_error": is_error,
                    }
                ],
            },
            toolUseResult=tur if tur is not None else {"stdout": output},
        )

    def turn_end(self, minute: float, pending_background: int = 0) -> dict:
        return self._base(
            "system",
            minute,
            subtype="turn_duration",
            pendingBackgroundAgentCount=pending_background,
        )

    def meta(self, rtype: str, **fields) -> dict:
        rec = {"type": rtype, "sessionId": self.sid, **fields}
        self.records.append(rec)
        return rec

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in self.records))
        return path


def cost_totals(cost: float, added: int, removed: int, duration: int = 1000) -> dict:
    """Fields of a cost-state record. All but totalDuration are cumulative over continuations."""
    return {
        "totalCostUSD": cost,
        "totalLinesAdded": added,
        "totalLinesRemoved": removed,
        "totalDuration": duration,
        "modelUsage": {},
    }


def basic_session(sid: str = "s-basic") -> LogBuilder:
    """One prompt, a split assistant message, an edit, a commit and a clean exit."""
    b = LogBuilder(sid)
    b.prompt(0, "Add a README")
    # One API message written as two records (thinking, then text + tool_use).
    b.assistant(1, [{"type": "thinking", "thinking": "plan"}], msg_id="m1", output_tokens=5)
    b.assistant(
        1,
        [
            {"type": "text", "text": "Writing it."},
            {
                "type": "tool_use",
                "id": "t-write",
                "name": "Write",
                "input": {"file_path": f"{CWD}/README.md", "content": "# demo"},
            },
        ],
        msg_id="m1",
        output_tokens=50,
        stop_reason="tool_use",
    )
    b.tool_result(2, "t-write", "ok", {"type": "create"})
    b.tool_use(
        3,
        "t-commit",
        "Bash",
        {"command": 'git add README.md && git commit -m "Add README"'},
        msg_id="m2",
    )
    b.tool_result(4, "t-commit", "[main abc1234] Add README\n 1 file changed")
    b.assistant(5, [{"type": "text", "text": "Done."}], msg_id="m3", stop_reason="end_turn")
    b.turn_end(5)
    b.meta("ai-title", aiTitle="Write the README")
    return b


@pytest.fixture
def claude_dir(tmp_path: Path) -> Path:
    root = tmp_path / ".claude"
    proj = root / "projects" / PROJECT

    basic_session().write(proj / "s-basic.jsonl")

    # A session with a subagent, its meta file, and a dangling subagent symlink.
    sub = LogBuilder("s-sub")
    sub.prompt(60, "Research something")
    sub.tool_use(
        61,
        "t-agent",
        "Agent",
        {"description": "Look things up", "subagent_type": "Explore", "prompt": "go"},
        msg_id="p1",
    )
    sub.tool_result(
        70,
        "t-agent",
        "found it",
        {"agentId": "a1", "status": "completed", "resolvedModel": "claude-haiku-4-5"},
    )
    sub.assistant(71, [{"type": "text", "text": "Summary"}], msg_id="p2", stop_reason="end_turn")
    sub.turn_end(71)
    sub.write(proj / "s-sub.jsonl")
    agent = LogBuilder("s-sub")
    agent.assistant(
        62, [{"type": "text", "text": "searching"}], msg_id="x1", model="claude-haiku-4-5"
    )
    agent.assistant(
        69,
        [{"type": "text", "text": "found it"}],
        msg_id="x2",
        model="claude-haiku-4-5",
        stop_reason="end_turn",
    )
    for r in agent.records:
        r["isSidechain"] = True
    subdir = proj / "s-sub" / "subagents"
    agent.write(subdir / "agent-a1.jsonl")
    (subdir / "agent-a1.meta.json").write_text(
        json.dumps(
            {"agentType": "Explore", "description": "Look things up", "toolUseId": "t-agent"}
        )
    )
    try:
        (subdir / "agent-gone.jsonl").symlink_to(subdir / "does-not-exist.jsonl")
    except OSError:
        pass  # Windows needs Developer Mode or admin rights for symlinks

    # A session that was interrupted mid-turn and then continued in s-next.
    prev = LogBuilder("s-prev")
    prev.prompt(120, "Long task")
    prev.tool_use(121, "t-sleep", "Bash", {"command": "sleep 100"}, msg_id="q1")
    prev.interrupt(122)
    prev.meta("cost-state", **cost_totals(0.75, 2, 0, duration=2000))
    prev.meta("continued-in", continuedInSessionId="s-next")
    prev.write(proj / "s-prev.jsonl")

    nxt = LogBuilder("s-next")
    # The continuation starts with a verbatim copy of its predecessor's records.
    nxt.records.extend(json.loads(json.dumps(r)) for r in prev.records)
    nxt.prompt(200, "Carry on")
    nxt.assistant(201, [{"type": "text", "text": "ok"}], msg_id="n1", stop_reason="end_turn")
    nxt.turn_end(201)
    # Its cost record carries over s-prev's totals: its own share is $1.25, +3 / -1 lines.
    nxt.meta("cost-state", **cost_totals(2.0, 5, 1, duration=1000))
    nxt.write(proj / "s-next.jsonl")

    # A session with no human prompt at all (e.g. started and closed).
    empty = LogBuilder("s-empty")
    empty.meta("permission-mode", permissionMode="default")
    empty.write(proj / "s-empty.jsonl")

    (root / "sessions").mkdir()
    return root


@pytest.fixture
def laptop_dir(tmp_path: Path) -> Path:
    """A second config directory, as if synced from another machine.

    It holds one session of its own and an older copy of s-basic.
    """
    root = tmp_path / "laptop" / ".claude"
    proj = root / "projects" / PROJECT

    own = LogBuilder("s-laptop")
    own.prompt(300, "Fix the build on the laptop")
    own.assistant(301, [{"type": "text", "text": "Fixed."}], msg_id="l1", stop_reason="end_turn")
    own.turn_end(301)
    own.write(proj / "s-laptop.jsonl")

    old = basic_session()
    old.records = [r for r in old.records if parse_minute(r) is None or parse_minute(r) < 3]
    old.write(proj / "s-basic.jsonl")

    (root / "sessions").mkdir()
    return root


def parse_minute(rec: dict) -> float | None:
    if "timestamp" not in rec:
        return None
    t = datetime.fromisoformat(rec["timestamp"].replace("Z", "+00:00"))
    return (t - BASE).total_seconds() / 60
