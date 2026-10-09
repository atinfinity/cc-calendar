// Entry point: state, data loading, filters, list view, live updates.
import { renderCalendar } from "./calendar.js";
import { renderCostsPane } from "./costspane.js";
import { frictionParts, renderDetail } from "./detail.js";
import { exportSessions } from "./export.js";
import { EMPTY_FILTER, activeFilterCount, matchesListFilter, renderListFilters } from "./listfilter.js";
import { bindNotifyToggle, checkTransitions } from "./notify.js";
import { overviewRange, renderOverview } from "./overview.js";
import { renderProject } from "./project.js";
import { buildReport, buildRetrospective, copyText } from "./report.js";
import { costPer } from "./summary.js";
import { bloatTitle } from "./contextchart.js";
import { bindShortcuts } from "./shortcuts.js";
import { renderRequestsPane } from "./requestspane.js";
import { renderPrs as renderPrsPane } from "./prspane.js";
import { renderToolsPane } from "./toolspane.js";
import { renderHoursPane } from "./hours.js";
import { closeLog, openLog } from "./transcript.js";
import { majorChange, readHash, stateHash } from "./urlstate.js";
import {
  CACHE_LOW, EFFORT_COLORS, MIN_HOUR_PX, STATUS_HINTS, STATUS_LABELS, addDays, cacheTitle, fmtAgo, fmtCost, fmtDateTime,
  fmtDuration, fmtPct, fmtTokens, h, hitSnippet, matchSnippet, RATINGS, ratingBadge, paletteColor,
  prefs, searchText, shortModel, startOfDay, startOfWeek, statusColor, tagChips,
} from "./util.js";

const $ = (id) => document.getElementById(id);
const DEFAULT_HOUR_PX = 42;
const MAX_HOUR_PX = 240;

export const state = {
  sessions: [],
  byId: new Map(),
  view: prefs.get("view", "calendar"),
  span: prefs.get("span", "week"), // "day" | "week" | "month" | "year"
  heat: prefs.get("heat", "time"), // month, year and Hours shading: "time" | "cost" | "commits"
  anchor: startOfDay(new Date()), // any day inside the displayed range
  hourPx: prefs.get("hourPx", DEFAULT_HOUR_PX),
  colorBy: prefs.get("colorBy", "project"),
  gap: prefs.get("gap", 15),
  search: "",
  fullText: prefs.get("fullText", false), // also search the transcripts on the server
  ft: null, // the last full-text result: {query, hits: Map(id → hit), pending}, or {error}
  projects: new Set(prefs.get("projects", [])), // empty = all
  statuses: new Set(prefs.get("statuses", Object.keys(STATUS_LABELS))),
  hideNoPrompt: prefs.get("hideNoPrompt", true),
  sort: prefs.get("listSort", { key: "start", dir: "desc" }),
  listFilter: { ...EMPTY_FILTER, ...prefs.get("listFilter", {}) }, // list view only
  showSummary: prefs.get("summary", false),
  compareRanges: prefs.get("compareRanges", false), // Summary: compare with the previous range
  showTools: prefs.get("tools", false),
  showCosts: prefs.get("costs", false),
  showRequests: prefs.get("requests", false),
  showPrs: prefs.get("prs", false),
  highlightPr: null, // PR URL to select in the project page's Pull requests table
  showHours: prefs.get("hours", false),
  appVersion: null, // cc-calendar version reported by the server
  dataVersion: 0, // bumped on every reload so cached aggregates refresh
  showMarks: prefs.get("marks", true),
  selectedId: null,
  project: null, // path of the project whose page is open, or null
  projectColors: new Map(),
  modelColors: new Map(),
  claudeDirs: [], // [{name, path}] of the config directories being read
  sourceColors: new Map(),
  tagColors: new Map(),
  tags: [], // [{tag, count}] of every tag in use, most used first
  notesError: null, // why the notes file could not be read, if it could not
};

// Which config directory a session came from only matters when there are several.
export function multiSource() {
  return state.claudeDirs.length > 1;
}

// The saved choice stays "source" across a single-directory run, but colors by project there;
// likewise "tag" while no session has a tag.
export function colorMode() {
  if (state.colorBy === "source" && !multiSource()) return "project";
  if (state.colorBy === "tag" && !state.tags.length) return "project";
  return state.colorBy;
}

const UNTAGGED_COLOR = "#9aa0a6";

// Likewise, a saved source filter is ignored while only one directory is read.
function listFilter() {
  return multiSource() ? state.listFilter : { ...state.listFilter, source: "" };
}

// ------------------------------------------------------------------ data

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  return res.json();
}

// The version of the running server, which can differ from what is installed until it restarts.
function showVersion(version) {
  const badge = document.getElementById("app-version");
  badge.textContent = version ? `v${version}` : "";
  badge.title = version ? `cc-calendar ${version} is running` : "";
  document.getElementById("help-version").textContent = version ? `cc-calendar ${version}` : "";
}

async function loadSessions() {
  const data = await fetchJSON(`/api/sessions?gap=${state.gap}`);
  state.sessions = data.sessions;
  state.appVersion = data.version;
  showVersion(data.version);
  state.claudeDirs = data.claude_dirs || [];
  state.tags = data.tags || [];
  state.notesError = data.notes_error || null;
  state.byId = new Map(data.sessions.map((s) => [s.id, s]));
  state.dataVersion++;
  const first = !loaded;
  loaded = true;
  if (first) dropUnknown();
  assignColors();
  renderAll();
  if (first) {
    restoring = false;
    await refreshDetail();
    document.querySelector(`[data-sid="${state.selectedId}"]`)?.scrollIntoView({ block: "nearest" });
  }
  checkTransitions(data.sessions, select);
}

function assignColors() {
  const count = (key) => {
    const m = new Map();
    for (const s of state.sessions) m.set(s[key], (m.get(s[key]) || 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]).map(([k]) => k);
  };
  state.projectColors = new Map(count("project").map((p, i) => [p, paletteColor(i)]));
  state.modelColors = new Map(count("model").map((m, i) => [m, paletteColor(i + 2)]));
  state.sourceColors = new Map(state.claudeDirs.map((d, i) => [d.name, paletteColor(i)]));
  // state.tags is already most used first.
  state.tagColors = new Map(state.tags.map((t, i) => [t.tag, paletteColor(i)]));
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
  const mode = colorMode();
  if (mode === "cost") return COST_BANDS[costBand(s)].color;
  if (mode === "status") return statusColor(s.status);
  if (mode === "model") return state.modelColors.get(s.model) || "#888";
  if (mode === "effort") return EFFORT_COLORS[s.effort] || "#888";
  if (mode === "source") return state.sourceColors.get(s.source) || "#888";
  // A session with several tags takes its first one's color.
  if (mode === "tag") return s.tags.length ? state.tagColors.get(s.tags[0]) || "#888" : UNTAGGED_COLOR;
  return state.projectColors.get(s.project) || "#888";
}

function sourcePath(name) {
  return state.claudeDirs.find((d) => d.name === name)?.path || name;
}

export function legendItems(visible) {
  const mode = colorMode();
  const counts = new Map();
  for (const s of visible) {
    let key, label, color;
    if (mode === "cost") {
      key = costBand(s); label = COST_BANDS[key].label; color = COST_BANDS[key].color;
    } else if (mode === "status") {
      key = s.status; label = STATUS_LABELS[s.status]; color = statusColor(s.status);
    } else if (mode === "model") {
      key = s.model; label = shortModel(s.model); color = colorFor(s);
    } else if (mode === "effort") {
      key = s.effort || ""; label = s.effort || "unknown"; color = colorFor(s);
    } else if (mode === "source") {
      key = sourcePath(s.source); label = s.source; color = colorFor(s);
    } else if (mode === "tag") {
      key = s.tags[0] ?? ""; label = s.tags[0] ?? "(untagged)"; color = colorFor(s);
    } else {
      key = s.project; label = s.project_name; color = colorFor(s);
    }
    const e = counts.get(key) || { label, color, n: 0, title: key };
    e.n++;
    counts.set(key, e);
  }
  if (mode === "effort") {
    const rank = (k) => { const i = Object.keys(EFFORT_COLORS).indexOf(k); return i < 0 ? 99 : i; };
    return [...counts.entries()].sort((a, b) => rank(a[0]) - rank(b[0])).map(([, e]) => ({ ...e, title: "Effort most API requests ran at" }));
  }
  if (mode === "tag") {
    // Untagged last; the color follows the first tag of sessions with several.
    return [...counts.entries()].sort((a, b) => (a[0] === "") - (b[0] === "") || b[1].n - a[1].n)
      .map(([k, e]) => ({ ...e, title: k ? "Sessions whose first tag is this one" : "Sessions without tags" }));
  }
  if (mode === "cost") {
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
    if (q && !searchText(s).toLowerCase().includes(q) && !ftHit(s)) return false;
    return true;
  });
}

// ------------------------------------------------------------------ full-text search

const FT_MIN = 3; // the index matches substrings of at least three characters
const FT_POLL_MS = 2000;
let ftToken = 0;
let ftTimer = null;

// The full-text hit for a session under the current query, or null.
export function ftHit(s) {
  const ft = state.ft;
  if (!state.fullText || !ft?.hits || ft.query !== state.search.trim()) return null;
  return ft.hits.get(s.id) || null;
}

// Where the search box matched: titles and prompts first, else the full-text hit.
export function searchSnippet(s, { openable = false } = {}) {
  const local = matchSnippet(s, state.search);
  if (local) return local;
  const hit = ftHit(s);
  return hit ? hitSnippet(hit, openable ? () => openHit(s.id) : null) : null;
}

// Ask the server for the query in the search box; repeats while the index is still being built.
async function runFullText() {
  clearTimeout(ftTimer);
  const token = ++ftToken;
  const q = state.search.trim();
  if (!state.fullText || q.length < FT_MIN) {
    const changed = state.ft?.hits?.size;
    state.ft = null;
    renderFullTextStatus();
    if (changed) renderMain();
    return;
  }
  renderFullTextStatus(true);
  let ft;
  try {
    const data = await fetchJSON(`/api/search?q=${encodeURIComponent(q)}`);
    ft = { query: q, hits: new Map(Object.entries(data.hits)), pending: data.pending };
  } catch (e) {
    ft = { error: e.message };
  }
  if (token !== ftToken) return;
  const sel = state.selectedId;
  const before = sel && JSON.stringify(state.ft?.query === q ? state.ft.hits?.get(sel) : null);
  state.ft = ft;
  if (ft.pending) ftTimer = setTimeout(runFullText, FT_POLL_MS);
  renderFullTextStatus();
  renderMain();
  // The detail pane shows the selected session's hit.
  if (sel && JSON.stringify(ft.hits?.get(sel) || null) !== before) refreshDetail();
}

function renderFullTextStatus(searching = false) {
  const el = $("full-text-status");
  const q = state.search.trim();
  const ft = state.ft;
  let text = "";
  let title = "";
  if (state.fullText && q) {
    if (q.length < FT_MIN) text = `Full text needs ${FT_MIN}+ characters`;
    else if (searching && !ft?.hits) text = "Searching…";
    else if (ft?.error) {
      text = "Full text unavailable";
      title = ft.error;
    } else if (ft?.hits) {
      text = `${ft.hits.size} in transcripts`;
      if (ft.pending) {
        text += " · indexing";
        title = `Transcripts are still being indexed (${ft.pending} files left), so more sessions may match`;
      }
    }
  }
  el.textContent = text;
  el.title = title;
  // Keep the query clear of the status.
  $("search").style.paddingRight = text ? `${el.offsetWidth + 14}px` : "";
}

function setFullText(on) {
  state.fullText = on;
  prefs.set("fullText", on);
  $("search").placeholder = on ? "Search sessions and transcripts…" : "Search sessions…";
  renderMain();
  runFullText();
}

// Select the session and open its log at the full-text hit.
async function openHit(id) {
  const hit = ftHit(state.byId.get(id) || { id });
  if (!hit) return;
  const query = state.ft.query;
  await select(id);
  if (state.detail?.id === id) openLog(state.detail, hit.agent, { ts: hit.ts, query });
}

// ------------------------------------------------------------------ selection

export async function select(id) {
  state.selectedId = id;
  syncURL();
  document.querySelectorAll(".bar.selected, tr.selected").forEach((el) => el.classList.remove("selected"));
  document.querySelectorAll(`[data-sid="${id}"]`).forEach((el) => el.classList.add("selected"));
  await refreshDetail();
}

function closeDetail() {
  state.selectedId = null;
  refreshDetail();
  renderMain();
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
      onClose: closeDetail,
      onOpenLog: (agent, target) => openLog(d, agent, target),
      onSelect: (sid) => select(sid),
      onOpenProject: () => openProject(d.project),
      onOpenPr: (url) => { state.highlightPr = url; openProject(d.project); },
      searchHit: state.byId.has(d.id) ? searchHitFor(d.id) : null,
      showSource: multiSource(),
      sourcePath,
      notes: { tags: state.tags, error: state.notesError, onSaved: () => loadSessions().catch(() => {}) },
    });
  } catch (e) {
    pane.replaceChildren(h("div", { class: "empty" }, "Session not found."));
  }
}

function searchHitFor(id) {
  const hit = ftHit(state.byId.get(id));
  return hit ? hitSnippet(hit, () => openHit(id)) : null;
}

// ------------------------------------------------------------------ rendering

function renderAll() {
  renderToolbar();
  renderMain();
}

// Show a project's page in place of the calendar or list.
export function openProject(project) {
  state.project = project;
  renderAll();
  $("project-view").querySelector(".project-body")?.scrollTo(0, 0);
}

function closeProject() {
  state.project = null;
  renderAll();
}

function renderMain() {
  syncURL();
  $("calendar-view").hidden = state.view !== "calendar" || state.project != null;
  $("list-view").hidden = state.view !== "list" || state.project != null;
  $("project-view").hidden = state.project == null;
  if (state.project != null) {
    // Live updates re-render the page; keep the reader's place.
    const top = $("project-view").querySelector(".project-body")?.scrollTop || 0;
    renderProject($("project-view"), state.project, { onBack: closeProject });
    $("project-view").querySelector(".project-body")?.scrollTo(0, top);
    return;
  }
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
  renderTools(visible);
  renderCosts(visible);
  renderRequests(visible);
  renderPrs(visible);
  renderHours(visible);
}

function renderTools(visible) {
  const pane = $("tools-pane");
  pane.hidden = !(state.showTools && state.view === "calendar");
  if (pane.hidden) return;
  const days = rangeDays();
  const start = days[0].getTime();
  const end = addDays(days[days.length - 1], 1).getTime();
  const ids = visible.filter((s) => s.segments.some(([a, b]) => b >= start && a < end)).map((s) => s.id);
  renderToolsPane(pane, { start, end, ids, key: `${start}|${end}|${state.dataVersion}|${ids.join(",")}` });
}

// Per-day rows in the week and month views; the day and year views get one total.
function renderCosts(visible) {
  const pane = $("costs-pane");
  pane.hidden = !(state.showCosts && state.view === "calendar");
  if (pane.hidden) return;
  const days = rangeDays();
  const start = days[0].getTime();
  const end = addDays(days[days.length - 1], 1).getTime();
  const perDay = state.span === "week" || state.span === "month";
  const bounds = perDay ? days.map((d) => [d.getTime(), addDays(d, 1).getTime()]) : [[start, end]];
  const labels = perDay ? days.map((d) => `${d.toLocaleDateString([], { weekday: "short" })} ${d.getDate()}`) : null;
  const ids = visible.filter((s) => s.segments.some(([a, b]) => b >= start && a < end)).map((s) => s.id);
  renderCostsPane(pane, { bounds, labels, ids, key: `${bounds.join(",")}|${state.dataVersion}|${ids.join(",")}` });
}

function renderRequests(visible) {
  const pane = $("requests-pane");
  pane.hidden = !(state.showRequests && state.view === "calendar");
  if (pane.hidden) return;
  const days = rangeDays();
  const start = days[0].getTime();
  const end = addDays(days[days.length - 1], 1).getTime();
  const ids = visible.filter((s) => s.segments.some(([a, b]) => b >= start && a < end)).map((s) => s.id);
  renderRequestsPane(pane, {
    start, end, ids,
    key: `${start}|${end}|${state.dataVersion}|${ids.join(",")}`,
    onOpen: (id, ts) => openEvent(id, ts, "prompt"),
  });
}

// PRs that sessions in the displayed range worked on, with their totals over all sessions.
function renderPrs(visible) {
  const pane = $("prs-pane");
  pane.hidden = !(state.showPrs && state.view === "calendar");
  if (pane.hidden) return;
  const days = rangeDays();
  const start = days[0].getTime();
  const end = addDays(days[days.length - 1], 1).getTime();
  const ids = visible.filter((s) => s.segments.some(([a, b]) => b >= start && a < end)).map((s) => s.id);
  renderPrsPane(pane, {
    slot: "pane", ids, scope: "worked on in this range", exportName: "pull-requests",
    key: `${state.dataVersion}|${state.gap}|${ids.join(",")}`,
  });
}

function renderHours(visible) {
  const pane = $("hours-pane");
  pane.hidden = !(state.showHours && state.view === "calendar");
  if (!pane.hidden) renderHoursPane(pane, visible, { days: rangeDays(), rerender: renderMain });
}

function renderToolbar() {
  document.querySelectorAll("#view-toggle button").forEach((b) =>
    b.classList.toggle("active", state.project == null && b.dataset.view === state.view));
  document.querySelectorAll("#color-by button").forEach((b) =>
    b.classList.toggle("active", b.dataset.color === colorMode()));
  document.querySelector('#color-by [data-color="source"]').hidden = !multiSource();
  document.querySelector('#color-by [data-color="tag"]').hidden = !state.tags.length;
  document.querySelectorAll("#span-toggle button").forEach((b) =>
    b.classList.toggle("active", b.dataset.span === state.span));
  $("go-today").textContent = { day: "Today", week: "This week", month: "This month", year: "This year" }[state.span];
  $("summary-toggle").classList.toggle("active", state.showSummary);
  $("tools-toggle").classList.toggle("active", state.showTools);
  $("costs-toggle").classList.toggle("active", state.showCosts);
  $("requests-toggle").classList.toggle("active", state.showRequests);
  $("prs-toggle").classList.toggle("active", state.showPrs);
  $("hours-toggle").classList.toggle("active", state.showHours);
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
        `${e.name} `, h("span", { class: "muted" }, `(${e.n})`),
        h("button", {
          class: "open-project",
          title: "Open the project page",
          onclick: (ev) => { ev.preventDefault(); $("project-menu").hidden = true; openProject(path); },
        }, "Page"))),
  );
}

const STATUS_ORDER = Object.keys(STATUS_LABELS);
const RATING_ORDER = RATINGS.map(([v]) => v);

// [key, header, sort value, first direction when clicked, numeric column?]
const LIST_COLUMNS = [
  ["status", "", (s) => STATUS_ORDER.indexOf(s.status), "asc", false],
  ["title", "Title", (s) => s.title.toLowerCase(), "asc", false],
  ["tags", "Tags", (s) => (s.tags.length ? s.tags.join(", ").toLowerCase() : null), "asc", false],
  ["rating", "Rating", (s) => (s.rating ? RATING_ORDER.indexOf(s.rating) : null), "asc", false],
  ["project", "Project", (s) => s.project_name.toLowerCase(), "asc", false],
  ["source", "Source", (s) => s.source.toLowerCase(), "asc", false],
  ["start", "Started", (s) => s.start, "desc", true],
  ["end", "Last activity", (s) => s.end, "desc", true],
  ["length", "Length", (s) => s.end - s.start, "desc", true],
  ["prompts", "Prompts", (s) => s.prompt_count, "desc", true],
  ["tokens", "Tokens", (s) => s.tokens, "desc", true],
  ["cost", "Cost", (s) => s.cost, "desc", true],
  ["cache", "Cache", (s) => s.cache_hit, "asc", true],
  ["percommit", "$/commit", (s) => costPer(s.cost, (s.commit_list || []).length), "desc", true],
  ["friction", "Friction", (s) => s.friction.total, "desc", true],
  ["ctxavg", "Avg ctx", (s) => s.context_avg, "desc", true],
  ["ctxpeak", "Peak ctx", (s) => s.context_peak, "desc", true],
];

function listColumns() {
  return multiSource() ? LIST_COLUMNS : LIST_COLUMNS.filter((c) => c[0] !== "source");
}

function sortRows(rows) {
  const col = listColumns().find((c) => c[0] === state.sort.key) || LIST_COLUMNS[3];
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

// The list view's rows: the shared filters, then the list-only ones, in the chosen order.
function listRows(visible) {
  const f = listFilter();
  return sortRows(visible.filter((s) => matchesListFilter(s, f)));
}

function setListFilter(changes) {
  state.listFilter = { ...state.listFilter, ...changes };
  prefs.set("listFilter", state.listFilter);
  // "change" fires before Tab moves focus; render after the move so focus lands on the next control.
  setTimeout(renderMain, 0);
}

function renderList(visible) {
  const rows = listRows(visible);
  renderListFilters($("list-filters"), visible, listFilter(), setListFilter, { sources: multiSource() });
  $("list-count").textContent = activeFilterCount(listFilter())
    ? `${rows.length} of ${visible.length} sessions`
    : `${rows.length} sessions`;
  if (!rows.length) {
    $("list").replaceChildren(h("div", { class: "empty" }, "No sessions match the filters."));
    return;
  }
  const header = listColumns().map(([key, label, , , numeric]) => {
    const sorted = state.sort.key === key;
    return h("th", {
      class: ["sortable", numeric ? "num" : "", sorted ? "sorted" : ""].join(" ").trim(),
      title: key === "status" ? "Sort by status" : key === "cache" ? "Sort by cache hit rate" : key === "percommit" ? "Sort by cost per commit"
        : key === "friction" ? "Sort by friction: interrupts, API errors, queued prompts and failed tool calls added up" : key === "ctxavg" ? "Sort by average context per request" : key === "ctxpeak" ? "Sort by peak context" : `Sort by ${label.toLowerCase()}`,
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
          h("td", { class: "title-cell" }, s.title,
            s.note ? h("span", { class: "note-mark", title: noteTitle(s.note) }, " 📝") : null,
            searchSnippet(s, { openable: true })),
          h("td", { class: "tags-cell" }, tagChips(s.tags)),
          h("td", {}, ratingBadge(s.rating)),
          h("td", { title: s.project }, h("span", { class: "dot", style: { background: state.projectColors.get(s.project), marginRight: "5px" } }),
            projectLink(s.project, s.project_name)),
          multiSource()
            ? h("td", { title: sourcePath(s.source) }, h("span", { class: "dot", style: { background: state.sourceColors.get(s.source), marginRight: "5px" } }), s.source)
            : null,
          h("td", { class: "num" }, fmtDateTime(s.start)),
          h("td", { class: "num", title: fmtDateTime(s.end) }, fmtAgo(s.end)),
          h("td", { class: "num" }, fmtDuration(s.end - s.start)),
          h("td", { class: "num" }, s.prompt_count),
          h("td", { class: "num" }, fmtTokens(s.tokens)),
          h("td", { class: "num" }, fmtCost(s.cost, s.cost_estimated)),
          h("td", { class: "num" + (s.cache_hit != null && s.cache_hit < CACHE_LOW ? " warn" : ""), title: cacheTitle(s.cache_hit, s.cache_saved) },
            fmtPct(s.cache_hit)),
          h("td", { class: "num", title: outputTitle(s) }, fmtCost(costPer(s.cost, (s.commit_list || []).length), s.cost_estimated)),
          h("td", { class: "num", title: frictionParts(s.friction).map(([, text]) => text).join(" · ") }, s.friction.total),
          h("td", { class: "num" }, s.context_avg == null ? "–" : fmtTokens(s.context_avg)),
          h("td", { class: "num" + (s.context_bloated ? " warn" : ""), title: s.context_bloated ? bloatTitle(s) : null },
            s.context_peak == null ? "–" : fmtTokens(s.context_peak)),
        ))),
    ),
  );
}

// What a session produced, for the $/commit cell's tooltip.
function outputTitle(s) {
  const n = (s.commit_list || []).length;
  const prs = (s.pr_list || []).length;
  const parts = [`${n} commit${n === 1 ? "" : "s"}`, `${prs} PR${prs === 1 ? "" : "s"}`, `${s.files_changed || 0} files edited`];
  if (s.lines_added != null) parts.push(`+${s.lines_added} / −${s.lines_removed ?? 0} lines`);
  return parts.join(" · ");
}

// The start of a note, for a tooltip.
function noteTitle(note) {
  return note.length > 300 ? note.slice(0, 300) + "…" : note;
}

// A project name that opens the project page.
export function projectLink(project, name) {
  return h("button", {
    class: "project-link",
    title: `${project}\nOpen the project page`,
    onclick: (e) => { e.stopPropagation(); openProject(project); },
  }, name);
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

function setView(view) {
  state.view = view;
  state.project = null;
  prefs.set("view", view);
  renderAll();
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

function goToday() {
  state.anchor = startOfDay(new Date());
  renderMain();
}

function setHourPx(px) {
  state.hourPx = Math.max(MIN_HOUR_PX, Math.min(MAX_HOUR_PX, Math.round(px)));
  prefs.set("hourPx", state.hourPx);
  renderMain();
}

function bind() {
  document.querySelectorAll("#view-toggle button").forEach((b) =>
    b.addEventListener("click", () => setView(b.dataset.view)));
  document.querySelectorAll("#color-by button").forEach((b) =>
    b.addEventListener("click", () => {
      state.colorBy = b.dataset.color;
      prefs.set("colorBy", state.colorBy);
      renderAll();
    }));
  document.querySelectorAll("#span-toggle button").forEach((b) =>
    b.addEventListener("click", () => setSpan(b.dataset.span)));
  $("go-today").onclick = goToday;
  $("go-prev").onclick = () => shift(-1);
  $("go-next").onclick = () => shift(1);
  bindNotifyToggle($("notify-toggle"));
  $("summary-toggle").onclick = () => {
    state.showSummary = !state.showSummary;
    prefs.set("summary", state.showSummary);
    renderAll();
  };
  $("tools-toggle").onclick = () => {
    state.showTools = !state.showTools;
    prefs.set("tools", state.showTools);
    renderAll();
  };
  $("costs-toggle").onclick = () => {
    state.showCosts = !state.showCosts;
    prefs.set("costs", state.showCosts);
    renderAll();
  };
  $("requests-toggle").onclick = () => {
    state.showRequests = !state.showRequests;
    prefs.set("requests", state.showRequests);
    renderAll();
  };
  $("prs-toggle").onclick = () => {
    state.showPrs = !state.showPrs;
    prefs.set("prs", state.showPrs);
    renderAll();
  };
  $("hours-toggle").onclick = () => {
    state.showHours = !state.showHours;
    prefs.set("hours", state.showHours);
    renderAll();
  };
  $("copy-report").onclick = async () => {
    const btn = $("copy-report");
    const ok = await copyText(buildReport(filtered(), rangeDays(), $("range-label").textContent,
      state.compareRanges ? state.span : null));
    btn.textContent = ok ? "Copied ✓" : "Copy failed";
    clearTimeout(btn.timer);
    btn.timer = setTimeout(() => { btn.textContent = "Copy report"; }, 1500);
  };
  $("copy-retro").onclick = async () => {
    const btn = $("copy-retro");
    const ok = await copyText(buildRetrospective(filtered(), rangeDays(), $("range-label").textContent, state.span));
    btn.textContent = ok ? "Copied ✓" : "Copy failed";
    clearTimeout(btn.timer);
    btn.timer = setTimeout(() => { btn.textContent = "Copy retrospective"; }, 1500);
  };
  for (const btn of document.querySelectorAll("#export button")) {
    btn.onclick = () => exportSessions(listRows(filtered()), btn.dataset.format, state.appVersion);
  }
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
    searchTimer = setTimeout(() => {
      state.search = e.target.value;
      renderMain();
      runFullText();
    }, 150);
  });
  $("full-text").checked = state.fullText;
  $("full-text").onchange = (e) => setFullText(e.target.checked);
  if (state.fullText) $("search").placeholder = "Search titles, prompts and transcripts…";
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
  bindKeys();
}

// ------------------------------------------------------------------ keyboard

// The sessions j / k move through, in order, or null where they do not apply: the list's rows,
// or the sessions drawn in the day or week calendar by start time.
function sessionOrder() {
  if (state.project != null) return null;
  const visible = filtered();
  if (state.view === "list") return listRows(visible);
  if (state.span !== "day" && state.span !== "week") return null;
  const days = rangeDays();
  const start = days[0].getTime();
  const end = addDays(days[days.length - 1], 1).getTime();
  return visible
    .filter((s) => s.segments.some(([a, b]) => b >= start && a < end))
    .sort((a, b) => a.start - b.start);
}

function step(dir) {
  const rows = sessionOrder();
  if (!rows?.length) return false;
  const i = rows.findIndex((s) => s.id === state.selectedId);
  const next = i < 0
    ? rows[dir > 0 ? 0 : rows.length - 1]
    : rows[Math.min(rows.length - 1, Math.max(0, i + dir))];
  select(next.id);
  document.querySelector(`[data-sid="${next.id}"]`)?.scrollIntoView({ block: "nearest" });
}

function openSelectedLog() {
  if (!state.selectedId) return false;
  (async () => {
    if (state.detail?.id !== state.selectedId) await refreshDetail();
    if (state.detail?.id === state.selectedId) openLog(state.detail, null);
  })();
}

function bindKeys() {
  const inCalendar = () => state.view === "calendar" && state.project == null;
  const nav = (fn) => () => (inCalendar() ? fn() : false);
  const span = (name) => () => {
    state.view = "calendar";
    state.project = null;
    prefs.set("view", state.view);
    setSpan(name);
  };
  bindShortcuts({
    ArrowLeft: nav(() => shift(-1)),
    ArrowRight: nav(() => shift(1)),
    t: nav(goToday),
    d: span("day"),
    w: span("week"),
    m: span("month"),
    y: span("year"),
    c: () => setView("calendar"),
    l: () => setView("list"),
    "/": () => $("search").focus(),
    j: () => step(1),
    k: () => step(-1),
    Enter: openSelectedLog,
    o: openSelectedLog,
  }, [
    // Esc closes one thing per press, topmost first (the overlay and transcript come before).
    () => !$("project-menu").hidden && ($("project-menu").hidden = true),
    () => document.activeElement === $("search") && ($("search").blur(), true),
    () => state.selectedId != null && (closeDetail(), true),
    () => state.project != null && (closeProject(), true),
  ]);
}

// ------------------------------------------------------------------ URL

let loaded = false; // the first session list has arrived
let restoring = true; // the state comes from the URL, so do not add history entries

// Put the current view in the URL hash: a new history entry when the view changes, so Back
// returns to it, but selecting a session only replaces the current entry.
function syncURL() {
  const hash = stateHash(state);
  if (hash === location.hash) return;
  if (restoring || !majorChange(hash, location.hash)) history.replaceState(null, "", hash);
  else history.pushState(null, "", hash);
}

// Take the view from the URL hash. Keys it does not name keep their remembered value.
function applyHash() {
  const u = readHash();
  if (u.view) {
    state.view = u.view;
    prefs.set("view", u.view);
  }
  if (u.span) {
    state.span = u.span;
    prefs.set("span", u.span);
  }
  state.anchor = u.anchor || startOfDay(new Date());
  state.selectedId = u.selectedId || null;
  state.project = u.project ?? null;
  dropUnknown();
}

// Forget a session or project the URL names but the logs do not have.
function dropUnknown() {
  if (!loaded) return; // checked once the sessions arrive
  if (state.selectedId && !state.byId.has(state.selectedId)) state.selectedId = null;
  if (state.project != null && !state.sessions.some((s) => s.project === state.project)) state.project = null;
}

window.addEventListener("popstate", () => {
  const before = state.selectedId;
  restoring = true;
  applyHash();
  // The transcript and menu belong to the view being left.
  closeLog();
  $("project-menu").hidden = true;
  renderAll();
  restoring = false;
  if (state.selectedId !== before) refreshDetail();
});

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
      // New transcript lines may match; the index catches up in the background.
      if (state.ft?.hits && payload.sessions.length) setTimeout(runFullText, FT_POLL_MS);
    }, 300);
  };
}

// Keep "now" line and relative times fresh even when nothing is written.
setInterval(() => { if (state.view === "calendar") renderMain(); }, 60_000);

applyHash();
bind();
loadSessions().catch((e) => {
  $("calendar").replaceChildren(h("div", { class: "empty" }, `Failed to load sessions: ${e.message}`));
});
connectEvents();
