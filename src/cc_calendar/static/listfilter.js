// Extra filters of the list view: model, branch, source, tag, output, date range and cost range.
import { hasOutput } from "./summary.js";
import { h, shortModel } from "./util.js";

export const EMPTY_FILTER = { model: "", branch: "", source: "", tag: "", output: "", from: "", to: "", costMin: "", costMax: "" };

// The tag filter's value for sessions without tags; tags are trimmed, so none starts with a space.
const UNTAGGED = " untagged";

// Local midnight at the start of a "YYYY-MM-DD" date input value, plus `days`, in ms.
function midnight(value, days = 0) {
  const [y, m, d] = value.split("-").map(Number);
  return new Date(y, m - 1, d + days).getTime();
}

// True when the session passes every filter that is set. Dates match sessions active on any
// day from `from` to `to` (both inclusive); costs are in USD.
export function matchesListFilter(s, f) {
  if (f.model && s.model !== f.model) return false;
  if (f.branch && s.branch !== f.branch) return false;
  if (f.source && s.source !== f.source) return false;
  if (f.tag === UNTAGGED ? s.tags.length : f.tag && !s.tags.some((t) => t.toLowerCase() === f.tag.toLowerCase())) return false;
  if (f.output && hasOutput(s) !== (f.output === "yes")) return false;
  if (f.from && (s.end == null || s.end < midnight(f.from))) return false;
  if (f.to && (s.start == null || s.start >= midnight(f.to, 1))) return false;
  if (f.costMin !== "" && !((s.cost || 0) >= Number(f.costMin))) return false;
  if (f.costMax !== "" && !((s.cost || 0) <= Number(f.costMax))) return false;
  return true;
}

export function activeFilterCount(f) {
  return Object.keys(EMPTY_FILTER).filter((k) => f[k] !== "").length;
}

// Values of `key` among the sessions, most common first; the selected one is kept even if absent.
function options(sessions, key, selected) {
  const counts = new Map();
  for (const s of sessions) if (s[key]) counts.set(s[key], (counts.get(s[key]) || 0) + 1);
  if (selected && !counts.has(selected)) counts.set(selected, 0);
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

// The tag choices: tags among the sessions, most common first, then "(untagged)".
function tagSelect(sessions, f, set) {
  const counts = new Map();
  let untagged = 0;
  for (const s of sessions) {
    if (!s.tags.length) untagged++;
    for (const t of s.tags) counts.set(t, (counts.get(t) || 0) + 1);
  }
  if (!counts.size && !f.tag) return null;
  if (f.tag && f.tag !== UNTAGGED && !counts.has(f.tag)) counts.set(f.tag, 0);
  const tags = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  return h("label", { class: "muted" }, "Tag ",
    h("select", { "data-key": "tag", onchange: set("tag") },
      h("option", { value: "" }, "All tags"),
      ...tags.map(([v, n]) => h("option", { value: v, selected: v === f.tag }, `${v} (${n})`)),
      h("option", { value: UNTAGGED, selected: f.tag === UNTAGGED }, `(untagged) (${untagged})`)));
}

// Renders the filter controls; `sessions` supply the model, branch and source choices.
// `onChange(changes)` merges into the current filter, so a control rendered earlier stays correct.
// The source filter is offered only when `sources` is set (several config directories).
export function renderListFilters(container, sessions, f, onChange, { sources = false } = {}) {
  const set = (key) => (e) => onChange({ [key]: e.target.value });
  const select = (key, label, all, fmt) => h("label", { class: "muted" }, label + " ",
    h("select", { "data-key": key, onchange: set(key) },
      h("option", { value: "" }, all),
      ...options(sessions, key, f[key]).map(([v, n]) =>
        h("option", { value: v, selected: v === f[key] }, `${fmt(v)} (${n})`))));
  const input = (key, attrs) => h("input", { ...attrs, "data-key": key, value: f[key], onchange: set(key) });
  const n = activeFilterCount(f);
  // Re-rendering must not take the caret away or drop a value still being typed.
  const focused = container.contains(document.activeElement) ? document.activeElement : null;
  const draft = focused?.tagName === "INPUT" ? focused.value : null;
  // replaceChildren would turn a null into the text "null".
  container.replaceChildren(...[
    select("model", "Model", "All models", shortModel),
    select("branch", "Branch", "All branches", (v) => v),
    sources ? select("source", "Source", "All sources", (v) => v) : null,
    tagSelect(sessions, f, set),
    h("label", { class: "muted", title: "Output: commits, pull requests or edited files" }, "Output ",
      h("select", { "data-key": "output", onchange: set("output") },
        h("option", { value: "" }, "Any output"),
        h("option", { value: "yes", selected: f.output === "yes" }, "With output"),
        h("option", { value: "no", selected: f.output === "no" }, "No output"))),
    h("label", { class: "muted", title: "Sessions active on any day in this range" }, "Active ",
      input("from", { type: "date", "aria-label": "From date", max: f.to || null }), " – ",
      input("to", { type: "date", "aria-label": "To date", min: f.from || null })),
    h("label", { class: "muted", title: "Session cost in USD" }, "Cost $",
      input("costMin", { type: "number", min: 0, step: "any", placeholder: "min", "aria-label": "Minimum cost" }), " – $",
      input("costMax", { type: "number", min: 0, step: "any", placeholder: "max", "aria-label": "Maximum cost" })),
    n ? h("button", { onclick: () => onChange({ ...EMPTY_FILTER }) }, `Clear ${n} filter${n > 1 ? "s" : ""}`) : null,
  ].filter(Boolean));
  const again = focused?.dataset.key && container.querySelector(`[data-key="${focused.dataset.key}"]`);
  if (again) {
    if (draft !== null) again.value = draft;
    again.focus();
  }
}
