// Export the sessions shown in the list view as CSV or JSON.
import { activeMs, costPer } from "./summary.js";

// ISO 8601 in local time with its UTC offset, e.g. 2026-10-04T09:30:00+09:00.
export function isoLocal(ms) {
  if (ms == null) return null;
  const d = new Date(ms);
  const pad = (n) => String(Math.trunc(Math.abs(n))).padStart(2, "0");
  const off = -d.getTimezoneOffset();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
    + `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
    + `${off >= 0 ? "+" : "-"}${pad(off / 60)}:${pad(off % 60)}`;
}

const round = (x, digits) => (x == null ? null : Number(x.toFixed(digits)));

// One flat record per session; the same fields go into both formats.
export function sessionRecords(rows) {
  return rows.map((s) => ({
    id: s.id,
    title: s.title,
    project: s.project_name,
    project_path: s.project,
    source: s.source,
    branch: s.branch || null,
    status: s.status,
    rating: s.rating || null,
    start: isoLocal(s.start),
    end: isoLocal(s.end),
    active_minutes: round(activeMs(s, -Infinity, Infinity) / 60000, 1),
    span_minutes: s.start != null && s.end != null ? round((s.end - s.start) / 60000, 1) : null,
    prompts: s.prompt_count,
    tokens: s.tokens,
    cost_usd: round(s.cost, 4),
    cost_estimated: Boolean(s.cost_estimated),
    cache_hit_rate: round(s.cache_hit, 4),
    model: s.model || null,
    effort: s.effort || null,
    claude_code_version: s.version || null,
    commits: (s.commit_list || []).length,
    pull_requests: (s.pr_list || []).length,
    files_changed: s.files_changed ?? 0,
    lines_added: s.lines_added ?? null,
    lines_removed: s.lines_removed ?? null,
    cost_per_commit: round(costPer(s.cost, (s.commit_list || []).length), 4),
    tags: [...(s.tags || [])],
    note: s.note || "",
  }));
}

function csvCell(v) {
  if (v == null) return "";
  let text = String(v);
  // Spreadsheets run cells starting with these as formulas; titles come from prompts.
  if (typeof v === "string" && /^[=+\-@\t\r]/.test(text)) text = "'" + text;
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function toCSV(records, fields) {
  // Tags cannot contain commas, but ";" keeps the cell readable without quotes.
  const cell = (v) => csvCell(Array.isArray(v) ? v.join(";") : v);
  const lines = [fields.join(","), ...records.map((r) => fields.map((f) => cell(r[f])).join(","))];
  return lines.join("\r\n") + "\r\n";
}

export const EXPORT_FIELDS = [
  "id", "title", "project", "project_path", "source", "branch", "status", "rating", "start", "end",
  "active_minutes", "span_minutes", "prompts", "tokens", "cost_usd", "cost_estimated",
  "cache_hit_rate", "model", "effort", "claude_code_version", "commits", "pull_requests", "files_changed", "lines_added", "lines_removed",
  "cost_per_commit", "tags", "note",
];

// Bump when a field is renamed, removed or changes meaning; adding fields does not need it.
export const SCHEMA_VERSION = 1;

// CSV stays a plain table (the header row is its schema); JSON carries the format and version.
export function exportSessions(rows, format, appVersion) {
  const records = sessionRecords(rows);
  // The BOM lets Excel open non-ASCII titles as UTF-8.
  const body = format === "csv"
    ? "\uFEFF" + toCSV(records, EXPORT_FIELDS)
    : JSON.stringify({
      format: "cc-calendar.sessions",
      schema_version: SCHEMA_VERSION,
      generator: appVersion ? `cc-calendar ${appVersion}` : "cc-calendar",
      exported_at: isoLocal(Date.now()),
      sessions: records,
    }, null, 2) + "\n";
  const type = format === "csv" ? "text/csv;charset=utf-8" : "application/json";
  const url = URL.createObjectURL(new Blob([body], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `cc-calendar-sessions-${isoLocal(Date.now()).slice(0, 10)}.${format}`;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
