// Month calendar and yearly heatmap: one cell per day, shaded by active time, cost or commits.
import { openDay, openMonth, state } from "./app.js";
import { projectCommits } from "./project.js";
import { dayTotalLabel, renderSummary, summarize } from "./summary.js";
import { addDays, fmtCost, fmtDuration, h, prefs, startOfWeek } from "./util.js";

export const LEVELS = 4;
export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// Shading level 0..LEVELS of a value, relative to the largest value shown.
export const heatLevel = (v, max) => (v > 0 && max > 0 ? Math.max(1, Math.ceil((LEVELS * v) / max)) : 0);

// Value a cell is shaded by: `t` holds ms, cost and commits.
export const heatValue = (t) => (state.heat === "cost" ? t.cost : state.heat === "commits" ? t.commits : t.ms);

// The "Shade by" control and the scale, shared by the month and year views and the Hours pane.
export function shadeBy(rerender) {
  const metric = state.heat;
  const setMetric = (m) => { state.heat = m; prefs.set("heat", m); rerender(); };
  const option = (m, label) => h("button", { class: metric === m ? "active" : "", onclick: () => setMetric(m) }, label);
  return [
    h("span", { class: "muted" }, "Shade by"),
    h("div", { class: "seg small" }, option("time", "Active time"), option("cost", "Cost"), option("commits", "Commits")),
    h("span", { class: "heat-scale" }, "Less",
      ...[...Array(LEVELS + 1)].map((_, l) => h("i", { class: `heat l${l}` })), "More"),
  ];
}

// First and last day (exclusive) of the month or year containing the anchor.
export function overviewRange(span, anchor) {
  if (span === "year") {
    const y = anchor.getFullYear();
    return [new Date(y, 0, 1), new Date(y + 1, 0, 1)];
  }
  const y = anchor.getFullYear();
  const m = anchor.getMonth();
  return [new Date(y, m, 1), new Date(y, m + 1, 1)];
}

export function renderOverview(container, visible, { legend, rangeLabel, rangeCount, summaryPane, rerender }) {
  const year = state.span === "year";
  const [first, end] = overviewRange(state.span, state.anchor);
  // Whole weeks so the grid is rectangular; days outside the range are drawn but dimmed.
  const gridStart = startOfWeek(first);
  const days = [];
  for (let d = gridStart; d < end || d.getDay() !== 1; d = addDays(d, 1)) days.push(d);
  const inRange = (d) => d >= first && d < end;

  const overlaps = (from, to) => (s) => s.segments.some(([a, b]) => b >= from && a < to);
  // The dimmed days of the neighbouring months still show their activity; totals cover the range only.
  const shown = visible.filter(overlaps(days[0].getTime(), addDays(days[days.length - 1], 1).getTime()));
  const sessions = shown.filter(overlaps(first.getTime(), end.getTime()));
  const summary = summarize(shown, days.map((d) => [d.getTime(), addDays(d, 1).getTime()]));
  const totals = summarize(sessions, [[first.getTime(), end.getTime()]]);
  // Commits per day, by when they were made.
  const dayIndex = new Map(days.map((d, i) => [d.toDateString(), i]));
  summary.days.forEach((t) => { t.commits = 0; });
  for (const c of projectCommits(shown)) {
    const i = c.ts == null ? undefined : dayIndex.get(new Date(c.ts).toDateString());
    if (i !== undefined) summary.days[i].commits++;
  }

  rangeLabel.textContent = year
    ? String(first.getFullYear())
    : first.toLocaleDateString([], { year: "numeric", month: "long" });
  rangeCount.textContent = `${sessions.length} sessions` + (totals.total.ms || totals.total.cost
    ? ` · ${fmtDuration(totals.total.ms)} · ${fmtCost(totals.total.cost, totals.total.estimated)}`
    : "");
  summaryPane.hidden = !state.showSummary;
  if (state.showSummary) renderSummary(summaryPane, totals, [rangeLabel.textContent]);

  const value = heatValue;
  let max = 0;
  days.forEach((d, i) => { if (inRange(d)) max = Math.max(max, value(summary.days[i])); });
  const level = (v) => heatLevel(v, max);

  // Keep a budget value being typed when live updates re-render the legend.
  const focused = legend.contains(document.activeElement) ? document.activeElement : null;
  legend.replaceChildren(...shadeBy(rerender), h("span", { class: "muted" }, "Click a day to open it"),
    year ? null : renderBudget(monthPace(totals.total.cost, first, end, new Date()), totals.total.estimated, rerender));
  const again = focused?.dataset.key && legend.querySelector(`[data-key="${focused.dataset.key}"]`);
  if (again) {
    again.value = focused.value;
    again.focus();
  }

  const todayKey = new Date().toDateString();
  const tipText = (d, t) => {
    const date = d.toLocaleDateString([], { weekday: "short", year: "numeric", month: "short", day: "numeric" });
    // A commit can fall on a day with no active time, e.g. one made just after midnight.
    const parts = [
      t.ms || t.cost ? `${fmtDuration(t.ms)} active · ${fmtCost(t.cost, t.estimated)}` : null,
      t.commits ? commitCount(t.commits) : null,
      t.sessions ? `${t.sessions} session${t.sessions > 1 ? "s" : ""}` : null,
    ].filter(Boolean);
    return `${date}\n${parts.length ? parts.join(" · ") : "No activity"}`;
  };

  if (year) {
    container.replaceChildren(renderYear(days, summary, inRange, level, value, tipText, todayKey));
  } else {
    container.replaceChildren(renderMonth(days, summary, inRange, level, value, tipText, todayKey));
  }
  container.scrollTop = 0;
}

// Spend pace of a month: the daily average over the days elapsed, and for the current month the
// month-end total at that pace. Past months use their actual total; future months have no figures.
export function monthPace(cost, first, end, now) {
  const days = Math.round((end - first) / 86400000);
  if (now < first) return { status: "future", days };
  if (now >= end) return { status: "past", days, elapsed: days, spent: cost, daily: cost / days, projected: cost };
  const elapsed = now.getDate();
  return { status: "current", days, elapsed, spent: cost, daily: cost / elapsed, projected: (cost / elapsed) * days };
}

// Monthly budget and plan price, in USD, kept in this browser. 0 means not set.
const budgetPrefs = () => ({ budget: prefs.get("budget", 0), plan: prefs.get("planPrice", 0) });
let editingBudget = false;

// One line under the legend: spent, daily average, projection and progress against the budget.
function renderBudget(pace, estimated, rerender) {
  const { budget, plan } = budgetPrefs();
  const toggle = h("button", {
    class: editingBudget ? "active" : "",
    title: "Set a monthly budget and plan price, kept in this browser",
    onclick: () => { editingBudget = !editingBudget; rerender(); },
  }, "Budget");
  const cost = (v) => fmtCost(v, estimated);
  const parts = [];
  if (pace.status === "future") {
    parts.push(h("span", { class: "muted" }, "No spending yet"));
  } else {
    parts.push(h("span", {}, `Spent ${cost(pace.spent)}`),
      h("span", { class: "muted" }, `${cost(pace.daily)}/day`));
    if (pace.status === "current") {
      parts.push(h("span", { title: `${pace.elapsed} of ${pace.days} days elapsed, at the daily average so far` },
        `Projected ${cost(pace.projected)}`, h("span", { class: "muted" }, ` (day ${pace.elapsed} of ${pace.days})`)));
    }
    if (budget > 0) {
      const over = pace.projected > budget;
      const pct = (v) => Math.min(100, (100 * v) / budget);
      parts.push(h("span", {
        class: "budget-bar" + (over ? " over" : ""),
        title: `${Math.round((100 * pace.spent) / budget)}% of the ${fmtCost(budget)} budget spent`
          + (pace.status === "current" ? `, ${Math.round((100 * pace.projected) / budget)}% projected` : ""),
      }, h("i", { class: "projected", style: { width: `${pct(pace.projected)}%` } }),
      h("i", { class: "spent", style: { width: `${pct(pace.spent)}%` } })),
      h("span", { class: over ? "budget-over" : "muted" }, over
        ? `${pace.status === "current" ? "Projected over" : "Over"} ${fmtCost(budget)} budget by ${cost(pace.projected - budget)}`
        : `${Math.round((100 * pace.spent) / budget)}% of ${fmtCost(budget)} budget`));
    }
    if (plan > 0) {
      parts.push(h("span", { class: "muted", title: "What this month's usage would cost at API list prices, against your subscription's monthly price" },
        pace.status === "current"
          ? `API equivalent ${cost(pace.projected)} projected vs plan ${fmtCost(plan)}`
          : `API equivalent ${cost(pace.spent)} vs plan ${fmtCost(plan)}`));
    }
  }
  const field = (key, label, value) => h("label", { class: "muted" }, `${label} $`,
    h("input", {
      type: "number", min: 0, step: "any", placeholder: "none", value: value || "", "data-key": key, "aria-label": label,
      onchange: (e) => { prefs.set(key, Math.max(0, Number(e.target.value) || 0)); rerender(); },
    }));
  return h("div", { class: "budget" }, toggle,
    editingBudget ? h("span", { class: "budget-edit" },
      field("budget", "Monthly budget", budget), field("planPrice", "Plan price", plan)) : null,
    ...parts,
    h("span", { class: "muted budget-note", title: "Costs are estimated from the logs at API list prices; check your Anthropic console or plan for billing" },
      "Rough estimates, not billing data"));
}

const commitCount = (n) => `${n} commit${n > 1 ? "s" : ""}`;

function renderMonth(days, summary, inRange, level, value, tipText, todayKey) {
  // Top projects per day, by active time.
  const topProjects = days.map((_, i) => summary.rows
    .filter((r) => r.days[i] > 0)
    .sort((a, b) => b.days[i] - a.days[i]));
  return h("div", { class: "month" },
    ...WEEKDAYS.map((w) => h("div", { class: "month-head" }, w)),
    ...days.map((d, i) => {
      const t = summary.days[i];
      const projects = topProjects[i];
      return h("div", {
        class: ["month-day", `heat l${inRange(d) ? level(value(t)) : 0}`,
          inRange(d) ? "" : "outside", d.toDateString() === todayKey ? "today" : ""].join(" ").trim(),
        title: tipText(d, t),
        onclick: () => openDay(d),
      },
      h("div", { class: "month-date" }, d.getDate() === 1
        ? d.toLocaleDateString([], { month: "short", day: "numeric" })
        : String(d.getDate())),
      h("div", { class: "month-total" }, dayTotalLabel(t)),
      state.heat === "commits" && t.commits ? h("div", { class: "month-total" }, commitCount(t.commits)) : null,
      h("div", { class: "month-projects" },
        ...projects.slice(0, 3).map((r) => h("div", { class: "month-project", title: `${r.name} · ${fmtDuration(r.days[i])}` },
          h("span", { class: "dot", style: { background: state.projectColors.get(r.project) } }), r.name)),
        projects.length > 3 ? h("div", { class: "muted" }, `+${projects.length - 3} more`) : null));
    }));
}

function renderYear(days, summary, inRange, level, value, tipText, todayKey) {
  const weeks = Math.ceil(days.length / 7);
  const grid = h("div", { class: "year-grid", style: { gridTemplateColumns: `28px repeat(${weeks}, 14px)` } });
  // Month labels over the week in which each month starts.
  grid.append(h("div", {}));
  for (let w = 0; w < weeks; w++) {
    const start = days.slice(w * 7, w * 7 + 7).find((d) => inRange(d) && d.getDate() === 1);
    grid.append(h("div", { class: "year-month" }, start ? start.toLocaleDateString([], { month: "short" }) : ""));
  }
  for (let row = 0; row < 7; row++) {
    grid.append(h("div", { class: "year-weekday" }, row % 2 === 0 ? WEEKDAYS[row] : ""));
    for (let w = 0; w < weeks; w++) {
      const i = w * 7 + row;
      const d = days[i];
      if (!d || !inRange(d)) {
        grid.append(h("div", {}));
        continue;
      }
      const t = summary.days[i];
      grid.append(h("div", {
        class: `year-day heat l${level(value(t))}` + (d.toDateString() === todayKey ? " today" : ""),
        title: tipText(d, t),
        onclick: () => openDay(d),
      }));
    }
  }

  // Per-month totals under the heatmap.
  const months = new Map();
  days.forEach((d, i) => {
    if (!inRange(d)) return;
    const m = months.get(d.getMonth()) || { label: d.toLocaleDateString([], { month: "short" }), ms: 0, cost: 0, estimated: false };
    m.ms += summary.days[i].ms;
    m.cost += summary.days[i].cost;
    m.estimated ||= summary.days[i].estimated;
    months.set(d.getMonth(), m);
  });
  const totals = h("div", { class: "year-months" }, ...[...months.entries()].map(([m, t]) => h("button", {
    class: "year-month-total",
    title: "Show this month",
    onclick: () => openMonth(days.find((d) => inRange(d) && d.getMonth() === m)),
  }, h("strong", {}, t.label), h("span", { class: "muted" }, t.ms || t.cost ? `${fmtDuration(t.ms)} · ${fmtCost(t.cost, t.estimated)}` : "–"))));
  return h("div", { class: "year" }, grid, totals);
}
