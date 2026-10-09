# Features

## Calendar views

![Week calendar colored by project](images/calendar.png)

- **Week and day calendar**:
    - Each session is drawn as bars covering its active periods.
    - A session is split wherever it sat idle longer than the **Split after** threshold (15
      minutes by default).
    - Overlapping sessions sit side by side.
    - Click a date in the week view to open that day on its own.
    - Zoom with the − / + buttons or ++ctrl++ / ++cmd++ + mouse wheel; **Reset** goes back to the
      default.
- **Month and year views**: a month calendar and a GitHub-style yearly heatmap, with one cell
  per day.
    - Cells are shaded by active time, cost or commits; switch with "Shade by".
    - Month cells list the day's busiest projects.
    - The year view adds per-month totals.
    - Click a day to open it in the day view, or a month total to open that month.
- **Colors** by project, status, model, effort (the level most requests ran at), source (with
  several config directories), tag or cost
  (< \$1 / \$1–5 / \$5–20 / \$20–50 / ≥ \$50).
    - **Tag** colors a session by its first tag, so put the main one first. Sessions without tags
      are gray. The button shows once any session has a tag.
- **Event marks** on each bar show when prompts, commits, compactions and API errors happened.
    - The tooltip counts them for that block.
    - Click a mark to open the transcript at that point.
    - Click the marks key at the right of the legend to hide or show them.
- **Activity density**: a heat strip behind each day shows prompts and responses per 10 minutes.
- **Live updates**: new log lines are picked up within a second.
- **Views in the URL**: the address keeps the calendar or list view, the span, the date, the
  selected session and the open project page.
    - Reloading the page keeps your place, and you can bookmark a view.
    - The browser's Back and Forward buttons step through range, span and view changes and the
      project page. Selecting a session does not add a step.
    - A bookmark shows the same view on any day. A session or project the logs no longer have is
      left out.

![Month view](images/month.png)

## Time, cost and usage

- **Time and cost totals**:
    - Each date shows that day's active time and cost.
    - The Summary table breaks the displayed range down by project.
    - A session's cost is split across days by when its requests ran.
- **Markdown report**: "Copy report" copies the displayed range as Markdown. The report covers:
    - active time and cost per project
    - each session's title and tags (notes are left out)
    - the commits made in the range

    Issue and PR numbers such as `#12` become links to the repository's `origin` remote.
- **Tool usage**: the Tools pane aggregates tool calls in the displayed range:
    - most used tools, with error counts and rates
    - calls made inside subagents
    - MCP servers
    - subagent runs by type, with their tokens and cost
- **Hours of the week**: the Hours pane is a weekday × hour-of-day heatmap of the displayed
  range, to show when you work with Claude Code.
    - Cells are shaded by active time, cost or commits, with the same "Shade by" control as the
      month and year views.
    - Hover a cell for its totals; each row ends with that weekday's total.
    - Hours are in the browser's time zone, and weeks start on Monday like the week view.
    - It follows the current filters.
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
- **Notes and tags**: the **Notes** card in the detail pane keeps a note and tags for the
  session. Click **+ Add note or tags** to start.
    - The note is plain text, up to 2,000 characters. It saves when you leave the box, with
      ++cmd+enter++ / ++ctrl+enter++, or with ++esc++.
    - Type a tag and press ++enter++ or a comma to add it; tags already in use are suggested.
      Click ✕ on a tag to remove it.
    - Tags that differ only in case count as one, written the way they were first used.
    - The list view has a **Tags** column and a **Tag** filter, including "(untagged)". A 📝
      next to a title marks a note; hover it to read the start.
    - The calendar tooltip shows the tags, and the search box matches notes and tags.
    - They are saved in a file of their own; see
      [Notes and tags](getting-started.md#notes-and-tags) for where.
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
    - Markdown rendering and collapsible tool calls. Images linked in a transcript show as links and
      are not loaded (see [Privacy](privacy.md)).
    - Optional thinking and metadata.
    - Drill-down into subagent transcripts.
    - A stats panel per transcript, with tokens and cost by model and calls and errors by tool.
      Its active time counts gaps of up to 5 minutes, whatever the calendar's **Split after**
      setting.
    - ‹ › buttons to step through prompts, commits, compactions and errors, and through
      search matches when opened from a full-text hit.
- **List view**:
    - Search over titles, the start of each prompt, notes and tags, or the whole transcripts with
      [full-text search](#full-text-search).
    - Filter by project and status; each status chip shows its count. **With prompts only** (on
      by default) hides sessions in which no prompt was sent. These filters apply to every view.
    - Narrow the list further by model, git branch, source (with several config directories),
      tag, date range and cost range. The date range keeps sessions that were active on any day in it.
      These filters apply to the list only; the **Clear N filters** button resets them.
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
    - project, source config directory, branch and status
    - prompts, tokens, cost and cache hit rate
    - model, effort, Claude Code version and number of commits
    - tags and note

    See [Export format](export.md) for the fields and the JSON envelope.

![List view](images/list.png)

## Full-text search

The search box matches titles, the start of each prompt, notes and tags. Tick **Full text** next
to it to also search the transcripts themselves:

![Full-text search in the list view](images/search.png)

- What is searched: prompts and slash commands, assistant replies, tool inputs (commands, file
  paths, edits), tool output, errors, background task results, and subagent transcripts.
  Thinking is not searched.
- Queries need at least 3 characters. Case and line breaks are ignored, and words in Japanese
  and other languages without spaces match too.
- A matching session shows a snippet of its first hit, with where it was (e.g. "Tool output"),
  when, and how many matches the session has, including how many are in subagent transcripts
  (e.g. "11 matches (2 in subagents)"). The snippet appears in the list, the calendar tooltip
  and the detail pane.
- **Open ↗** opens the transcript at the hit. **Matches** in the transcript steps through every
  match in it.
- The toggle is remembered. The other filters still apply, and the status at the right of the
  search box counts hits over all sessions.

The text is kept in a SQLite index on disk. It is built in the background the first time, which
takes a while for large logs; until it is done the status says "indexing" and results fill in as
it goes. After that it is updated as logs grow, and a restart reads only new lines. The index is a
cache and safe to delete; it is rebuilt on the next start.

| Platform | Default location |
| --- | --- |
| macOS | `~/Library/Caches/cc-calendar/search.db` |
| Linux | `$XDG_CACHE_HOME/cc-calendar/search.db` (`~/.cache/…` when unset) |
| Windows | `%LOCALAPPDATA%\cc-calendar\search.db` |

`--search-index PATH` puts it elsewhere. It takes a little under half the space of the logs it
covers. If the file cannot be written, the index is kept in memory and rebuilt on each start; if
your Python's SQLite lacks FTS5 with the trigram tokenizer (SQLite 3.34 or later), the status reads "Full text unavailable" and the
rest of the search still works.

## Keyboard shortcuts

Press ++"?"++ or click **?** in the top bar for this list. Button tooltips show their key too.

| Keys | Action |
| --- | --- |
| ++arrow-left++ / ++arrow-right++ | Previous / next day, week, month or year (calendar view) |
| ++t++ | Back to today, this week, month or year (calendar view) |
| ++d++ / ++w++ / ++m++ / ++y++ | Day / week / month / year span, switching to the calendar view |
| ++c++ / ++l++ | Calendar / list view |
| ++slash++ | Focus the search box |
| ++j++ / ++k++ | Next / previous session: by start time in the day and week views, in row order in the list |
| ++enter++ / ++o++ | Open the selected session's transcript |
| ++esc++ | Close the topmost thing: shortcut list, transcript, project menu, search box, detail pane, project page |

Keys typed in a form field go to the field, and only ++esc++ works there. Leaving the search
box with ++esc++ keeps its text.

While a transcript is open, these keys work instead:

| Keys | Action |
| --- | --- |
| ++n++ / ++p++ | Next / previous event: prompt, commit, compaction or API error |
| ++bracket-right++ / ++bracket-left++ | Next / previous prompt |
| ++s++ | Show or hide Stats |
| ++e++ | Expand or collapse tool calls |
| ++b++ | Back to the parent session from a subagent's transcript |
| ++arrow-up++ / ++arrow-down++, ++page-up++ / ++page-down++, ++space++ | Scroll |
| ++esc++ | Close the transcript |

++"?"++ shows both lists here too.
