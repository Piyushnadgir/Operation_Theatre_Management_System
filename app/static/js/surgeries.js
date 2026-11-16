// Surgeries screen (SAD 4.5): schedulers and admins see the schedule form and a
// calendar day view of theatre slots with reschedule and cancel; doctors and nurses
// see their own upcoming surgeries, their notifications and a read-only day view.

import { api } from "./api.js";
import {
  addMinutes, dangerButton, el, formatDateTime, formatTime, hideMessage, notify, priorityBadge,
  showMessage, smallButton, statusBadge, toInputDate, toInputDateTime, whileBusy,
} from "./dom.js";
import { describeConflicts, loadLookups, theatreName } from "./lookups.js";
import { can } from "./roles.js";
import { durationSelect, scheduleForm } from "./schedule.js";

export async function renderSurgeries(container) {
  const lookups = await loadLookups();
  container.append(el("h1", { tabindex: "-1", text: "Surgeries" }));

  if (can("manageSurgeries")) {
    container.append(scheduleForm(lookups, (surgery) => {
      dateInput.value = surgery.start_time.slice(0, 10);
      loadDay();
    }));
  } else {
    container.append(await myUpcomingSurgeries(lookups));
  }
  container.append(await myNotifications());

  // ---------- day view ----------
  const dateInput = el("input", { id: "day-date", type: "date", value: toInputDate(new Date()) });
  const theatreFilter = el("select", { id: "day-theatre" },
    el("option", { value: "" }, "All theatres"),
    lookups.theatres.filter((item) => item.isActive).map((item) =>
      el("option", { value: String(item.theatreId) }, item.name)));
  const dayMessage = el("div", { class: "message", role: "status", hidden: true });
  const day = el("div", { class: "day-view", "aria-live": "polite" });

  container.append(el("section", { class: "card", "aria-labelledby": "day-title" },
    el("h2", { id: "day-title", text: "Theatre schedule" }),
    el("div", { class: "toolbar" },
      el("div", { class: "field" }, el("label", { for: "day-date", text: "Day" }), dateInput),
      el("div", { class: "field" }, el("label", { for: "day-theatre", text: "Theatre" }), theatreFilter)),
    dayMessage,
    day));

  dateInput.addEventListener("change", loadDay);
  theatreFilter.addEventListener("change", loadDay);

  async function loadDay() {
    showMessage(dayMessage, "loading", "Loading…");
    try {
      const surgeries = await api("GET", "/surgeries", {
        query: { date: dateInput.value, theatre_id: theatreFilter.value },
      });
      hideMessage(dayMessage);
      drawDay(surgeries);
    } catch (error) {
      showMessage(dayMessage, "error", error.message);
    }
  }

  // One column per theatre, surgeries in time order (a simple calendar day view).
  function drawDay(surgeries) {
    surgeries.sort((a, b) => a.start_time.localeCompare(b.start_time));
    const shownIds = theatreFilter.value
      ? [Number(theatreFilter.value)]
      : [...new Set([
        ...lookups.theatres.filter((item) => item.isActive).map((item) => item.theatreId),
        ...surgeries.map((surgery) => surgery.theatre_id),
      ])];
    day.replaceChildren(...shownIds.map((theatreId) => {
      const own = surgeries.filter((surgery) => surgery.theatre_id === theatreId);
      return el("section", { class: "day-column", "aria-label": `Theatre ${theatreName(lookups, theatreId)}` },
        el("h3", { text: theatreName(lookups, theatreId) }),
        own.length === 0 ? el("p", { class: "hint", text: "No surgeries." }) : own.map(surgeryCard));
    }));
  }

  function surgeryCard(surgery) {
    const card = el("article", { class: `surgery-card priority-border-${surgery.priority}` },
      el("p", { class: "surgery-time", text: `${formatTime(surgery.start_time)}–${formatTime(surgery.end_time)}` }),
      el("p", { class: "surgery-patient", text: surgery.patient_name }),
      el("p", {}, priorityBadge(surgery.priority), " ", statusBadge(surgery.status)));
    if (can("manageSurgeries") && surgery.status === "scheduled") {
      card.append(el("div", { class: "actions" },
        smallButton("Reschedule", () => openReschedule(surgery)),
        dangerButton("Cancel", () => cancel(surgery))));
    }
    return card;
  }

  // SAD 4.5: destructive actions ask for confirmation.
  async function cancel(surgery) {
    if (!window.confirm(`Cancel the surgery for ${surgery.patient_name} at ${formatDateTime(surgery.start_time)}? Its resources will be released.`)) return;
    try {
      await api("DELETE", `/surgeries/${surgery.surgery_id}`);
      notify("success", `Surgery for ${surgery.patient_name} cancelled. Its theatre and equipment are free again.`);
      loadDay();
    } catch (error) {
      notify("error", error.message);
    }
  }

  // Reschedule in a dialog. The surgery keeps its equipment: the current allocations
  // are sent again so they move to the new time (OT-F-011).
  function openReschedule(surgery) {
    const minutes = Math.round((new Date(surgery.end_time) - new Date(surgery.start_time)) / 60000);
    const start = el("input", { id: "r-start", type: "datetime-local", step: "300", value: toInputDateTime(new Date(surgery.start_time)) });
    const duration = durationSelect("r-duration", minutes);
    if (!duration.value) duration.append(el("option", { value: String(minutes), selected: true }, `${minutes} min`));
    const theatre = el("select", { id: "r-theatre" }, lookups.theatres.filter((item) => item.isActive).map((item) =>
      el("option", { value: String(item.theatreId), selected: item.theatreId === surgery.theatre_id }, item.name)));
    const message = el("div", { class: "message", role: "alert", tabindex: "-1", hidden: true });
    const save = el("button", { type: "submit", class: "button" }, "Save new time");
    const close = el("button", { type: "button", class: "button button-secondary" }, "Close");

    const form = el("form", { method: "dialog", novalidate: true },
      el("h2", { text: `Reschedule: ${surgery.patient_name}` }),
      el("div", { class: "field" }, el("label", { for: "r-start", text: "New start" }), start),
      el("div", { class: "field" }, el("label", { for: "r-duration", text: "Duration" }), duration),
      el("div", { class: "field" }, el("label", { for: "r-theatre", text: "Theatre" }), theatre),
      message,
      el("p", { class: "toolbar" }, save, close));
    const dialog = el("dialog", { "aria-label": "Reschedule surgery" }, form);
    close.addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => dialog.remove());

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      hideMessage(message);
      try {
        const current = await api("GET", "/allocations", { query: { surgeryId: surgery.surgery_id } });
        await whileBusy(save, "Saving…", () => api("PUT", `/surgeries/${surgery.surgery_id}`, {
          body: {
            start_time: start.value,
            end_time: addMinutes(start.value, Number(duration.value)),
            theatre_id: Number(theatre.value),
            equipment_ids: current.map((allocation) => allocation.equipmentId),
          },
        }));
        dialog.close();
        notify("success", `Surgery for ${surgery.patient_name} moved to ${start.value.replace("T", " ")}.`);
        dateInput.value = start.value.slice(0, 10);
        loadDay();
      } catch (error) {
        const text = error.status === 409
          ? ["Not moved. These are not free at the new time:",
            ...describeConflicts(error.conflicts, lookups).map((line) => `• ${line}`)].join("\n")
          : `Not moved: ${error.message}`;
        showMessage(message, "error", text);
        message.focus();
      }
    });

    document.body.append(dialog);
    dialog.showModal();
    start.focus();
  }

  await loadDay();
}

// Doctors and nurses: their own upcoming surgeries (SAD 4.5).
async function myUpcomingSurgeries(lookups) {
  const surgeries = await api("GET", "/me/surgeries");
  const section = el("section", { class: "card", "aria-labelledby": "mine-title" },
    el("h2", { id: "mine-title", text: "My upcoming surgeries" }));
  if (surgeries.length === 0) {
    section.append(el("p", { class: "hint", text: "You have no upcoming surgeries." }));
    return section;
  }
  section.append(el("div", { class: "table-wrap" }, el("table", {},
    el("thead", {}, el("tr", {}, ["When", "Patient", "Theatre", "Priority", "Status"].map((title) => el("th", { scope: "col", text: title })))),
    el("tbody", {}, surgeries.map((surgery) => el("tr", {},
      el("td", { text: `${formatDateTime(surgery.start_time)}–${formatTime(surgery.end_time)}` }),
      el("td", { text: surgery.patient_name }),
      el("td", { text: theatreName(lookups, surgery.theatre_id) }),
      el("td", {}, priorityBadge(surgery.priority)),
      el("td", {}, statusBadge(surgery.status))))))));
  return section;
}

// Notifications about moved surgeries (OT-F-023), newest first.
async function myNotifications() {
  const section = el("section", { class: "card", "aria-labelledby": "notes-title" },
    el("h2", { id: "notes-title", text: "My notifications" }));
  const list = el("ul", { class: "notifications" });
  section.append(list);

  async function draw() {
    const notifications = await api("GET", "/emergencies/notifications");
    if (notifications.length === 0) {
      list.replaceChildren(el("li", { class: "hint", text: "No notifications." }));
      return;
    }
    list.replaceChildren(...notifications.map((note) => {
      const item = el("li", { class: note.is_read ? "read" : "unread" },
        el("span", { class: "badge", text: note.is_read ? "Read" : "● New" }),
        el("span", { text: `${formatDateTime(note.created_at)}: ${note.message}` }));
      if (!note.is_read) {
        item.append(smallButton("Mark as read", async () => {
          await api("PATCH", `/emergencies/notifications/${note.notification_id}/read`);
          draw();
        }));
      }
      return item;
    }));
  }

  await draw();
  return section;
}
