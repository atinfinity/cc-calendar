// Context size per request for the detail pane, drawn as inline SVG.
import { compactDetail, fmtDateTime, fmtTokens, h } from "./util.js";

const W = 300;
const H = 70;
const SVG_NS = "http://www.w3.org/2000/svg";
// Same as BLOAT_TOKENS in parser.py.
const BLOAT_TOKENS = 200000;

function svg(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) el.setAttribute(k, v);
  el.append(...children.filter(Boolean));
  return el;
}

// Round figures without the decimal: "200k", "1M".
const fmtRound = (n) => fmtTokens(n).replace(/\.0(?=[kMB]$)/, "");

// Why a session counts as bloated, for tooltips in the list and the detail pane.
export function bloatTitle(s) {
  return `Bloated context: ${s.context_over} requests each resent more than ${fmtRound(BLOAT_TOKENS)} tokens.`
    + " Every request resends the whole context, so these cost several times more than requests on a compacted context.";
}

// `d`: the session detail, with `context` ({points, requests, limit, bloat_tokens, compactions}).
export function contextCard(d) {
  const c = d.context;
  if (!c || c.requests < 2) return null;
  const n = c.requests;
  const peak = d.context_peak;
  // Show the model's limit as the top line when it is not far above the peak; a 1M window
  // would flatten a session that compacts at 200k.
  const top = c.limit && c.limit <= peak * 1.5 ? c.limit : peak * 1.1;
  const x = (i) => (n > 1 ? (i / (n - 1)) * W : W / 2);
  const y = (tok) => H - (Math.min(tok, top) / top) * H;
  const line = c.points.map(([i, , tok]) => `${x(i).toFixed(1)},${y(tok).toFixed(1)}`).join(" ");
  const area = `M${x(c.points[0][0]).toFixed(1)},${H} L${line.replaceAll(" ", " L")} L${x(c.points.at(-1)[0]).toFixed(1)},${H} Z`;

  const cursor = svg("line", { class: "ctx-cursor", y1: 0, y2: H, "vector-effect": "non-scaling-stroke", visibility: "hidden" });
  const chart = svg("svg", { class: "ctx-chart", viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img",
    "aria-label": `Context size per request, peak ${fmtTokens(peak)} tokens` },
    svg("path", { class: "ctx-area", d: area }),
    svg("polyline", { class: "ctx-line", points: line, "vector-effect": "non-scaling-stroke" }),
    c.bloat_tokens < top
      ? svg("line", { class: "ctx-bloat", x1: 0, x2: W, y1: y(c.bloat_tokens), y2: y(c.bloat_tokens), "vector-effect": "non-scaling-stroke" })
      : null,
    top === c.limit ? svg("line", { class: "ctx-limit", x1: 0, x2: W, y1: 0.5, y2: 0.5, "vector-effect": "non-scaling-stroke" }) : null,
    ...c.compactions.map((i) => svg("line", { class: "ctx-compact", x1: x(i), x2: x(i), y1: 0, y2: H, "vector-effect": "non-scaling-stroke" })),
    cursor,
  );

  const idle = `${n} requests · avg ${fmtTokens(d.context_avg)} · peak ${fmtTokens(peak)}`
    + (c.limit ? ` · limit ${fmtRound(c.limit)}` : "");
  const readout = h("div", { class: "muted ctx-readout" }, idle);
  // Hovering shows the nearest request and any compaction right before it.
  chart.addEventListener("mousemove", (e) => {
    const box = chart.getBoundingClientRect();
    const at = ((e.clientX - box.left) / box.width) * (n - 1);
    const p = c.points.reduce((a, b) => (Math.abs(b[0] - at) < Math.abs(a[0] - at) ? b : a));
    cursor.setAttribute("x1", x(p[0]));
    cursor.setAttribute("x2", x(p[0]));
    cursor.setAttribute("visibility", "visible");
    const k = c.compactions.findIndex((i) => Math.abs(x(i) - x(p[0])) < W / 100);
    readout.textContent = `Request ${p[0] + 1} · ${fmtDateTime(p[1])} · ${fmtTokens(p[2])} tokens`
      + (c.limit ? ` (${Math.round((100 * p[2]) / c.limit)}% of limit)` : "")
      + (k >= 0 ? ` · compaction${compactDetail(d.compactions[k]) ? ": " + compactDetail(d.compactions[k]) : ""}` : "");
  });
  chart.addEventListener("mouseleave", () => {
    cursor.setAttribute("visibility", "hidden");
    readout.textContent = idle;
  });

  const legend = h("div", { class: "ctx-legend muted" },
    h("span", { class: "key line" }, "context per request"),
    c.compactions.length ? h("span", { class: "key compact" }, `compaction (${c.compactions.length})`) : null,
    c.bloat_tokens < top ? h("span", { class: "key bloat" }, `${fmtRound(c.bloat_tokens)} (bloat line)`) : null,
    top === c.limit ? h("span", { class: "key limit" }, "model limit") : null);

  return h("section", { class: "card" },
    h("h3", {}, "Context size"),
    h("div", { class: "card-body" },
      d.context_bloated ? h("div", { class: "ctx-warn", title: bloatTitle(d) },
        `Bloated context: ${d.context_over} requests over ${fmtRound(c.bloat_tokens)} tokens`) : null,
      chart, readout, legend));
}
