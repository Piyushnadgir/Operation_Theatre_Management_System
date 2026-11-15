// Emergencies screen (OT-F-020 to OT-F-023, SAD 4.5 "one-screen emergency form").
// Admins, doctors and schedulers log an emergency on one screen; the result shows
// which surgeries were moved. Everyone sees the priority queue.

import { api } from "./api.js";
import { refreshEmergencyBanner } from "./banner.js";
import {
  addMinutes, el, formatDateTime, formatTime, hideMessage, priorityBadge, showMessage,
  statusBadge, toInputDateTime, whileBusy,
} from "./dom.js";
import { loadLookups, theatreName } from "./lookups.js";
import { can } from "./roles.js";
import { durationSelect } from "./schedule.js";

// Now, rounded up to the next 5 minutes: an emergency starts as soon as possible.
function nowRounded() {
  const date = new Date();
  date.setSeconds(0, 0);
  date.setMinutes(Math.ceil(date.getMinutes() / 5) * 5);
  return toInputDateTime(date);
}

export async function renderEmergencies(container) {
  const lookups = await loadLookups();
  const queueSection = el("section", { class: "card", "aria-labelledby": "queue-title" });
  container.append(el("h1", { tabindex: "-1", text: "Emergencies" }));
  if (can("logEmergency")) container.append(intakeForm(lookups, () => drawQueue(queueSection, lookups)));
  container.append(queueSection);
  await drawQueue(queueSection, lookups);
}

function intakeForm(lookups, onLogged) {
  const message = el("div", { class: "message", role: "alert", tabindex: "-1", hidden: true });
  const result = el("div", { "aria-live": "polite" });
  const patient = el("input", { id: "e-patient", required: true, maxlength: "100", autocomplete: "off" });
  const priority = el("select", { id: "e-priority" },
    el("option", { value: "critical", selected: true }, "⚠ Critical"),
    el("option", { value: "urgent" }, "▲ Urgent"));
  const theatres = lookups.theatres.filter((item) => item.isActive && item.status !== "maintenance");
  const theatre = el("select", { id: "e-theatre", required: true },
    theatres.map((item) => el("option", { value: String(item.theatreId) }, item.name)));
  const start = el("input", { id: "e-start", type: "datetime-local", step: "300", value: nowRounded() });
  const duration = durationSelect("e-duration", 60);
  const save = el("button", { type: "submit", class: "button button-emergency" }, "⚠ Log emergency");

  // Doctors and nurses can be named here if this role may list staff (admin, scheduler).
  const staffBoxes = (type) => lookups.staff.filter((person) => person.is_active && person.staff_type === type)
    .map((person) => el("label", {}, el("input", { type: "checkbox", name: type, value: String(person.staff_id) }), ` ${person.name}`));
  const staffFields = lookups.staff.length === 0 ? [] : [
    el("fieldset", { class: "field" }, el("legend", { text: "Doctors" }), el("div", { class: "check-list" }, staffBoxes("doctor"))),
    el("fieldset", { class: "field" }, el("legend", { text: "Nurses" }), el("div", { class: "check-list" }, staffBoxes("nurse"))),
  ];

  const form = el("form", { class: "card emergency-form", novalidate: true, "aria-labelledby": "intake-title" },
    el("h2", { id: "intake-title", text: "Log an emergency" }),
    el("div", { class: "form-grid" },
      el("div", { class: "field" }, el("label", { for: "e-patient", text: "Patient name" }), patient),
      el("div", { class: "field" }, el("label", { for: "e-priority", text: "Priority" }), priority),
      el("div", { class: "field" }, el("label", { for: "e-theatre", text: "Theatre" }), theatre),
      el("div", { class: "field" }, el("label", { for: "e-start", text: "Start" }), start),
      el("div", { class: "field" }, el("label", { for: "e-duration", text: "Duration" }), duration),
    ),
    el("div", { class: "form-grid" }, staffFields),
    message,
    save,
    result);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    hideMessage(message);
    result.replaceChildren();
    if (!patient.value.trim() || !theatre.value || !start.value) {
      showMessage(message, "error", "Enter the patient name, a theatre and a start time.");
      message.focus();
      return;
    }
    const ids = (name) => [...form.querySelectorAll(`input[name=${name}]:checked`)].map((box) => Number(box.value));
    const body = {
      patient_name: patient.value.trim(),
      priority: priority.value,
      theatre_id: Number(theatre.value),
      start_time: start.value,
      end_time: addMinutes(start.value, Number(duration.value)),
      doctor_ids: ids("doctor"),
      nurse_ids: ids("nurse"),
    };
    try {
      const response = await whileBusy(save, "Logging…", () => api("POST", "/emergencies", { body }));
      result.replaceChildren(emergencyResult(response, lookups));
      patient.value = "";
      refreshEmergencyBanner();
      onLogged();
      result.querySelector("h3").focus();
    } catch (error) {
      // 409: the slot is held by an equal or higher priority surgery (OT-F-022).
      showMessage(message, "error", `Not logged: ${error.message}`);
      message.focus();
    }
  });
  return form;
}

// The outcome: the emergency slot and the surgeries that were moved for it.
function emergencyResult(response, lookups) {
  const slot = response.slot;
  const box = el("div", { class: "message message-success" },
    el("h3", { tabindex: "-1", text: `Emergency logged for ${slot.patient_name}` }),
    el("p", {}, priorityBadge(slot.priority),
      ` ${theatreName(lookups, slot.theatre_id)}, ${formatDateTime(slot.start_time)}–${formatTime(slot.end_time)}`));
  if (response.moved_surgeries.length === 0) {
    box.append(el("p", { text: "No other surgery had to be moved." }));
  } else {
    box.append(
      el("p", { text: `${response.moved_surgeries.length} surgery(ies) moved to make room:` }),
      el("div", { class: "table-wrap" }, el("table", {},
        el("thead", {}, el("tr", {}, ["Patient", "Was", "Now"].map((title) => el("th", { scope: "col", text: title })))),
        el("tbody", {}, response.moved_surgeries.map((moved) => el("tr", {},
          el("td", { text: moved.patient_name }),
          el("td", { text: `${formatDateTime(moved.old_start_time)}–${formatTime(moved.old_end_time)}` }),
          el("td", { text: `${formatDateTime(moved.new_start_time)}–${formatTime(moved.new_end_time)}` })))))));
  }
  box.append(el("p", { text: `${response.notifications_created} notification(s) sent to the people affected.` }));
  return box;
}

// OT-F-021: critical before urgent, first come first served within a priority.
async function drawQueue(section, lookups) {
  const queue = await api("GET", "/emergencies/queue");
  section.replaceChildren(el("h2", { id: "queue-title", text: "Emergency queue" }));
  if (queue.length === 0) {
    section.append(el("p", { class: "hint", text: "No active emergencies." }));
    return;
  }
  section.append(el("div", { class: "table-wrap" }, el("table", {},
    el("thead", {}, el("tr", {}, ["#", "Patient", "Priority", "Theatre", "When", "Status"].map((title) => el("th", { scope: "col", text: title })))),
    el("tbody", {}, queue.map((item, index) => el("tr", {},
      el("td", { text: String(index + 1) }),
      el("td", { text: item.patient_name }),
      el("td", {}, priorityBadge(item.priority)),
      el("td", { text: theatreName(lookups, item.theatre_id) }),
      el("td", { text: `${formatDateTime(item.start_time)}–${formatTime(item.end_time)}` }),
      el("td", {}, statusBadge(item.status))))))));
}
