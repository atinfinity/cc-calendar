# Getting started

## Install

The recommended way is [uv](https://docs.astral.sh/uv/), which fetches Python 3.12 or later
automatically if needed. pipx and pip work too.

=== "Install as a tool"

    ```sh
    uv tool install cc-calendar
    cc-calendar
    ```

    Update it later with `uv tool upgrade cc-calendar`.

    If you installed v0.3.0 or earlier from GitHub, switch to the PyPI package once with
    `uv tool install --force cc-calendar`. `uv tool upgrade` works from then on.

=== "Run without installing"

    ```sh
    uvx cc-calendar
    ```

=== "pipx or pip"

    These need Python 3.12 or later already installed.

    ```sh
    pipx install cc-calendar
    cc-calendar
    ```

    Update it later with `pipx upgrade cc-calendar`. Without pipx, install it into a virtual
    environment with pip:

    ```sh
    python3 -m venv .venv
    .venv/bin/pip install cc-calendar
    .venv/bin/cc-calendar
    ```

=== "Run from a checkout"

    ```sh
    git clone https://github.com/atinfinity/cc-calendar
    cd cc-calendar
    uv run cc-calendar
    ```

The server binds to `127.0.0.1` on a free port and opens your browser. It reads the logs under
`~/.claude/projects/`, so any session you have run with Claude Code shows up straight away.

Linux, macOS and Windows are supported. On Windows the logs are read from
`%USERPROFILE%\.claude\projects\`; one limitation: **Copy resume command** joins two commands
with `&&`, which cmd and PowerShell 7 accept but Windows PowerShell 5.1 does not — there,
replace the `&&` with `;`.

## Options

| Option | Description |
| --- | --- |
| `--port N` | Listen on a specific port instead of a free one |
| `--no-browser` | Do not open a browser window |
| `--claude-dir [NAME=]PATH` | Read logs from another Claude Code config directory (default `~/.claude`). Repeat it to show several directories in one calendar |
| `--notes PATH` | File that keeps your session notes and tags (default: see [Notes and tags](#notes-and-tags)) |
| `--search-index PATH` | File that keeps the full-text search index (default: see [Full-text search](features.md#full-text-search)) |
| `--version` | Print the version and exit |

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
- **Day / Week / Month / Year** picks the span. Use ◀ ▶ to move and **This week** (**Today**, **This month** or **This year**, following the
  span) to come back.
- Use the search box, the project filter and the status chips to narrow every view. **With
  prompts only** (on by default) hides sessions in which no prompt was sent. Totals and reports
  follow these filters. Tick **Full text** to search the whole transcripts, not just
  titles and prompts; see [Full-text search](features.md#full-text-search).
- Click a session to open its detail pane. From the detail pane, open the transcript.
- **Summary**, **Tools** and **Copy report** work on the displayed range.
- Press `?` for keyboard shortcuts: `←` `→` to move, `j` `k` to step through sessions, `Enter`
  to open the transcript, `Esc` to close. See [Keyboard shortcuts](features.md#keyboard-shortcuts).

## Notes and tags

Notes and tags you add to sessions are saved in one JSON file, keyed by session ID:

| Platform | Default location |
| --- | --- |
| macOS | `~/Library/Application Support/cc-calendar/notes.json` |
| Linux | `$XDG_DATA_HOME/cc-calendar/notes.json` (`~/.local/share/…` when unset) |
| Windows | `%APPDATA%\cc-calendar\notes.json` |

Point `--notes` at another file to keep it somewhere else, such as a synced folder to share notes
between machines; changes made to the file elsewhere are picked up. One file serves every
`--claude-dir`. Notes stay in the file after Claude Code deletes a session's old log.
