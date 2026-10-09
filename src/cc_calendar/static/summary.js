// Active time and cost per day and per project for the displayed range.
import { projectLink, state } from "./app.js";
import { fmtCost, fmtDuration, h } from "./util.js";

const BUCKET_MS = 600_000;

// Active time: the drawn segments clipped to [from, to), so it follows the "Split after" setting.
export function activeMs(s, from, to) {
  let ms = 0;
  for (const [a, b] of s.segments) ms += Math.max(0, Math.min(b, to) - Math.max(a, from));
  return ms;
}

// Cost: the session's cost split by when its API requests happened.
function costIn(s, from, to) {
  if (!s.cost) return 0;
  let total = 0;
  let inside = 0;
  for (const [bucket, c] of Object.entries(s.cost_density || {})) {
    const t = Number(bucket) * BUCKET_MS;
    total += c;
    if (t >= from && t < to) inside += c;
  }
  if (total > 0) return (s.cost * inside) / total;
  // No priced requests (e.g. unknown model): fall back to the share of active time.
  const all = activeMs(s, -Infinity, Infinity);
  return all > 0 ? (s.cost * activeMs(s, from, to)) / all : 0;
}

// True when the session left anything behind: a commit, a pull request or an edited file.
export function hasOutput(s) {
  return Boolean((s.commit_list || []).length || (s.pr_list || []).length || s.files_changed);
}

// Cost per unit of output, or null when there is none to divide by.
export function costPer(cost, count) {
  return count ? cost / count : null;
}

// Commits made in [from, to); undated commits count while the session was active in the range.
// A continued session repeats its predecessor's records, so `seen` keys drop the copies.
function addCommits(s, from, to, seen) {
  for (const c of s.commit_list || []) {
    if (c.ts != null ? c.ts < from || c.ts >= to : !activeMs(s, from, to)) continue;
    seen.add(c.sha || `${c.subject}|${c.ts}`);
  }
}

// Totals per day and per project. `bounds` holds each day's [start, end) in ms.
export function summarize(sessions, bounds) {
  const days = bounds.map(() => ({ ms: 0, cost: 0, estimated: false, sessions: 0 }));
  const projects = new Map();
  for (const s of sessions) {
    let row = projects.get(s.project);
    if (!row) {
      row = {
        project: s.project, name: s.project_name, days: bounds.map(() => 0), ms: 0, cost: 0, estimated: false, sessions: 0,
        commitKeys: new Set(), prUrls: new Set(),
      };
      projects.set(s.project, row);
    }
    let touched = false;
    bounds.forEach(([from, to], i) => {
      const ms = activeMs(s, from, to);
      const cost = costIn(s, from, to);
      if (!ms && !cost) return;
      touched = true;
      days[i].ms += ms;
      days[i].cost += cost;
      days[i].estimated ||= s.cost_estimated;
      days[i].sessions++;
      row.days[i] += ms;
      row.ms += ms;
      row.cost += cost;
      row.estimated ||= s.cost_estimated;
      addCommits(s, from, to, row.commitKeys);
    });
    if (!touched) continue;
    row.sessions++;
    // Pull requests carry no time, so they count in every range the session was active in.
    for (const pr of s.pr_list || []) row.prUrls.add(pr.url);
  }
  const rows = [...projects.values()].filter((r) => r.sessions).sort((a, b) => b.ms - a.ms || b.cost - a.cost);
  for (const r of rows) {
    r.commits = r.commitKeys.size;
    r.prs = r.prUrls.size;
  }
  const total = {
    ms: days.reduce((n, d) => n + d.ms, 0),
    cost: days.reduce((n, d) => n + d.cost, 0),
    estimated: days.some((d) => d.estimated),
    commits: rows.reduce((n, r) => n + r.commits, 0),
    prs: rows.reduce((n, r) => n + r.prs, 0),
  };
  return { days, rows, total };
}

export function dayTotalLabel(d) {
  return d.ms || d.cost ? `${fmtDuration(d.ms)} · ${fmtCost(d.cost, d.estimated)}` : "";
}

export function renderSummary(container, summary, dayLabels) {
  const { days, rows, total } = summary;
  if (!rows.length) {
    container.replaceChildren(h("div", { class: "muted" }, "No activity in this range."));
    return;
  }
  const perDay = dayLabels.length > 1;
  const dayCells = (values, cls = "") => (perDay ? values.map((ms) => h("td", { class: "num " + cls }, ms ? fmtDuration(ms) : "")) : []);
  container.replaceChildren(
    h("table", {},
      h("thead", {}, h("tr", {},
        h("th", {}, "Project"),
        ...(perDay ? dayLabels.map((l) => h("th", { class: "num" }, l)) : []),
        h("th", { class: "num" }, "Active time"),
        h("th", { class: "num" }, "Cost"),
        h("th", { class: "num" }, "Sessions"),
        h("th", { class: "num" }, "Commits"),
        h("th", { class: "num" }, "PRs"),
        h("th", { class: "num", title: "Cost divided by the commits made in the range" }, "$/commit"))),
      h("tbody", {}, rows.map((r) =>
        h("tr", {},
          h("td", {},
            h("span", { class: "dot", style: { background: state.projectColors.get(r.project) } }), projectLink(r.project, r.name)),
          ...dayCells(r.days),
          h("td", { class: "num strong" }, fmtDuration(r.ms)),
          h("td", { class: "num" }, fmtCost(r.cost, r.estimated)),
          h("td", { class: "num" }, r.sessions),
          ...outputCells(r)))),
      h("tfoot", {}, h("tr", {},
        h("td", {}, "Total"),
        ...dayCells(days.map((d) => d.ms)),
        h("td", { class: "num strong" }, fmtDuration(total.ms)),
        h("td", { class: "num" }, fmtCost(total.cost, total.estimated)),
        h("td", { class: "num" }, rows.reduce((n, r) => n + r.sessions, 0)),
        ...outputCells(total)))),
    h("div", { class: "muted note" },
      "Active time is the drawn bars (split after the idle threshold). A session's cost is divided by when its requests ran. "
      + "Pull requests count in any range their session was active in."),
  );
}

// Commits, PRs and cost per commit of a Summary row or the total.
function outputCells(r) {
  const per = costPer(r.cost, r.commits);
  return [
    h("td", { class: "num" }, r.commits || ""),
    h("td", { class: "num" }, r.prs || ""),
    h("td", { class: "num" }, per == null ? "–" : fmtCost(per, r.estimated)),
  ];
}
