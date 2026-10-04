// Keyboard shortcuts and the overlay that lists them.
import { h } from "./util.js";

const $ = (id) => document.getElementById(id);

// [section, [keys, description] rows]: what the "?" overlay shows.
const SHORTCUTS = [
  [null, [
    [["←", "→"], "Previous / next day, week, month or year"],
    [["t"], "Today, this week, month or year"],
    [["d", "w", "m", "y"], "Day / week / month / year"],
    [["c", "l"], "Calendar / list"],
    [["/"], "Search"],
    [["j", "k"], "Next / previous session"],
    [["Enter", "o"], "Open the selected session's transcript"],
    [["Esc"], "Close the topmost pane"],
    [["?"], "Show this list"],
  ]],
  ["Transcript", [
    [["n", "p"], "Next / previous event"],
    [["]", "["], "Next / previous prompt"],
    [["s"], "Stats"],
    [["e"], "Expand tools"],
    [["b"], "Back to the parent session"],
    [["↑", "↓", "Space"], "Scroll"],
    [["Esc"], "Close the transcript"],
  ]],
];

// Whether keys typed at `el` belong to it; checkboxes and buttons take no letters.
export const typing = (el) =>
  el instanceof HTMLElement && (el.isContentEditable || ["SELECT", "TEXTAREA"].includes(el.tagName) ||
    (el.tagName === "INPUT" && !["checkbox", "radio", "button", "submit", "reset"].includes(el.type)));

export const helpOpen = () => !$("help-modal").hidden;

let returnFocus = null; // where focus goes back to when the overlay closes

function showHelp(show) {
  if (show === helpOpen()) return;
  $("help-modal").hidden = !show;
  if (show) {
    returnFocus = document.activeElement;
    $("help-close").focus();
  } else {
    returnFocus?.focus?.({ preventScroll: true });
    returnFocus = null;
    // The element may have been hidden meanwhile; do not leave focus on the closed overlay.
    if ($("help-modal").contains(document.activeElement)) document.activeElement.blur();
  }
}

// `keys` maps e.key to a handler; a handler that returns false did not apply, so the key keeps
// its default action. `closers` run in order on Esc until one returns true.
export function bindShortcuts(keys, closers) {
  $("help-keys").replaceChildren(...SHORTCUTS.flatMap(([section, rows]) => [
    section ? h("tr", {}, h("th", { colspan: 2 }, section)) : null,
    ...rows.map(([ks, text]) => h("tr", {},
      h("td", {}, ...ks.flatMap((k, i) => [i ? " " : null, h("kbd", {}, k)])),
      h("td", {}, text))),
  ].filter(Boolean)));
  $("help-btn").onclick = () => showHelp(!helpOpen());
  $("help-close").onclick = () => showHelp(false);
  $("help-modal").addEventListener("click", (e) => {
    if (e.target.id === "help-modal") showHelp(false);
  });

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
    if (e.key === "Escape") {
      if (helpOpen()) showHelp(false);
      else if (!$("log-modal").hidden) return; // the transcript closes itself
      else if (!closers.some((close) => close())) return;
      // Also keeps the search box from clearing its text.
      e.preventDefault();
      return;
    }
    // In a form field keys are typed as usual.
    if (typing(e.target)) return;
    if (e.key === "?") {
      showHelp(!helpOpen());
      e.preventDefault();
      return;
    }
    // The transcript has its own keys (transcript.js).
    if (helpOpen() || !$("log-modal").hidden) return;
    // Enter on a focused button or link presses it.
    if (e.key === "Enter" && e.target instanceof Element && e.target.closest("button, a, summary")) return;
    const handler = keys[e.key];
    if (handler && handler() !== false) e.preventDefault();
  });
}
