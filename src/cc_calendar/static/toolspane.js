// Tool usage across the sessions in the displayed range: most used tools, errors, MCP servers, subagents.
import { fmtCost, fmtTokens, h } from "./util.js";

const TOP = 15;
const HIGH_ERROR_RATE = 0.1;
let lastKey = null;
let lastVersion = null;
let lastData = null;
let showAll = false;

// One decimal below 10% so that a handful of errors among many calls does not read as 0%.
const fmtPct = (r) => `${(r * 100).toFixed(r < 0.1 ? 1 : 0)}%`;

// `key` changes with the range or the filtered sessions, `version` with each reload of the data.
export async function renderToolsPane(container, { start, end, ids, key, version }) {
  if (key !== lastKey || version !== lastVersion) {
    // A reload keeps the table for the same range and sessions until the new one is in, instead
    // of flashing "Loading" each time a transcript changes.
    if (key !== lastKey || !lastData) {
      lastData = null;
      container.replaceChildren(h("div", { class: "muted" }, "Loading tool usage…"));
    }
    lastKey = key;
    lastVersion = version;
    let data;
    try {
      const res = await fetch("/api/tools", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start, end, sessions: ids }),
      });
      if (!res.ok) throw new Error(String(res.status));
      data = await res.json();
    } catch (e) {
      if (key === lastKey && version === lastVersion) container.replaceChildren(h("div", { class: "muted" }, `Could not load tool usage (${e.message}).`));
      return;
    }
    if (key !== lastKey || version !== lastVersion) return; // a newer request superseded this one
    lastData = data;
  }
  if (lastData) draw(container, lastData);
}

function draw(container, d) {
  if (!d.calls) {
    container.replaceChildren(h("div", { class: "muted" }, "No tool calls in this range."));
    return;
  }
  const rate = (e, n) => h("td", { class: "num" + (n && e / n >= HIGH_ERROR_RATE ? " warn" : "") }, e ? fmtPct(e / n) : "");
  const max = d.tools[0].calls;
  const tools = showAll ? d.tools : d.tools.slice(0, TOP);
  const toolTable = h("table", {},
    h("thead", {}, h("tr", {},
      h("th", {}, "Tool"), h("th", { class: "num" }, "Calls"), h("th", {}),
      h("th", { class: "num" }, "Errors"), h("th", { class: "num" }, "Error rate"),
      h("th", { class: "num", title: "Calls made inside subagents" }, "In subagents"),
      h("th", { class: "num" }, "Sessions"))),
    h("tbody", {}, tools.map((t) => h("tr", {},
      h("td", { title: t.name }, t.name),
      h("td", { class: "num strong" }, t.calls),
      h("td", {}, h("span", { class: "usage-bar", style: { width: `${Math.max(2, (80 * t.calls) / max)}px` } })),
      h("td", { class: "num" }, t.errors || ""),
      rate(t.errors, t.calls),
      h("td", { class: "num" }, t.subagent_calls || ""),
      h("td", { class: "num" }, t.sessions)))));
  const more = d.tools.length > TOP
    ? h("button", { class: "link-btn", onclick: () => { showAll = !showAll; draw(container, d); } },
      showAll ? "Show top " + TOP : `Show all ${d.tools.length} tools`)
    : null;

  const side = [];
  if (d.mcp.length) {
    side.push(h("table", {},
      h("thead", {}, h("tr", {},
        h("th", {}, "MCP server"), h("th", { class: "num" }, "Calls"),
        h("th", { class: "num" }, "Tools"), h("th", { class: "num" }, "Error rate"))),
      h("tbody", {}, d.mcp.map((m) => h("tr", {},
        h("td", {}, m.server), h("td", { class: "num strong" }, m.calls),
        h("td", { class: "num" }, m.tools), rate(m.errors, m.calls))))));
  }
  if (d.subagents.length) {
    side.push(h("table", {},
      h("thead", {}, h("tr", {},
        h("th", {}, "Subagent"), h("th", { class: "num" }, "Runs"), h("th", { class: "num" }, "Tool calls"),
        h("th", { class: "num" }, "Tokens"), h("th", { class: "num" }, "Cost"))),
      h("tbody", {}, d.subagents.map((a) => h("tr", {},
        h("td", {}, a.type), h("td", { class: "num strong" }, a.runs), h("td", { class: "num" }, a.calls),
        h("td", { class: "num" }, fmtTokens(a.tokens)), h("td", { class: "num" }, fmtCost(a.cost, true)))))));
  }

  container.replaceChildren(
    h("div", { class: "tools-head" },
      h("strong", {}, `${d.calls} tool calls`),
      ` · ${d.errors} errors (${fmtPct(d.errors / d.calls)}) · ${d.sessions} session${d.sessions > 1 ? "s" : ""}`),
    h("div", { class: "tools-grid" }, h("div", {}, toolTable, more), side.length ? h("div", { class: "tools-side" }, ...side) : null),
  );
}
