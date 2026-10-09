// Modal transcript viewer with lazy loading and subagent drill-down.
import {
  MARK_KINDS, cacheTitle, compactDetail, costTitle, fmtCost, fmtEffortMix, fmtDateTime, fmtDuration, fmtPct, fmtTime, fmtTokens, h, prefs, renderMarkdown,
  shortModel,
} from "./util.js";
import { helpOpen, typing } from "./shortcuts.js";

const PAGE = 300;
const $ = (id) => document.getElementById(id);

const view = {
  detail: null,
  agent: null, // subagent id, or null for the main transcript
  entries: [],
  total: 0,
  events: [], // [index, ts, kind] of entries matching the calendar's event marks
  query: null, // full-text search the log was opened for
  matches: [], // [index, ts] of the entries containing it
  focus: null, // index of the entry last jumped to
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
  const statsToggle = $("log-stats-toggle");
  statsToggle.checked = prefs.get("logStats", false);
  statsToggle.addEventListener("change", () => {
    prefs.set("logStats", statsToggle.checked);
    loadStats();
  });
  $("log-close").addEventListener("click", closeLog);
  $("log-back").addEventListener("click", () => openLog(view.detail, null));
  $("log-modal").addEventListener("click", (e) => {
    if (e.target.id === "log-modal") closeLog();
  });
  $("log-body").addEventListener("scroll", (e) => {
    const b = e.currentTarget;
    if (!view.loading && b.scrollTop + b.clientHeight > b.scrollHeight - 400) loadMore();
  });
  document.addEventListener("keydown", onKey);
}

// Keys while the viewer is open. The global handler (shortcuts.js) runs first and has
// already taken Esc and ? when the shortcut list is open.
const KEYS = {
  n: () => step(null, 1),
  p: () => step(null, -1),
  "]": () => step("prompt", 1),
  "[": () => step("prompt", -1),
  s: () => $("log-stats-toggle").click(),
  e: () => $("log-expand").click(),
  b: () => $("log-back").hidden ? false : openLog(view.detail, null),
};

function onKey(e) {
  if ($("log-modal").hidden || e.defaultPrevented || helpOpen()) return;
  if (e.key === "Escape") {
    closeLog();
    e.preventDefault();
    return;
  }
  if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing || typing(e.target)) return;
  const handler = KEYS[e.key];
  if (handler && handler() !== false) e.preventDefault();
}

// `target` ({ts, kind}) scrolls to the event nearest to that moment once the log loads;
// {ts, query} scrolls to the entry containing `query` that is nearest to `ts`.
export async function openLog(detail, agentId, target = null) {
  bind();
  view.detail = detail;
  view.agent = agentId || null;
  view.entries = [];
  view.total = 0;
  view.events = [];
  view.query = target?.query || null;
  view.matches = [];
  view.focus = null;
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
  // Arrow keys, Page Up / Down and Space scroll the transcript.
  $("log-body").focus({ preventScroll: true });
  $("log-stats").replaceChildren();
  $("log-events").replaceChildren();
  loadStats();
  const token = view.token;
  await loadMore();
  if (target && token === view.token) {
    const near = view.query ? nearest(view.matches, target.ts) : nearestEvent(target);
    if (near) jumpTo(near[0], { open: !!view.query });
  }
}

function nearest(list, ts) {
  let best = null;
  for (const m of list) {
    if (!best || (m[1] != null && (best[1] == null || Math.abs(m[1] - ts) < Math.abs(best[1] - ts)))) best = m;
  }
  return best;
}

function stepMatch(dir) {
  const at = anchorIndex();
  const m = dir > 0 ? view.matches.find((x) => x[0] > at) : view.matches.findLast((x) => x[0] < at);
  if (m) jumpTo(m[0], { open: true });
}

// ------------------------------------------------------------------ events

function nearestEvent({ ts, kind }) {
  let best = null;
  for (const ev of view.events) {
    if (ev[2] !== kind || ev[1] == null) continue;
    if (!best || Math.abs(ev[1] - ts) < Math.abs(best[1] - ts)) best = ev;
  }
  return best;
}

// The entry the reader is looking at: the last jump target while it is on screen,
// otherwise the first entry at the top of the viewport.
function anchorIndex() {
  const body = $("log-body");
  const top = body.getBoundingClientRect().top;
  const focused = view.focus != null && body.querySelector(`[data-i="${view.focus}"]`);
  if (focused) {
    const r = focused.getBoundingClientRect();
    if (r.bottom > top && r.top < top + body.clientHeight) return view.focus;
  }
  for (const el of body.querySelectorAll("[data-i]")) {
    if (el.getBoundingClientRect().bottom > top) return Number(el.dataset.i);
  }
  return -1;
}

// Jump to the next (+1) or previous (-1) event of `kind`, or of any kind when it is null.
function step(kind, dir) {
  const list = kind ? view.events.filter((ev) => ev[2] === kind) : view.events;
  const at = anchorIndex();
  const ev = dir > 0 ? list.find((x) => x[0] > at) : list.findLast((x) => x[0] < at);
  if (ev) jumpTo(ev[0]);
}

// `open` expands a tool call, to show the input or output that matched.
async function jumpTo(i, { open = false } = {}) {
  const token = view.token;
  while (view.entries.length <= i && view.entries.length < view.total) {
    await loadMore(Math.min(2000, Math.max(PAGE, i + 1 - view.entries.length)));
    if (token !== view.token) return;
  }
  // Tool results are drawn inside their call; otherwise fall back to the nearest drawn entry before i.
  const e = view.entries[i];
  if (e?.kind === "tool_result") {
    const use = view.entries.find((x) => x.kind === "tool_use" && x.id === e.tool_use_id);
    if (use) i = use.i;
  }
  const body = $("log-body");
  let el = body.querySelector(`[data-i="${i}"]`);
  if (!el) el = [...body.querySelectorAll("[data-i]")].filter((x) => Number(x.dataset.i) <= i).pop();
  if (!el) return;
  view.focus = Number(el.dataset.i);
  const details = open && el.querySelector("details");
  if (details && !details.open) details.open = true;
  body.querySelectorAll(".entry.flash").forEach((x) => x.classList.remove("flash"));
  el.scrollIntoView({ block: "center" });
  // Restart the animation even when jumping to the same entry twice.
  void el.offsetWidth;
  el.classList.add("flash");
  renderEventNav();
}

function renderEventNav() {
  const bar = $("log-events");
  const parts = MARK_KINDS.map(([kind, label]) => {
    const plural = `${label}s`;
    const list = view.events.filter((ev) => ev[2] === kind);
    if (!list.length) return null;
    const pos = list.findIndex((ev) => ev[0] === view.focus);
    const key = (k) => (kind === "prompt" ? ` (${k})` : "");
    return h("span", { class: "ev-nav" },
      h("i", { class: `mark-sample ${kind}` }),
      h("span", {}, `${plural} `, h("span", { class: "muted" }, pos >= 0 ? `${pos + 1}/${list.length}` : list.length)),
      h("button", { title: `Previous ${plural.toLowerCase()}${key("[")}`, onclick: () => step(kind, -1) }, "‹"),
      h("button", { title: `Next ${plural.toLowerCase()}${key("]")}`, onclick: () => step(kind, 1) }, "›"));
  }).filter(Boolean);
  if (view.query) {
    const pos = view.matches.findIndex((m) => m[0] === view.focus);
    parts.push(h("span", { class: "ev-nav", title: `Entries containing “${view.query}”` },
      h("i", { class: "mark-sample match" }),
      h("span", {}, "Matches ", h("span", { class: "muted" },
        pos >= 0 ? `${pos + 1}/${view.matches.length}` : view.matches.length)),
      h("button", { title: "Previous match", onclick: () => stepMatch(-1) }, "‹"),
      h("button", { title: "Next match", onclick: () => stepMatch(1) }, "›")));
  }
  bar.hidden = !parts.length;
  bar.replaceChildren(...parts);
}

// ------------------------------------------------------------------ stats

async function loadStats() {
  const panel = $("log-stats");
  panel.hidden = !$("log-stats-toggle").checked;
  if (panel.hidden || panel.dataset.token === String(view.token)) return;
  const token = view.token;
  panel.dataset.token = String(token);
  panel.replaceChildren(h("div", { class: "muted" }, "Loading stats…"));
  const params = new URLSearchParams();
  if (view.agent) params.set("agent", view.agent);
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(view.detail.id)}/stats?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const st = await res.json();
    if (token === view.token) renderStats(panel, st);
  } catch (err) {
    if (token === view.token) panel.replaceChildren(h("div", { class: "muted" }, `Failed to load stats: ${err.message}`));
  }
}

// "mcp__claude-in-chrome__computer" → "claude-in-chrome › computer"
function toolLabel(name) {
  const m = /^mcp__(.+?)__(.+)$/.exec(name);
  return m ? `${m[1]} › ${m[2]}` : name;
}

function tile(label, value, sub, title) {
  return h("div", { class: "tile", title: title || "" },
    h("div", { class: "k" }, label),
    h("div", { class: "v" }, value, sub ? h("small", {}, ` ${sub}`) : null));
}

function compactSizes(list) {
  const sized = (list || []).filter((c) => c.pre != null);
  return sized.map((c) => `${fmtTokens(c.pre)}→${fmtTokens(c.post)}`).join(", ");
}

function renderStats(panel, st) {
  const d = view.detail;
  const main = !view.agent;
  const t = st.tokens;
  const toolCalls = st.tools.reduce((n, x) => n + x.calls, 0);
  const toolErrors = st.tools.reduce((n, x) => n + x.errors, 0);
  // The main log's own cost excludes subagents; the session total comes from the detail.
  const subs = main ? d.subagents : [];
  const subCost = subs.reduce((n, a) => n + (a.cost || 0), 0);
  const subTokens = subs.reduce((n, a) => n + (a.tokens || 0), 0);

  const tiles = [
    tile("Span", fmtDuration(st.end - st.start), st.start ? `${fmtTime(st.start)}–${fmtTime(st.end)}` : "", st.start ? `${fmtDateTime(st.start)} – ${fmtDateTime(st.end)}` : ""),
    tile("Active time", fmtDuration(st.active_ms), "", `Gaps over ${st.idle_threshold_ms / 60000} minutes are not counted`),
    main ? tile("Prompts", st.prompts, st.commands ? `+ ${st.commands} commands` : "") : null,
    tile("API requests", st.requests, st.api_errors ? `${st.api_errors} errors` : ""),
    tile("Tool calls", toolCalls, toolErrors ? `${toolErrors} errors` : ""),
    st.interrupts ? tile("Interrupts", st.interrupts) : null,
    st.compactions ? tile("Compactions", st.compactions, compactSizes(st.compaction_sizes), "Context size before → after each compaction") : null,
    fmtEffortMix(st.efforts) ? tile("Effort", fmtEffortMix(st.efforts), "", "Share of API requests per effort level") : null,
    st.thinking_blocks ? tile("Thinking blocks", st.thinking_blocks) : null,
    tile("Input", fmtTokens(t.input), "tok"),
    tile("Output", fmtTokens(t.output), "tok"),
    tile("Cache read", fmtTokens(t.cache_read), "tok"),
    tile("Cache write", fmtTokens(t.cache_write), "tok"),
    st.cache_hit == null ? null : tile("Cache hit", fmtPct(st.cache_hit),
      st.cache_saved >= 0 ? `saved ${fmtCost(st.cache_saved, true)}` : `${fmtCost(-st.cache_saved, true)} extra`,
      cacheTitle(st.cache_hit, st.cache_saved)),
    tile(main && subs.length ? "Cost (this log)" : "Cost", fmtCost(st.cost, true), "", "Estimated from token usage"),
    main && subs.length ? tile("Subagents", subs.length, `${fmtTokens(subTokens)} tok · ${fmtCost(subCost, true)}`) : null,
    main ? tile("Session total", fmtCost(d.cost, d.cost_estimated), "", costTitle(d)) : null,
    main && d.cost_state && (d.cost_state.totalLinesAdded || d.cost_state.totalLinesRemoved)
      ? tile("Lines", `+${d.cost_state.totalLinesAdded} / −${d.cost_state.totalLinesRemoved}`) : null,
  ];

  const maxCalls = Math.max(1, ...st.tools.map((x) => x.calls));
  const num = (v) => h("td", { class: "num" }, v);
  const modelTable = h("div", {},
    h("table", {},
      h("thead", {}, h("tr", {}, ...["Model", "Requests", "Input", "Output", "Cache read", "Cache write", "Cost"].map((c, i) =>
        h("th", { class: i ? "num" : "" }, c)))),
      h("tbody", {}, ...st.models.map((m) => h("tr", {},
        h("td", { title: m.model }, shortModel(m.model)), num(m.requests), num(fmtTokens(m.input)), num(fmtTokens(m.output)),
        num(fmtTokens(m.cache_read)), num(fmtTokens(m.cache_write)), num(fmtCost(m.cost, true)))))));
  const toolTable = h("div", {},
    h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Tool"), h("th", { class: "num" }, "Calls"), h("th", { class: "num" }, "Errors"), h("th", {}))),
      h("tbody", {}, ...st.tools.map((x) => h("tr", {},
        h("td", { title: x.name }, toolLabel(x.name)), num(x.calls), h("td", { class: "num" + (x.errors ? " err" : "") }, x.errors || ""),
        h("td", { class: "bar-cell" }, h("div", { class: "hbar", style: { width: `${(100 * x.calls) / maxCalls}%` } })))))));

  panel.replaceChildren(
    h("div", { class: "tiles" }, ...tiles.filter(Boolean)),
    h("div", { class: "stats-tables" },
      st.models.length ? modelTable : null,
      st.tools.length ? toolTable : null));
}

export function closeLog() {
  $("log-modal").hidden = true;
  // A focused control would keep taking Enter while hidden.
  if ($("log-modal").contains(document.activeElement)) document.activeElement.blur();
  view.token++;
}

async function loadMore(limit = PAGE) {
  const token = view.token;
  // A jump may need pages while a scroll-triggered load is in flight: wait for it.
  while (view.loading) await new Promise((r) => setTimeout(r, 30));
  if (token !== view.token || (view.total && view.entries.length >= view.total)) return;
  view.loading = true;
  const params = new URLSearchParams({ offset: view.entries.length, limit });
  if (view.agent) params.set("agent", view.agent);
  if (view.query && !view.entries.length) params.set("q", view.query);
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(view.detail.id)}/log?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (token !== view.token) return;
    view.total = data.total;
    if (data.events) {
      view.events = data.events;
      view.matches = data.matches || [];
      renderEventNav();
    }
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
    node.dataset.i = e.i;
    if (e.event) node.classList.add(`ev-${e.event}`);
    if (e.event && e.event !== "prompt") {
      const label = MARK_KINDS.find(([k]) => k === e.event)[1];
      node.prepend(h("span", { class: `ev-badge ${e.event}` }, label));
    }
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
      if (e.event) {
        const detail = compactDetail(e);
        return h("div", { class: "entry compact" }, detail ? `— context compacted (${detail}) —` : e.text);
      }
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
