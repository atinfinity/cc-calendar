---
title: cc-calendar
description: A Google Calendar-style view of your Claude Code sessions.
---

# cc-calendar

A Google Calendar-style view of your [Claude Code](https://claude.com/claude-code) sessions.

`cc-calendar` reads the transcripts Claude Code already writes to `~/.claude/projects/`. It shows
when you worked, on what, what it cost and what came out of it: commits, changed files and pull
requests. It runs as a local web UI that updates live while sessions run.

[Get started](getting-started.md){ .md-button .md-button--primary }
[View on GitHub](https://github.com/atinfinity/cc-calendar){ .md-button }

![Week calendar colored by project](images/calendar.png)

## At a glance

<div class="grid cards" markdown>

-   **Calendar of your sessions**

    ---

    Each session is drawn over the periods it was active. Switch between day, week, month and
    year views.

    [:octicons-arrow-right-24: Calendar views](features.md#calendar-views)

-   **Time and cost**

    ---

    See active time and cost per day and per project, plus cache efficiency and tool usage.

    [:octicons-arrow-right-24: Time, cost and usage](features.md#time-cost-and-usage)

-   **From prompt to commit**

    ---

    Each request is listed with the commits that followed it, along with changed files, pull
    requests and subagents. Every session has a full transcript viewer.

    [:octicons-arrow-right-24: Sessions in detail](features.md#sessions-in-detail)

-   **Stays on your machine**

    ---

    The server listens only on localhost and reads your logs read-only. It makes no network
    requests.

    [:octicons-arrow-right-24: Privacy](privacy.md)

</div>

## Quick start

```sh
uv tool install git+https://github.com/atinfinity/cc-calendar@v0.2.0
cc-calendar
```

The server opens your browser on a free localhost port. See [Getting started](getting-started.md)
for options.

!!! note

    Screenshots on this site show fictional demo data.
