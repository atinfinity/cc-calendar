// Cost across the sessions in the displayed range, by model and token type, and per day.
import { fmtCost, fmtTokens, h, idleRecacheTitle, shortModel } from "./util.js";

// In the order the server sends tokens and costs.
const TYPES = [["in", "Input"], ["out", "Output"], ["write", "Cache write"], ["read", "Cache read"]];
const BAR_PX = 240;
let lastKey = null;
let lastVersion = null;
let lastData = null;

// `bounds` holds one [start, end) per row of the per-day table, or the whole range when
// `labels` is null. `key` changes with the range or the filtered sessions, `version` with each reload of the data.
export async function renderCostsPane(container, { bounds, labels, ids, key, version }) {
  if (key !== lastKey || version !== lastVersion) {
    // A reload keeps the table for the same range and sessions until the new one is in, instead
    // of flashing "Loading" each time a transcript changes.
    if (key !== lastKey || !lastData) {
      lastData = null;
      container.replaceChildren(h("div", { class: "muted" }, "Loading cost breakdown…"));
    }
    lastKey = key;
    lastVersion = version;
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
      if (key === lastKey && version === lastVersion) container.replaceChildren(h("div", { class: "muted" }, `Could not load the cost breakdown (${e.message}).`));
      return;
    }
    if (key !== lastKey || version !== lastVersion) return; // a newer request superseded this one
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
    whatIfSection(d),
  );
}

// What-if: the same tokens re-priced as if one model's requests had run on another.
// Kept across redraws, so the choice survives a range change.
const SCOPES = [["both", "main thread and subagents"], ["main", "main thread"], ["agent", "subagents"]];
const whatIf = { from: null, to: null, scope: "both" };

function whatIfSection(d) {
  const usage = d.usage || [];
  if (!usage.length || !d.prices?.length) return null;
  const byCost = new Map();
  for (const u of usage) byCost.set(u.model, (byCost.get(u.model) || 0) + u.cost);
  const sources = [...byCost].sort((a, b) => b[1] - a[1]).map(([m]) => m);
  if (whatIf.from !== "*" && !sources.includes(whatIf.from)) whatIf.from = sources[0];
  if (!d.prices.some((p) => p.model === whatIf.to)) {
    // Default to the newest Sonnet, or the first other model in the price table.
    const other = d.prices.filter((p) => !whatIf.from.startsWith(p.model));
    whatIf.to = (other.find((p) => p.model.includes("sonnet")) || other[0] || d.prices[0]).model;
  }
  const rates = d.prices.find((p) => p.model === whatIf.to).rates;
  const hit = (u) => (whatIf.from === "*" || u.model === whatIf.from)
    && (whatIf.scope === "both" || u.agent === (whatIf.scope === "agent"));
  const affected = usage.filter(hit);
  const actual = sum(usage.map((u) => u.cost));
  const was = sum(affected.map((u) => u.cost));
  const now = sum(affected.map((u) => sum(u.scaled.map((n, i) => (n * rates[i]) / 1e6))));
  const estimate = actual - was + now;
  const diff = Math.abs(estimate - actual) < 0.005 ? 0 : estimate - actual;
  const sign = diff < 0 ? "−" : diff > 0 ? "+" : "";
  const tokens = sum(affected.map((u) => sum(u.tokens)));

  const section = h("div", { class: "what-if" });
  const redraw = () => section.replaceWith(whatIfSection(d));
  const pick = (key, options) => h("select", { onchange: (e) => { whatIf[key] = e.target.value; redraw(); } },
    options.map(([value, label, title]) => h("option", { value, title, selected: value === whatIf[key] }, label)));
  const fmtRate = (r) => `$${r[0]} in / $${r[1]} out per M`;
  section.append(
    h("div", { class: "what-if-pick" },
      h("strong", {}, "What if"), " ",
      pick("from", [["*", "any model"], ...sources.map((m) => [m, shortModel(m), m])]),
      " ran as ",
      pick("to", d.prices.map((p) => [p.model, shortModel(p.model), fmtRate(p.rates)])),
      " in ",
      pick("scope", SCOPES)),
    h("div", { class: "what-if-result" },
      `Actual ${fmtCost(actual, d.estimated)} · What if `,
      h("strong", {}, fmtCost(estimate, true)),
      " · Difference ",
      h("span", { class: diff < 0 ? "what-if-less" : diff > 0 ? "what-if-more" : "" },
        `${sign}${fmtCost(Math.abs(diff))}`,
        actual && diff ? ` (${sign}${Math.abs(Math.round((100 * diff) / actual))}%)` : "")),
    h("div", { class: "muted note" },
      affected.length
        ? `Re-prices ${fmtCost(was, d.estimated)} of the actual cost (${fmtTokens(tokens)} tokens) at ${shortModel(whatIf.to)}'s rates (${fmtRate(rates)}). `
        : "No requests match this choice. ",
      "A rough estimate from the same token counts: a different model, or another effort level, "
        + "would write different amounts, so real token counts would differ.",
      d.recorded
        ? " Sessions with Claude Code's own cost record are re-priced at the same ratio of recorded to estimated cost, so both figures are on the same footing."
        : ""),
  );
  return section;
}
