"""In-memory index of all sessions, updated incrementally as transcript files grow."""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from .parser import SessionAcc

log = logging.getLogger(__name__)


@dataclass
class FileState:
    offset: int = 0
    inode: int | None = None


class Store:
    def __init__(self, claude_dir: Path):
        self.claude_dir = claude_dir
        self.projects_dir = claude_dir / "projects"
        self.sessions_dir = claude_dir / "sessions"
        self.sessions: dict[str, SessionAcc] = {}
        self.files: dict[Path, FileState] = {}
        self.lock = threading.RLock()

    # ------------------------------------------------------------------ scanning

    def scan(self) -> None:
        if not self.projects_dir.is_dir():
            log.warning("no projects directory at %s", self.projects_dir)
            return
        with self.lock:
            for path in sorted(self.projects_dir.glob("*/*.jsonl")):
                self.update_file(path)
            for path in sorted(self.projects_dir.glob("*/*/subagents/*.meta.json")):
                self.update_file(path)
            for path in sorted(self.projects_dir.glob("*/*/subagents/*.jsonl")):
                self.update_file(path)

    def classify(self, path: Path) -> tuple[str, str, str | None] | None:
        """-> (kind, session_id, agent_id) for a path under projects/, or None."""
        try:
            rel = path.relative_to(self.projects_dir)
        except ValueError:
            return None
        parts = rel.parts
        if len(parts) == 2 and parts[1].endswith(".jsonl"):
            return "main", parts[1][: -len(".jsonl")], None
        if len(parts) == 4 and parts[2] == "subagents" and parts[3].startswith("agent-"):
            name = parts[3][len("agent-") :]
            if name.endswith(".meta.json"):
                return "meta", parts[1], name[: -len(".meta.json")]
            if name.endswith(".jsonl"):
                return "sub", parts[1], name[: -len(".jsonl")]
        return None

    def update_file(self, path: Path) -> str | None:
        """Read new bytes from `path`; return the affected session id."""
        info = self.classify(path)
        if info is None:
            return None
        kind, sid, agent_id = info
        with self.lock:
            session = self._session(sid, path)
            if kind == "meta":
                try:
                    session.apply_subagent_meta(agent_id, json.loads(path.read_text()))
                except (OSError, ValueError):
                    pass
                return sid
            try:
                st = path.stat()
            except OSError:  # deleted or dangling symlink
                return None
            state = self.files.get(path)
            if state is None or st.st_size < state.offset or st.st_ino != state.inode:
                if state is not None and kind == "main":
                    # Rewritten from scratch: rebuild the session but keep subagent data.
                    subagents = session.subagents
                    session = self._session(sid, path, reset=True)
                    session.subagents = subagents
                state = FileState(0, st.st_ino)
                self.files[path] = state
            if st.st_size == state.offset:
                return sid
            for rec in self._read_new(path, state):
                if kind == "main":
                    session.feed(rec)
                else:
                    session.feed_subagent(agent_id, str(path), rec)
            return sid

    def _session(self, sid: str, path: Path, reset: bool = False) -> SessionAcc:
        s = self.sessions.get(sid)
        if s is None or reset:
            project_dir = path.relative_to(self.projects_dir).parts[0]
            main_path = self.projects_dir / project_dir / f"{sid}.jsonl"
            s = SessionAcc(session_id=sid, path=str(main_path), project_dir=project_dir)
            self.sessions[sid] = s
        return s

    @staticmethod
    def _read_new(path: Path, state: FileState):
        with open(path, "rb") as f:
            f.seek(state.offset)
            data = f.read()
        end = data.rfind(b"\n")
        if end < 0:
            return
        state.offset += end + 1
        for line in data[: end + 1].splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                yield rec

    # ------------------------------------------------------------------ live status

    def live_sessions(self) -> dict[str, dict]:
        """sessionId -> live process info, for Claude Code processes that are still alive."""
        out: dict[str, dict] = {}
        if not self.sessions_dir.is_dir():
            return out
        for p in self.sessions_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text())
            except (OSError, ValueError):
                continue
            pid, sid = data.get("pid"), data.get("sessionId")
            if not isinstance(pid, int) or not sid or not _pid_alive(pid):
                continue
            out[sid] = data
        return out

    # ------------------------------------------------------------------ continuation

    def continued_from(self) -> dict[str, str]:
        with self.lock:
            return {s.continued_in: s.session_id for s in self.sessions.values() if s.continued_in}


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
