# cc-calendar

A Google Calendar-style weekly view of your [Claude Code](https://claude.com/claude-code) sessions.

`cc-calendar` reads the transcripts Claude Code already writes to `~/.claude/projects/` and shows
when you worked, on what, what it cost, and what came out of it — commits, changed files and pull
requests — in a local web UI that updates live while sessions run.

## Install

Requires [uv](https://docs.astral.sh/uv/) (Python 3.12+ is fetched automatically).

```sh
uv tool install git+https://github.com/atinfinity/cc-calendar
cc-calendar
```

Or run it from a checkout:

```sh
uv run cc-calendar
```

The server binds to `127.0.0.1` on a free port and opens your browser.

| Option | Description |
| --- | --- |
| `--port N` | Listen on a specific port instead of a free one |
| `--no-browser` | Do not open a browser window |
| `--claude-dir PATH` | Read logs from another Claude Code config directory (default `~/.claude`) |

## Features

- **Week and day calendar** — each session is drawn as bars covering its active periods; a session is
  split wherever it sat idle longer than the chosen threshold (15 minutes by default). Overlapping
  sessions sit side by side. Click a date in the week view to open that day on its own. Zoom with
  the − / + buttons or Ctrl + mouse wheel.
- **Activity density** — a heat strip behind each day shows prompts and responses per 10 minutes.
- **Colors** by project, status, model or cost (< $1 / $1–5 / $5–20 / $20–50 / ≥ $50).
- **Status** — Running and Waiting for live sessions, Done or Interrupted for finished ones, with
  the underlying checks (turn ended, no background work left, clean exit, working tree clean).
- **Detail pane** — tokens, cost, context usage, every request you made with the commits that
  followed it, files changed, pull requests, subagents and background tasks, and links between
  a session and the one it was continued in.
- **Transcript viewer** — Markdown rendering, collapsible tool calls, optional thinking and
  metadata, drill-down into subagent transcripts, and a stats panel per transcript (active time,
  requests, tokens and cost by model, tool calls and errors by tool).
- **List view** with search over titles and prompts, project and status filters, and sorting.
- **Live updates** — new log lines are picked up within a second.

Cost comes from Claude Code's own cost record when the session wrote one. Otherwise it is estimated
from token usage and a built-in price table, and shown with a `~` prefix.

## Privacy

Everything stays on your machine. The server listens only on localhost, reads your logs read-only,
keeps its index in memory, and makes no network requests. Commit hashes that do not appear in the
logs are looked up with `git log` in the session's working directory.

## Development

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

The frontend is plain HTML, CSS and ES modules in `src/cc_calendar/static/` — no build step.
Tests use synthetic logs only; never commit real transcripts.

## License

MIT. Bundles [marked](https://github.com/markedjs/marked) (MIT) and
[DOMPurify](https://github.com/cure53/DOMPurify) (Apache-2.0 / MPL-2.0).
