// Keyboard shortcuts and the overlay that lists them.
import { h } from "./util.js";

const $ = (id) => document.getElementById(id);

// [keys, description]: what the "?" overlay shows.
const SHORTCUTS = [
  [["←", "→"], "Previous / next day, week, month or year"],
  [["t"], "Today, this week, month or year"],
  [["d", "w", "m", "y"], "Day / week / month / year"],
  [["c", "l"], "Calendar / list"],
  [["/"], "Search"],
  [["j", "k"], "Next / previous session"],
  [["Enter", "o"], "Open the selected session's transcript"],
  [["Esc"], "Close the topmost pane"],
  [["?"], "Show this list"],
];

const typing = (el) =>
  el instanceof HTMLElement && (el.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName));

function showHelp(show) {
  const modal = $("help-modal");
  modal.hidden = !show;
  if (show) $("help-close").focus();
}

// `keys` maps e.key to a handler; a handler that returns false did not apply, so the key keeps
// its default action. `closers` run in order on Esc until one returns true.
export function bindShortcuts(keys, closers) {
  $("help-keys").replaceChildren(...SHORTCUTS.map(([ks, text]) => h("tr", {},
    h("td", {}, ...ks.flatMap((k, i) => [i ? " " : null, h("kbd", {}, k)])),
    h("td", {}, text))));
  $("help-btn").onclick = () => showHelp($("help-modal").hidden);
  $("help-close").onclick = () => showHelp(false);
  $("help-modal").addEventListener("click", (e) => {
    if (e.target.id === "help-modal") showHelp(false);
  });

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
    if (e.key === "Escape") {
      if (!$("help-modal").hidden) showHelp(false);
      else if (!$("log-modal").hidden) return; // the transcript closes itself
      else if (!closers.some((close) => close())) return;
      // Also keeps the search box from clearing its text.
      e.preventDefault();
      return;
    }
    // While the transcript is open only Esc works; in a form field keys are typed as usual.
    if (!$("log-modal").hidden || typing(e.target)) return;
    if (e.key === "?") {
      showHelp($("help-modal").hidden);
      e.preventDefault();
      return;
    }
    if (!$("help-modal").hidden) return;
    // Enter on a focused button or link presses it.
    if (e.key === "Enter" && e.target instanceof Element && e.target.closest("button, a, summary")) return;
    const handler = keys[e.key];
    if (handler && handler() !== false) e.preventDefault();
  });
}
