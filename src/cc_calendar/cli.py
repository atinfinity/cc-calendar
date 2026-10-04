"""Command-line entry point."""

from __future__ import annotations

import argparse
import re
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from . import __version__, notes, search
from .server import create_app
from .store import ClaudeDir

HOST = "127.0.0.1"
NAME_RE = re.compile(r"[\w.-]+")


def free_port() -> int:
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def open_when_ready(url: str, port: int, timeout: float = 60.0) -> None:
    """Open the browser once the server accepts connections (startup parses all logs first)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((HOST, port), timeout=0.5):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.2)


def claude_dirs(specs: list[str]) -> list[ClaudeDir]:
    """Parse `[NAME=]PATH` specs; skip missing or repeated directories with a warning."""
    home_claude = (Path.home() / ".claude").resolve()
    out: list[ClaudeDir] = []
    for spec in specs:
        name, sep, rest = spec.partition("=")
        if not (sep and NAME_RE.fullmatch(name)):
            name, rest = "", spec
        path = Path(rest).expanduser().resolve()
        if not path.is_dir():
            print(f"cc-calendar: warning: skipping {rest}: not a directory", file=sys.stderr)
            continue
        if any(d.path == path for d in out):
            print(f"cc-calendar: warning: skipping {rest}: given twice", file=sys.stderr)
            continue
        if not name:
            if path == home_claude:
                name = "local"
            elif path.name == ".claude":
                name = path.parent.name or "claude"
            else:
                name = path.name or "claude"
        taken = {d.name for d in out}
        unique, n = name, 2
        while unique in taken:
            unique, n = f"{name}-{n}", n + 1
        out.append(ClaudeDir(unique, path))
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="cc-calendar", description="Weekly calendar view of your Claude Code sessions."
    )
    parser.add_argument("--port", type=int, default=0, help="port to listen on (default: any free)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    parser.add_argument(
        "--claude-dir",
        action="append",
        metavar="[NAME=]PATH",
        help="Claude Code config directory to read; repeat to show several together "
        "(default: ~/.claude)",
    )
    parser.add_argument(
        "--notes",
        metavar="PATH",
        type=Path,
        help=f"file that keeps your session notes and tags (default: {notes.default_path()})",
    )
    parser.add_argument(
        "--search-index",
        metavar="PATH",
        type=Path,
        help="file that caches the full-text search index "
        f"(default: {search.default_path()}; safe to delete)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    port = args.port or free_port()
    url = f"http://{HOST}:{port}/"
    dirs = claude_dirs(args.claude_dir or [str(Path.home() / ".claude")])
    notes_path = (args.notes or notes.default_path()).expanduser()
    index_path = (args.search_index or search.default_path()).expanduser()
    app = create_app(dirs, notes_path=notes_path, index_path=index_path)
    reading = ", ".join(f"{d.name} ({d.path})" for d in dirs) or "nothing"
    print(f"cc-calendar {__version__}: reading {reading} — serving {url}")
    if error := app.state.notes.error:
        print(f"cc-calendar: warning: notes cannot be saved: {error}", file=sys.stderr)
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url, port), daemon=True).start()
    uvicorn.run(app, host=HOST, port=port, log_level="warning")
