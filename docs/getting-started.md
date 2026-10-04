# Getting started

## Install

cc-calendar requires [uv](https://docs.astral.sh/uv/). uv fetches Python 3.12 or later
automatically if needed.

=== "Install as a tool"

    ```sh
    uv tool install git+https://github.com/atinfinity/cc-calendar@v0.3.0
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
| `--claude-dir [NAME=]PATH` | Read logs from another Claude Code config directory (default `~/.claude`). Repeat it to show several directories in one calendar |

## Several config directories

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

## Finding your way around

- **Calendar / List** at the top switches between the calendar and a sortable table of sessions.
- **Day / Week / Month / Year** picks the span. Use ◀ ▶ to move and **Today** to come back.
- Use the search box, the project filter and the status chips to narrow every view. Totals and
  reports follow these filters.
- Click a session to open its detail pane. From the detail pane, open the transcript.
- **Summary**, **Tools** and **Copy report** work on the displayed range.
- Press `?` for keyboard shortcuts: `←` `→` to move, `j` `k` to step through sessions, `Enter`
  to open the transcript, `Esc` to close. See [Keyboard shortcuts](features.md#keyboard-shortcuts).
