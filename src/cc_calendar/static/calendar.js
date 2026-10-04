// Week or day calendar: activity segments as bars, laid out in lanes like Google Calendar.
import { colorFor, legendItems, openDay, rangeDays, state } from "./app.js";
import { dayTotalLabel, renderSummary, summarize } from "./summary.js";
import { MARK_KINDS, compactDetail, MIN_HOUR_PX, STATUS_LABELS, addDays, fmtCost, fmtDuration, fmtTime, h, matchSnippet } from "./util.js";

const HOUR_MS = 3600_000;
const BUCKET_MS = 600_000;
const MIN_BAR_PX = 4;
// Lanes treat every bar as at least this long: its minimum height at the smallest zoom.
// Using the current zoom instead would make bars swap sides when zooming.
const MIN_LANE_MS = (MIN_BAR_PX / MIN_HOUR_PX) * HOUR_MS;
let scrolledOnce = false;

export function renderCalendar(container, visible, { onSelect, onOpenEvent, onToggleMarks, legend, rangeLabel, rangeCount, summaryPane }) {
  const prevScroll = container.scrollTop;
  hideTip();
  const days = rangeDays();
  const weekStartMs = days[0].getTime();
  const weekEndMs = addDays(days[days.length - 1], 1).getTime();
  const hourPx = state.hourPx;
  const now = Date.now();
  const todayKey = new Date().toDateString();

  const inWeek = visible.filter((s) =>
    s.segments.some(([a, b]) => b >= weekStartMs && a < weekEndMs));

  const fmtDay = (d) => d.toLocaleDateString([], { weekday: "short", month: "numeric", day: "numeric" });
  const first = days[0].toLocaleDateString([], { year: "numeric", month: "short", day: "numeric", weekday: days.length === 1 ? "short" : undefined });
  rangeLabel.textContent = days.length === 1
    ? first
    : `${first} – ${days[days.length - 1].toLocaleDateString([], { month: "short", day: "numeric" })}`;
  const bounds = days.map((d) => [d.getTime(), addDays(d, 1).getTime()]);
  const summary = summarize(inWeek, bounds);
  rangeCount.textContent = `${inWeek.length} sessions` + (summary.total.ms || summary.total.cost
    ? ` · ${fmtDuration(summary.total.ms)} · ${fmtCost(summary.total.cost, summary.total.estimated)}`
    : "");
  summaryPane.hidden = !state.showSummary;
  if (state.showSummary) {
    renderSummary(summaryPane, summary, days.map((d) => `${d.toLocaleDateString([], { weekday: "short" })} ${d.getDate()}`));
  }
  legend.replaceChildren(...legendItems(inWeek).map((e) =>
    h("span", { title: e.title || "" }, h("span", { class: "dot", style: { background: e.color } }), `${e.label} ${e.n}`)),
  h("button", {
    class: "marks-key" + (state.showMarks ? "" : " off"),
    title: state.showMarks ? "Hide event marks on the bars" : "Show event marks on the bars",
    onclick: onToggleMarks,
  }, ...MARK_KINDS.map(([kind, label]) => h("span", {}, h("i", { class: `mark-sample ${kind}` }), label))));

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

  const cols = `56px repeat(${days.length}, minmax(90px, 1fr))`;
  const isWeek = days.length > 1;
  const head = h("div", { class: "cal-head", style: { gridTemplateColumns: cols } },
    h("div", {}),
    ...days.map((d, i) => h("div", {
      class: [d.toDateString() === todayKey ? "today" : "", isWeek ? "link" : ""].join(" ").trim(),
      title: isWeek ? "Show this day" : "",
      onclick: isWeek ? () => openDay(d) : null,
    }, fmtDay(d), h("span", { class: "day-total" }, dayTotalLabel(summary.days[i])))));

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
    for (const p of layout(inWeek, dayStart, dayEnd)) {
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
      }, height >= 15 ? s.title : "", ...(state.showMarks ? barMarks(s, p, scale, height, onOpenEvent) : []));
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
function layout(sessions, dayStart, dayEnd) {
  const minMs = MIN_LANE_MS;
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

// Marks for the events that fall inside this piece of the bar; clicking one opens the log there.
function barMarks(s, p, scale, height, onOpenEvent) {
  if (height < 8) return [];
  // Keep marks at the very start or end of the bar fully visible.
  const y = (t) => Math.min(Math.max((t - p.start) * scale, 5), height - 5);
  return (s.marks || [])
    .filter(([t]) => t >= p.start && t <= p.end)
    .map(([t, kind, extra]) => h("i", {
      class: `mark m-${kind}`,
      style: { top: `${y(t)}px` },
      onclick: (e) => {
        e.stopPropagation();
        hideTip();
        onOpenEvent(s.id, t, kind);
      },
      onmouseenter: (e) => showMarkTip(e, s, t, kind, extra),
      onmouseleave: (e) => showTip(e, s, p),
    }));
}

function showMarkTip(e, s, t, kind, extra) {
  const label = MARK_KINDS.find(([k]) => k === kind)[1];
  const detail = kind === "compact" ? compactDetail(extra) : "";
  tip().replaceChildren(...[
    h("div", { style: { fontWeight: 600 } }, h("i", { class: `mark-sample ${kind}` }), ` ${label} · ${fmtTime(t)}`),
    detail ? h("div", {}, detail) : null,
    h("div", { class: "muted" }, s.title),
    h("div", { class: "muted" }, "Click to open the log here"),
  ].filter(Boolean));
  tip().hidden = false;
  moveTip(e);
}

function markCounts(s, from, to) {
  const n = {};
  for (const [t, kind] of s.marks || []) if (t >= from && t <= to) n[kind] = (n[kind] || 0) + 1;
  const parts = MARK_KINDS.filter(([k]) => n[k]).map(([k, , noun]) => `${n[k]} ${noun}${n[k] > 1 ? "s" : ""}`);
  return parts.length ? h("div", { class: "muted" }, `This block: ${parts.join(" · ")}`) : null;
}

const tip = () => document.getElementById("tooltip");

function showTip(e, s, p) {
  const t = tip();
  // replaceChildren would turn a null into the text "null".
  t.replaceChildren(...[
    h("div", { style: { fontWeight: 600 } }, s.title),
    h("div", { class: "muted" }, `${s.project_name}${s.branch ? " · " + s.branch : ""}`),
    h("div", {}, `${fmtTime(p.segStart)} – ${fmtTime(p.segEnd)} (${fmtDuration(p.segEnd - p.segStart)})`),
    h("div", { class: "muted" }, `${STATUS_LABELS[s.status]} · ${s.prompt_count} prompts · ${fmtCost(s.cost, s.cost_estimated)}`),
    markCounts(s, p.segStart, p.segEnd),
    matchSnippet(s, state.search),
  ].filter(Boolean));
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
