// Project page: everything about one project over all time, ignoring the filters.
import { select, state } from "./app.js";
import { activeMs, costPer, summarize } from "./summary.js";
import {
  STATUS_LABELS, fmtAgo, fmtCost, fmtDateTime, fmtDuration, fmtTokens, h, statusColor,
} from "./util.js";

// Calendar months from the first session to the last, newest first, as [start, end) ms.
function monthBounds(sessions) {
  const first = new Date(Math.min(...sessions.map((s) => s.start)));
  const last = new Date(Math.max(...sessions.map((s) => s.end)));
  const out = [];
  for (let d = new Date(first.getFullYear(), first.getMonth(), 1); d <= last; d = new Date(d.getFullYear(), d.getMonth() + 1, 1)) {
    out.push([d.getTime(), new Date(d.getFullYear(), d.getMonth() + 1, 1).getTime()]);
  }
  return out.reverse();
}

// Commits of all sessions, newest first. A continued session repeats its predecessor's records,
// so the same commit can appear in two sessions; keep the first.
export function projectCommits(sessions) {
  const seen = new Set();
  const out = [];
  for (const s of [...sessions].sort((a, b) => a.start - b.start)) {
    for (const c of s.commit_list || []) {
      const key = c.sha || `${c.subject}|${c.ts}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ ...c, session: s });
    }
  }
  return out.sort((a, b) => (b.ts ?? 0) - (a.ts ?? 0));
}

function sessionLink(s) {
  return h("a", { href: "#", title: "Show this session", onclick: (e) => { e.preventDefault(); select(s.id); } }, s.title);
}

function commitSha(c, repo) {
  if (!c.sha) return h("span", { class: "sha muted" }, "–");
  const tag = h("span", { class: "sha", title: c.sha }, c.sha.slice(0, 7));
  return repo && /^[0-9a-f]{7,40}$/.test(c.sha)
    ? h("a", { href: `${repo}/commit/${c.sha}`, target: "_blank", rel: "noopener" }, tag)
    : tag;
}

export function renderProject(container, project, { onBack }) {
  const sessions = state.sessions.filter((s) => s.project === project && s.start != null);
  const back = h("button", { onclick: onBack }, "← Back");
  if (!sessions.length) {
    container.replaceChildren(h("div", { class: "toolbar" }, back), h("div", { class: "empty" }, "No sessions in this project."));
    return;
  }
  const latest = sessions.reduce((a, b) => (b.end > a.end ? b : a));
  const repo = sessions.find((s) => s.repo_url)?.repo_url;
  const months = monthBounds(sessions);
  const byMonth = summarize(sessions, months);
  const total = byMonth.total;
  const commits = projectCommits(sessions);
  const commitsIn = ([from, to]) => commits.filter((c) => c.ts != null && c.ts >= from && c.ts < to).length;
  const prs = new Set(sessions.flatMap((s) => (s.pr_list || []).map((pr) => pr.url)));
  // Only sessions that wrote Claude Code's cost record know their line counts.
  const counted = sessions.filter((s) => s.lines_added != null);
  const lines = counted.reduce((n, s) => n + s.lines_added + (s.lines_removed || 0), 0);
  const lineCost = counted.reduce((n, s) => n + (s.cost || 0), 0);
  const branches = new Set(sessions.map((s) => s.branch).filter(Boolean));
  const maxMs = Math.max(...byMonth.days.map((d) => d.ms), 1);
  const stat = (text, title) => h("span", { class: "stat", title }, text);

  const head = h("div", { class: "toolbar" },
    back,
    h("span", { class: "dot", style: { background: state.projectColors.get(project) } }),
    h("strong", { class: "project-name" }, latest.project_name),
    h("span", { class: "muted" }, project),
    repo ? h("a", { href: repo, target: "_blank", rel: "noopener" }, "Repository ↗") : null,
    h("div", { class: "spacer" }),
    h("span", { class: "muted" }, "All time, ignoring the filters"));

  const stats = h("div", { class: "stats" },
    stat(`${fmtDuration(total.ms)} active`, "The drawn bars of all sessions (split after the idle threshold)"),
    stat(fmtCost(total.cost, total.estimated)),
    stat(`${sessions.length} sessions`),
    stat(`${sessions.reduce((n, s) => n + s.prompt_count, 0)} prompts`),
    stat(`${fmtTokens(sessions.reduce((n, s) => n + s.tokens, 0))} tok`),
    stat(`${commits.length} commits`),
    stat(`${prs.size} PR${prs.size === 1 ? "" : "s"}`),
    commits.length ? stat(`${fmtCost(costPer(total.cost, commits.length), total.estimated)}/commit`) : null,
    lines ? stat(`${fmtCost(costPer(lineCost, lines), counted.some((s) => s.cost_estimated))}/line`,
      `${lines} lines added or removed in ${counted.length} of ${sessions.length} sessions; only sessions with Claude Code's cost record count`) : null,
    branches.size ? stat(`${branches.size} branch${branches.size > 1 ? "es" : ""}`, [...branches].join("\n")) : null,
    stat(`First ${fmtDateTime(Math.min(...sessions.map((s) => s.start)))}`),
    stat(`Last activity ${fmtAgo(latest.end)}`, fmtDateTime(latest.end)));

  const monthTable = h("table", {},
    h("thead", {}, h("tr", {},
      h("th", {}, "Month"), h("th", {}, ""), h("th", { class: "num" }, "Active time"),
      h("th", { class: "num" }, "Cost"), h("th", { class: "num" }, "Sessions"), h("th", { class: "num" }, "Commits"))),
    h("tbody", {}, months.map((m, i) => {
      const d = byMonth.days[i];
      return h("tr", {},
        h("td", {}, new Date(m[0]).toLocaleDateString([], { year: "numeric", month: "short" })),
        h("td", { class: "bar-cell" }, d.ms ? h("div", { class: "hbar", style: { width: `${(100 * d.ms) / maxMs}%` } }) : null),
        h("td", { class: "num" }, d.ms ? fmtDuration(d.ms) : "–"),
        h("td", { class: "num" }, d.cost ? fmtCost(d.cost, d.estimated) : "–"),
        h("td", { class: "num" }, d.sessions || "–"),
        h("td", { class: "num" }, commitsIn(m) || "–"));
    })));

  const rows = [...sessions].sort((a, b) => b.start - a.start);
  const sessionTable = h("table", {},
    h("thead", {}, h("tr", {},
      h("th", {}, ""), h("th", {}, "Title"), h("th", {}, "Branch"), h("th", { class: "num" }, "Started"),
      h("th", { class: "num" }, "Active"), h("th", { class: "num" }, "Cost"), h("th", { class: "num" }, "Commits"))),
    h("tbody", {}, rows.map((s) => h("tr", {
      "data-sid": s.id,
      class: s.id === state.selectedId ? "selected" : "",
      onclick: () => select(s.id),
    },
      h("td", {}, h("span", { class: "dot", title: STATUS_LABELS[s.status], style: { background: statusColor(s.status) } })),
      h("td", { class: "title-cell" }, s.title),
      h("td", {}, s.branch || ""),
      h("td", { class: "num" }, fmtDateTime(s.start)),
      h("td", { class: "num" }, fmtDuration(activeMs(s, -Infinity, Infinity))),
      h("td", { class: "num" }, fmtCost(s.cost, s.cost_estimated)),
      h("td", { class: "num" }, (s.commit_list || []).length || "")))));

  const commitList = commits.length
    ? h("table", {}, h("tbody", {}, commits.map((c) => h("tr", {},
      h("td", { class: "num" }, c.ts != null ? fmtDateTime(c.ts) : ""),
      h("td", {}, commitSha(c, repo)),
      h("td", { class: "title-cell" }, c.subject || "(no message)"),
      h("td", { class: "muted" }, sessionLink(c.session))))))
    : h("div", { class: "muted" }, "No commits detected.");

  const section = (title, body) => h("section", { class: "card" }, h("h3", {}, title), h("div", { class: "card-body" }, body));
  container.replaceChildren(head, h("div", { class: "project-body" },
    stats,
    section("Activity by month", monthTable),
    section(`Sessions (${sessions.length})`, sessionTable),
    section(`Commits (${commits.length})`, commitList)));
}
