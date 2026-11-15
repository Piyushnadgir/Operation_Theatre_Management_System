// Small helpers for building the page safely and showing messages.
//
// Safety rule (OT-SR-006, SAD 3.9): data from the API is NEVER inserted with innerHTML.
// el() puts all text in with textContent / text nodes, which the browser always treats
// as plain text. A patient called "<script>alert(1)</script>" is shown exactly like that
// and never runs. This is the app's escape helper: there is no other way to add text.

// Properties that must be set on the element itself rather than as attributes.
const PROPERTIES = new Set(["value", "checked", "disabled", "selected", "hidden", "required"]);

// el("button", { class: "button", onclick: save }, "Save") -> <button class="button">Save</button>
export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null) continue;
    if (key === "text") node.textContent = value;
    else if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (PROPERTIES.has(key)) node[key] = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    // Strings become text nodes, so they can never become HTML.
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

// Show a message in a message box. kind is "error", "success", "info" or "loading".
export function showMessage(box, kind, text) {
  box.className = `message message-${kind}`;
  box.textContent = text;
  box.hidden = false;
}

export function hideMessage(box) {
  box.hidden = true;
  box.textContent = "";
}

// The global message box at the top of the page.
export function notify(kind, text) {
  const box = document.getElementById("global-message");
  showMessage(box, kind, text);
  // Errors take keyboard focus so screen-reader and keyboard users notice them.
  if (kind === "error") {
    box.tabIndex = -1;
    box.focus();
  }
}

// Disable a button while a request runs, so it cannot be pressed twice.
export async function whileBusy(button, label, work) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = label;
  try {
    return await work();
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

// ---------- dates ----------
// Times are hospital clock time with no time zone, as the API stores them.

function pad(number) {
  return String(number).padStart(2, "0");
}

// Date -> "2026-12-01T09:00", the format of <input type="datetime-local"> and of the API.
export function toInputDateTime(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

// Date -> "2026-12-01", for <input type="date">.
export function toInputDate(date) {
  return toInputDateTime(date).slice(0, 10);
}

// "2026-12-01T09:00:00" -> "01 Dec 2026, 09:00"
export function formatDateTime(isoText) {
  const date = new Date(isoText);
  return date.toLocaleString("en-GB", {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

// "2026-12-01T09:00:00" -> "09:00"
export function formatTime(isoText) {
  return new Date(isoText).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

// Add minutes to a "YYYY-MM-DDTHH:MM" value and return the same format.
export function addMinutes(inputValue, minutes) {
  const date = new Date(inputValue);
  date.setMinutes(date.getMinutes() + minutes);
  return toInputDateTime(date);
}

// ---------- status labels: never colour alone (SAD 4.5) ----------
// Each label has an icon and words; the CSS class adds the colour.

const PRIORITY_LABELS = {
  critical: "⚠ Critical",
  urgent: "▲ Urgent",
  routine: "● Routine",
};

const STATUS_LABELS = {
  available: "✔ Available",
  in_use: "● In use",
  occupied: "● Occupied",
  cleaning: "⟳ Cleaning",
  maintenance: "✖ Maintenance",
  scheduled: "◷ Scheduled",
  in_progress: "▶ In progress",
  completed: "✔ Completed",
  cancelled: "✖ Cancelled",
};

export function priorityBadge(priority) {
  return el("span", { class: `badge priority-${priority}`, text: PRIORITY_LABELS[priority] || priority });
}

export function statusBadge(status) {
  return el("span", { class: `badge status-${status}`, text: STATUS_LABELS[status] || status });
}

// Equipment asset tag as on the SAD Figure 4.3 board: equipment 12 -> "EQ-0012".
export function assetTag(equipmentId) {
  return "EQ-" + String(equipmentId).padStart(4, "0");
}

// A form in a modal dialog. onSubmit runs when Save is pressed; if it throws, the
// error is shown in the dialog and it stays open. Esc or Close closes it.
export function openDialog(title, body, onSubmit, saveLabel = "Save") {
  const message = el("div", { class: "message", role: "alert", tabindex: "-1", hidden: true });
  const save = el("button", { type: "submit", class: "button" }, saveLabel);
  const close = el("button", { type: "button", class: "button button-secondary" }, "Close");
  const form = el("form", { method: "dialog", novalidate: true },
    el("h2", { text: title }), body, message, el("p", { class: "toolbar" }, save, close));
  const dialog = el("dialog", { "aria-label": title }, form);
  close.addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => dialog.remove());
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    hideMessage(message);
    try {
      await whileBusy(save, "Saving…", onSubmit);
      dialog.close();
    } catch (error) {
      showMessage(message, "error", error.message);
      message.focus();
    }
  });
  document.body.append(dialog);
  dialog.showModal();
  const first = form.querySelector("input, select");
  if (first) first.focus();
}
