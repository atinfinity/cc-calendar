# Getting started

## Install

cc-calendar requires [uv](https://docs.astral.sh/uv/). uv fetches Python 3.12 or later
automatically if needed.

=== "Install as a tool"

    ```sh
    uv tool install git+https://github.com/atinfinity/cc-calendar@v0.2.0
    cc-calendar
    ```

=== "Run from a checkout"

    ```sh
    git clone https://github.com/atinfinity/cc-calendar
    cd cc-calendar
    uv run cc-calendar
    ```

The server binds to `127.0.0.1` on a free port and opens your browser. It reads the logs under
`~/.claude/projects/`, so any session you have run with Claude Code shows up straight away.

## Options

| Option | Description |
| --- | --- |
| `--port N` | Listen on a specific port instead of a free one |
| `--no-browser` | Do not open a browser window |
| `--claude-dir PATH` | Read logs from another Claude Code config directory (default `~/.claude`) |

## Finding your way around

- **Calendar / List** at the top switches between the calendar and a sortable table of sessions.
- **Day / Week / Month / Year** picks the span. Use ◀ ▶ to move and **Today** to come back.
- Use the search box, the project filter and the status chips to narrow every view. Totals and
  reports follow these filters.
- Click a session to open its detail pane. From the detail pane, open the transcript.
- **Summary**, **Tools** and **Copy report** work on the displayed range.
