// Staff screen for admins (OT-F-030, OT-F-031): list, add, edit and deactivate doctors
// and nurses, edit their shifts, and check who is available for a time range.

import { api } from "./api.js";
import { el, formatDateTime, hideMessage, notify, openDialog, showMessage, toInputDateTime, whileBusy } from "./dom.js";

export async function renderStaff(container) {
  const typeFilter = el("select", { id: "st-type" },
    el("option", { value: "" }, "Doctors and nurses"),
    el("option", { value: "doctor" }, "Doctors"),
    el("option", { value: "nurse" }, "Nurses"));
  const showInactive = el("input", { id: "st-inactive", type: "checkbox" });
  const from = el("input", { id: "st-from", type: "datetime-local", step: "300" });
  const to = el("input", { id: "st-to", type: "datetime-local", step: "300" });
  const tableArea = el("div", { class: "table-wrap", "aria-live": "polite" });
  let staff = [];
  let availability = new Map(); // staff_id -> true/false for the chosen range

  container.append(
    el("h1", { tabindex: "-1", text: "Staff" }),
    addStaffForm(load),
    el("section", { class: "card", "aria-labelledby": "staff-list-title" },
      el("h2", { id: "staff-list-title", text: "Doctors and nurses" }),
      el("div", { class: "toolbar" },
        el("div", { class: "field" }, el("label", { for: "st-type", text: "Show" }), typeFilter),
        el("div", { class: "field" }, el("label", { for: "st-inactive" }, showInactive, " Include deactivated"))),
      el("div", { class: "toolbar" },
        el("div", { class: "field" }, el("label", { for: "st-from", text: "Available from" }), from),
        el("div", { class: "field" }, el("label", { for: "st-to", text: "until" }), to),
        el("button", { type: "button", class: "button button-secondary", onclick: checkAvailability }, "Check availability")),
      tableArea));

  typeFilter.addEventListener("change", load);
  showInactive.addEventListener("change", load);

  async function load() {
    staff = await api("GET", "/staff", {
      query: { staff_type: typeFilter.value, include_inactive: showInactive.checked },
    });
    draw();
  }

  // OT-F-031: availability query for a time range, one request per person.
  async function checkAvailability() {
    if (!from.value || !to.value) {
      notify("error", "Choose the start and end of the time range first.");
      return;
    }
    try {
      const results = await Promise.all(staff.filter((person) => person.is_active).map((person) =>
        api("GET", `/staff/${person.staff_id}/availability`, { query: { start_time: from.value, end_time: to.value } })
          .then((result) => [person.staff_id, result.available])));
      availability = new Map(results);
      draw();
    } catch (error) {
      notify("error", error.message);
    }
  }

  function draw() {
    if (staff.length === 0) {
      tableArea.replaceChildren(el("p", { class: "hint", text: "No staff records yet." }));
      return;
    }
    const headings = ["Name", "Type", "Specialization", "Status", "Login", "Available in range", "Actions"];
    tableArea.replaceChildren(el("table", {},
      el("thead", {}, el("tr", {}, headings.map((title) => el("th", { scope: "col", text: title })))),
      el("tbody", {}, staff.map((person) => {
        let available = "—";
        if (availability.has(person.staff_id)) available = availability.get(person.staff_id) ? "✔ Available" : "✖ Not available";
        return el("tr", {},
          el("td", { text: person.name }),
          el("td", { text: person.staff_type === "doctor" ? "Doctor" : "Nurse" }),
          el("td", { text: person.specialization || "—" }),
          el("td", { text: person.is_active ? "✔ Active" : "✖ Deactivated" }),
          el("td", { text: person.user_id ? "✔ Linked" : "—" }),
          el("td", { text: available }),
          el("td", {}, person.is_active ? [
            el("button", { type: "button", class: "link-button", onclick: () => editStaff(person, load) }, "Edit"),
            el("button", { type: "button", class: "link-button", onclick: () => editShifts(person) }, "Shifts"),
            el("button", { type: "button", class: "link-button", onclick: () => deactivate(person, load) }, "Deactivate"),
          ] : "—"));
      }))));
  }

  await load();
}

// Add a doctor or nurse. If a username and password are given, a login is created
// first and linked, so the person can see their own surgeries and notifications.
function addStaffForm(onAdded) {
  const message = el("div", { class: "message", role: "alert", tabindex: "-1", hidden: true });
  const name = el("input", { id: "new-name", required: true, maxlength: "100" });
  const type = el("select", { id: "new-type" },
    el("option", { value: "doctor" }, "Doctor"), el("option", { value: "nurse" }, "Nurse"));
  const specialization = el("input", { id: "new-spec", maxlength: "100" });
  const username = el("input", { id: "new-username", maxlength: "50", autocomplete: "off" });
  const password = el("input", { id: "new-password", type: "password", maxlength: "128", autocomplete: "new-password" });
  const save = el("button", { type: "submit", class: "button" }, "Add staff member");

  const form = el("form", { id: "add-staff-form", class: "card", novalidate: true, "aria-labelledby": "add-staff-title" },
    el("h2", { id: "add-staff-title", text: "Add a doctor or nurse" }),
    el("div", { class: "form-grid" },
      el("div", { class: "field" }, el("label", { for: "new-name", text: "Name" }), name),
      el("div", { class: "field" }, el("label", { for: "new-type", text: "Type" }), type),
      el("div", { class: "field" }, el("label", { for: "new-spec", text: "Specialization (optional)" }), specialization)),
    el("p", { class: "hint", text: "Optional: create a login so this person can see their own surgeries." }),
    el("div", { class: "form-grid" },
      el("div", { class: "field" }, el("label", { for: "new-username", text: "Username" }), username),
      el("div", { class: "field" }, el("label", { for: "new-password", text: "Password (at least 8 characters)" }), password)),
    message,
    save);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    hideMessage(message);
    if (!name.value.trim()) {
      showMessage(message, "error", "Enter the name.");
      message.focus();
      return;
    }
    if (Boolean(username.value.trim()) !== Boolean(password.value)) {
      showMessage(message, "error", "For a login, enter both a username and a password, or leave both empty.");
      message.focus();
      return;
    }
    try {
      await whileBusy(save, "Saving…", async () => {
        let userId = null;
        if (username.value.trim()) {
          const user = await api("POST", "/auth/users", {
            body: { username: username.value.trim(), password: password.value, role: type.value },
          });
          userId = user.user_id;
        }
        await api("POST", "/staff", {
          body: { name: name.value.trim(), staff_type: type.value, specialization: specialization.value.trim() || null, user_id: userId },
        });
      });
      showMessage(message, "success", `${name.value.trim()} added.`);
      form.reset();
      onAdded();
    } catch (error) {
      showMessage(message, "error", `Not added: ${error.message}`);
    }
    message.focus();
  });
  return form;
}

function editStaff(person, onSaved) {
  const name = el("input", { id: "edit-name", value: person.name, maxlength: "100" });
  const specialization = el("input", { id: "edit-spec", value: person.specialization || "", maxlength: "100" });
  openDialog(`Edit ${person.name}`, el("div", {},
    el("div", { class: "field" }, el("label", { for: "edit-name", text: "Name" }), name),
    el("div", { class: "field" }, el("label", { for: "edit-spec", text: "Specialization" }), specialization)),
  async () => {
    await api("PUT", `/staff/${person.staff_id}`, {
      body: { name: name.value.trim(), specialization: specialization.value.trim() || null },
    });
    notify("success", `${name.value.trim()} saved.`);
    onSaved();
  });
}

// SAD 4.5: destructive actions ask for confirmation.
async function deactivate(person, onDone) {
  if (!window.confirm(`Deactivate ${person.name}? They can no longer be assigned to surgeries. The record is kept.`)) return;
  try {
    await api("DELETE", `/staff/${person.staff_id}`);
    notify("success", `${person.name} deactivated.`);
    onDone();
  } catch (error) {
    notify("error", error.message);
  }
}

// Shifts: the list is edited as a whole and saved with one PUT, which replaces all shifts.
async function editShifts(person) {
  const { shifts } = await api("GET", `/staff/${person.staff_id}/shifts`);
  const rows = el("div", {});

  function addRow(startValue = "", endValue = "") {
    const index = rows.children.length + 1;
    const start = el("input", { type: "datetime-local", step: "300", value: startValue, id: `shift-start-${index}` });
    const end = el("input", { type: "datetime-local", step: "300", value: endValue, id: `shift-end-${index}` });
    const row = el("div", { class: "toolbar shift-row" },
      el("div", { class: "field" }, el("label", { for: start.id, text: `Shift ${index} start` }), start),
      el("div", { class: "field" }, el("label", { for: end.id, text: "end" }), end));
    row.append(el("button", { type: "button", class: "button button-secondary", onclick: () => row.remove() }, "Remove"));
    rows.append(row);
  }

  for (const shift of shifts) addRow(toInputDateTime(new Date(shift.start_time)), toInputDateTime(new Date(shift.end_time)));
  const addButton = el("button", { type: "button", class: "button button-secondary", onclick: () => addRow() }, "+ Add shift");
  const note = el("p", { class: "hint", text: shifts.length ? `Current shifts start ${formatDateTime(shifts[0].start_time)}.` : "No shifts yet." });

  openDialog(`Shifts: ${person.name}`, el("div", {}, note, rows, addButton), async () => {
    const list = [...rows.querySelectorAll(".shift-row")].map((row) => {
      const [start, end] = row.querySelectorAll("input");
      return { start_time: start.value, end_time: end.value };
    }).filter((shift) => shift.start_time && shift.end_time);
    // The API rejects overlapping shifts with 400 and a reason, shown in the dialog.
    await api("PUT", `/staff/${person.staff_id}/shifts`, { body: { shifts: list } });
    notify("success", `Shifts saved for ${person.name}.`);
  });
}
