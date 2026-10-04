// Entry point: state, data loading, filters, list view, live updates.
import { renderCalendar } from "./calendar.js";
import { renderDetail } from "./detail.js";
import { overviewRange, renderOverview } from "./overview.js";
import { openLog } from "./transcript.js";
import {
  CACHE_LOW, EFFORT_COLORS, MIN_HOUR_PX, STATUS_HINTS, STATUS_LABELS, addDays, cacheTitle, fmtAgo, fmtCost, fmtDateTime,
  fmtDuration, fmtPct, fmtTokens, h, matchSnippet, paletteColor,
  prefs, shortModel, startOfDay, startOfWeek, statusColor,
} from "./util.js";

const $ = (id) => document.getElementById(id);
const DEFAULT_HOUR_PX = 42;
const MAX_HOUR_PX = 240;

export const state = {
  sessions: [],
  byId: new Map(),
  view: prefs.get("view", "calendar"),
  span: prefs.get("span", "week"), // "day" | "week" | "month" | "year"
  heat: prefs.get("heat", "time"), // month and year shading: "time" | "cost"
  anchor: startOfDay(new Date()), // any day inside the displayed range
  hourPx: prefs.get("hourPx", DEFAULT_HOUR_PX),
  colorBy: prefs.get("colorBy", "project"),
  gap: prefs.get("gap", 15),
  search: "",
  projects: new Set(prefs.get("projects", [])), // empty = all
  statuses: new Set(prefs.get("statuses", Object.keys(STATUS_LABELS))),
  hideNoPrompt: prefs.get("hideNoPrompt", true),
  sort: prefs.get("listSort", { key: "start", dir: "desc" }),
  showSummary: prefs.get("summary", false),
  showMarks: prefs.get("marks", true),
  selectedId: null,
  projectColors: new Map(),
  modelColors: new Map(),
};

// ------------------------------------------------------------------ data

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  return res.json();
}

async function loadSessions() {
  const data = await fetchJSON(`/api/sessions?gap=${state.gap}`);
  state.sessions = data.sessions;
  state.byId = new Map(data.sessions.map((s) => [s.id, s]));
  assignColors();
  renderAll();
}

function assignColors() {
  const count = (key) => {
    const m = new Map();
    for (const s of state.sessions) m.set(s[key], (m.get(s[key]) || 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]).map(([k]) => k);
  };
  state.projectColors = new Map(count("project").map((p, i) => [p, paletteColor(i)]));
  state.modelColors = new Map(count("model").map((m, i) => [m, paletteColor(i + 2)]));
}

// Fixed thresholds so a color means the same amount in every week.
const COST_BANDS = [
  { max: 1, label: "< $1", color: "#7d8ea3" },
  { max: 5, label: "$1–5", color: "#d4b02a" },
  { max: 20, label: "$5–20", color: "#e8801a" },
  { max: 50, label: "$20–50", color: "#d63a2f" },
  { max: Infinity, label: "≥ $50", color: "#8e1b5e" },
];

function costBand(s) {
  return COST_BANDS.findIndex((b) => (s.cost || 0) < b.max);
}

export function colorFor(s) {
  if (state.colorBy === "cost") return COST_BANDS[costBand(s)].color;
  if (state.colorBy === "status") return statusColor(s.status);
  if (state.colorBy === "model") return state.modelColors.get(s.model) || "#888";
  if (state.colorBy === "effort") return EFFORT_COLORS[s.effort] || "#888";
  return state.projectColors.get(s.project) || "#888";
}

export function legendItems(visible) {
  const counts = new Map();
  for (const s of visible) {
    let key, label, color;
    if (state.colorBy === "cost") {
      key = costBand(s); label = COST_BANDS[key].label; color = COST_BANDS[key].color;
    } else if (state.colorBy === "status") {
      key = s.status; label = STATUS_LABELS[s.status]; color = statusColor(s.status);
    } else if (state.colorBy === "model") {
      key = s.model; label = shortModel(s.model); color = colorFor(s);
    } else if (state.colorBy === "effort") {
      key = s.effort || ""; label = s.effort || "unknown"; color = colorFor(s);
    } else {
      key = s.project; label = s.project_name; color = colorFor(s);
    }
    const e = counts.get(key) || { label, color, n: 0, title: key };
    e.n++;
    counts.set(key, e);
  }
  if (state.colorBy === "effort") {
    const rank = (k) => { const i = Object.keys(EFFORT_COLORS).indexOf(k); return i < 0 ? 99 : i; };
    return [...counts.entries()].sort((a, b) => rank(a[0]) - rank(b[0])).map(([, e]) => ({ ...e, title: "Effort most API requests ran at" }));
  }
  if (state.colorBy === "cost") {
    return [...counts.entries()].sort((a, b) => a[0] - b[0]).map(([, e]) => ({ ...e, title: "" }));
  }
  return [...counts.values()].sort((a, b) => b.n - a.n);
}

export function filtered() {
  const q = state.search.trim().toLowerCase();
  return state.sessions.filter((s) => {
    if (state.hideNoPrompt && s.prompt_count === 0) return false;
    if (!state.statuses.has(s.status)) return false;
    if (state.projects.size && !state.projects.has(s.project)) return false;
    if (q && !s.search.toLowerCase().includes(q)) return false;
    return true;
  });
}

// ------------------------------------------------------------------ selection

export async function select(id) {
  state.selectedId = id;
  document.querySelectorAll(".bar.selected, tr.selected").forEach((el) => el.classList.remove("selected"));
  document.querySelectorAll(`[data-sid="${id}"]`).forEach((el) => el.classList.add("selected"));
  await refreshDetail();
}

// Select the session and open its log at the event closest to `ts`.
async function openEvent(id, ts, kind) {
  await select(id);
  if (state.detail?.id === id) openLog(state.detail, null, { ts, kind });
}

async function refreshDetail() {
  const pane = $("detail");
  if (!state.selectedId) {
    pane.hidden = true;
    return;
  }
  pane.hidden = false;
  try {
    const d = await fetchJSON(`/api/sessions/${state.selectedId}?gap=${state.gap}`);
    if (d.id !== state.selectedId) return;
    state.detail = d;
    renderDetail(pane, d, {
      onClose: () => { state.selectedId = null; refreshDetail(); renderMain(); },
      onOpenLog: (agent, target) => openLog(d, agent, target),
      onSelect: (sid) => select(sid),
    });
  } catch (e) {
    pane.replaceChildren(h("div", { class: "empty" }, "Session not found."));
  }
}

// ------------------------------------------------------------------ rendering

function renderAll() {
  renderToolbar();
  renderMain();
}

function renderMain() {
  $("calendar-view").hidden = state.view !== "calendar";
  $("list-view").hidden = state.view !== "list";
  const visible = filtered();
  const overview = state.span === "month" || state.span === "year";
  // Month and year cells are shaded by time or cost, so bar zoom and colors do not apply.
  for (const id of ["zoom", "color-by", "color-by-label"]) $(id).hidden = overview;
  if (state.view === "calendar" && overview) {
    renderOverview($("calendar"), visible, {
      legend: $("legend"),
      rangeLabel: $("range-label"),
      rangeCount: $("range-count"),
      summaryPane: $("summary"),
      rerender: renderMain,
    });
  } else if (state.view === "calendar") {
    renderCalendar($("calendar"), visible, {
      onSelect: select,
      onOpenEvent: openEvent,
      legend: $("legend"),
      rangeLabel: $("range-label"),
      rangeCount: $("range-count"),
      summaryPane: $("summary"),
      onToggleMarks: () => {
        state.showMarks = !state.showMarks;
        prefs.set("marks", state.showMarks);
        renderMain();
      },
    });
  } else {
    renderList(visible);
  }
}

function renderToolbar() {
  document.querySelectorAll("#view-toggle button").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === state.view));
  document.querySelectorAll("#color-by button").forEach((b) =>
    b.classList.toggle("active", b.dataset.color === state.colorBy));
  document.querySelectorAll("#span-toggle button").forEach((b) =>
    b.classList.toggle("active", b.dataset.span === state.span));
  $("go-today").textContent = { day: "Today", week: "This week", month: "This month", year: "This year" }[state.span];
  $("summary-toggle").classList.toggle("active", state.showSummary);
  $("gap").value = String(state.gap);
  $("hide-noprompt").checked = state.hideNoPrompt;

  const counts = {};
  for (const s of state.sessions) {
    if (state.hideNoPrompt && s.prompt_count === 0) continue;
    counts[s.status] = (counts[s.status] || 0) + 1;
  }
  $("status-chips").replaceChildren(
    ...Object.entries(STATUS_LABELS).map(([key, label]) =>
      h("button", {
        class: "chip" + (state.statuses.has(key) ? "" : " off"),
        title: `${STATUS_HINTS[key]}. Click to toggle.`,
        onclick: () => {
          state.statuses.has(key) ? state.statuses.delete(key) : state.statuses.add(key);
          prefs.set("statuses", [...state.statuses]);
          renderAll();
        },
      }, h("span", { class: "dot", style: { background: statusColor(key) } }), `${label} ${counts[key] || 0}`)),
  );

  const n = state.projects.size;
  $("project-btn").textContent = n ? `${n} project${n > 1 ? "s" : ""} ▾` : "All projects ▾";
}

function renderProjectMenu() {
  const menu = $("project-menu");
  const projects = new Map();
  for (const s of state.sessions) {
    const e = projects.get(s.project) || { name: s.project_name, n: 0 };
    e.n++;
    projects.set(s.project, e);
  }
  const entries = [...projects.entries()].sort((a, b) => b[1].n - a[1].n);
  const save = () => { prefs.set("projects", [...state.projects]); renderAll(); };
  menu.replaceChildren(
    h("div", { class: "actions" },
      h("button", { onclick: () => { state.projects.clear(); save(); renderProjectMenu(); } }, "All"),
    ),
    ...entries.map(([path, e]) =>
      h("label", { title: path },
        h("input", {
          type: "checkbox",
          checked: state.projects.has(path),
          onchange: (ev) => {
            ev.target.checked ? state.projects.add(path) : state.projects.delete(path);
            save();
          },
        }),
        h("span", { class: "dot", style: { background: state.projectColors.get(path) } }),
        `${e.name} `, h("span", { class: "muted" }, `(${e.n})`))),
  );
}

const STATUS_ORDER = Object.keys(STATUS_LABELS);

// [key, header, sort value, first direction when clicked, numeric column?]
const LIST_COLUMNS = [
  ["status", "", (s) => STATUS_ORDER.indexOf(s.status), "asc", false],
  ["title", "Title", (s) => s.title.toLowerCase(), "asc", false],
  ["project", "Project", (s) => s.project_name.toLowerCase(), "asc", false],
  ["start", "Started", (s) => s.start, "desc", true],
  ["end", "Last activity", (s) => s.end, "desc", true],
  ["length", "Length", (s) => s.end - s.start, "desc", true],
  ["prompts", "Prompts", (s) => s.prompt_count, "desc", true],
  ["tokens", "Tokens", (s) => s.tokens, "desc", true],
  ["cost", "Cost", (s) => s.cost, "desc", true],
  ["cache", "Cache", (s) => s.cache_hit, "asc", true],
];

function sortRows(rows) {
  const col = LIST_COLUMNS.find((c) => c[0] === state.sort.key) || LIST_COLUMNS[3];
  const value = col[2];
  const sign = state.sort.dir === "asc" ? 1 : -1;
  const start = (s) => s.start || 0;
  return [...rows].sort((a, b) => {
    const x = value(a);
    const y = value(b);
    if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1; // missing values last
    const c = typeof x === "string" ? x.localeCompare(y) : x - y;
    return sign * c || start(b) - start(a);
  });
}

function setSort(key) {
  const col = LIST_COLUMNS.find((c) => c[0] === key);
  const dir = state.sort.key === key ? (state.sort.dir === "asc" ? "desc" : "asc") : col[3];
  state.sort = { key, dir };
  prefs.set("listSort", state.sort);
  renderMain();
}

function renderList(visible) {
  const rows = sortRows(visible);
  $("list-count").textContent = `${rows.length} sessions`;
  if (!rows.length) {
    $("list").replaceChildren(h("div", { class: "empty" }, "No sessions match the filters."));
    return;
  }
  const header = LIST_COLUMNS.map(([key, label, , , numeric]) => {
    const sorted = state.sort.key === key;
    return h("th", {
      class: ["sortable", numeric ? "num" : "", sorted ? "sorted" : ""].join(" ").trim(),
      title: key === "status" ? "Sort by status" : key === "cache" ? "Sort by cache hit rate" : `Sort by ${label.toLowerCase()}`,
      onclick: () => setSort(key),
    }, label, sorted ? (state.sort.dir === "asc" ? " ▲" : " ▼") : "");
  });
  $("list").replaceChildren(
    h("table", {},
      h("thead", {}, h("tr", {}, ...header)),
      h("tbody", {}, rows.map((s) =>
        h("tr", {
          "data-sid": s.id,
          class: s.id === state.selectedId ? "selected" : "",
          onclick: () => select(s.id),
        },
          h("td", {}, h("span", { class: "dot", title: STATUS_LABELS[s.status], style: { background: statusColor(s.status) } })),
          h("td", { class: "title-cell" }, s.title, matchSnippet(s, state.search)),
          h("td", { title: s.project }, h("span", { class: "dot", style: { background: state.projectColors.get(s.project), marginRight: "5px" } }), s.project_name),
          h("td", { class: "num" }, fmtDateTime(s.start)),
          h("td", { class: "num", title: fmtDateTime(s.end) }, fmtAgo(s.end)),
          h("td", { class: "num" }, fmtDuration(s.end - s.start)),
          h("td", { class: "num" }, s.prompt_count),
          h("td", { class: "num" }, fmtTokens(s.tokens)),
          h("td", { class: "num" }, fmtCost(s.cost, s.cost_estimated)),
          h("td", { class: "num" + (s.cache_hit != null && s.cache_hit < CACHE_LOW ? " warn" : ""), title: cacheTitle(s.cache_hit, s.cache_saved) },
            fmtPct(s.cache_hit)),
        ))),
    ),
  );
}

// ------------------------------------------------------------------ controls

export function rangeDays() {
  if (state.span === "day") return [startOfDay(state.anchor)];
  if (state.span === "month" || state.span === "year") {
    const [first, end] = overviewRange(state.span, state.anchor);
    const days = [];
    for (let d = first; d < end; d = addDays(d, 1)) days.push(d);
    return days;
  }
  const start = startOfWeek(state.anchor);
  return [...Array(7)].map((_, i) => addDays(start, i));
}

function setSpan(span, day) {
  state.span = span;
  if (day) state.anchor = startOfDay(day);
  prefs.set("span", span);
  renderAll();
}

export function openDay(day) {
  setSpan("day", day);
}

export function openMonth(day) {
  setSpan("month", day);
}

// Move the displayed range back (-1) or forward (+1) by one day, week, month or year.
function shift(dir) {
  const a = state.anchor;
  if (state.span === "month") state.anchor = new Date(a.getFullYear(), a.getMonth() + dir, 1);
  else if (state.span === "year") state.anchor = new Date(a.getFullYear() + dir, 0, 1);
  else state.anchor = addDays(a, dir * (state.span === "day" ? 1 : 7));
  renderMain();
}

function setHourPx(px) {
  state.hourPx = Math.max(MIN_HOUR_PX, Math.min(MAX_HOUR_PX, Math.round(px)));
  prefs.set("hourPx", state.hourPx);
  renderMain();
}

function bind() {
  document.querySelectorAll("#view-toggle button").forEach((b) =>
    b.addEventListener("click", () => {
      state.view = b.dataset.view;
      prefs.set("view", state.view);
      renderAll();
    }));
  document.querySelectorAll("#color-by button").forEach((b) =>
    b.addEventListener("click", () => {
      state.colorBy = b.dataset.color;
      prefs.set("colorBy", state.colorBy);
      renderAll();
    }));
  document.querySelectorAll("#span-toggle button").forEach((b) =>
    b.addEventListener("click", () => setSpan(b.dataset.span)));
  $("go-today").onclick = () => { state.anchor = startOfDay(new Date()); renderMain(); };
  $("go-prev").onclick = () => shift(-1);
  $("go-next").onclick = () => shift(1);
  $("summary-toggle").onclick = () => {
    state.showSummary = !state.showSummary;
    prefs.set("summary", state.showSummary);
    renderAll();
  };
  $("zoom-in").onclick = () => setHourPx(state.hourPx * 1.25);
  $("zoom-out").onclick = () => setHourPx(state.hourPx / 1.25);
  $("zoom-reset").onclick = () => setHourPx(DEFAULT_HOUR_PX);
  $("calendar").addEventListener("wheel", (e) => {
    if ((!e.ctrlKey && !e.metaKey) || $("zoom").hidden) return;
    e.preventDefault();
    setHourPx(state.hourPx * (e.deltaY < 0 ? 1.1 : 1 / 1.1));
  }, { passive: false });
  $("gap").onchange = (e) => {
    state.gap = Number(e.target.value);
    prefs.set("gap", state.gap);
    loadSessions();
  };
  $("hide-noprompt").onchange = (e) => {
    state.hideNoPrompt = e.target.checked;
    prefs.set("hideNoPrompt", state.hideNoPrompt);
    renderAll();
  };
  let searchTimer;
  $("search").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { state.search = e.target.value; renderMain(); }, 150);
  });
  $("reload").onclick = () => { loadSessions(); refreshDetail(); };
  $("project-btn").onclick = (e) => {
    e.stopPropagation();
    const menu = $("project-menu");
    menu.hidden = !menu.hidden;
    if (!menu.hidden) renderProjectMenu();
  };
  document.addEventListener("click", (e) => {
    if (!$("project-filter").contains(e.target)) $("project-menu").hidden = true;
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && $("log-modal").hidden && state.selectedId) {
      state.selectedId = null;
      refreshDetail();
      renderMain();
    }
  });
}

// ------------------------------------------------------------------ live updates

function connectEvents() {
  const indicator = $("live-indicator");
  const es = new EventSource("/api/events");
  let timer = null;
  es.onopen = () => indicator.classList.remove("off");
  es.onerror = () => indicator.classList.add("off");
  es.onmessage = (ev) => {
    const payload = JSON.parse(ev.data);
    clearTimeout(timer);
    // Coalesce bursts of writes from busy sessions.
    timer = setTimeout(async () => {
      await loadSessions();
      if (state.selectedId && (payload.live || payload.sessions.includes(state.selectedId))) {
        refreshDetail();
      }
    }, 300);
  };
}

// Keep "now" line and relative times fresh even when nothing is written.
setInterval(() => { if (state.view === "calendar") renderMain(); }, 60_000);

bind();
loadSessions().catch((e) => {
  $("calendar").replaceChildren(h("div", { class: "empty" }, `Failed to load sessions: ${e.message}`));
});
connectEvents();
