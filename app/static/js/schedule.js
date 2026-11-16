// "Schedule a surgery" form (OT-F-010, OT-F-013, OT-NF-003).
//
// Designed for at most 8 interactions (counted in docs/ui_notes.md):
// sensible defaults (tomorrow 09:00, 2 hours, routine), the first free theatre is
// picked automatically, and availability is shown next to every choice.
// On a 409 the message names each busy resource and every entry is kept,
// so the scheduler only fixes what is wrong and saves again.

import { api } from "./api.js";
import {
  addMinutes, assetTag, checkOption, el, hideMessage, reasonWithoutName, showMessage, toInputDateTime, whileBusy,
} from "./dom.js";
import { describeConflicts } from "./lookups.js";

const DURATIONS = [30, 60, 90, 120, 150, 180, 240, 300];

export function durationLabel(minutes) {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return [hours ? `${hours} h` : "", rest ? `${rest} min` : ""].join(" ").trim();
}

export function durationSelect(id, selectedMinutes) {
  return el("select", { id },
    DURATIONS.map((minutes) =>
      el("option", { value: String(minutes), selected: minutes === selectedMinutes }, durationLabel(minutes))));
}

function tomorrowAtNine() {
  const date = new Date();
  date.setDate(date.getDate() + 1);
  date.setHours(9, 0, 0, 0);
  return toInputDateTime(date);
}

// A field with a visible label (every input has a label: SAD 4.5 accessibility).
function field(labelText, input, ...extra) {
  return el("div", { class: "field" }, el("label", { for: input.id, text: labelText }), input, ...extra);
}

// The same, spanning two grid columns so the form grid has no empty cell.
function wideField(labelText, input, ...extra) {
  const wide = field(labelText, input, ...extra);
  wide.classList.add("field-wide");
  return wide;
}

// A list of checkboxes. items: [{ id, label, problem }]; a problem disables the box and is
// shown on a second line, without repeating the name.
function fillCheckList(container, name, items, checkedIds) {
  container.replaceChildren(
    ...items.map((item) => checkOption({
      name,
      value: item.id,
      label: item.label,
      note: item.problem ? `✖ ${reasonWithoutName(item.problem, item.label)}` : "✔ Available",
      checked: !item.problem && checkedIds.has(item.id),
      disabled: Boolean(item.problem),
    })),
  );
  if (items.length === 0) container.append(el("p", { class: "hint", text: "None available." }));
}

function checkedIds(container) {
  return [...container.querySelectorAll("input:checked")].map((box) => Number(box.value));
}

// Build the form. lookups comes from loadLookups(); onSaved(surgery) runs after a save.
export function scheduleForm(lookups, onSaved) {
  const message = el("div", { class: "message", role: "alert", tabindex: "-1", hidden: true });
  const patient = el("input", { id: "s-patient", required: true, maxlength: "100", autocomplete: "off" });
  const start = el("input", { id: "s-start", type: "datetime-local", required: true, step: "300", value: tomorrowAtNine() });
  const duration = durationSelect("s-duration", 120);
  const priority = el("select", { id: "s-priority" },
    el("option", { value: "routine", selected: true }, "● Routine"),
    el("option", { value: "urgent" }, "▲ Urgent"),
    el("option", { value: "critical" }, "⚠ Critical"));
  const theatre = el("select", { id: "s-theatre", required: true });
  const availability = el("p", { class: "hint", "aria-live": "polite" });
  const doctors = el("div", { class: "check-list", id: "s-doctors" });
  const nurses = el("div", { class: "check-list", id: "s-nurses" });
  const equipment = el("div", { class: "check-list", id: "s-equipment" });
  const equipmentNote = el("p", { class: "hint" });
  const save = el("button", { type: "submit", class: "button" }, "Schedule surgery");

  // Once the user picks a theatre themselves, it is not changed automatically.
  let theatreChosenByUser = false;
  theatre.addEventListener("change", () => { theatreChosenByUser = true; });

  function slot() {
    return { start: start.value, end: addMinutes(start.value, Number(duration.value)) };
  }

  // Check every theatre, person and item for the chosen time. A counter makes sure
  // an older, slower answer cannot overwrite a newer one.
  let refreshNumber = 0;
  async function refreshAvailability() {
    if (!start.value) return;
    const myNumber = ++refreshNumber;
    const range = slot();
    availability.textContent = "Checking availability…";
    try {
      const theatres = lookups.theatres.filter((item) => item.isActive);
      const theatreResults = await Promise.all(theatres.map((item) =>
        api("GET", `/theatres/${item.theatreId}/availability`, { query: range })));

      const activeStaff = lookups.staff.filter((person) => person.is_active);
      const doctorList = activeStaff.filter((person) => person.staff_type === "doctor");
      const nurseList = activeStaff.filter((person) => person.staff_type === "nurse");
      const staffCheck = activeStaff.length === 0 ? { conflicts: [] } : await api("POST", "/staff/validate-assignment", {
        body: {
          doctor_ids: doctorList.map((person) => person.staff_id),
          nurse_ids: nurseList.map((person) => person.staff_id),
          start_time: range.start,
          end_time: range.end,
        },
      });

      const items = lookups.equipment.filter((item) => item.isActive && item.status !== "maintenance");
      const itemResults = await Promise.all(items.map((item) =>
        api("GET", `/equipment/${item.equipmentId}/availability`, { query: range })));

      if (myNumber !== refreshNumber) return; // a newer check has started

      // Theatres: busy ones stay in the list but cannot be chosen, with the reason.
      const previous = Number(theatre.value);
      theatre.replaceChildren(...theatres.map((item, index) => {
        const result = theatreResults[index];
        const text = result.available ? `${item.name} — ✔ free` : `${item.name} — ✖ ${result.reasons.join(", ")}`;
        return el("option", { value: String(item.theatreId), disabled: !result.available }, text);
      }));
      const free = theatres.filter((item, index) => theatreResults[index].available);
      const keep = free.find((item) => item.theatreId === previous && theatreChosenByUser);
      theatre.value = String((keep || free[0] || {}).theatreId || "");

      // Staff: off-shift or inactive people cannot be ticked (OT-F-033).
      const problems = new Map(staffCheck.conflicts.map((issue) => [issue.resource_id, issue.message]));
      const toItem = (person) => ({ id: person.staff_id, label: person.name, problem: problems.get(person.staff_id) });
      fillCheckList(doctors, "doctor", doctorList.map(toItem), new Set(checkedIds(doctors)));
      fillCheckList(nurses, "nurse", nurseList.map(toItem), new Set(checkedIds(nurses)));

      // Equipment: SAD 4.5 says only items free for the slot are offered.
      const freeItems = items.filter((item, index) => itemResults[index].available);
      fillCheckList(equipment, "equipment",
        freeItems.map((item) => ({ id: item.equipmentId, label: `${item.name} (${assetTag(item.equipmentId)})` })),
        new Set(checkedIds(equipment)));
      const hidden = lookups.equipment.filter((item) => item.isActive).length - freeItems.length;
      equipmentNote.textContent = hidden > 0 ? `${hidden} item(s) not offered: busy or under maintenance at this time.` : "";

      availability.textContent = `${free.length} of ${theatres.length} theatres free at this time.`;
    } catch (error) {
      if (myNumber === refreshNumber) availability.textContent = `Could not check availability: ${error.message}`;
    }
  }

  start.addEventListener("change", refreshAvailability);
  duration.addEventListener("change", refreshAvailability);

  const form = el("form", { id: "schedule-form", class: "card", novalidate: true, "aria-labelledby": "schedule-title" },
    el("h2", { id: "schedule-title", text: "Schedule a surgery" }),
    el("div", { class: "form-grid" },
      field("Patient name", patient),
      field("Start", start),
      field("Duration", duration),
      field("Priority", priority),
      wideField("Theatre", theatre, availability),
    ),
    el("div", { class: "form-grid" },
      el("fieldset", { class: "field" }, el("legend", { text: "Doctors" }), doctors),
      el("fieldset", { class: "field" }, el("legend", { text: "Nurses" }), nurses),
      el("fieldset", { class: "field" }, el("legend", { text: "Equipment" }), equipment, equipmentNote),
    ),
    message,
    save,
  );

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    hideMessage(message);
    const name = patient.value.trim();
    if (!name || !start.value || !theatre.value) {
      showMessage(message, "error", "Enter the patient name and a start time, and choose a free theatre.");
      message.focus();
      return;
    }
    const range = slot();
    const body = {
      patient_name: name,
      theatre_id: Number(theatre.value),
      start_time: range.start,
      end_time: range.end,
      doctor_ids: checkedIds(doctors),
      nurse_ids: checkedIds(nurses),
      equipment_ids: checkedIds(equipment),
      priority: priority.value,
    };
    try {
      const surgery = await whileBusy(save, "Saving…", () => api("POST", "/surgeries", { body }));
      showMessage(message, "success",
        `Surgery scheduled for ${surgery.patient_name}: ${theatre.selectedOptions[0].text.split(" — ")[0]}, ${range.start.replace("T", " ")}.`);
      patient.value = "";
      for (const box of form.querySelectorAll("input[type=checkbox]")) box.checked = false;
      theatreChosenByUser = false;
      onSaved(surgery);
      refreshAvailability();
    } catch (error) {
      if (error.status === 409) {
        // Sequence Diagram 1: show the conflict details, naming each resource.
        const lines = describeConflicts(error.conflicts, lookups).map((line) => `• ${line}`);
        showMessage(message, "error",
          ["Not saved. These are not free at this time:", ...lines,
            "Change the time or the resources and save again. Your entries are kept."].join("\n"));
      } else {
        showMessage(message, "error", `Not saved: ${error.message}`);
      }
    }
    message.focus();
  });

  refreshAvailability();
  return form;
}
