// Shared helpers: formatting, colors, DOM, persistence.

export const STATUS_LABELS = {
  running: "Running",
  waiting: "Waiting",
  done: "Done",
  interrupted: "Interrupted",
};

// Smallest calendar zoom, in pixels per hour.
export const MIN_HOUR_PX = 12;

export const STATUS_HINTS = {
  running: "Claude Code is working on this session right now",
  waiting: "Claude Code is open and waiting for your input",
  done: "The last turn finished and nothing was left running",
  interrupted: "The session ended mid-turn, was stopped with Esc, or left background work unfinished",
};

export function statusColor(status) {
  return getComputedStyle(document.documentElement).getPropertyValue(`--${status}`).trim() || "#888";
}

// Categorical palette that stays readable with white text in both themes.
const PALETTE = [
  "#7c5cd6", "#d08a1c", "#2f80ed", "#2e9d5b", "#d64545", "#1597a5",
  "#b9478f", "#6b8e23", "#8d6e63", "#4b6cb7", "#c2571a", "#5f7c8a",
];

export function paletteColor(index) {
  return PALETTE[index % PALETTE.length];
}

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === undefined || c === null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function fmtTokens(n) {
  if (!n) return "0";
  if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(n);
}

export function fmtCost(cost, estimated) {
  if (cost == null) return "–";
  const s = "$" + (cost >= 100 ? cost.toFixed(0) : cost.toFixed(2));
  return estimated ? "~" + s : s;
}

// Below this cache hit rate a session is flagged as reusing its cache poorly.
export const CACHE_LOW = 0.9;

export function fmtPct(ratio) {
  return ratio == null ? "–" : `${Math.round(ratio * 100)}%`;
}

export function cacheTitle(hit, saved) {
  if (hit == null) return "No input tokens";
  const effect = saved >= 0 ? `saved ${fmtCost(saved, true)}` : `cost ${fmtCost(-saved, true)} extra`;
  return `Cache reads are ${fmtPct(hit)} of input tokens. Caching ${effect} compared with no caching (cache write premium included).`;
}

export function fmtDuration(ms) {
  if (ms == null || ms < 0) return "–";
  const m = Math.round(ms / 60000);
  if (m < 60) return `${m}m`;
  const hrs = Math.floor(m / 60);
  if (hrs < 24) return `${hrs}h ${m % 60}m`;
  return `${Math.floor(hrs / 24)}d ${hrs % 24}h`;
}

export function fmtTime(ms) {
  if (ms == null) return "–";
  return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function fmtDateTime(ms) {
  if (ms == null) return "–";
  return new Date(ms).toLocaleString([], {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export function fmtAgo(ms) {
  if (ms == null) return "–";
  const d = Date.now() - ms;
  if (d < 60000) return "just now";
  if (d < 3600000) return `${Math.round(d / 60000)}m ago`;
  if (d < 86400000) return `${Math.round(d / 3600000)}h ago`;
  return fmtDateTime(ms);
}

export function startOfDay(date) {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d;
}

export function startOfWeek(date) {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  const dow = (d.getDay() + 6) % 7; // Monday = 0
  d.setDate(d.getDate() - dow);
  return d;
}

export function addDays(date, n) {
  const d = new Date(date);
  d.setDate(d.getDate() + n);
  return d;
}

export function shortModel(model) {
  if (!model) return "unknown";
  return model.replace(/^claude-/, "").replace(/-\d{8}$/, "");
}

export const prefs = {
  get(key, fallback) {
    try {
      const v = localStorage.getItem("cc-calendar:" + key);
      return v === null ? fallback : JSON.parse(v);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem("cc-calendar:" + key, JSON.stringify(value));
    } catch {
      /* storage unavailable */
    }
  },
};

const SNIPPET_CONTEXT = 40;

// When a search matches a prompt rather than the title, show where it matched.
// The text the search box matches: note, tags, title and prompts.
export function searchText(s) {
  return [s.note || "", ...(s.tags || []), s.search].join(" ");
}

// Tags as chips, or null when there are none.
export function tagChips(tags) {
  return tags?.length ? h("span", { class: "tags" }, tags.map((t) => h("span", { class: "tag" }, t))) : null;
}

export function matchSnippet(s, query) {
  const q = query.trim().toLowerCase();
  if (!q || s.title.toLowerCase().includes(q)) return null;
  const text = searchText(s).replace(/\s+/g, " ");
  const i = text.toLowerCase().indexOf(q);
  if (i < 0) return null;
  const from = Math.max(0, i - SNIPPET_CONTEXT);
  const to = Math.min(text.length, i + q.length + SNIPPET_CONTEXT);
  return h("div", { class: "snippet" },
    from > 0 ? "…" : "", text.slice(from, i),
    h("mark", {}, text.slice(i, i + q.length)),
    text.slice(i + q.length, to), to < text.length ? "…" : "");
}

// What a full-text hit is, e.g. "Bash call", "Tool output", "Subagent reply".
const HIT_KINDS = {
  prompt: "Prompt", assistant: "Reply", tool_use: "Tool call", tool_result: "Tool output",
  error: "API error", notification: "Background task",
};

function hitLabel(hit) {
  const label = hit.kind === "tool_use" && hit.name ? `${hit.name} call` : HIT_KINDS[hit.kind] || hit.kind;
  return hit.agent ? `Subagent ${label[0].toLowerCase()}${label.slice(1)}` : label;
}

// A full-text search hit: where and when it matched, and the text around it. `onOpen` adds a
// button that opens the log there.
export function hitSnippet(hit, onOpen = null) {
  const { before, match, after } = hit.snippet;
  // The main log does not show matches in subagent logs, so say how many are there.
  const sub = hit.in_subagents || 0;
  let more = hit.count > 1 ? ` · ${hit.count} matches` : "";
  if (hit.count > 1 && sub === hit.count) more += " in subagents";
  else if (sub > 0 && sub < hit.count) more += ` (${sub} in subagent${sub > 1 ? "s" : ""})`;
  return h("div", { class: "snippet" },
    h("span", { class: "hit-meta" }, `${hitLabel(hit)}${hit.ts ? " · " + fmtDateTime(hit.ts) : ""}${more}: `),
    before, match ? h("mark", {}, match) : null, after,
    onOpen ? h("button", {
      class: "log-link hit-open",
      title: "Open the log at this match",
      onclick: (e) => { e.stopPropagation(); onOpen(); },
    }, "Open ↗") : null);
}

// Images in a transcript can point at any host. Strip their URLs while sanitizing (in an inert
// document, so nothing is fetched) and show them as links instead; the server's
// Content-Security-Policy blocks whatever else slips through.
if (window.DOMPurify) {
  window.DOMPurify.addHook("afterSanitizeAttributes", (node) => {
    if (node.nodeName !== "IMG") return;
    const src = node.getAttribute("src") || "";
    node.removeAttribute("srcset");
    if (src.startsWith("data:image/")) return;
    node.removeAttribute("src");
    node.setAttribute("data-remote-src", src);
  });
}

function remoteImageLink(img) {
  const src = img.dataset.remoteSrc;
  const label = `Image: ${img.getAttribute("alt") || src || "no address"}`;
  const title = "Remote image, not loaded";
  if (!/^https?:\/\//i.test(src)) return h("span", { class: "remote-img", title }, label);
  return h("a", { class: "remote-img", href: src, target: "_blank", rel: "noopener noreferrer", title: `${title}: ${src}` }, label);
}

export function renderMarkdown(text) {
  const div = h("div", { class: "md" });
  if (window.marked && window.DOMPurify) {
    div.innerHTML = window.DOMPurify.sanitize(window.marked.parse(text, { breaks: true }));
    for (const img of div.querySelectorAll("img[data-remote-src]")) img.replaceWith(remoteImageLink(img));
  } else {
    div.style.whiteSpace = "pre-wrap";
    div.textContent = text;
  }
  return div;
}

export const MARK_KINDS = [
  // [kind, label, noun in running text]
  ["prompt", "Prompt", "prompt"],
  ["commit", "Commit", "commit"],
  ["compact", "Compaction", "compaction"],
  ["error", "API error", "API error"],
];

// Effort levels, highest first, with fixed colors for "Color by Effort".
export const EFFORT_COLORS = {
  max: "#5b2a86",
  xhigh: "#8e1b5e",
  high: "#d63a2f",
  medium: "#e8801a",
  low: "#4a90c2",
};

// {high: 30, low: 10} → "high 75% · low 25%"; a single level is shown bare.
export function fmtEffortMix(mix) {
  const total = Object.values(mix || {}).reduce((n, v) => n + v, 0);
  if (!total) return "";
  if (Object.keys(mix).length === 1) return Object.keys(mix)[0];
  return Object.entries(mix).map(([e, n]) => `${e} ${Math.round((100 * n) / total)}%`).join(" · ");
}

// Compaction details: "auto · 168k → 32k tokens"
export function compactDetail(c) {
  const size = c?.pre != null ? `${fmtTokens(c.pre)}${c.post != null ? ` → ${fmtTokens(c.post)}` : ""} tokens` : "";
  return [c?.trigger, size].filter(Boolean).join(" · ");
}
