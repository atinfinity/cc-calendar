# cc-calendar

[![PyPI](https://img.shields.io/pypi/v/cc-calendar?label=PyPI)](https://pypi.org/project/cc-calendar/)

A Google Calendar-style weekly view of your [Claude Code](https://claude.com/claude-code) sessions.

`cc-calendar` reads the transcripts Claude Code already writes to `~/.claude/projects/` and shows
when you worked, on what, what it cost, and what came out of it — commits, changed files and pull
requests — in a local web UI that updates live while sessions run.

**Project site:** <https://atinfinity.github.io/cc-calendar/>

![Week calendar colored by project](https://raw.githubusercontent.com/atinfinity/cc-calendar/main/docs/images/calendar.png)

## Install

With [uv](https://docs.astral.sh/uv/) (Python 3.12+ is fetched automatically):

```sh
uv tool install cc-calendar
cc-calendar
```

Or try it without installing: `uvx cc-calendar`. Update with `uv tool upgrade cc-calendar`.

With Python 3.12+ already installed, `pipx install cc-calendar` works too.

Installed v0.3.0 or earlier from GitHub? Switch to the PyPI package once with
`uv tool install --force cc-calendar`; `uv tool upgrade` works from then on.

To run it from a checkout:

```sh
uv run cc-calendar
```

The server binds to `127.0.0.1` on a free port and opens your browser.

| Option | Description |
| --- | --- |
| `--port N` | Listen on a specific port instead of a free one |
| `--no-browser` | Do not open a browser window |
| `--claude-dir [NAME=]PATH` | Read logs from another Claude Code config directory (default `~/.claude`). Repeat it to show several directories in one calendar |
| `--notes PATH` | File that keeps your session notes and tags (default: see [Notes and tags](https://atinfinity.github.io/cc-calendar/getting-started/#notes-and-tags)) |
| `--search-index PATH` | File that keeps the full-text search index (default: see [Full-text search](https://atinfinity.github.io/cc-calendar/features/#full-text-search)) |
| `--version` | Print the version and exit |

### Several config directories

Pass `--claude-dir` more than once to see sessions from several places together, such as
`~/.claude` directories synced from other machines or separate configs used with
`CLAUDE_CONFIG_DIR`. Only the directories you list are read, so include `~/.claude` to keep
your local sessions:

```sh
cc-calendar --claude-dir ~/.claude --claude-dir ~/sync/laptop/.claude --claude-dir work=~/.claude-work
```

Each directory gets a name: the one you give with `NAME=`, otherwise `local` for `~/.claude`, the
parent folder for a path ending in `.claude` (`laptop` above), or the folder itself. Sessions show
where they came from in the list (**Source** column and filter), the detail pane, the calendar
tooltip and the CSV/JSON export (`source`), and **Color by → Source** colors them by directory.
A session found in more than one directory is shown once, from the copy with the latest activity.

### Notes and tags

Notes and tags you add to sessions are saved in one JSON file, keyed by session ID:

| Platform | Default location |
| --- | --- |
| macOS | `~/Library/Application Support/cc-calendar/notes.json` |
| Linux | `$XDG_DATA_HOME/cc-calendar/notes.json` (`~/.local/share/…` when unset) |
| Windows | `%APPDATA%\cc-calendar\notes.json` |

Point `--notes` at another file to keep it somewhere else, such as a synced folder to share notes
between machines; changes made to the file elsewhere are picked up. One file serves every
`--claude-dir`. Notes stay in the file after Claude Code deletes a session's old log.

### Full-text search

Tick **Full text** next to the search box to also search what Claude wrote: assistant replies,
tool inputs (commands, file paths, edits), tool output, background task results and subagent
transcripts. Thinking is not searched. Queries need at least 3 characters, ignore case and line breaks, and work for Japanese
and other languages without spaces. Matching sessions show a snippet of the first hit in the list,
the calendar tooltip and the detail pane; **Open ↗** opens the transcript at that hit, and
**Matches** in the transcript steps through the others.

The text is kept in a SQLite index, built in the background on first start and updated as logs
grow, so later starts only read new lines. Until it is complete, the status in the search box
says so and results fill in as it goes. The index is a cache and safe to delete:

| Platform | Default location |
| --- | --- |
| macOS | `~/Library/Caches/cc-calendar/search.db` |
| Linux | `$XDG_CACHE_HOME/cc-calendar/search.db` (`~/.cache/…` when unset) |
| Windows | `%LOCALAPPDATA%\cc-calendar\search.db` |

Point `--search-index` at another file to keep it elsewhere. It takes a little under half the space of
the logs it covers.

## Features

- **Week and day calendar** — each session is drawn as bars covering its active periods; a session is
  split wherever it sat idle longer than the **Split after** threshold (15 minutes by default). Overlapping
  sessions sit side by side. Click a date in the week view to open that day on its own. Zoom with
  the − / + buttons or Ctrl/⌘ + mouse wheel.
- **Month and year views** — a month calendar and a GitHub-style yearly heatmap, one cell per day
  shaded by active time or cost (switch with "Shade by"). Month cells list the day's busiest
  projects; the year view adds per-month totals. Click a day to open it in the day view, or a
  month total to open that month.
- **Time and cost totals** — each date shows that day's active time and cost, and the Summary
  table breaks the displayed range down by project. Active time is the drawn bars; a session's cost
  is split across days by when its requests ran. Totals follow the current filters.
- **Markdown report** — "Copy report" copies the displayed day, week, month or year as Markdown:
  active time and cost per project, each session's title and tags (not notes) and the commits made in the range. Ready
  to paste into a standup note or a daily report; it follows the current filters. Issue and PR
  numbers such as `#12` become links to the repository's `origin` remote.
- **Tool usage** — the Tools pane aggregates tool calls in the displayed range: most used tools,
  error counts and rates (10% or more is highlighted), calls made inside subagents, MCP servers,
  and subagent runs by type with their tool calls, tokens and cost. It follows the current filters.
- **Cache efficiency** — each session shows its cache hit rate (cache reads as a share of input
  tokens) and roughly how much caching saved. Sort the list by Cache to find sessions with poor
  reuse; rates below 90% are highlighted (Claude Code usually reuses well over 90%).
- **Event marks** — marks on each bar show when prompts, commits, compactions and API errors
  happened, and the tooltip counts them for that block. Click a mark (or a request or commit time
  in the detail pane) to open the transcript at that point; the transcript has ‹ › buttons to step
  through each kind of event. Click the key next to the legend to hide the marks.
- **Activity density** — a heat strip behind each day shows prompts and responses per 10 minutes.
- **Colors** by project, status, model, effort (the level most requests ran at), source (with
  several config directories), tag (the first tag of each session) or cost
  (< $1 / $1–5 / $5–20 / $20–50 / ≥ $50).
- **Effort and compactions** — the detail pane and transcript stats show the share of requests
  per effort level, and each compaction shows its trigger and context size before → after
  (e.g. `auto · 168k → 32k tokens`) in the mark tooltip, the transcript and the detail pane.
- **Status** — Running and Waiting for live sessions, Done or Interrupted for finished ones, with
  the underlying checks (turn ended, no background work left, clean exit, working tree clean).
- **Notifications** — turn on "Notify" in the top bar to get a desktop notification when a live
  session goes from Running to Waiting for your input, or ends Interrupted, while the tab is in the
  background. Off by default; clicking the notification opens the session.
- **Detail pane** — tokens, cost, context usage, every request you made with the commits that
  followed it, files changed, pull requests, subagents and background tasks, and links between
  a session and the one it was continued in.
- **Resume** — "Copy resume command" in the detail pane copies
  `cd <project dir> && claude --resume <session id>`, so you can pick a session up again from a
  terminal.
- **Transcript viewer** — Markdown rendering, collapsible tool calls, optional thinking and
  metadata, drill-down into subagent transcripts, and a stats panel per transcript (active time,
  requests, tokens and cost by model, tool calls and errors by tool). The panel's active time counts
  gaps of up to 5 minutes, whatever the calendar's **Split after** setting.
- **Notes and tags** — add a note and tags to a session in the detail pane to find it again
  later. The note saves when you leave the box (or with ⌘/Ctrl+Enter); `Enter` or a comma adds a
  tag, with suggestions from tags already in use. Tags that differ only in case count as one.
  Tags show in the list (**Tags** column and filter) and the calendar tooltip, and a 📝 marks
  sessions with a note. See [where they are saved](https://atinfinity.github.io/cc-calendar/getting-started/#notes-and-tags).
- **List view** with search over titles, the start of each prompt, notes and tags (a match inside a prompt or note is shown under the title), optional
  [full-text search](https://atinfinity.github.io/cc-calendar/features/#full-text-search) over the whole transcripts, project and status filters, and sorting by
  any column (click a header; click again to reverse). List-only filters narrow it down further
  by model, git branch, source (with several config directories), tag, date range (sessions active on
  any day in the range) and cost range.
- **Project page** — click a project name (in the list, the Summary table, the detail pane or the
  project menu) to see the project over all time: total active time and cost, activity by month,
  every session, and its commit history with links to the repository.
- **Export** — download the sessions shown in the list view as CSV or JSON, in the current filter
  and sort order: start, end, active time, project, source directory, branch, status, prompts,
  tokens, cost, cache hit rate, model, effort, Claude Code version, commit count, tags and note. Times are
  ISO 8601 with your UTC offset. See the [export format](https://atinfinity.github.io/cc-calendar/export/).
- **Keyboard shortcuts** — `←` / `→` previous / next range, `t` today, `d` / `w` / `m` / `y` span,
  `c` / `l` calendar / list, `/` search, `j` / `k` next / previous session, `Enter` open its
  transcript, `Esc` close. In a transcript, `n` / `p` step through events, `]` / `[` through
  prompts, `s` / `e` toggle Stats / Expand tools, and `b` goes back to the parent session. Press `?` (or click **?** in the top bar)
  for the full list.
- **Views in the URL** — the address keeps the view, span, date, selected session and project
  page, so reloading keeps your place, Back and Forward step through range and view changes, and
  views can be bookmarked.
- **Live updates** — new log lines are picked up within a second.

| Session detail | Transcript with stats |
| --- | --- |
| ![Detail pane](https://raw.githubusercontent.com/atinfinity/cc-calendar/main/docs/images/detail.png) | ![Transcript viewer](https://raw.githubusercontent.com/atinfinity/cc-calendar/main/docs/images/transcript.png) |
| **List view** | **Month view** |
| ![List view](https://raw.githubusercontent.com/atinfinity/cc-calendar/main/docs/images/list.png) | ![Month view](https://raw.githubusercontent.com/atinfinity/cc-calendar/main/docs/images/month.png) |

Screenshots show fictional demo data.

Cost comes from Claude Code's own cost record when the session wrote one. Otherwise it is estimated
from token usage and a built-in price table, and shown with a `~` prefix.

Treat all costs as rough figures, not billing data. The price table in
`src/cc_calendar/pricing.py` uses Anthropic API list prices as of when it was last updated. It does
not know about subscription plans, discounts or price changes. Models missing from the table count
as $0, so it needs updating when new models ship.

## Privacy

Everything stays on your machine. The server listens only on localhost, reads your logs read-only,
and makes no network requests. It writes two files: the notes file
([Notes and tags](https://atinfinity.github.io/cc-calendar/getting-started/#notes-and-tags)), only when you add or change a note or tag, and the
[full-text search index](https://atinfinity.github.io/cc-calendar/features/#full-text-search), a cache built from your logs. Requests from other
websites cannot change either. Commit hashes that do not appear in the
logs are looked up with `git log` in the session's working directory.

## Development

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

The frontend is plain HTML, CSS and ES modules in `src/cc_calendar/static/` — no build step.
Tests use synthetic logs only; never commit real transcripts.

Releases are published to PyPI by pushing a version tag; see
[Releasing](https://atinfinity.github.io/cc-calendar/development/#releasing).

The README screenshots are rendered from fictional data generated by `scripts/demo_data.py`, using
your installed Google Chrome:

```sh
uv run --with playwright python scripts/screenshots.py
```

The project site is built with [Zensical](https://zensical.org/) from `docs/` and `zensical.toml`,
and deployed to GitHub Pages on every push to `main`. Preview it locally:

```sh
uv run --group docs zensical serve
```

## Acknowledgements

Inspired by the tool shown in [this post by @tokkyo](https://x.com/tokkyo/status/2106240136778575897).
This is an independent reimplementation and is not affiliated with the original.

## License

MIT. Bundles [marked](https://github.com/markedjs/marked) (MIT) and
[DOMPurify](https://github.com/cure53/DOMPurify) (Apache-2.0 / MPL-2.0).
