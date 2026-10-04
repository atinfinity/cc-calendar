// The view state kept in the URL hash, so reload, back / forward and bookmarks keep the view:
// #view=calendar&span=week&date=2026-10-04&session=<id>&project=<path>
const VIEWS = ["calendar", "list"];
const SPANS = ["day", "week", "month", "year"];

const pad = (n) => String(n).padStart(2, "0");

// Local date as YYYY-MM-DD.
function fmtDate(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function parseDate(text) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text || "");
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.getMonth() === Number(m[2]) - 1 && d.getDate() === Number(m[3]) ? d : null;
}

// The hash for a state. View, span and date are always written so a bookmark shows the same
// view whatever this browser remembers; session and project only when one is open.
export function stateHash({ view, span, anchor, selectedId, project }) {
  const p = new URLSearchParams({ view, span, date: fmtDate(anchor) });
  if (selectedId) p.set("session", selectedId);
  if (project != null) p.set("project", project);
  return "#" + p.toString();
}

// Values in the current hash, leaving out keys that are missing or invalid. Whether a session
// or project exists is checked by the caller once the sessions are loaded.
export function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  const out = {};
  if (VIEWS.includes(p.get("view"))) out.view = p.get("view");
  if (SPANS.includes(p.get("span"))) out.span = p.get("span");
  const date = parseDate(p.get("date"));
  if (date) out.anchor = date;
  if (p.get("session")) out.selectedId = p.get("session");
  if (p.get("project")) out.project = p.get("project");
  return out;
}

// Whether two hashes differ in more than the selected session: such a change gets its own
// history entry, while selecting a session only replaces the current one.
export function majorChange(a, b) {
  const strip = (hash) => {
    const p = new URLSearchParams(hash.replace(/^#/, ""));
    p.delete("session");
    return p.toString();
  };
  return strip(a) !== strip(b);
}
