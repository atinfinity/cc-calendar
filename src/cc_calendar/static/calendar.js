// Weekly calendar: activity segments as bars, laid out in lanes like Google Calendar.
import { colorFor, legendItems, state } from "./app.js";
import { STATUS_LABELS, addDays, fmtCost, fmtDuration, fmtTime, h } from "./util.js";

const HOUR_MS = 3600_000;
const BUCKET_MS = 600_000;
const MIN_BAR_PX = 4;
let scrolledOnce = false;

export function renderCalendar(container, visible, { onSelect, legend, rangeLabel, rangeCount }) {
  const prevScroll = container.scrollTop;
  hideTip();
  const days = [...Array(7)].map((_, i) => addDays(state.weekStart, i));
  const weekStartMs = days[0].getTime();
  const weekEndMs = addDays(state.weekStart, 7).getTime();
  const hourPx = state.hourPx;
  const now = Date.now();
  const todayKey = new Date().toDateString();

  const inWeek = visible.filter((s) =>
    s.segments.some(([a, b]) => b >= weekStartMs && a < weekEndMs));

  const fmtDay = (d) => d.toLocaleDateString([], { weekday: "short", month: "numeric", day: "numeric" });
  rangeLabel.textContent = `${days[0].toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" })} – ${days[6].toLocaleDateString([], { month: "short", day: "numeric" })}`;
  rangeCount.textContent = `${inWeek.length} sessions`;
  legend.replaceChildren(...legendItems(inWeek).map((e) =>
    h("span", { title: e.title || "" }, h("span", { class: "dot", style: { background: e.color } }), `${e.label} ${e.n}`)));

  // Density: prompts + responses per 10 minutes, summed over visible sessions.
  const density = new Map();
  for (const s of inWeek) {
    for (const [bucket, n] of Object.entries(s.density)) {
      const b = Number(bucket);
      density.set(b, (density.get(b) || 0) + n);
    }
  }
  let maxDensity = 1;
  for (const [b, n] of density) {
    const t = b * BUCKET_MS;
    if (t >= weekStartMs && t < weekEndMs) maxDensity = Math.max(maxDensity, n);
  }

  const cols = "56px repeat(7, minmax(90px, 1fr))";
  const head = h("div", { class: "cal-head", style: { gridTemplateColumns: cols } },
    h("div", {}),
    ...days.map((d) => h("div", { class: d.toDateString() === todayKey ? "today" : "" }, fmtDay(d))));

  const body = h("div", { class: "cal-body", style: { gridTemplateColumns: cols, height: `${24 * hourPx}px` } });
  const gutter = h("div", { class: "gutter" });
  for (let hr = 1; hr < 24; hr++) {
    gutter.append(h("span", { style: { top: `${hr * hourPx}px` } }, `${hr}:00`));
  }
  body.append(gutter);

  for (const day of days) {
    const dayStart = day.getTime();
    const dayEnd = addDays(day, 1).getTime();
    const scale = (24 * hourPx) / (dayEnd - dayStart); // px per ms (handles DST days)
    const col = h("div", { class: "day" + (day.toDateString() === todayKey ? " today" : "") });
    for (let hr = 1; hr < 24; hr++) col.append(h("div", { class: "hour-line", style: { top: `${hr * hourPx}px` } }));

    for (let b = Math.floor(dayStart / BUCKET_MS); b * BUCKET_MS < dayEnd; b++) {
      const n = density.get(b);
      if (!n) continue;
      const top = (b * BUCKET_MS - dayStart) * scale;
      col.append(h("div", {
        class: "density",
        title: `${n} messages`,
        style: {
          top: `${top}px`,
          height: `${Math.max(1, BUCKET_MS * scale)}px`,
          background: `rgba(var(--density), ${0.15 + 0.85 * (n / maxDensity)})`,
        },
      }));
    }

    const bars = h("div", { class: "bars" });
    for (const p of layout(inWeek, dayStart, dayEnd, scale)) {
      const s = p.session;
      const top = (p.start - dayStart) * scale;
      const height = Math.max(MIN_BAR_PX, (p.end - p.start) * scale);
      const bar = h("div", {
        class: "bar" + (s.id === state.selectedId ? " selected" : ""),
        "data-sid": s.id,
        style: {
          top: `${top}px`,
          height: `${height}px`,
          left: `${(p.lane / p.lanes) * 100}%`,
          width: `calc(${100 / p.lanes}% - 1px)`,
          background: colorFor(s),
        },
        onclick: () => onSelect(s.id),
        onmouseenter: (e) => showTip(e, s, p),
        onmousemove: moveTip,
        onmouseleave: hideTip,
      }, height >= 15 ? s.title : "");
      bars.append(bar);
    }
    col.append(bars);

    if (now >= dayStart && now < dayEnd) {
      col.append(h("div", { class: "now-line", style: { top: `${(now - dayStart) * scale}px` } }));
    }
    body.append(col);
  }

  container.replaceChildren(head, body);
  if (!scrolledOnce) {
    scrolledOnce = true;
    container.scrollTop = Math.max(0, 7 * hourPx);
  } else {
    container.scrollTop = prevScroll;
  }
}

// Clip each session's segments to the day and assign side-by-side lanes to overlaps.
function layout(sessions, dayStart, dayEnd, scale) {
  const minMs = MIN_BAR_PX / scale;
  const pieces = [];
  for (const s of sessions) {
    for (const [a, b] of s.segments) {
      if (b < dayStart || a >= dayEnd) continue;
      const start = Math.max(a, dayStart);
      const end = Math.min(Math.max(b, a + 1), dayEnd);
      pieces.push({ session: s, start, end, visEnd: Math.max(end, start + minMs), segStart: a, segEnd: b });
    }
  }
  pieces.sort((x, y) => x.start - y.start || y.visEnd - x.visEnd);

  let cluster = [];
  let laneEnds = [];
  let clusterEnd = -Infinity;
  const flush = () => {
    for (const p of cluster) p.lanes = laneEnds.length;
    cluster = [];
    laneEnds = [];
  };
  for (const p of pieces) {
    if (p.start >= clusterEnd) flush();
    let lane = laneEnds.findIndex((end) => end <= p.start);
    if (lane < 0) {
      lane = laneEnds.length;
      laneEnds.push(p.visEnd);
    } else {
      laneEnds[lane] = p.visEnd;
    }
    p.lane = lane;
    cluster.push(p);
    clusterEnd = Math.max(clusterEnd, p.visEnd);
  }
  flush();
  return pieces;
}

const tip = () => document.getElementById("tooltip");

function showTip(e, s, p) {
  const t = tip();
  t.replaceChildren(
    h("div", { style: { fontWeight: 600 } }, s.title),
    h("div", { class: "muted" }, `${s.project_name}${s.branch ? " · " + s.branch : ""}`),
    h("div", {}, `${fmtTime(p.segStart)} – ${fmtTime(p.segEnd)} (${fmtDuration(p.segEnd - p.segStart)})`),
    h("div", { class: "muted" }, `${STATUS_LABELS[s.status]} · ${s.prompt_count} prompts · ${fmtCost(s.cost, s.cost_estimated)}`),
  );
  t.hidden = false;
  moveTip(e);
}

function moveTip(e) {
  const t = tip();
  const x = Math.min(e.clientX + 14, window.innerWidth - t.offsetWidth - 8);
  const y = Math.min(e.clientY + 14, window.innerHeight - t.offsetHeight - 8);
  t.style.left = `${x}px`;
  t.style.top = `${y}px`;
}

function hideTip() {
  tip().hidden = true;
}
