// Concurrent active sessions over one day: a step line in a narrow column beside the day view.
import { fmtDuration, fmtTime, h } from "./util.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const W = 60;
const PAD = 6;

function svg(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) el.setAttribute(k, v);
  el.append(...children.filter(Boolean));
  return el;
}

// [start, end, n] steps covering [from, to): how many sessions had an active segment (a drawn
// bar) at each moment. Adjacent steps always differ in n.
export function concurrency(sessions, from, to) {
  const events = [];
  for (const s of sessions) {
    for (const [a, b] of s.segments) {
      const lo = Math.max(a, from);
      const hi = Math.min(b, to);
      if (hi > lo) events.push([lo, 1], [hi, -1]);
    }
  }
  // At the same moment, ends go first, so back-to-back segments do not count twice.
  events.sort((x, y) => x[0] - y[0] || x[1] - y[1]);
  const steps = [];
  let n = 0;
  let t = from;
  const push = (end) => {
    if (end <= t) return;
    const last = steps.at(-1);
    if (last && last[2] === n) last[1] = end;
    else steps.push([t, end, n]);
    t = end;
  };
  for (const [at, d] of events) {
    push(at);
    n += d;
  }
  push(to);
  return steps;
}

// Header cell and body column for the day view. `scale` is px per ms.
export function concurrencyColumn(sessions, dayStart, dayEnd, scale) {
  const steps = concurrency(sessions, dayStart, dayEnd);
  const peak = Math.max(0, ...steps.map((st) => st[2]));
  const parallel = steps.reduce((ms, [a, b, n]) => ms + (n >= 2 ? b - a : 0), 0);
  const head = h("div", {
    class: "conc-head",
    title: "Sessions active at the same time (drawn bars that overlap)"
      + (parallel ? `\nTwo or more at once for ${fmtDuration(parallel)}` : ""),
  }, "Parallel", h("span", { class: "day-total" }, peak ? `peak ${peak}` : ""));
  const height = (dayEnd - dayStart) * scale;
  const col = h("div", { class: "conc" });
  if (!peak) return { head, col };

  const x = (n) => PAD + (n / peak) * (W - 2 * PAD);
  const y = (t) => ((t - dayStart) * scale).toFixed(1);
  const points = steps.flatMap(([a, b, n]) => [`${x(n)},${y(a)}`, `${x(n)},${y(b)}`]).join(" ");
  const guides = peak <= 10
    ? Array.from({ length: peak }, (_, i) => svg("line", { class: "conc-guide", x1: x(i + 1), x2: x(i + 1), y1: 0, y2: height }))
    : [];
  const hits = steps.filter((st) => st[2] > 0).map(([a, b, n]) =>
    svg("rect", { class: "conc-hit", x: 0, y: y(a), width: W, height: Math.max(1, (b - a) * scale).toFixed(1) },
      svg("title", {}, `${n} session${n > 1 ? "s" : ""} active · ${fmtTime(a)} – ${fmtTime(b)}`)));
  col.append(svg("svg", { width: W, height, viewBox: `0 0 ${W} ${height}`, role: "img",
    "aria-label": `Concurrent active sessions, peak ${peak}` },
    ...guides,
    svg("polygon", { class: "conc-area", points: `${x(0)},${y(dayStart)} ${points} ${x(0)},${y(dayEnd)}` }),
    svg("polyline", { class: "conc-line", points }),
    ...hits));
  return { head, col };
}
