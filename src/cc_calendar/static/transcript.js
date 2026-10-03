// Modal transcript viewer with lazy loading and subagent drill-down.
import { fmtDateTime, fmtTime, h, prefs, renderMarkdown } from "./util.js";

const PAGE = 300;
const $ = (id) => document.getElementById(id);

const view = {
  detail: null,
  agent: null, // subagent id, or null for the main transcript
  entries: [],
  total: 0,
  loading: false,
  token: 0, // guards against responses for a log we already navigated away from
};

let bound = false;

function bind() {
  if (bound) return;
  bound = true;
  for (const [id, key] of [["log-thinking", "logThinking"], ["log-meta", "logMeta"], ["log-expand", "logExpand"]]) {
    const el = $(id);
    el.checked = prefs.get(key, false);
    el.addEventListener("change", () => {
      prefs.set(key, el.checked);
      rerender();
    });
  }
  $("log-close").addEventListener("click", closeLog);
  $("log-back").addEventListener("click", () => openLog(view.detail, null));
  $("log-modal").addEventListener("click", (e) => {
    if (e.target.id === "log-modal") closeLog();
  });
  $("log-body").addEventListener("scroll", (e) => {
    const b = e.currentTarget;
    if (b.scrollTop + b.clientHeight > b.scrollHeight - 400) loadMore();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("log-modal").hidden) {
      e.stopPropagation();
      closeLog();
    }
  });
}

export function openLog(detail, agentId) {
  bind();
  view.detail = detail;
  view.agent = agentId || null;
  view.entries = [];
  view.total = 0;
  view.loading = false;
  view.token++;

  const sub = agentId ? detail.subagents.find((a) => a.id === agentId) : null;
  $("log-title").textContent = sub
    ? `${sub.type || "Subagent"}: ${sub.description || agentId}`
    : detail.title;
  $("log-back").hidden = !agentId;
  $("log-body").replaceChildren(h("div", { class: "load-more" }, "Loading…"));
  $("log-body").scrollTop = 0;
  $("log-modal").hidden = false;
  loadMore();
}

function closeLog() {
  $("log-modal").hidden = true;
  view.token++;
}

async function loadMore() {
  if (view.loading || (view.total && view.entries.length >= view.total)) return;
  view.loading = true;
  const token = view.token;
  const params = new URLSearchParams({ offset: view.entries.length, limit: PAGE });
  if (view.agent) params.set("agent", view.agent);
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(view.detail.id)}/log?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (token !== view.token) return;
    view.total = data.total;
    const start = view.entries.length;
    view.entries.push(...data.entries);
    appendEntries(start);
  } catch (err) {
    if (token !== view.token) return;
    $("log-body").replaceChildren(h("div", { class: "load-more" }, `Failed to load log: ${err.message}`));
  } finally {
    if (token === view.token) view.loading = false;
  }
}

function rerender() {
  if ($("log-modal").hidden) return;
  $("log-body").replaceChildren();
  appendEntries(0);
}

function appendEntries(from) {
  const body = $("log-body");
  body.querySelector(".load-more")?.remove();
  const opts = {
    thinking: $("log-thinking").checked,
    meta: $("log-meta").checked,
    expand: $("log-expand").checked,
  };
  // Pair results with their calls so a tool renders as one collapsible block.
  const results = new Map();
  const uses = new Set();
  for (const e of view.entries) {
    if (e.kind === "tool_result") results.set(e.tool_use_id, e);
    else if (e.kind === "tool_use") uses.add(e.id);
  }

  let lastDay = from > 0 ? new Date(view.entries[from - 1].ts || 0).toDateString() : null;
  const frag = document.createDocumentFragment();
  for (let i = from; i < view.entries.length; i++) {
    const e = view.entries[i];
    if (e.kind === "tool_result" && uses.has(e.tool_use_id)) {
      continue;
    }
    const node = renderEntry(e, results, opts);
    if (!node) continue;
    const day = e.ts ? new Date(e.ts).toDateString() : lastDay;
    if (day && day !== lastDay) {
      frag.append(h("div", { class: "entry compact" }, fmtDateTime(e.ts)));
      lastDay = day;
    }
    frag.append(node);
  }
  if (!view.entries.length) frag.append(h("div", { class: "load-more" }, "This log is empty."));
  else if (view.entries.length < view.total) {
    frag.append(h("div", { class: "load-more" }, `${view.entries.length} / ${view.total} entries — scroll for more`));
  }
  body.append(frag);
}

function metaLine(label, ts) {
  return h("div", { class: "meta-line" }, label, ts ? ` · ${fmtTime(ts)}` : "");
}

function renderEntry(e, results, opts) {
  switch (e.kind) {
    case "user":
      return h("div", { class: "entry user" },
        metaLine(e.command ? "You (command)" : "You", e.ts),
        h("div", { class: "bubble" }, e.command ? h("code", {}, e.text) : renderMarkdown(e.text)));
    case "assistant":
      return h("div", { class: "entry assistant" }, metaLine("Claude", e.ts), h("div", { class: "bubble" }, renderMarkdown(e.text)));
    case "thinking":
      if (!opts.thinking) return null;
      return h("div", { class: "entry thinking" }, metaLine("Thinking", e.ts), h("div", { class: "bubble" }, e.text));
    case "tool_use":
      return renderTool(e, results.get(e.id), opts);
    case "tool_result":
      return renderTool(null, e, opts);
    case "interrupt":
    case "error":
      return h("div", { class: `entry ${e.kind}` }, e.text);
    case "compact":
      return h("div", { class: "entry compact" },
        e.text.length > 80
          ? h("details", {}, h("summary", {}, "— context compacted (summary) —"), h("pre", { style: { textAlign: "left" } }, e.text))
          : e.text);
    case "notification":
      return h("div", { class: "entry notification" }, metaLine("Background task", e.ts), h("pre", {}, e.text));
    case "meta":
    case "attachment":
    case "system":
      if (!opts.meta) return null;
      return h("div", { class: `entry ${e.kind}` }, metaLine(e.kind, e.ts), e.kind === "attachment" ? e.text : h("pre", {}, e.text));
    default:
      return null;
  }
}

function renderTool(use, result, opts) {
  const name = use?.name || result?.name || "tool";
  const isError = result?.is_error;
  const sub = use && (name === "Agent" || name === "Task")
    ? view.detail.subagents.find((a) => a.tool_use_id === use.id && a.has_log)
    : null;
  const summary = h("summary", {},
    h("strong", {}, name), " ", use?.summary || "",
    isError ? h("span", { class: "err" }, "  ✗ error") : null,
    result ? null : h("span", { class: "muted" }, "  (no result)"));
  const box = h("details", { open: opts.expand || undefined }, summary);
  // Build the body lazily: big inputs and outputs make the DOM slow otherwise.
  const fill = () => {
    if (box.dataset.filled) return;
    box.dataset.filled = "1";
    if (use?.input && use.input !== "{}") box.append(h("div", { class: "meta-line" }, "Input"), h("pre", {}, use.input));
    // The result may have arrived on a later page than the call.
    result ||= use && view.entries.find((x) => x.kind === "tool_result" && x.tool_use_id === use.id);
    if (result) box.append(h("div", { class: "meta-line" }, isError ? "Error" : "Result"), h("pre", { class: isError ? "err" : "" }, result.text || "(empty)"));
  };
  if (opts.expand) fill();
  box.addEventListener("toggle", () => box.open && fill());
  return h("div", { class: "entry tool" },
    use?.ts ? metaLine("Tool", use.ts) : null,
    box,
    sub ? h("button", { style: { marginTop: "4px" }, onclick: () => openLog(view.detail, sub.id) }, "Open subagent log →") : null);
}
