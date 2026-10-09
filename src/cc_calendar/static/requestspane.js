// The most expensive prompts sent in the displayed range, each with the requests it started.
import { projectLink, state } from "./app.js";
import { fmtCost, fmtDateTime, fmtTokens, h } from "./util.js";

const TOP = 10;
let lastKey = null;
let lastVersion = null;
let lastData = null;
let showAll = false;

// `key` changes with the range or the filtered sessions, `version` with each reload of the data.
// `onOpen(id, ts)` opens the session's transcript at the prompt sent at `ts`.
export async function renderRequestsPane(container, { start, end, ids, key, version, onOpen }) {
  if (key !== lastKey || version !== lastVersion) {
    // A reload keeps the table for the same range and sessions until the new one is in, instead
    // of flashing "Loading" each time a transcript changes.
    if (key !== lastKey || !lastData) {
      lastData = null;
      container.replaceChildren(h("div", { class: "muted" }, "Loading requests…"));
    }
    lastKey = key;
    lastVersion = version;
    let data;
    try {
      const res = await fetch("/api/requests", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start, end, sessions: ids }),
      });
      if (!res.ok) throw new Error(String(res.status));
      data = await res.json();
    } catch (e) {
      if (key === lastKey && version === lastVersion) container.replaceChildren(h("div", { class: "muted" }, `Could not load requests (${e.message}).`));
      return;
    }
    if (key !== lastKey || version !== lastVersion) return; // a newer request superseded this one
    lastData = data;
  }
  if (lastData) draw(container, lastData, onOpen);
}

function draw(container, d, onOpen) {
  const rows = d.top.filter((r) => state.byId.has(r.session));
  if (!rows.length) {
    container.replaceChildren(h("div", { class: "muted" }, "No prompts in this range."));
    return;
  }
  const max = rows[0].cost || 1;
  const shown = showAll ? rows : rows.slice(0, TOP);
  const table = h("table", {},
    h("thead", {}, h("tr", {},
      h("th", { class: "num" }, "Cost"), h("th", {}),
      h("th", {}, "Prompt"), h("th", {}, "Project"), h("th", {}, "Session"),
      h("th", { class: "num" }, "Sent"),
      h("th", { class: "num" }, "Tokens"),
      h("th", { class: "num", title: "API requests until the next prompt, and subagents started in that span" }, "Requests"))),
    h("tbody", {}, shown.map((r) => {
      const s = state.byId.get(r.session);
      const line = r.text.split("\n")[0] || "(empty prompt)";
      return h("tr", {
        "data-sid": r.session,
        title: "Open the transcript at this prompt",
        onclick: () => onOpen(r.session, r.ts),
      },
        h("td", { class: "num strong" }, fmtCost(r.cost, r.estimated)),
        h("td", {}, h("span", { class: "usage-bar", style: { width: `${Math.max(2, (80 * r.cost) / max)}px` } })),
        h("td", { class: "prompt-cell", title: r.text }, r.kind === "command" ? h("span", { class: "kind" }, "cmd") : null, line),
        h("td", { title: s.project },
          h("span", { class: "dot", style: { background: state.projectColors.get(s.project) } }), projectLink(s.project, s.project_name)),
        h("td", { class: "title-cell", title: s.title }, s.title),
        h("td", { class: "num" }, fmtDateTime(r.ts)),
        h("td", { class: "num" }, fmtTokens(r.tokens)),
        h("td", { class: "num" }, r.requests, r.subagents ? h("span", { class: "muted" }, ` + ${r.subagents} sub`) : null));
    })));
  const more = rows.length > TOP
    ? h("button", { class: "link-btn", onclick: () => { showAll = !showAll; draw(container, d, onOpen); } },
      showAll ? "Show top " + TOP : rows.length < d.prompts ? `Show top ${rows.length}` : `Show all ${rows.length} prompts`)
    : null;
  container.replaceChildren(
    h("div", { class: "tools-head" },
      h("strong", {}, "Most expensive requests"),
      ` · ${d.prompts} prompt${d.prompts === 1 ? "" : "s"} in this range, ${fmtCost(d.cost, d.estimated)} in all`),
    table, more,
    h("div", { class: "muted note" },
      "A prompt's cost covers the requests from it until the next prompt, subagents started in between included. Click a row to open the transcript there."),
  );
}
