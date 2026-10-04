// Markdown report of the displayed range, for a standup note or a daily report.
import { activeMs, summarize } from "./summary.js";
import { addDays, fmtCost, fmtDuration } from "./util.js";

// `days` are the displayed dates; `label` is the range as shown in the toolbar.
export function buildReport(visible, days, label) {
  const from = days[0].getTime();
  const to = addDays(days[days.length - 1], 1).getTime();
  const sessions = visible
    .filter((s) => s.segments.some(([a, b]) => b >= from && a < to))
    .sort((a, b) => a.start - b.start);
  const { rows, total } = summarize(sessions, [[from, to]]);
  const lines = [`## Claude Code: ${label}`, ""];
  if (!rows.length) {
    lines.push("No activity.");
    return lines.join("\n") + "\n";
  }
  lines.push(`**${fmtDuration(total.ms)}** active · ${fmtCost(total.cost, total.estimated)} · ${sessions.length} session${sessions.length > 1 ? "s" : ""}`, "");
  for (const r of rows) {
    lines.push(`### ${r.name} (${fmtDuration(r.ms)} · ${fmtCost(r.cost, r.estimated)})`, "");
    for (const s of sessions.filter((x) => x.project === r.project)) {
      lines.push(`- ${linkRefs(oneLine(s.title), s.repo_url)} (${fmtDuration(activeMs(s, from, to))})`);
      for (const c of (s.commit_list || []).filter((c) => c.ts == null || (c.ts >= from && c.ts < to))) {
        const sha = c.sha ? `\`${c.sha.slice(0, 7)}\` ` : "";
        lines.push(`  - ${sha}${linkRefs(oneLine(c.subject || "(no message)"), s.repo_url)}`);
      }
    }
    lines.push("");
  }
  return lines.join("\n");
}

// "#12" -> "[#12](https://github.com/o/r/issues/12)"; GitHub redirects to the PR when it is one.
function linkRefs(text, repo) {
  if (!repo) return text;
  return text.replace(/(^|[^\w&#/[])#(\d+)\b/g, (_, pre, n) => `${pre}[#${n}](${repo}/issues/${n})`);
}

function oneLine(text) {
  return String(text).replace(/\s+/g, " ").trim();
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Fallback for browsers that block the async clipboard API.
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.append(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}
