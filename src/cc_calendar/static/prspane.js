// Pull requests: cost, active time and commits per PR, from all the sessions that worked on it.
// Shown for the displayed range, on the project page and in the detail pane.
import { select, state } from "./app.js";
import { exportPrs } from "./export.js";
import { fmtCost, fmtDateTime, fmtDuration, fmtTokens, h } from "./util.js";

export const ATTRIBUTION_NOTE = "A session's requests up to a PR it opens go to that PR; a session that opens several gives each the work since the previous one, "
  + "and a continued session counts with the one it continues. Later work on a PR's branch (review fixes) is added to it. "
  + "Totals cover all of a PR's sessions, also those outside the range or the filters.";

// Results by caller ("pane", "project", "detail"), so a redraw does not fetch again.
const cache = new Map();

// The PRs the sessions `ids` worked on: {prs, unattributed}. `key` changes with the sessions,
// the data or the idle gap; a stale answer resolves to null.
export async function fetchPrs(slot, ids, key) {
  const hit = cache.get(slot);
  if (hit?.key === key && hit.data) return hit.data;
  const promise = hit?.key === key ? hit.promise : fetch("/api/prs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessions: ids, gap: state.gap }),
  }).then((res) => {
    if (!res.ok) throw new Error(String(res.status));
    return res.json();
  });
  cache.set(slot, { key, promise });
  let data;
  try {
    data = await promise;
  } catch (e) {
    if (cache.get(slot)?.key === key) cache.delete(slot); // try again next time
    throw e;
  }
  if (cache.get(slot)?.key !== key) return null; // a newer request superseded this one
  cache.set(slot, { key, data });
  return data;
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

function prLink(pr) {
  return h("a", { href: pr.url, target: "_blank", rel: "noopener", title: pr.url, onclick: (e) => e.stopPropagation() },
    pr.number != null ? `#${pr.number}` : "PR");
}

function sessionsTitle(pr) {
  return pr.sessions.map((s) => {
    const title = state.byId.get(s.id)?.title || s.id;
    return `${fmtCost(s.cost, pr.estimated)}  ${title}${s.id === pr.opened_in ? " (opened it)" : ""}`;
  }).join("\n");
}

// One row per PR; a click shows the session that opened it. `highlight` is a PR URL.
export function prTable(prs, { highlight } = {}) {
  const max = Math.max(...prs.map((p) => p.cost), 0) || 1;
  return h("table", { class: "pr-table" },
    h("thead", {}, h("tr", {},
      h("th", {}, "PR"), h("th", {}, "Title"), h("th", {}, "Repository"), h("th", { class: "num" }, "Opened"),
      h("th", { class: "num", title: "Sessions that worked on the PR" }, "Sessions"),
      h("th", { class: "num" }, "Active"), h("th", { class: "num" }, "Cost"), h("th", {}),
      h("th", { class: "num" }, "Commits"))),
    h("tbody", {}, prs.map((pr) => h("tr", {
      "data-pr": pr.url,
      class: pr.url === highlight ? "selected" : "",
      title: state.byId.has(pr.opened_in) ? "Show the session that opened it" : null,
      onclick: () => state.byId.has(pr.opened_in) && select(pr.opened_in),
    },
      h("td", {}, prLink(pr)),
      h("td", { class: "title-cell", title: pr.title || "" }, pr.title || h("span", { class: "muted" }, "(no title recorded)")),
      h("td", { title: pr.head ? `Branch ${pr.head}` : null }, pr.repo || ""),
      h("td", { class: "num" }, fmtDateTime(pr.created)),
      h("td", { class: "num", title: sessionsTitle(pr) }, pr.sessions.length),
      h("td", { class: "num" }, pr.active_ms ? fmtDuration(pr.active_ms) : "–"),
      h("td", { class: "num strong", title: `${plural(pr.requests, "request")} · ${fmtTokens(pr.tokens)} tokens` }, fmtCost(pr.cost, pr.estimated)),
      h("td", {}, h("span", { class: "usage-bar", style: { width: `${Math.max(2, (80 * pr.cost) / max)}px` } })),
      h("td", { class: "num" }, pr.commits || "")))));
}

function unattributedLine(u) {
  if (!u.sessions) return null;
  return h("div", { class: "muted", title: "Work in no PR's span and on no PR's branch" },
    `Unattributed: ${fmtCost(u.cost, u.estimated)} and ${fmtDuration(u.active_ms)} active in ${plural(u.sessions, "session")}`
    + (u.commits ? `, ${plural(u.commits, "commit")}` : "") + ".");
}

function exportButtons(data, name) {
  return h("span", { class: "pr-export" },
    h("span", { class: "muted" }, "Export "),
    h("span", { class: "seg small", title: "Download these pull requests" },
      ["csv", "json"].map((format) => h("button", { onclick: () => exportPrs(data, format, state.appVersion, name) }, format.toUpperCase()))));
}

// Fill `container` with the PR table for the sessions `ids`. `scope` names them in the
// heading ("in this range", "in this project").
export async function renderPrs(container, { slot, ids, key, scope, exportName, highlight }) {
  let data = cache.get(slot)?.key === key ? cache.get(slot).data : null;
  if (!data) {
    container.replaceChildren(h("div", { class: "muted" }, "Loading pull requests…"));
    try {
      data = await fetchPrs(slot, ids, key);
    } catch (e) {
      container.replaceChildren(h("div", { class: "muted" }, `Could not load pull requests (${e.message}).`));
      return;
    }
    if (!data) return;
  }
  const total = data.prs.reduce((n, p) => n + p.cost, 0);
  container.replaceChildren(
    h("div", { class: "tools-head" },
      h("strong", {}, plural(data.prs.length, "pull request")),
      data.prs.length ? ` ${scope} · ${fmtCost(total, data.prs.some((p) => p.estimated))} in all` : ` ${scope}`,
      data.prs.length ? exportButtons(data, exportName) : null),
    unattributedLine(data.unattributed),
    data.prs.length ? prTable(data.prs, { highlight }) : null,
    h("div", { class: "muted note" }, ATTRIBUTION_NOTE, data.prs.length ? " Click a row to show the session that opened the PR." : ""),
  );
  // After the caller has placed (and maybe scrolled) the page.
  if (highlight) requestAnimationFrame(() => container.querySelector("tr.selected")?.scrollIntoView({ block: "center" }));
}

// The detail pane's PR list: each PR the session worked on, with its cost, and a link to the
// project page's table. `onOpenPr(url)` opens it there.
export function detailPrList(d, onOpenPr) {
  const list = h("ul", { class: "plain-list" }, d.prs.map((p) => prItem(p)));
  const box = h("details", { open: true, hidden: !d.prs.length },
    h("summary", {}, `Pull requests (${d.prs.length})`), list);
  const key = `${d.id}|${state.dataVersion}|${state.gap}`;
  fetchPrs("detail", [d.id], key).then((data) => {
    if (!data) return;
    const known = new Map(data.prs.map((p) => [p.url, p]));
    // PRs only linked here (merged or commented on) stay, without a cost.
    const rows = [...data.prs, ...d.prs.filter((p) => !known.has(p.url))];
    box.hidden = !rows.length;
    box.querySelector("summary").textContent = `Pull requests (${rows.length})`;
    list.replaceChildren(...rows.map((p) => prItem(p, known.get(p.url), d.id, onOpenPr)));
  }).catch(() => {});
  return box;
}

function prItem(p, pr, sid, onOpenPr) {
  const share = pr?.sessions.find((s) => s.id === sid);
  return h("li", {},
    h("a", { href: p.url, target: "_blank", rel: "noopener" }, p.number ? `#${p.number}` : p.url),
    p.repo ? ` ${p.repo}` : "",
    pr?.title ? h("span", { class: "muted" }, ` ${pr.title}`) : null,
    pr ? h("div", { class: "muted" },
      `${fmtCost(pr.cost, pr.estimated)} in ${plural(pr.sessions.length, "session")}`,
      share && pr.sessions.length > 1 ? `, ${fmtCost(share.cost, pr.estimated)} here` : "",
      pr.opened_in === sid ? " · opened here" : "",
      onOpenPr ? [" · ", h("a", {
        href: "#", title: "Show it in the project's Pull requests table",
        onclick: (e) => { e.preventDefault(); onOpenPr(p.url); },
      }, "Pull requests table")] : null)
      : null);
}
