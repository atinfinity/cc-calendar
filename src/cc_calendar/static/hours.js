// Hours pane: active time, cost and commits by weekday and hour of day (a punch card) for the
// displayed range, in the browser's time zone.
import { state } from "./app.js";
import { WEEKDAYS, heatLevel, heatValue, shadeBy } from "./overview.js";
import { projectCommits } from "./project.js";
import { activeMs } from "./summary.js";
import { addDays, fmtCost, fmtDuration, h } from "./util.js";

const BUCKET_MS = 600_000;
const HOUR_MS = 3_600_000;

// 7 x 24 cells, Monday first like the week view.
function hourCells(sessions, start, end) {
  const cells = WEEKDAYS.map(() => [...Array(24)].map(() =>
    ({ ms: 0, cost: 0, estimated: false, commits: 0, sessions: new Set() })));
  const cellAt = (t) => {
    const d = new Date(t);
    return cells[(d.getDay() + 6) % 7][d.getHours()];
  };
  for (const s of sessions) {
    // Active time: the drawn segments, cut at each local hour.
    const active = new Map();
    for (const [a, b] of s.segments) {
      const to = Math.min(b, end);
      for (let t = Math.max(a, start); t < to;) {
        // Step back by the minutes past the local hour rather than setMinutes(0): in the hour
        // repeated when clocks go back, setMinutes picks the first 1:00 and t never advances.
        const d = new Date(t);
        const past = d.getMinutes() * 60_000 + d.getSeconds() * 1000 + d.getMilliseconds();
        const next = Math.min(t - past + HOUR_MS, to);
        const c = cellAt(t);
        active.set(c, (active.get(c) || 0) + next - t);
        t = next;
      }
    }
    for (const [c, ms] of active) {
      c.ms += ms;
      c.sessions.add(s.id);
    }
    // Cost: split by when the session's requests ran, as in the Summary table.
    if (!s.cost) continue;
    const density = Object.entries(s.cost_density || {});
    const total = density.reduce((n, [, c]) => n + c, 0);
    const shares = new Map();
    if (total > 0) {
      for (const [bucket, c] of density) {
        const t = Number(bucket) * BUCKET_MS;
        if (t < start || t >= end) continue;
        const cell = cellAt(t);
        shares.set(cell, (shares.get(cell) || 0) + (s.cost * c) / total);
      }
    } else {
      // No priced requests (e.g. unknown model): fall back to the share of active time.
      const all = activeMs(s, -Infinity, Infinity);
      for (const [c, ms] of active) if (all > 0) shares.set(c, (s.cost * ms) / all);
    }
    for (const [c, cost] of shares) {
      c.cost += cost;
      c.estimated ||= s.cost_estimated;
      c.sessions.add(s.id);
    }
  }
  for (const c of projectCommits(sessions)) {
    if (c.ts != null && c.ts >= start && c.ts < end) cellAt(c.ts).commits++;
  }
  return cells;
}

const sum = (cells) => cells.reduce((t, c) => ({
  ms: t.ms + c.ms, cost: t.cost + c.cost, estimated: t.estimated || c.estimated, commits: t.commits + c.commits,
}), { ms: 0, cost: 0, estimated: false, commits: 0 });

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

function totalsText(t) {
  return [
    `${fmtDuration(t.ms)} active`,
    fmtCost(t.cost, t.estimated),
    plural(t.commits, "commit"),
    ...(t.sessions !== undefined ? [plural(t.sessions, "session")] : []),
  ].join(" · ");
}

// `days` are the displayed days; sessions are already filtered.
export function renderHoursPane(container, visible, { days, rerender }) {
  const start = days[0].getTime();
  const end = addDays(days[days.length - 1], 1).getTime();
  const sessions = visible.filter((s) => s.segments.some(([a, b]) => b >= start && a < end));
  const cells = hourCells(sessions, start, end);
  const all = cells.flat();
  const total = sum(all);
  if (!total.ms && !total.cost && !total.commits) {
    container.replaceChildren(h("div", { class: "muted" }, "No activity in this range."));
    return;
  }

  const max = Math.max(...all.map(heatValue));
  const fmtValue = (t) => (state.heat === "cost" ? fmtCost(t.cost, t.estimated)
    : state.heat === "commits" ? String(t.commits) : fmtDuration(t.ms));
  // How many of each weekday the range covers, for the tooltips.
  const weekdayCount = WEEKDAYS.map((_, row) => days.filter((d) => (d.getDay() + 6) % 7 === row).length);
  const hourLabel = (hr) => `${hr}:00–${hr + 1}:00`;
  const tip = (row, hr, c) => {
    const head = `${WEEKDAYS[row]} ${hourLabel(hr)}` + (weekdayCount[row] > 1 ? ` (${weekdayCount[row]} days)` : "");
    return c.ms || c.cost || c.commits ? `${head}\n${totalsText({ ...c, sessions: c.sessions.size })}` : `${head}\nNo activity`;
  };

  let busiest = null;
  cells.forEach((row, r) => row.forEach((c, hr) => {
    if (heatValue(c) > 0 && (!busiest || heatValue(c) > heatValue(busiest.c))) busiest = { r, hr, c };
  }));

  const table = h("table", { class: "hours-grid" },
    h("thead", {}, h("tr", {},
      h("th", {}),
      ...[...Array(24)].map((_, hr) => h("th", { class: "hours-hour", scope: "col", title: hourLabel(hr) }, hr % 3 === 0 ? String(hr) : "")),
      h("th", { class: "num", scope: "col" }, "Total"))),
    h("tbody", {}, cells.map((row, r) => {
      const rowTotal = sum(row);
      return h("tr", {},
        h("th", { scope: "row" }, WEEKDAYS[r]),
        ...row.map((c, hr) => {
          const text = tip(r, hr, c);
          return h("td", { class: `hours-cell heat l${heatLevel(heatValue(c), max)}`, title: text, "aria-label": text });
        }),
        h("td", { class: "num", title: `${WEEKDAYS[r]}\n${totalsText(rowTotal)}` },
          heatValue(rowTotal) ? fmtValue(rowTotal) : "–"));
    })));

  container.replaceChildren(
    h("div", { class: "tools-head" },
      h("strong", {}, "By weekday and hour"),
      ` · ${totalsText(total)}`,
      busiest ? ` · busiest: ${WEEKDAYS[busiest.r]} ${hourLabel(busiest.hr)}` : ""),
    // The month and year views already show "Shade by" in their legend.
    h("div", { class: "legend hours-legend" }, ...(state.span === "month" || state.span === "year" ? [] : shadeBy(rerender)),
      h("span", { class: "muted" }, `Local time (${Intl.DateTimeFormat().resolvedOptions().timeZone})`)),
    table,
  );
}
