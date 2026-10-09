// The Notes card of the detail pane: an outcome rating, a free-text note and tags, saved to the
// server right away.
import { OUTCOMES, h } from "./util.js";

// The editor on screen. It is kept across re-renders of the detail pane while it is being
// edited, so live updates never take away focus or text that is still being typed.
let current = null;

async function save(sid, note, tags, outcome) {
  const res = await fetch(`/api/sessions/${encodeURIComponent(sid)}/notes`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note, tags, outcome }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`);
  return body;
}

// `tags` are all tags in use, most used first, for suggestions. `error` is set when the notes
// file could not be read, which turns editing off. `onSaved(sid, {note, tags, outcome})` runs
// after a save.
export function notesCard(d, { tags: allTags, error, onSaved }) {
  if (current?.sid === d.id && current.busy()) return current.el;

  if (error) {
    current = null;
    return h("section", { class: "card notes-card" }, h("h3", {}, "Notes"),
      h("div", { class: "card-body muted" }, `Notes are turned off: ${error}`));
  }

  let saved = { note: d.note || "", tags: [...(d.tags || [])], outcome: d.outcome || "" };
  let tags = [...saved.tags];
  let outcome = saved.outcome;
  const status = h("span", { class: "notes-status", role: "status" });
  const textarea = h("textarea", {
    rows: 3,
    maxlength: 2000,
    placeholder: "Note — saved when you leave the box (⌘/Ctrl+Enter saves too)",
    "aria-label": "Note",
  });
  textarea.value = saved.note;
  const chips = h("span", { class: "tags" });
  const listId = `tag-options-${d.id}`;
  const input = h("input", {
    type: "text",
    class: "tag-input",
    list: listId,
    maxlength: 40,
    placeholder: "Add tag…",
    "aria-label": "Add tag",
    title: "Enter or a comma adds the tag",
  });
  const datalist = h("datalist", { id: listId });

  let timer;
  function showStatus(text, cls = "") {
    status.textContent = text;
    status.className = `notes-status ${cls}`;
    clearTimeout(timer);
    if (!cls) timer = setTimeout(() => { status.textContent = ""; }, 1500);
  }

  async function commit() {
    const note = textarea.value;
    if (note.trim() === saved.note.trim() && tags.join("\n") === saved.tags.join("\n")
      && outcome === saved.outcome) return;
    const sid = d.id;
    try {
      const out = await save(sid, note, tags, outcome);
      saved = { ...out, outcome: out.outcome || "" };
      // The server may have trimmed the note or re-cased a tag.
      if (textarea.value === note && document.activeElement !== textarea) textarea.value = saved.note;
      tags = [...saved.tags];
      outcome = saved.outcome;
      renderTags();
      renderOutcome();
      showStatus("Saved ✓");
      onSaved(sid, saved);
    } catch (e) {
      showStatus(`Not saved: ${e.message}`, "error");
    }
  }

  function renderTags() {
    chips.replaceChildren(...tags.map((t) => h("span", { class: "tag" }, t,
      h("button", {
        class: "tag-remove",
        title: `Remove ${t}`,
        "aria-label": `Remove tag ${t}`,
        onclick: () => { tags = tags.filter((x) => x !== t); renderTags(); commit(); input.focus(); },
      }, "✕"))));
    const have = new Set(tags.map((t) => t.toLowerCase()));
    datalist.replaceChildren(...allTags.filter((t) => !have.has(t.tag.toLowerCase()))
      .map((t) => h("option", { value: t.tag })));
  }

  // One click sets the outcome; clicking the active one again clears it.
  const outcomeButtons = OUTCOMES.map(([v, label, symbol]) => h("button", {
    class: `outcome-${v}`,
    title: `Rate this session ${label.toLowerCase()} (click again to clear)`,
    onclick: () => { outcome = outcome === v ? "" : v; renderOutcome(); commit(); },
  }, `${symbol} ${label}`));

  function renderOutcome() {
    OUTCOMES.forEach(([v], i) => {
      outcomeButtons[i].classList.toggle("active", outcome === v);
      outcomeButtons[i].setAttribute("aria-pressed", String(outcome === v));
    });
  }

  function addTags() {
    const add = input.value.split(",").map((t) => t.trim().replace(/\s+/g, " ")).filter(Boolean);
    input.value = "";
    if (!add.length) return;
    const have = new Set(tags.map((t) => t.toLowerCase()));
    for (const t of add) {
      if (have.has(t.toLowerCase())) continue;
      have.add(t.toLowerCase());
      // Reuse the spelling of a tag already in use elsewhere.
      tags.push(allTags.find((x) => x.tag.toLowerCase() === t.toLowerCase())?.tag || t);
    }
    renderTags();
    commit();
  }

  textarea.addEventListener("blur", commit);
  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      commit();
    } else if (e.key === "Escape") {
      // Leave the box (saving it) rather than closing the pane.
      e.preventDefault();
      e.stopPropagation();
      textarea.blur();
    }
  });
  input.addEventListener("keydown", (e) => {
    if (e.isComposing) return;
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTags();
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      input.value = "";
      input.blur();
    }
  });
  // Choosing a suggestion fills the box without a key press.
  input.addEventListener("input", (e) => {
    if (e.inputType === "insertReplacementText") addTags();
  });

  const body = h("div", { class: "card-body" }, textarea, h("div", { class: "tag-row" }, chips, input, datalist));
  const outcomeRow = h("div", { class: "outcome-row" },
    h("span", { class: "muted" }, "Outcome"), h("span", { class: "seg small", role: "group", "aria-label": "Outcome" }, ...outcomeButtons));
  const heading = h("h3", {}, "Notes ", status);
  const el = h("section", { class: "card notes-card" }, heading, outcomeRow, body);
  renderTags();
  renderOutcome();

  if (!saved.note && !saved.tags.length) {
    // The heading is hidden, so the save status shows next to the rating.
    el.classList.add("collapsed");
    outcomeRow.append(status);
    el.append(h("button", {
      class: "notes-add",
      onclick: (e) => {
        e.currentTarget.remove();
        el.classList.remove("collapsed");
        heading.append(status);
        textarea.focus();
      },
    }, "+ Add note or tags"));
  }

  current = {
    sid: d.id,
    el,
    busy: () => el.contains(document.activeElement) || textarea.value.trim() !== saved.note || input.value !== "",
  };
  return el;
}
