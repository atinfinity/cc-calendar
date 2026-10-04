# Features

## Calendar views

![Week calendar colored by project](images/calendar.png)

- **Week and day calendar**:
    - Each session is drawn as bars covering its active periods.
    - A session is split wherever it sat idle longer than the chosen threshold (15 minutes by
      default).
    - Overlapping sessions sit side by side.
    - Click a date in the week view to open that day on its own.
    - Zoom with the − / + buttons or ++ctrl++ + mouse wheel.
- **Month and year views**: a month calendar and a GitHub-style yearly heatmap, with one cell
  per day.
    - Cells are shaded by active time or cost; switch with "Shade by".
    - Month cells list the day's busiest projects.
    - The year view adds per-month totals.
    - Click a day to open it in the day view, or a month total to open that month.
- **Colors** by project, status, model, effort (the level most requests ran at), source (with
  several config directories) or cost
  (< \$1 / \$1–5 / \$5–20 / \$20–50 / ≥ \$50).
- **Event marks** on each bar show when prompts, commits, compactions and API errors happened.
    - The tooltip counts them for that block.
    - Click a mark to open the transcript at that point.
- **Activity density**: a heat strip behind each day shows prompts and responses per 10 minutes.
- **Live updates**: new log lines are picked up within a second.

![Month view](images/month.png)

## Time, cost and usage

- **Time and cost totals**:
    - Each date shows that day's active time and cost.
    - The Summary table breaks the displayed range down by project.
    - A session's cost is split across days by when its requests ran.
- **Markdown report**: "Copy report" copies the displayed range as Markdown. The report covers:
    - active time and cost per project
    - each session's title
    - the commits made in the range

    Issue and PR numbers such as `#12` become links to the repository's `origin` remote.
- **Tool usage**: the Tools pane aggregates tool calls in the displayed range:
    - most used tools, with error counts and rates
    - calls made inside subagents
    - MCP servers
    - subagent runs by type, with their tokens and cost
- **Cache efficiency**: each session shows its cache hit rate and roughly how much caching saved.
  Rates below 90% are highlighted.

!!! info "About costs"

    Cost comes from Claude Code's own cost record when the session wrote one. Otherwise it is
    estimated from token usage and a built-in price table, and shown with a `~` prefix.

    Treat all costs as rough figures, not billing data. The price table uses Anthropic API list
    prices as of when it was last updated. It does not know about subscription plans, discounts or
    price changes.

## Sessions in detail

![Detail pane](images/detail.png)

- **Status**:
    - Running and Waiting for live sessions; Done or Interrupted for finished ones.
    - The underlying checks are shown: turn ended, no background work left, clean exit and
      working tree clean.
- **Notifications**:
    - Turn on "Notify" in the top bar. The browser asks for permission the first time.
    - You get a desktop notification when a live session goes from Running to Waiting for your
      input, or ends Interrupted.
    - Notifications are sent only while the cc-calendar tab is in the background. Click one to
      open that session.
    - Off by default; the setting is remembered in this browser.
- **Detail pane** shows:
    - tokens, cost and context usage
    - every request you made, with the commits that followed it
    - files changed and pull requests
    - subagents and background tasks
    - links between a session and the one it was continued in
- **Resume**: "Copy resume command" copies
  `cd <project dir> && claude --resume <session id>`. Paste it into a terminal to pick the session
  up again. Claude Code looks sessions up by the directory they were started in, so the command
  changes to that directory first.
- **Effort and compactions**:
    - The share of requests at each effort level.
    - Each compaction's trigger and context size before → after, e.g.
      `auto · 168k → 32k tokens`.

![Transcript viewer with stats](images/transcript.png)

- **Transcript viewer**:
    - Markdown rendering and collapsible tool calls.
    - Optional thinking and metadata.
    - Drill-down into subagent transcripts.
    - A stats panel per transcript.
    - ‹ › buttons to step through prompts, commits, compactions and errors.
- **List view**:
    - Search over titles and prompts.
    - Filter by project and status.
    - Narrow the list further by model, git branch, source (with several config directories),
      date range and cost range. The date range keeps sessions that were active on any day in it.
      These filters apply to the list only; **Clear** resets them.
    - Sort by any column.
- **Project page**: click a project name to open it. Project names can be clicked in the list,
  the Summary table, the detail pane, and the project menu (**Page**). The page covers all time
  and ignores the filters. It shows:
    - total active time, cost, sessions, prompts, tokens and commits
    - active time, cost, sessions and commits per month
    - every session of the project; click one to open its details
    - the commit history, newest first, with links to the commits on GitHub or GitLab

    **← Back** or ++esc++ returns to the calendar or list.

![Project page](images/project.png)

- **Export**: download the sessions shown in the list view as CSV or JSON. The file follows
  the current filters and sort order. It covers:
    - start and end (ISO 8601 with your UTC offset) and active time
    - project, branch and status
    - prompts, tokens, cost and cache hit rate
    - model, effort, Claude Code version and number of commits

    See [Export format](export.md) for the fields and the JSON envelope.

![List view](images/list.png)
