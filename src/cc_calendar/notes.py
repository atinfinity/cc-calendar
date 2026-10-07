"""Notes and tags the user attaches to sessions, kept in a JSON file of their own.

The logs stay read-only; besides the full-text search index (a cache), this file is the only
thing cc-calendar writes. It is keyed by session id, so one file serves every config directory,
and entries are kept after a session's log is gone (Claude Code deletes old logs on its own).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path

NOTE_LIMIT = 2000
TAG_LIMIT = 40
TAGS_PER_SESSION = 20
FILE_VERSION = 1


def default_path() -> Path:
    """notes.json in the platform's per-user data directory."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "cc-calendar" / "notes.json"


class NotesUnavailable(Exception):
    """The notes file could not be read, so it must not be overwritten."""


def clean_note(note: str) -> str:
    note = note.replace("\r\n", "\n").strip()
    if len(note) > NOTE_LIMIT:
        raise ValueError(f"a note can be at most {NOTE_LIMIT} characters")
    return note


def clean_tags(tags: list[str], known: dict[str, str]) -> list[str]:
    """Trim and check tags, drop repeats, and reuse the spelling of a tag that differs only in
    case (`known` maps lowercased tags to their spelling)."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags:
        tag = " ".join(raw.split())
        if not tag:
            continue
        if "," in tag:
            raise ValueError("tags cannot contain commas")
        if len(tag) > TAG_LIMIT:
            raise ValueError(f"a tag can be at most {TAG_LIMIT} characters")
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(known.get(key, tag))
    if len(out) > TAGS_PER_SESSION:
        raise ValueError(f"a session can have at most {TAGS_PER_SESSION} tags")
    return out


class Notes:
    """The notes file, reloaded when it changes on disk (e.g. synced from another machine).

    `path=None` keeps notes in memory only.
    """

    def __init__(self, path: Path | None):
        self.path = path
        self.entries: dict[str, dict] = {}
        self.error: str | None = None
        self.lock = threading.Lock()
        self._mtime: tuple[int, int, int] | None = None
        with self.lock:
            self._load()

    def _stat(self) -> tuple[int, int, int] | None:
        """What identifies a version of the file. The mtime alone is not enough: on Windows two
        writes in quick succession can get the same one. Each save renames a new file into
        place, so the inode changes even then."""
        try:
            st = self.path.stat() if self.path else None
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size, st.st_ino) if st else None

    def _load(self) -> None:
        mtime = self._stat()
        self._mtime = mtime
        self.entries, self.error = {}, None
        if mtime is None:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("sessions", {}), dict):
                raise ValueError("expected an object with a 'sessions' object")
        except (OSError, ValueError) as e:
            self.error = f"{self.path} could not be read: {e}"
            return
        for sid, entry in data.get("sessions", {}).items():
            if not isinstance(entry, dict):
                continue
            note = entry.get("note")
            tags = entry.get("tags")
            entry["note"] = note if isinstance(note, str) else ""
            tags = tags if isinstance(tags, list) else []
            entry["tags"] = [t for t in tags if isinstance(t, str)]
            self.entries[sid] = entry

    def refresh(self) -> None:
        """Reload if the file changed since it was last read or written."""
        with self.lock:
            if self._stat() != self._mtime:
                self._load()

    def get(self, sid: str) -> dict:
        entry = self.entries.get(sid) or {}
        return {"note": entry.get("note", ""), "tags": list(entry.get("tags", []))}

    def all_tags(self) -> list[dict]:
        """Every tag with the number of sessions that have it, most used first."""
        counts: dict[str, int] = {}
        for entry in self.entries.values():
            for tag in entry["tags"]:
                counts[tag] = counts.get(tag, 0) + 1
        return [
            {"tag": t, "count": n}
            for t, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].casefold()))
        ]

    def set(self, sid: str, note: str, tags: list[str]) -> dict:
        with self.lock:
            if self._stat() != self._mtime:
                self._load()
            if self.error:
                raise NotesUnavailable(self.error)
            # Spellings from other sessions only, so a tag used just here can be re-cased.
            known = {
                t.casefold(): t
                for other, entry in self.entries.items()
                if other != sid
                for t in entry["tags"]
            }
            note = clean_note(note)
            tags = clean_tags(tags, known)
            if note or tags:
                entry = self.entries.setdefault(sid, {})
                updated = datetime.now().astimezone().isoformat(timespec="seconds")
                entry.update(note=note, tags=tags, updated=updated)
            else:
                self.entries.pop(sid, None)
            self._save()
            return self.get(sid)

    def _save(self) -> None:
        if self.path is None:
            return
        data = {"version": FILE_VERSION, "sessions": self.entries}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write a temporary file next to it and rename, so a crash never leaves half a file.
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".notes-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
                f.write("\n")
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        self._mtime = self._stat()
