// Active time and cost per day and per project for the displayed range.
import { projectLink, state } from "./app.js";
import { OUTCOMES, fmtCost, fmtDuration, h } from "./util.js";

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

// Totals per day and per project. `bounds` holds each day's [start, end) in ms.
export function summarize(sessions, bounds) {
  const days = bounds.map(() => ({ ms: 0, cost: 0, estimated: false, sessions: 0 }));
  const projects = new Map();
  for (const s of sessions) {
    let row = projects.get(s.project);
    if (!row) {
      row = { project: s.project, name: s.project_name, days: bounds.map(() => 0), ms: 0, cost: 0, estimated: false, sessions: 0 };
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
    });
    if (touched) row.sessions++;
  }
  const rows = [...projects.values()].filter((r) => r.sessions).sort((a, b) => b.ms - a.ms || b.cost - a.cost);
  const total = {
    ms: days.reduce((n, d) => n + d.ms, 0),
    cost: days.reduce((n, d) => n + d.cost, 0),
    estimated: days.some((d) => d.estimated),
  };
  return { days, rows, total, outcomes: byOutcome(sessions, bounds) };
}

export function dayTotalLabel(d) {
  return d.ms || d.cost ? `${fmtDuration(d.ms)} · ${fmtCost(d.cost, d.estimated)}` : "";
}

// Active time, cost and sessions per rated outcome in the range; unrated sessions are left out.
function byOutcome(sessions, bounds) {
  const out = new Map();
  for (const s of sessions) {
    if (!s.outcome) continue;
    let ms = 0;
    let cost = 0;
    for (const [from, to] of bounds) {
      ms += activeMs(s, from, to);
      cost += costIn(s, from, to);
    }
    if (!ms && !cost) continue;
    const o = out.get(s.outcome) || { ms: 0, cost: 0, estimated: false, sessions: 0 };
    o.ms += ms;
    o.cost += cost;
    o.estimated ||= s.cost_estimated;
    o.sessions++;
    out.set(s.outcome, o);
  }
  return out;
}

// One line under the table: time and cost of the sessions rated done, partial and failed, and of
// the rest, so it is easy to see what failed sessions cost. Shown once a session in range is rated.
function outcomeLine(outcomes, total) {
  if (!outcomes?.size) return null;
  let ms = total.ms;
  let cost = total.cost;
  const part = (cls, title, text, o) => h("span", { class: cls, title }, `${text} ${fmtDuration(o.ms)} · ${fmtCost(o.cost, o.estimated)}`);
  const parts = OUTCOMES.filter(([v]) => outcomes.has(v)).map(([v, label, symbol]) => {
    const o = outcomes.get(v);
    ms -= o.ms;
    cost -= o.cost;
    return part(`outcome-${v}`, `${o.sessions} session${o.sessions > 1 ? "s" : ""} rated ${label.toLowerCase()}`, `${symbol} ${label}`, o);
  });
  if (ms > 0 || cost > 0.005) {
    parts.push(part("muted", "Sessions without an outcome", "Unrated", { ms: Math.max(0, ms), cost: Math.max(0, cost), estimated: total.estimated }));
  }
  return h("div", { class: "outcome-summary" }, h("span", { class: "muted" }, "By outcome:"), ...parts);
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
        h("th", { class: "num" }, "Sessions"))),
      h("tbody", {}, rows.map((r) =>
        h("tr", {},
          h("td", {},
            h("span", { class: "dot", style: { background: state.projectColors.get(r.project) } }), projectLink(r.project, r.name)),
          ...dayCells(r.days),
          h("td", { class: "num strong" }, fmtDuration(r.ms)),
          h("td", { class: "num" }, fmtCost(r.cost, r.estimated)),
          h("td", { class: "num" }, r.sessions)))),
      h("tfoot", {}, h("tr", {},
        h("td", {}, "Total"),
        ...dayCells(days.map((d) => d.ms)),
        h("td", { class: "num strong" }, fmtDuration(total.ms)),
        h("td", { class: "num" }, fmtCost(total.cost, total.estimated)),
        h("td", { class: "num" }, rows.reduce((n, r) => n + r.sessions, 0))))),
    h("div", { class: "muted note" },
      "Active time is the drawn bars (split after the idle threshold). A session's cost is divided by when its requests ran."),
  );
  const line = outcomeLine(summary.outcomes, total);
  if (line) container.lastChild.before(line);
}
