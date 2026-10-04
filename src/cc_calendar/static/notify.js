// Desktop notifications when a live session needs input or ends interrupted.
import { prefs } from "./util.js";

const supported = typeof window !== "undefined" && "Notification" in window;
let enabled = supported && prefs.get("notify", false) && Notification.permission === "granted";
let previous = null; // id -> status at the last load; null until the first load

// What a status change means for the user, or null when it needs no attention.
export function transitionMessage(before, after) {
  if (before === "running" && after === "waiting") return "Waiting for your input";
  if ((before === "running" || before === "waiting") && after === "interrupted") return "Ended without finishing";
  return null;
}

// Call after every session load; notifies about changes since the previous load.
export function checkTransitions(sessions, onClick) {
  const now = new Map(sessions.map((s) => [s.id, s.status]));
  const before = previous;
  previous = now;
  // Nothing to compare on the first load; a focused tab already shows the change.
  if (!before || !enabled || document.hasFocus()) return;
  for (const s of sessions) {
    const message = transitionMessage(before.get(s.id), s.status);
    if (!message) continue;
    const n = new Notification(`${message}: ${s.title}`, {
      body: s.project_name + (s.branch ? ` · ${s.branch}` : ""),
      tag: s.id, // a newer change of the same session replaces the older notification
    });
    n.onclick = () => { window.focus(); onClick(s.id); n.close(); };
  }
}

// Wires the toggle button; asks for permission when it is turned on.
export function bindNotifyToggle(button) {
  if (!supported) {
    button.hidden = true;
    return;
  }
  const update = () => {
    button.classList.toggle("active", enabled);
    button.title = Notification.permission === "denied"
      ? "Notifications are blocked for this page in the browser's site settings"
      : enabled
        ? "Notifications on: a session waits for input or ends interrupted while this tab is in the background"
        : "Notify when a session waits for input or ends interrupted";
  };
  button.onclick = async () => {
    if (!enabled && Notification.permission !== "granted") await Notification.requestPermission();
    enabled = !enabled && Notification.permission === "granted";
    prefs.set("notify", enabled);
    update();
  };
  update();
}
