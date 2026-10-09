# Export format

The **Export** buttons in the list view download the sessions shown there as CSV or JSON. The file
contains the sessions that pass the current filters (search, projects, statuses, "With prompts
only", and the list filters for model, branch, source, rating, tag, output, dates and cost), in the current sort
order.

The file is named `cc-calendar-sessions-YYYY-MM-DD.csv` or `.json`, using the date of the export.

!!! warning "Exports contain your session data"

    Titles are taken from your prompts, paths come from your machine, and your notes are included.
    Treat exported files like the transcripts themselves.

## Fields

CSV and JSON carry the same fields, in this order.

| Field | Type | Description |
| --- | --- | --- |
| `id` | string | Claude Code session ID |
| `title` | string | Session title: Claude Code's generated title, else the first line of the first prompt |
| `project` | string | Project name as shown in the app |
| `project_path` | string | Working directory of the session |
| `source` | string | Name of the Claude config directory the session was read from, as in the Source column (`local` with the default `~/.claude`). See [Several config directories](getting-started.md#several-config-directories) |
| `branch` | string or null | Git branch recorded in the log |
| `status` | string | `running`, `waiting`, `done` or `interrupted` |
| `rating` | string or null | How you rated the session: `done`, `partial` or `failed`; `null` when not rated. See [Notes and tags](getting-started.md#notes-and-tags) |
| `start` | string | First activity, ISO 8601 with your UTC offset, e.g. `2026-09-29T20:15:00+09:00` |
| `end` | string | Last activity, same format |
| `active_minutes` | number | Active time: the length of the drawn bars, one decimal place |
| `span_minutes` | number or null | Minutes from `start` to `end`, idle time included, one decimal place |
| `prompts` | integer | Prompts you sent |
| `tokens` | integer | All tokens, subagents included: input, output, cache reads and cache writes |
| `cost_usd` | number | Cost in US dollars, four decimal places |
| `cost_estimated` | boolean | `true` when the cost is estimated from token usage (shown with `~` in the app) |
| `cache_hit_rate` | number or null | Cache reads as a share of all input-side tokens (input, cache writes and cache reads), from 0 to 1 |
| `idle_recache_usd` | number | Estimated cost of rewriting the prompt cache after idle gaps, four decimal places. See [Idle re-cache](features.md#time-cost-and-usage) |
| `model` | string or null | Model used for the most requests |
| `effort` | string or null | Effort level most requests ran at: `max`, `xhigh`, `high`, `medium` or `low` |
| `claude_code_version` | string or null | Claude Code version recorded in the log (the latest one if it changed) |
| `commits` | integer | Commits made in the session |
| `pull_requests` | integer | Pull requests the session opened or linked to |
| `files_changed` | integer | Files the session edited or wrote |
| `lines_added` | integer or null | Lines added, from Claude Code's cost record (a continued session's own share); `null` when the session wrote none or its share is unknown |
| `lines_removed` | integer or null | Lines removed, as for `lines_added` |
| `cost_per_commit` | number or null | `cost_usd` divided by `commits`, four decimal places; `null` without commits |
| `interrupts` | integer | Times you stopped Claude with Esc |
| `api_errors` | integer | API requests that failed (overloaded, rate limited, connection lost and the like) |
| `queued_prompts` | integer | Prompts you sent while Claude was still working, which it read before its turn ended |
| `tool_calls` | integer | Tool calls in the main session; subagents' calls are not counted |
| `tool_errors` | integer | Of `tool_calls`, those that returned an error, including commands that exited non-zero and tool uses you rejected |
| `friction` | integer | `interrupts` + `api_errors` + `queued_prompts` + `tool_errors`, as in the Friction column |
| `context_avg` | integer or null | Average context per main-thread request, in tokens: input, cache writes and cache reads. Subagents are not included. `null` without requests |
| `context_peak` | integer or null | Largest context of a single request, as for `context_avg` |
| `context_bloated` | boolean | `true` when at least 20 requests each resent more than 200k tokens. See [Context size](features.md#sessions-in-detail) |
| `tags` | array of strings | Tags you gave the session, in the order shown. In CSV, joined with `;` (tags cannot contain commas). Empty when there are none. See [Notes and tags](getting-started.md#notes-and-tags) |
| `note` | string | Your note on the session; empty when there is none. Line breaks are kept |

`active_minutes` depends on the **Split after … idle** setting. Idle gaps longer than that
setting are not counted.

Costs are rough figures, not billing data. See [About costs](features.md#time-cost-and-usage).

## CSV

- UTF-8 with a byte order mark, so Excel reads non-ASCII titles correctly. Lines end with CRLF.
- The first row is the header, with the field names above. There are no other metadata rows.
- Fields containing a comma, a double quote or a line break are quoted, with `"` doubled
  ([RFC 4180](https://www.rfc-editor.org/rfc/rfc4180)).
- Empty cells stand for `null`. Booleans are `true` / `false`.
- Some text values start with `=`, `+`, `-`, `@`, a tab or a carriage return. These are prefixed
  with `'`, so spreadsheets do not run them as formulas.

## JSON

JSON wraps the records in an object that identifies the format:

```json
{
  "format": "cc-calendar.sessions",
  "schema_version": 1,
  "generator": "cc-calendar 0.7.0",
  "exported_at": "2026-10-04T10:00:00+09:00",
  "sessions": [
    {
      "id": "0b6c1a52-…",
      "title": "Checkout page redesign",
      "project": "acme-web",
      "project_path": "/work/acme-web",
      "source": "local",
      "branch": "main",
      "status": "done",
      "rating": "partial",
      "start": "2026-09-29T20:15:00+09:00",
      "end": "2026-09-29T23:19:00+09:00",
      "active_minutes": 113,
      "span_minutes": 184,
      "prompts": 4,
      "tokens": 6035399,
      "cost_usd": 3.4354,
      "cost_estimated": true,
      "cache_hit_rate": 0.9712,
      "idle_recache_usd": 0.1825,
      "model": "claude-sonnet-5-5",
      "effort": "high",
      "claude_code_version": "2.1.0",
      "commits": 2,
      "pull_requests": 1,
      "files_changed": 6,
      "lines_added": 182,
      "lines_removed": 40,
      "cost_per_commit": 1.7177,
      "interrupts": 1,
      "api_errors": 0,
      "queued_prompts": 2,
      "tool_calls": 84,
      "tool_errors": 5,
      "friction": 8,
      "context_avg": 104512,
      "context_peak": 166830,
      "context_bloated": false,
      "tags": ["redesign", "PR review"],
      "note": "Waiting for design sign-off"
    }
  ]
}
```

| Key | Description |
| --- | --- |
| `format` | Always `cc-calendar.sessions` |
| `schema_version` | Version of the field definitions above |
| `generator` | cc-calendar version that wrote the file, for troubleshooting |
| `exported_at` | When the file was written |
| `sessions` | The records, in list order |

Numbers and booleans keep their JSON types. A missing value is `null`.

## Pull requests

The **Export** buttons of a [Pull requests](features.md#time-cost-and-usage) table (the pane and
the project page) download its rows as CSV or JSON, newest PR first. The file is named
`cc-calendar-pull-requests-YYYY-MM-DD.csv` or `.json`. CSV follows the rules above.

| Field | Type | Description |
| --- | --- | --- |
| `url` | string | Web URL of the pull request |
| `number` | integer or null | PR number |
| `repository` | string or null | `owner/name` |
| `title` | string or null | Title given to `gh pr create`; `null` when it was not recorded (for example when the PR was opened another way) |
| `head_branch` | string or null | Branch the PR was opened from |
| `created` | string | When the PR was opened, ISO 8601 with your UTC offset |
| `opened_in` | string | ID of the session that opened it |
| `sessions` | array | Sessions that worked on it, the opener first. In CSV, their IDs joined with `;`. In JSON, objects with `id` and `cost_usd` (that session's share) |
| `active_minutes` | number | Active time spent on it over all its sessions, one decimal place |
| `requests` | integer | API requests made for it, subagents included |
| `tokens` | integer | Tokens of those requests |
| `cost_usd` | number | Cost of those requests in US dollars, four decimal places |
| `cost_estimated` | boolean | `true` when any part of the cost is estimated from token usage |
| `commits` | integer | Commits made for it |

The totals cover every session that worked on the PR, also sessions outside the displayed range
or hidden by the filters. How work is attributed to a PR is described in
[Features](features.md#time-cost-and-usage); `active_minutes` depends on the **Split after … idle**
setting.

The JSON file has `"format": "cc-calendar.pull_requests"`, `schema_version`, `generator` and
`exported_at` as above, the records under `pull_requests`, and the work of the table's sessions
that went to no PR under `unattributed`:

```json
{
  "format": "cc-calendar.pull_requests",
  "schema_version": 1,
  "generator": "cc-calendar 0.7.0",
  "exported_at": "2026-10-04T10:00:00+09:00",
  "pull_requests": [
    {
      "url": "https://github.com/acme/acme-web/pull/42",
      "number": 42,
      "repository": "acme/acme-web",
      "title": "Redesign the checkout page",
      "head_branch": "checkout-redesign",
      "created": "2026-09-29T23:10:00+09:00",
      "opened_in": "0b6c1a52-…",
      "sessions": [
        { "id": "0b6c1a52-…", "cost_usd": 3.1021 },
        { "id": "5d0e77c4-…", "cost_usd": 0.8740 }
      ],
      "active_minutes": 131.5,
      "requests": 212,
      "tokens": 7120944,
      "cost_usd": 3.9761,
      "cost_estimated": true,
      "commits": 3
    }
  ],
  "unattributed": {
    "sessions": 1,
    "active_minutes": 12,
    "requests": 18,
    "tokens": 402311,
    "cost_usd": 0.3333,
    "cost_estimated": true,
    "commits": 0
  }
}
```

## Versioning

Each format (`cc-calendar.sessions`, `cc-calendar.pull_requests`) has its own `schema_version`. It
is bumped when a field is renamed or removed, or when its meaning or unit changes.
Adding a field does not bump it, so readers should ignore fields they do not know.

CSV has no version field. Read columns by their header names, not by position.

| Schema version | cc-calendar | Changes |
| --- | --- | --- |
| 1 | 0.3.0 | First version |
| 1 | 0.4.0 | Added `source`, `tags` and `note` |
| 1 | 0.6.0 | Added `pull_requests`, `files_changed`, `lines_added`, `lines_removed`, `cost_per_commit`, `rating`, `idle_recache_usd`, and `interrupts`, `api_errors`, `queued_prompts`, `tool_calls`, `tool_errors` and `friction`, and `context_avg`, `context_peak` and `context_bloated`. Added the pull request export (`cc-calendar.pull_requests`, schema version 1) |
