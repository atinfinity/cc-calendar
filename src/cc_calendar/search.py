"""Full-text index of transcripts: prompts, replies, tool calls and their output.

An SQLite FTS5 table with the trigram tokenizer, so any substring of three or more characters
matches, in any script (Japanese and Chinese have no spaces between words). The index lives in
the user's cache directory and remembers how far into each transcript it has read, so a restart
only indexes what was written since. Thinking is not indexed.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .parser import (
    classify_user,
    command_text,
    content_text,
    parse_ts,
    prompt_text,
    tool_result_text,
)

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
MIN_QUERY = 3  # trigrams: shorter queries cannot match
# Long texts (file contents, build logs) keep their start and end: an error is usually at the end.
TEXT_HEAD = 8_000
TEXT_TAIL = 2_000
SNIPPET_CONTEXT = 60
BUSY_TIMEOUT_MS = 30_000


def default_path() -> Path:
    """search.db in the platform's per-user cache directory."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "cc-calendar" / "search.db"


def normalize(text: str) -> str:
    """Collapse whitespace, so a query matches text that wraps differently."""
    return " ".join(text.split())


def clip(text: str) -> str:
    if len(text) <= TEXT_HEAD + TEXT_TAIL:
        return text
    return f"{text[:TEXT_HEAD]} … {text[-TEXT_TAIL:]}"


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def record_docs(rec: dict) -> list[tuple[str, str | None, str]]:
    """(kind, tool name, text) for each searchable part of a transcript record."""
    rtype = rec.get("type")
    msg = rec.get("message") or {}
    content = msg.get("content")
    out: list[tuple[str, str | None, str]] = []
    if rtype == "user":
        kind = classify_user(rec)
        if kind == "tool_result":
            for b in content if isinstance(content, list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    out.append(("tool_result", None, tool_result_text(b.get("content"))))
        elif kind == "prompt":
            out.append(("prompt", None, prompt_text(content)))
        elif kind == "command":
            out.append(("prompt", None, command_text(content_text(content))))
        elif kind == "notification":
            out.append(("notification", None, content_text(content)))
    elif rtype == "assistant":
        if msg.get("model") == "<synthetic>" or rec.get("isApiErrorMessage"):
            out.append(("error", None, content_text(content)))
        else:
            for b in content if isinstance(content, list) else []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    out.append(("assistant", None, b.get("text") or ""))
                elif b.get("type") == "tool_use":
                    name = b.get("name") or "?"
                    out.append(("tool_use", name, "\n".join(_strings(b.get("input")))))
    elif rtype == "attachment":
        prompt = (rec.get("attachment") or {}).get("prompt")
        if isinstance(prompt, str) and "<task-notification>" in prompt:
            out.append(("notification", None, prompt))
    return [(k, n, t) for k, n, t in out if t.strip()]


def fts_query(query: str) -> str | None:
    """The query as one FTS5 phrase (a substring match), or None when it is too short."""
    q = normalize(query)
    if len(q) < MIN_QUERY:
        return None
    return '"' + q.replace('"', '""') + '"'


def snippet(text: str, query: str) -> dict:
    """{before, match, after} around the first occurrence of `query` in `text`."""
    q = normalize(query).lower()
    low = text.lower()
    i = low.find(q) if len(low) == len(text) else -1
    if i < 0:
        return {"before": "", "match": "", "after": text[: 2 * SNIPPET_CONTEXT]}
    start = max(0, i - SNIPPET_CONTEXT)
    end = min(len(text), i + len(q) + SNIPPET_CONTEXT)
    return {
        "before": ("…" if start > 0 else "") + text[start:i],
        "match": text[i : i + len(q)],
        "after": text[i + len(q) : end] + ("…" if end < len(text) else ""),
    }


@dataclass
class Hit:
    path: str
    session_id: str
    agent_id: str | None
    count: int
    ts: int | None
    kind: str
    name: str | None
    text: str


def read_records(path: Path, offset: int) -> tuple[list[dict], int]:
    """Complete records after `offset`, and the offset just past the last complete line."""
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read()
    end = data.rfind(b"\n")
    if end < 0:
        return [], offset
    out = []
    for line in data[: end + 1].splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out, offset + end + 1


class SearchIndex:
    """Indexes transcripts on a background thread, in the order they are queued.

    `path=None` keeps the index in memory (used by tests).
    """

    def __init__(self, path: Path | None):
        self.path = path
        self.lock = threading.Lock()  # guards the connection
        self.conn = self._open(path)
        # path -> (session id, agent id or None) of files with bytes not indexed yet.
        self.queue: dict[Path, tuple[str, str | None]] = {}
        self.busy = False  # a file taken off the queue is being indexed
        self.cond = threading.Condition()
        self.closed = False
        self.thread = threading.Thread(target=self._run, name="search-index", daemon=True)
        self.thread.start()

    # ------------------------------------------------------------------ schema

    def _open(self, path: Path | None) -> sqlite3.Connection:
        if path is None:
            return self._init(sqlite3.connect(":memory:", check_same_thread=False))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            return self._open_file(path)
        except sqlite3.DatabaseError as e:  # corrupt or not a database: start over
            log.warning("rebuilding the search index at %s: %s", path, e)
            for p in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
                p.unlink(missing_ok=True)
            return self._open_file(path)

    def _open_file(self, path: Path) -> sqlite3.Connection:
        conn = self._connect(path)
        try:
            return self._init(conn)
        except BaseException:
            # Close before the caller deletes the file: Windows cannot unlink an open file.
            conn.close()
            raise

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        # Autocommit mode: transactions are begun and ended explicitly.
        conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        try:
            conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        except BaseException:
            conn.close()
            raise
        return conn

    @staticmethod
    def _init(conn: sqlite3.Connection) -> sqlite3.Connection:
        conn.isolation_level = None
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            conn.execute("BEGIN IMMEDIATE")
            for table in ("docs", "parts", "files"):
                conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.execute(
                "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL,"
                " session_id TEXT NOT NULL, agent_id TEXT, inode INTEGER, offset INTEGER)"
            )
            # One row per message, tool call or output; `docs` indexes their text.
            conn.execute(
                "CREATE TABLE parts (id INTEGER PRIMARY KEY, file INTEGER NOT NULL,"
                " ts INTEGER, kind TEXT, name TEXT, text TEXT)"
            )
            conn.execute("CREATE INDEX parts_file ON parts (file)")
            conn.execute(
                "CREATE VIRTUAL TABLE docs USING fts5(text, content = 'parts',"
                " content_rowid = 'id', tokenize = 'trigram')"
            )
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.execute("COMMIT")
        return conn

    # ------------------------------------------------------------------ writing

    def enqueue(self, path: Path, session_id: str, agent_id: str | None) -> None:
        with self.cond:
            self.queue[path] = (session_id, agent_id)
            self.cond.notify_all()

    def pending(self) -> int:
        """Files waiting to be indexed, including the one being indexed."""
        with self.cond:
            return len(self.queue) + self.busy

    def wait_idle(self, timeout: float | None = None) -> bool:
        with self.cond:
            return self.cond.wait_for(lambda: not self.queue and not self.busy, timeout)

    def _run(self) -> None:
        while True:
            with self.cond:
                self.cond.wait_for(lambda: self.queue or self.closed)
                if self.closed:
                    return
                path = next(iter(self.queue))
                sid, agent = self.queue.pop(path)
                self.busy = True
            try:
                self.index_file(path, sid, agent)
            except Exception:
                log.exception("could not index %s", path)
            finally:
                with self.cond:
                    self.busy = False
                    self.cond.notify_all()

    def index_file(self, path: Path, session_id: str, agent_id: str | None) -> None:
        """Index what was written to `path` since the last time.

        One write transaction from reading the offset to saving the new one, so two
        cc-calendar processes sharing the index never add the same records twice.
        """
        try:
            st = path.stat()
        except OSError:
            return
        with self.lock:
            conn = self.conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT id, inode, offset FROM files WHERE path = ?", (str(path),)
                ).fetchone()
                if row is not None and (row[1] != st.st_ino or st.st_size < row[2]):
                    # Replaced or rewritten from scratch: index it again.
                    self._forget(row[0])
                    row = None
                if row is None:
                    cur = conn.execute(
                        "INSERT INTO files (path, session_id, agent_id, inode, offset)"
                        " VALUES (?, ?, ?, ?, 0)",
                        (str(path), session_id, agent_id, st.st_ino),
                    )
                    row = (cur.lastrowid, st.st_ino, 0)
                file_id, _, offset = row
                if st.st_size > offset:
                    records, end = read_records(path, offset)
                    rows = self._rows(file_id, records, None if agent_id else session_id)
                    if rows:
                        last = conn.execute("SELECT max(id) FROM parts").fetchone()[0] or 0
                        conn.executemany(
                            "INSERT INTO parts (file, ts, kind, name, text) VALUES (?, ?, ?, ?, ?)",
                            rows,
                        )
                        conn.execute(
                            "INSERT INTO docs (rowid, text) SELECT id, text FROM parts"
                            " WHERE id > ?",
                            (last,),
                        )
                    conn.execute("UPDATE files SET offset = ? WHERE id = ?", (end, file_id))
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    @staticmethod
    def _rows(file_id: int, records: list[dict], session_id: str | None) -> list[tuple]:
        """`session_id`: for a main transcript, skip records copied from a predecessor."""
        out = []
        seen: set[str] = set()
        for rec in records:
            if session_id and rec.get("sessionId") not in (None, session_id):
                continue
            uuid = rec.get("uuid")
            if uuid:
                if uuid in seen:
                    continue
                seen.add(uuid)
            ts = parse_ts(rec.get("timestamp"))
            for kind, name, text in record_docs(rec):
                out.append((file_id, ts, kind, name, normalize(clip(text))))
        return out

    def prune(self, roots: list[Path], keep: set[str]) -> int:
        """Forget files under `roots` that are not in `keep` (deleted transcripts)."""
        with self.lock:
            conn = self.conn
            gone = [
                (fid,)
                for fid, p in conn.execute("SELECT id, path FROM files")
                if p not in keep and any(Path(p).is_relative_to(r) for r in roots)
            ]
            if gone:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for (fid,) in gone:
                        self._forget(fid)
                    conn.execute("COMMIT")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
            return len(gone)

    def _forget(self, file_id: int) -> None:
        """Remove a file and its rows; within a transaction."""
        self.conn.execute(
            "INSERT INTO docs (docs, rowid, text) SELECT 'delete', id, text FROM parts"
            " WHERE file = ?",
            (file_id,),
        )
        self.conn.execute("DELETE FROM parts WHERE file = ?", (file_id,))
        self.conn.execute("DELETE FROM files WHERE id = ?", (file_id,))

    # ------------------------------------------------------------------ searching

    def search(self, query: str) -> list[Hit]:
        """Per file: the number of matching parts and the first one."""
        match = fts_query(query)
        if match is None:
            return []
        with self.lock:
            firsts = self.conn.execute(
                "SELECT count(*), min(p.id) FROM docs JOIN parts p ON p.id = docs.rowid"
                " WHERE docs MATCH ? GROUP BY p.file",
                (match,),
            ).fetchall()
            out = []
            for count, part_id in firsts:
                row = self.conn.execute(
                    "SELECT f.path, f.session_id, f.agent_id, p.ts, p.kind, p.name, p.text"
                    " FROM parts p JOIN files f ON f.id = p.file WHERE p.id = ?",
                    (part_id,),
                ).fetchone()
                if row is not None:
                    path, sid, agent, ts, kind, name, text = row
                    out.append(Hit(path, sid, agent, count, ts, kind, name, text))
            return out

    def close(self) -> None:
        with self.cond:
            self.closed = True
            self.cond.notify_all()
        self.thread.join()
        with self.lock:
            self.conn.close()
