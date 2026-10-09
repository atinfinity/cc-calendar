// Active time and cost per day and per project for the displayed range.
import { projectLink, state } from "./app.js";
import { RATINGS, addDays, fmtCost, fmtDuration, h, prefs } from "./util.js";

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
  return { days, rows, total, ratings: byRating(sessions, bounds) };
}

export function dayTotalLabel(d) {
  return d.ms || d.cost ? `${fmtDuration(d.ms)} · ${fmtCost(d.cost, d.estimated)}` : "";
}

// Active time, cost and sessions per rating in the range; unrated sessions are left out.
function byRating(sessions, bounds) {
  const out = new Map();
  for (const s of sessions) {
    if (!s.rating) continue;
    let ms = 0;
    let cost = 0;
    for (const [from, to] of bounds) {
      ms += activeMs(s, from, to);
      cost += costIn(s, from, to);
    }
    if (!ms && !cost) continue;
    const o = out.get(s.rating) || { ms: 0, cost: 0, estimated: false, sessions: 0 };
    o.ms += ms;
    o.cost += cost;
    o.estimated ||= s.cost_estimated;
    o.sessions++;
    out.set(s.rating, o);
  }
  return out;
}

// One line under the table: time and cost of the sessions rated done, partial and failed, and of
// the rest, so it is easy to see what failed sessions cost. Shown once a session in range is rated.
function ratingLine(ratings, total) {
  if (!ratings?.size) return null;
  let ms = total.ms;
  let cost = total.cost;
  const part = (cls, title, text, o) => h("span", { class: cls, title }, `${text} ${fmtDuration(o.ms)} · ${fmtCost(o.cost, o.estimated)}`);
  const parts = RATINGS.filter(([v]) => ratings.has(v)).map(([v, label, symbol]) => {
    const o = ratings.get(v);
    ms -= o.ms;
    cost -= o.cost;
    return part(`rating-${v}`, `${o.sessions} session${o.sessions > 1 ? "s" : ""} rated ${label.toLowerCase()}`, `${symbol} ${label}`, o);
  });
  if (ms > 0 || cost > 0.005) {
    parts.push(part("muted", "Sessions without a rating", "Unrated", { ms: Math.max(0, ms), cost: Math.max(0, cost), estimated: total.estimated }));
  }
  return h("div", { class: "rating-summary" }, h("span", { class: "muted" }, "By rating:"), ...parts);
}

// The range of the same span just before the one starting at `first`: [start, end) as dates.
// Built from calendar dates rather than a fixed length, so months of any length and DST line up.
export function previousRange(span, first) {
  if (span === "year") return [new Date(first.getFullYear() - 1, 0, 1), first];
  if (span === "month") return [new Date(first.getFullYear(), first.getMonth() - 1, 1), first];
  return [addDays(first, span === "week" ? -7 : -1), first];
}

// Totals of the range before the one starting at `first`, from the same (filtered) sessions.
export function summarizePrevious(sessions, span, first) {
  const [from, to] = previousRange(span, first).map((d) => d.getTime());
  return summarize(sessions.filter((s) => s.segments.some(([a, b]) => b >= from && a < to)), [[from, to]]);
}

// "+1h 5m", "−$2.10", "+3"; "–" when there is no change worth showing.
export function fmtDelta(d, fmt = String, zero = 0) {
  if (Math.abs(d) <= zero) return "–";
  return (d > 0 ? "+" : "−") + fmt(Math.abs(d));
}

const DELTAS = [
  ["ms", "Active time", fmtDuration, 30_000],
  ["cost", "Cost", (c) => fmtCost(c), 0.005],
  ["sessions", "Sessions", String, 0],
  ["commits", "Commits", String, 0],
  ["prs", "PRs", String, 0],
];

function rangeName(span, [first, end]) {
  if (span === "year") return String(first.getFullYear());
  if (span === "month") return first.toLocaleDateString([], { year: "numeric", month: "long" });
  const opts = { month: "short", day: "numeric" };
  if (span === "day") return first.toLocaleDateString([], { weekday: "short", ...opts });
  return `${first.toLocaleDateString([], opts)} – ${addDays(end, -1).toLocaleDateString([], opts)}`;
}

// `compare` holds the filtered sessions and the first day of the range, for the comparison with
// the previous range; without it the table has no toggle.
export function renderSummary(container, summary, dayLabels, compare) {
  const { days, rows, total } = summary;
  const head = compare ? compareToggle(container, summary, dayLabels, compare) : null;
  if (compare && state.compareRanges) {
    renderComparison(container, head, summary, summarizePrevious(compare.sessions, state.span, compare.first), compare.first);
    return;
  }
  if (!rows.length) {
    container.replaceChildren(...[head, h("div", { class: "muted" }, "No activity in this range.")].filter(Boolean));
    return;
  }
  const perDay = dayLabels.length > 1;
  const dayCells = (values, cls = "") => (perDay ? values.map((ms) => h("td", { class: "num " + cls }, ms ? fmtDuration(ms) : "")) : []);
  container.replaceChildren(...(head ? [head] : []),
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
  const line = ratingLine(summary.ratings, total);
  if (line) container.lastChild.before(line);
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

function compareToggle(container, summary, dayLabels, compare) {
  const span = state.span;
  const on = state.compareRanges;
  const prev = previousRange(span, compare.first);
  return h("div", { class: "summary-head" },
    h("button", {
      class: on ? "active" : "",
      title: on ? "Show the displayed range on its own" : `Compare each project with the previous ${span}`,
      onclick: () => {
        state.compareRanges = !on;
        prefs.set("compareRanges", state.compareRanges);
        renderSummary(container, summary, dayLabels, compare);
      },
    }, `Compare with previous ${span}`),
    on ? h("span", { class: "muted" }, `vs. ${rangeName(span, prev)}`) : null);
}

// Totals per project for the displayed range next to the previous one, with the change. Projects
// active in only one of the two ranges are marked "new" or "absent".
function renderComparison(container, head, cur, prev, first) {
  const prevRows = new Map(prev.rows.map((r) => [r.project, r]));
  const curProjects = new Set(cur.rows.map((r) => r.project));
  const pairs = [
    ...cur.rows.map((r) => [r, prevRows.get(r.project)]),
    ...prev.rows.filter((r) => !curProjects.has(r.project)).map((r) => [null, r]),
  ];
  if (!pairs.length) {
    container.replaceChildren(head, h("div", { class: "muted" }, "No activity in this range or the previous one."));
    return;
  }
  const span = state.span;
  const prevName = rangeName(span, previousRange(span, first));
  const totals = (s) => ({ ...s.total, sessions: s.rows.reduce((n, r) => n + r.sessions, 0) });
  const cells = (c, p) => DELTAS.flatMap(([key, , fmt, zero]) => {
    const a = c?.[key] || 0;
    const b = p?.[key] || 0;
    const show = key === "cost" ? (v, e) => fmtCost(v, e) : fmt;
    return [
      h("td", { class: "num" + (key === "ms" ? " strong" : "") }, c ? show(a, c.estimated) : ""),
      h("td", { class: "num delta", title: `${prevName}: ${p ? show(b, p.estimated) : "no activity"}` },
        fmtDelta(a - b, fmt, zero)),
    ];
  });
  const mark = (c, p) => (!p ? h("span", { class: "range-mark", title: `No activity in ${prevName}` }, "new")
    : !c ? h("span", { class: "range-mark", title: "No activity in this range" }, "absent") : null);
  container.replaceChildren(head,
    h("table", { class: "compare" },
      h("thead", {}, h("tr", {},
        h("th", {}, "Project"),
        ...DELTAS.flatMap(([, label]) => [h("th", { class: "num" }, label), h("th", { class: "num", title: `Change from ${prevName}` }, "Δ")]))),
      h("tbody", {}, pairs.map(([c, p]) => {
        const r = c || p;
        return h("tr", { class: c ? "" : "absent" },
          h("td", {},
            h("span", { class: "dot", style: { background: state.projectColors.get(r.project) } }), projectLink(r.project, r.name),
            mark(c, p)),
          ...cells(c, p));
      })),
      h("tfoot", {}, h("tr", {}, h("td", {}, "Total"), ...cells(totals(cur), totals(prev))))),
    h("div", { class: "muted note" },
      `Δ is the change from ${prevName}; hover it for the previous value. The same filters apply to both ranges, `
      + "and a range still in progress is compared with the whole previous one."),
  );
}
