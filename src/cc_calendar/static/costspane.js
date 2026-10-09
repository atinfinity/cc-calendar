// Cost across the sessions in the displayed range, by model and token type, and per day.
import { fmtCost, fmtTokens, h, idleRecacheTitle, shortModel } from "./util.js";

// In the order the server sends tokens and costs.
const TYPES = [["in", "Input"], ["out", "Output"], ["write", "Cache write"], ["read", "Cache read"]];
const BAR_PX = 240;
let lastKey = null;
let lastData = null;

// `bounds` holds one [start, end) per row of the per-day table, or the whole range when
// `labels` is null. `key` changes when the range, the filtered sessions or the data change.
export async function renderCostsPane(container, { bounds, labels, ids, key }) {
  if (key !== lastKey) {
    lastKey = key;
    lastData = null;
    container.replaceChildren(h("div", { class: "muted" }, "Loading cost breakdown…"));
    let data;
    try {
      const res = await fetch("/api/costs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bounds, sessions: ids }),
      });
      if (!res.ok) throw new Error(String(res.status));
      data = await res.json();
    } catch (e) {
      if (key === lastKey) container.replaceChildren(h("div", { class: "muted" }, `Could not load the cost breakdown (${e.message}).`));
      return;
    }
    if (key !== lastKey) return; // a newer request superseded this one
    lastData = data;
  }
  if (lastData) draw(container, lastData, labels);
}

const sum = (xs) => xs.reduce((n, x) => n + x, 0);

// One segment per token type; the bar is `px` wide at the largest row's cost.
function bar(row, max, est) {
  const total = sum(row.cost);
  return h("span", { class: "cost-bar", style: { width: `${max ? (BAR_PX * total) / max : 0}px` } },
    TYPES.map(([cls, label], i) => row.cost[i] > 0 && h("span", {
      class: "cost-seg cost-" + cls,
      style: { width: `${(100 * row.cost[i]) / total}%` },
      title: `${label}: ${fmtCost(row.cost[i], est)} · ${fmtTokens(row.tokens[i])} tokens`,
    })));
}

// Requests in the range that rewrote an expired cache after a break; always an estimate.
function idleLine(idle) {
  if (!idle?.requests) return null;
  return h("div", { class: "muted", title: idleRecacheTitle(idle.requests, idle.tokens) },
    `Idle re-cache ${fmtCost(idle.cost, true)}: ${idle.requests} request${idle.requests > 1 ? "s" : ""} in `
    + `${idle.sessions} session${idle.sessions > 1 ? "s" : ""} rewrote an expired cache after a break. `
    + "/clear or /compact before a long break is cheaper.");
}

function draw(container, d, labels) {
  if (!d.models.length) {
    container.replaceChildren(h("div", { class: "muted" }, "No API requests in this range."));
    return;
  }
  const est = d.estimated;
  const total = sum(d.models.map((m) => sum(m.cost)));
  const typeTotals = TYPES.map((_, i) => sum(d.models.map((m) => m.cost[i])));
  const maxModel = Math.max(...d.models.map((m) => sum(m.cost)));
  const costCells = (row) => TYPES.map((_, i) => h("td", { class: "num", title: `${fmtTokens(row.tokens[i])} tokens` },
    row.cost[i] ? fmtCost(row.cost[i], est) : ""));
  const head = (first) => h("thead", {}, h("tr", {},
    h("th", {}, first), h("th", {}),
    ...TYPES.map(([cls, label]) => h("th", { class: "num" }, h("span", { class: "cost-key cost-" + cls }), label)),
    h("th", { class: "num" }, "Cost"), h("th", { class: "num" }, "Tokens")));
  const tableRow = (name, row, max, title) => h("tr", {},
    h("td", { title }, name),
    h("td", {}, bar(row, max, est)),
    ...costCells(row),
    h("td", { class: "num strong" }, sum(row.cost) ? fmtCost(sum(row.cost), est) : ""),
    h("td", { class: "num" }, sum(row.tokens) ? fmtTokens(sum(row.tokens)) : ""));

  const models = h("table", {},
    head("Model"),
    h("tbody", {}, d.models.map((m) => tableRow(shortModel(m.model), m, maxModel, m.model))));
  let days = null;
  if (labels) {
    const maxDay = Math.max(...d.days.map((r) => sum(r.cost)));
    days = h("table", {},
      head("Day"),
      h("tbody", {}, d.days.map((r, i) => tableRow(labels[i], r, maxDay))));
  }

  container.replaceChildren(
    h("div", { class: "tools-head" },
      h("strong", {}, fmtCost(total, est)),
      ` · ${d.sessions} session${d.sessions > 1 ? "s" : ""} · `,
      TYPES.map(([, label], i) => `${label} ${total ? Math.round((100 * typeTotals[i]) / total) : 0}%`).join(" · ")),
    idleLine(d.idle_recache),
    h("div", { class: "costs-grid" }, models, days),
    h("div", { class: "muted note" },
      "Subagent requests count under their own model. Hover a bar for cost and tokens. ",
      d.recorded
        ? `${d.recorded} of ${d.sessions} sessions have Claude Code's own cost record; their cost is split by the estimate's proportions.`
        : "Sessions with Claude Code's own cost record are split by the estimate's proportions."),
  );
}
