// Right-hand detail pane for one session.
import {
  STATUS_HINTS, STATUS_LABELS, CACHE_LOW, cacheTitle, compactDetail, fmtEffortMix, fmtAgo, fmtCost, fmtDateTime, fmtDuration, fmtPct, fmtTime, fmtTokens, h,
  shortModel, statusColor,
} from "./util.js";
import { copyText } from "./report.js";

const CHECKS = [
  ["turn_ended", "Turn ended", "Claude finished its last reply and was not interrupted with Esc"],
  ["no_background", "No background work", "No background shells or agents were left running"],
  ["clean_exit", "Clean exit", "Claude Code was exited normally (e.g. /exit), which records the final cost"],
  ["committed", "Working tree clean",
    "The repository has no uncommitted changes. This is its current state, not the state when the session ended"],
];

// Quote for POSIX shells unless the text is plainly safe.
export function shellQuote(text) {
  return /^[\w@%+=:,./-]+$/.test(text) ? text : `'${text.replaceAll("'", "'\\''")}'`;
}

// Claude Code finds a session by the directory it was started in, so cd there first.
export function resumeCommand(d) {
  const resume = `claude --resume ${shellQuote(d.id)}`;
  return d.cwd ? `cd ${shellQuote(d.cwd)} && ${resume}` : resume;
}

function resumeButton(d) {
  const live = d.status === "running" || d.status === "waiting";
  const cmd = resumeCommand(d);
  const btn = h("button", {
    title: `Copy: ${cmd}` + (live ? "\nThis session is still open; resuming it elsewhere runs it twice." : ""),
    onclick: async () => {
      const ok = await copyText(cmd);
      btn.textContent = ok ? "Copied ✓" : "Copy failed";
      clearTimeout(btn.timer);
      btn.timer = setTimeout(() => { btn.textContent = "Copy resume command"; }, 1500);
    },
  }, "Copy resume command");
  return btn;
}

function card(title, ...body) {
  return h("section", { class: "card" }, h("h3", {}, title), h("div", { class: "card-body" }, ...body));
}

function shaTag(ref) {
  if (!ref) return null;
  const isSha = /^[0-9a-f]{7,40}$/.test(ref);
  return h("span", { class: "sha", title: ref }, isSha ? ref.slice(0, 7) : "(unresolved) " + ref.slice(0, 40));
}

// A timestamp that opens the log scrolled to that moment.
function logLink(text, onclick, cls = "") {
  return h("button", { class: `log-link ${cls}`, title: "Open the log here", onclick }, text);
}

export function renderDetail(pane, d, { onClose, onOpenLog, onSelect }) {
  const statusBadge = h("span", { class: "badge", title: STATUS_HINTS[d.status], style: { background: statusColor(d.status) } }, STATUS_LABELS[d.status]);
  const ctx = d.context_pct == null ? null : h("span", { class: "stat", title: "Context used by the latest response" },
    "ctx ", h("span", { class: "ctx" }, h("i", { style: { width: `${Math.min(100, d.context_pct)}%` } })), ` ${d.context_pct}%`);

  const parts = [
    h("div", { class: "detail-head" },
      h("span", { class: "idtag", title: d.id }, d.id.slice(0, 8)),
      statusBadge,
      h("div", { class: "spacer" }),
      resumeButton(d),
      h("button", { class: "primary", onclick: () => onOpenLog(null) }, "Open log"),
      h("button", { onclick: onClose, "aria-label": "Close" }, "✕")),
    h("h2", {}, d.title),
    h("div", { class: "muted", title: d.cwd || d.project },
      `${d.project_name}${d.branch ? " · " + d.branch : ""}${d.permission_mode ? " · " + d.permission_mode : ""}`),
    h("div", { class: "muted" },
      `Started ${fmtDateTime(d.start)} · last activity ${fmtAgo(d.end)} · span ${fmtDuration(d.end - d.start)}`),
    h("div", { class: "stats" },
      h("span", { class: "stat" }, `${d.prompt_count} prompts`),
      h("span", { class: "stat", title: "Input + output + cache tokens, including subagents" }, `${fmtTokens(d.tokens)} tok`),
      h("span", { class: "stat", title: d.cost_estimated ? "Estimated from token usage" : "From Claude Code's cost record" }, fmtCost(d.cost, d.cost_estimated)),
      d.cache_hit == null ? null : h("span", { class: "stat" + (d.cache_hit < CACHE_LOW ? " warn" : ""), title: cacheTitle(d.cache_hit, d.cache_saved) },
        `cache ${fmtPct(d.cache_hit)}`),
      ctx,
      ...d.models.map((m) => h("span", { class: "stat" }, shortModel(m))),
      fmtEffortMix(d.efforts) ? h("span", { class: "stat", title: "Effort level: share of API requests" }, `effort ${fmtEffortMix(d.efforts)}`) : null,
      d.compactions.length ? h("span", { class: "stat", title: d.compactions.map((c) => `${fmtTime(c.ts)}  ${compactDetail(c)}`).join("\n") },
        `${d.compactions.length} compaction${d.compactions.length > 1 ? "s" : ""}`) : null),
  ];

  if (d.continued_from || d.continued_in) {
    parts.push(h("div", { class: "muted" },
      d.continued_from ? h("a", { href: "#", onclick: (e) => { e.preventDefault(); onSelect(d.continued_from); } }, "← Previous session") : null,
      d.continued_from && d.continued_in ? " · " : null,
      d.continued_in ? h("a", { href: "#", onclick: (e) => { e.preventDefault(); onSelect(d.continued_in); } }, "Continued in →") : null));
  }

  parts.push(card("Session state", h("div", { class: "checks" }, CHECKS.map(([key, label, hint]) => {
    const v = d.checks[key];
    const cls = v === true ? "ok" : v === false ? "ng" : "na";
    const mark = v === true ? "✓" : v === false ? "✗" : "–";
    const title = v == null ? `${hint} (unknown)` : hint;
    return h("span", { class: `check-pill ${cls}`, title }, `${mark} ${label}`);
  }))));

  // Outcomes
  const outcome = [];
  outcome.push(h("details", { open: d.commits.length > 0 && d.commits.length <= 10 },
    h("summary", {}, `Commits (${d.commits.length})`),
    d.commits.length
      ? h("ul", { class: "plain-list" }, d.commits.map((c) =>
          h("li", {}, shaTag(c.sha) || h("span", { class: "sha" }, "?"), c.subject || "", " ",
            c.ts ? logLink(fmtTime(c.ts), () => onOpenLog(null, { ts: c.ts, kind: "commit" })) : null)))
      : h("div", { class: "muted" }, "No commits detected.")));
  outcome.push(h("details", {},
    h("summary", {}, `Files changed (${d.files.length})`),
    h("ul", { class: "file-list" }, d.files.map((f) => h("li", { title: f.path }, relPath(f.path, d.cwd), f.count > 1 ? h("span", { class: "muted" }, ` ×${f.count}`) : null)))));
  if (d.prs.length) {
    outcome.push(h("details", { open: true },
      h("summary", {}, `Pull requests (${d.prs.length})`),
      h("ul", { class: "plain-list" }, d.prs.map((p) =>
        h("li", {}, h("a", { href: p.url, target: "_blank", rel: "noopener" }, p.number ? `#${p.number}` : p.url), p.repo ? ` ${p.repo}` : "")))));
  }
  if (d.cost_state && (d.cost_state.totalLinesAdded || d.cost_state.totalLinesRemoved)) {
    outcome.push(h("div", { class: "muted" }, `+${d.cost_state.totalLinesAdded} / −${d.cost_state.totalLinesRemoved} lines`));
  }
  parts.push(card("Outcome", ...outcome));

  // Prompts with the commits that followed them
  parts.push(card(`Requests (${d.prompts.length})`,
    d.prompts.length
      ? d.prompts.map((p) => {
          const text = h("div", { class: "text", onclick: (e) => e.currentTarget.classList.toggle("open") }, p.text);
          return h("div", { class: "prompt" },
            h("div", {},
              p.ts ? logLink(fmtDateTime(p.ts), () => onOpenLog(null, { ts: p.ts, kind: "prompt" }), "when") : null,
              p.kind === "command" ? h("span", { class: "kind" }, "command") : null,
              ...p.commits.map(shaTag)),
            text);
        })
      : h("div", { class: "muted" }, "No human prompts in this session.")));

  if (d.subagents.length) {
    parts.push(card(`Subagents (${d.subagents.length})`, d.subagents.map((a) =>
      h("div", { class: "sub-row" },
        h("div", { class: "grow" },
          h("div", {}, h("strong", {}, a.type || "agent"), " ", a.description || ""),
          h("div", { class: "muted" },
            `${shortModel(a.model)} · ${fmtTokens(a.tokens)} tok · ~$${a.cost.toFixed(2)}`,
            a.start ? ` · ${fmtTime(a.start)}–${fmtTime(a.end)}` : "",
            a.status ? ` · ${a.status}` : "")),
        a.has_log ? h("button", { onclick: () => onOpenLog(a.id) }, "Log") : null))));
  }

  if (d.background.length) {
    parts.push(card(`Background tasks (${d.background.length})`, d.background.map((b) =>
      h("div", { class: "sub-row" },
        h("div", { class: "grow" }, b.description || b.summary || b.id),
        h("span", { class: "muted" }, bgStatus(b, d))))));
  }

  parts.push(h("div", { class: "muted", style: { fontSize: "11px", marginTop: "10px" } },
    `Session ${d.id}${d.version ? " · Claude Code " + d.version : ""}`));

  const scroll = pane.scrollTop;
  pane.replaceChildren(...parts);
  pane.scrollTop = scroll;
}

function relPath(path, cwd) {
  if (cwd && path.startsWith(cwd + "/")) return path.slice(cwd.length + 1);
  return path;
}

// A task never reported as finished in a session that has exited was killed with it.
function bgStatus(b, d) {
  const live = d.status === "running" || d.status === "waiting";
  return b.status === "running" && !live ? "stopped" : b.status || "";
}
