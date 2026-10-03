"""Command-line entry point."""

from __future__ import annotations

import argparse
import socket
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from . import __version__
from .server import create_app

HOST = "127.0.0.1"


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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="cc-calendar", description="Weekly calendar view of your Claude Code sessions."
    )
    parser.add_argument("--port", type=int, default=0, help="port to listen on (default: any free)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    parser.add_argument(
        "--claude-dir",
        type=Path,
        default=Path.home() / ".claude",
        help="Claude Code config directory (default: ~/.claude)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    port = args.port or free_port()
    url = f"http://{HOST}:{port}/"
    app = create_app(args.claude_dir.expanduser())
    print(f"cc-calendar {__version__}: reading {args.claude_dir} — serving {url}")
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url, port), daemon=True).start()
    uvicorn.run(app, host=HOST, port=port, log_level="warning")
