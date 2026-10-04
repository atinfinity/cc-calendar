# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through
[GitHub's private vulnerability reporting](https://github.com/atinfinity/cc-calendar/security/advisories/new),
not in a public issue.

Include the cc-calendar version (`cc-calendar --version`), your OS and browser, and steps to
reproduce. Do not attach real Claude Code transcripts; use a minimal, made-up log instead.

This is a personal project maintained on a best-effort basis. Fixes go into the latest release only.

## Scope

cc-calendar runs a local web server that reads your Claude Code logs. Issues of particular interest:

- Another website or local user reading data from the server (for example through DNS rebinding,
  CORS, or a non-loopback bind)
- Script injection through log content shown in the UI (titles, prompts, transcripts)
- Reading or writing files outside the Claude Code config directory, other than its own notes
  file and search index
- Any network request that sends log data off the machine
