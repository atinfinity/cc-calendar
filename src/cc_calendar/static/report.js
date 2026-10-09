// Markdown report of the displayed range, for a standup note or a daily report.
import { activeMs, costPer, fmtDelta, hasOutput, previousRange, summarize, summarizePrevious } from "./summary.js";
import { RATINGS, addDays, fmtCost, fmtDuration, fmtPct } from "./util.js";

const RETRO_TOP = 5; // rows per list in the retrospective, so it stays short enough to paste

// `days` are the displayed dates; `label` is the range as shown in the toolbar. With `compareSpan`
// ("day", "week", ...) the totals line is followed by the change from the previous range.
export function buildReport(visible, days, label, compareSpan = null) {
  const from = days[0].getTime();
  const to = addDays(days[days.length - 1], 1).getTime();
  const sessions = visible
    .filter((s) => s.segments.some(([a, b]) => b >= from && a < to))
    .sort((a, b) => a.start - b.start);
  const { rows, total } = summarize(sessions, [[from, to]]);
  const lines = [`## Claude Code: ${label}`, ""];
  if (!rows.length) {
    lines.push("No activity.");
    return lines.join("\n") + "\n";
  }
  lines.push(`**${fmtDuration(total.ms)}** active · ${fmtCost(total.cost, total.estimated)} · ${sessions.length} session${sessions.length > 1 ? "s" : ""}`, "");
  if (compareSpan) {
    const prev = summarizePrevious(visible, compareSpan, days[0]);
    // Sessions overlapping the range, counted the same way as for the displayed one.
    const [pf, pt] = previousRange(compareSpan, days[0]).map((d) => d.getTime());
    const prevSessions = visible.filter((s) => s.segments.some(([a, b]) => b >= pf && a < pt)).length;
    lines.push(`vs. previous ${compareSpan}: ${[
      fmtDelta(total.ms - prev.total.ms, fmtDuration, 30_000),
      fmtDelta(total.cost - prev.total.cost, (c) => fmtCost(c), 0.005),
      `${fmtDelta(sessions.length - prevSessions)} sessions`,
      `${fmtDelta(total.commits - prev.total.commits)} commits`,
    ].join(" · ")}`, "");
  }
  for (const r of rows) {
    lines.push(`### ${r.name} (${fmtDuration(r.ms)} · ${fmtCost(r.cost, r.estimated)})`, "");
    for (const s of sessions.filter((x) => x.project === r.project)) {
      // Tags only: notes are often private, and the report is meant to be shared.
      const tags = (s.tags || []).map((t) => ` \`${t.replaceAll("`", "'")}\``).join("");
      lines.push(`- ${linkRefs(oneLine(s.title), s.repo_url)}${tags} (${fmtDuration(activeMs(s, from, to))})`);
      for (const c of (s.commit_list || []).filter((c) => c.ts == null || (c.ts >= from && c.ts < to))) {
        const sha = c.sha ? `\`${c.sha.slice(0, 7)}\` ` : "";
        lines.push(`  - ${sha}${linkRefs(oneLine(c.subject || "(no message)"), s.repo_url)}`);
      }
    }
    lines.push("");
  }
  return lines.join("\n");
}

// Markdown for drafting a retrospective with Claude: the range's totals and the change from the
// previous `span`, then the sessions worth discussing (most expensive, no output, most friction),
// followed by the request. Like the report, it follows the filters and leaves notes out.
export function buildRetrospective(visible, days, label, span) {
  const from = days[0].getTime();
  const to = addDays(days[days.length - 1], 1).getTime();
  const sessions = visible.filter((s) => s.segments.some(([a, b]) => b >= from && a < to));
  const { rows, total, ratings } = summarize(sessions, [[from, to]]);
  const lines = [`## Claude Code retrospective: ${label}`, ""];
  if (!rows.length) {
    lines.push("No activity.");
    return lines.join("\n") + "\n";
  }
  const prev = summarizePrevious(visible, span, days[0]);
  const prevRows = new Map(prev.rows.map((r) => [r.project, r]));
  const count = (summary) => summary.rows.reduce((n, r) => n + r.sessions, 0);
  const sessionCount = count({ rows });
  const perCommit = costPer(total.cost, total.commits);
  lines.push("### Totals", "",
    `- ${fmtDuration(total.ms)} active · ${fmtCost(total.cost, total.estimated)} · ${plural(sessionCount, "session")} · `
    + `${plural(total.commits, "commit")} · ${plural(total.prs, "PR")}`
    + (perCommit == null ? "" : ` · ${fmtCost(perCommit, total.estimated)} per commit`),
    `- vs. previous ${span}: ${changes(total, sessionCount, prev.total, count(prev))}`);
  if (ratings.size) {
    const rated = RATINGS.filter(([v]) => ratings.has(v)).map(([v, name]) => `${name} ${ratings.get(v).sessions}`);
    const unrated = sessionCount - [...ratings.values()].reduce((n, o) => n + o.sessions, 0);
    lines.push(`- Rated: ${rated.join(" · ")}${unrated ? ` · unrated ${unrated}` : ""}`);
  }
  lines.push("", "### By project", "");
  for (const r of rows.slice(0, RETRO_TOP)) {
    const p = prevRows.get(r.project);
    lines.push(`- ${r.name}: ${fmtDuration(r.ms)} · ${fmtCost(r.cost, r.estimated)} · ${plural(r.sessions, "session")} · `
      + `${plural(r.commits, "commit")} (${p ? changes(r, r.sessions, p, p.sessions) : `new this ${span}`})`);
  }
  more(lines, rows.length, "project");
  const absent = prev.rows.filter((r) => !rows.some((x) => x.project === r.project)).map((r) => r.name);
  if (absent.length) lines.push(`- Active in the previous ${span} only: ${absent.slice(0, RETRO_TOP).join(", ")}`);

  // Each session's own share of the range: time, cost and commits clipped to it.
  const inRange = sessions.map((s) => ({ s, ...summarize([s], [[from, to]]).total })).filter((x) => x.ms || x.cost);
  const byCost = inRange.filter((x) => x.cost >= 0.005).sort((a, b) => b.cost - a.cost);
  lines.push("", "### Most expensive sessions", "");
  for (const x of byCost.slice(0, RETRO_TOP)) lines.push(`- ${sessionLine(x)}`);
  if (!byCost.length) lines.push("- None with a cost.");
  const idle = byCost.filter((x) => !hasOutput(x.s));
  lines.push("", "### Sessions with no output", "");
  if (idle.length) {
    const cost = idle.reduce((n, x) => n + x.cost, 0);
    lines.push(`No commits, pull requests or edited files: ${plural(idle.length, "session")}, `
      + `${fmtCost(cost, idle.some((x) => x.s.cost_estimated))} in total.`, "");
    for (const x of idle.slice(0, RETRO_TOP)) lines.push(`- ${sessionLine(x)}`);
    more(lines, idle.length, "session");
  } else {
    lines.push("Every session with a cost left a commit, a pull request or an edited file.");
  }
  // Friction counts are per session, not clipped to the range.
  const f = { interrupts: 0, api_errors: 0, queued_prompts: 0, tool_calls: 0, tool_errors: 0 };
  for (const { s } of inRange) for (const k of Object.keys(f)) f[k] += s.friction?.[k] || 0;
  const rough = inRange.filter((x) => x.s.friction?.total).sort((a, b) => b.s.friction.total - a.s.friction.total);
  lines.push("", "### Friction", "", `- In total: ${frictionText(f)}`);
  for (const x of rough.slice(0, RETRO_TOP)) lines.push(`- ${sessionLine(x, false)}: ${frictionText(x.s.friction, true)}`);
  more(lines, rough.length, "session");
  lines.push("", "---", "",
    `Using the data above, draft a Keep / Problem / Try retrospective of my Claude Code use in ${label}:`,
    "- **Keep**: what worked and is worth continuing",
    "- **Problem**: what cost time or money without paying off, and where sessions struggled",
    `- **Try**: two or three concrete changes for the next ${span}`,
    "",
    "Refer to sessions by title and project. Friction counts cover whole sessions; a session's time, cost and commits "
    + "are its share of this range. Ask me when the data does not explain something instead of guessing.");
  return lines.join("\n") + "\n";
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// "+1h 5m · −$2.10 · +3 sessions · – commits" from two sets of totals.
function changes(c, cSessions, p, pSessions) {
  return [
    fmtDelta(c.ms - p.ms, fmtDuration, 30_000),
    fmtDelta(c.cost - p.cost, (v) => fmtCost(v), 0.005),
    `${fmtDelta(cSessions - pSessions)} sessions`,
    `${fmtDelta(c.commits - p.commits)} commits`,
  ].join(" · ");
}

function more(lines, n, word) {
  if (n > RETRO_TOP) lines.push(`- …and ${n - RETRO_TOP} more ${word}${n - RETRO_TOP === 1 ? "" : "s"}`);
}

// "Title (project) · $3.20 · 1h 5m · 2 commits · rated Failed"; `stats` false gives the title only.
function sessionLine({ s, ms, cost, commits }, stats = true) {
  const title = oneLine(s.title);
  const head = `${title.length > 80 ? title.slice(0, 79) + "…" : title} (${s.project_name})`;
  if (!stats) return head;
  const rating = RATINGS.find(([v]) => v === s.rating)?.[1];
  return [head, fmtCost(cost, s.cost_estimated), fmtDuration(ms), plural(commits, "commit"),
    ...(rating ? [`rated ${rating}`] : [])].join(" · ");
}

// Friction counts other than zero; `compact` leaves out the tool calls when none failed.
function frictionText(f, compact = false) {
  const rate = f.tool_calls ? ` (${fmtPct(f.tool_errors / f.tool_calls)})` : "";
  const parts = [
    [f.interrupts, plural(f.interrupts, "interrupt")],
    [f.api_errors, plural(f.api_errors, "API error")],
    [f.queued_prompts, `${plural(f.queued_prompts, "prompt")} sent while Claude was working`],
    [f.tool_errors || !compact, `${f.tool_errors} of ${plural(f.tool_calls, "tool call")} failed${rate}`],
  ];
  return parts.filter(([n]) => n).map(([, text]) => text).join(" · ") || "none";
}

// "#12" -> "[#12](https://github.com/o/r/issues/12)"; GitHub redirects to the PR when it is one.
function linkRefs(text, repo) {
  if (!repo) return text;
  return text.replace(/(^|[^\w&#/[])#(\d+)\b/g, (_, pre, n) => `${pre}[#${n}](${repo}/issues/${n})`);
}

function oneLine(text) {
  return String(text).replace(/\s+/g, " ").trim();
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Fallback for browsers that block the async clipboard API.
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.append(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}
