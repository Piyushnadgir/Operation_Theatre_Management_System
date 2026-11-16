// Equipment & Theatre Board (SAD 4.5, Figure 4.3; OT-F-040 to OT-F-042).
// Theatre status tiles, then the equipment inventory with search, a status filter,
// availability for a chosen time range, and per-item actions:
// Edit, Status and Retire (admin); Allocate and Release (admin, scheduler).

import { api } from "./api.js";
import {
  assetTag, dangerButton, el, formatDateTime, formatTime, notify, openDialog, smallButton, statusBadge, toInputDateTime,
} from "./dom.js";
import { describeConflicts, loadLookups, theatreName } from "./lookups.js";
import { can } from "./roles.js";

export async function renderBoard(container) {
  const search = el("input", { id: "eq-search", type: "search", placeholder: "Search equipment…", autocomplete: "off" });
  const statusFilter = el("select", { id: "eq-status" },
    el("option", { value: "" }, "All statuses"),
    el("option", { value: "available" }, "✔ Available"),
    el("option", { value: "in_use" }, "● In use"),
    el("option", { value: "maintenance" }, "✖ Maintenance"));
  const now = new Date();
  now.setMinutes(0, 0, 0);
  const from = el("input", { id: "eq-from", type: "datetime-local", step: "300", value: toInputDateTime(now) });
  const to = el("input", { id: "eq-to", type: "datetime-local", step: "300", value: toInputDateTime(new Date(now.getTime() + 2 * 3600000)) });
  const tiles = el("div", { class: "tiles", "aria-live": "polite" });
  const tableArea = el("div", { class: "table-wrap", "aria-live": "polite" });

  let lookups;
  let equipment = [];
  let allocations = [];          // current allocations, to show "In use (OT-1)" and to release
  let rangeResult = new Map();   // equipmentId -> availability answer for the chosen range

  container.append(
    el("div", { class: "title-row" },
      el("h1", { tabindex: "-1", text: "Equipment & Theatre Board" }),
      el("div", { class: "toolbar" },
        el("div", { class: "field" }, el("label", { for: "eq-search", class: "visually-hidden", text: "Search equipment" }), search),
        can("manageEquipment")
          ? el("button", { type: "button", class: "button", onclick: () => equipmentDialog(null, load) }, "+ Add equipment")
          : null,
        can("manageEquipment")
          ? el("button", { type: "button", class: "button button-secondary", onclick: () => theatreDialog(load) }, "+ Add theatre")
          : null)),
    el("section", { "aria-labelledby": "theatres-title" },
      el("h2", { id: "theatres-title", text: "Theatres" }),
      tiles),
    el("section", { "aria-labelledby": "inventory-title" },
      el("h2", { id: "inventory-title", text: "Equipment inventory" }),
      el("div", { class: "toolbar" },
        el("div", { class: "field" }, el("label", { for: "eq-status", text: "Status" }), statusFilter),
        el("div", { class: "field" }, el("label", { for: "eq-from", text: "Available from" }), from),
        el("div", { class: "field" }, el("label", { for: "eq-to", text: "until" }), to),
        el("button", { type: "button", class: "button button-secondary", onclick: checkRange }, "Check availability")),
      tableArea));

  search.addEventListener("input", drawTable);
  statusFilter.addEventListener("change", load);

  async function load() {
    lookups = await loadLookups();
    equipment = await api("GET", "/equipment", { query: { status: statusFilter.value } });
    allocations = can("allocate") ? await api("GET", "/allocations") : [];
    rangeResult = new Map();
    drawTiles();
    drawTable();
  }

  // ---------- theatre tiles: icon + words + colour, never colour alone ----------
  function drawTiles() {
    const theatres = lookups.theatres.filter((item) => item.isActive);
    if (theatres.length === 0) {
      tiles.replaceChildren(el("p", { class: "hint", text: "No theatres yet." }));
      return;
    }
    tiles.replaceChildren(...theatres.map((theatre) => {
      const tile = el("article", { class: `tile status-${theatre.status}`, "aria-label": `Theatre ${theatre.name}` },
        el("h3", { text: theatre.name }), statusBadge(theatre.status));
      if (can("manageEquipment")) tile.append(theatreActions(theatre));
      return tile;
    }));
  }

  // Admin: set cleaning / maintenance / available (occupied is set by the system), or retire.
  function theatreActions(theatre) {
    const id = `tile-status-${theatre.theatreId}`;
    const select = el("select", { id },
      ["available", "cleaning", "maintenance"].map((status) =>
        el("option", { value: status, selected: theatre.status === status }, status[0].toUpperCase() + status.slice(1))));
    const apply = el("button", {
      type: "button", class: "btn-small",
      onclick: async () => {
        try {
          await api("PATCH", `/theatres/${theatre.theatreId}/status`, { body: { status: select.value } });
          notify("success", `${theatre.name} is now ${select.value}.`);
          load();
        } catch (error) {
          notify("error", `${theatre.name}: ${error.message}`);
        }
      },
    }, "Set status");
    const retire = dangerButton("Retire", async () => {
      if (!window.confirm(`Retire theatre ${theatre.name}? It will no longer be bookable. Its history is kept.`)) return;
      try {
        await api("DELETE", `/theatres/${theatre.theatreId}`);
        notify("success", `${theatre.name} retired.`);
        load();
      } catch (error) {
        notify("error", conflictText(`${theatre.name} not retired`, error));
      }
    });
    return el("div", { class: "tile-actions" },
      el("label", { for: id, class: "visually-hidden", text: `Status of ${theatre.name}` }), select, apply, retire);
  }

  // ---------- equipment table ----------
  function drawTable() {
    const text = search.value.trim().toLowerCase();
    const rows = equipment.filter((item) =>
      [item.name, item.category || "", assetTag(item.equipmentId)].some((value) => value.toLowerCase().includes(text)));
    if (rows.length === 0) {
      tableArea.replaceChildren(el("p", { class: "hint", text: "No equipment matches." }));
      return;
    }
    const headings = ["Asset tag", "Name", "Category", "Status", "In chosen range", "Actions"];
    tableArea.replaceChildren(el("table", {},
      el("thead", {}, el("tr", {}, headings.map((title) => el("th", { scope: "col", text: title })))),
      el("tbody", {}, rows.map((item) => el("tr", {},
        el("td", { text: assetTag(item.equipmentId) }),
        el("td", { text: item.name }),
        el("td", { text: item.category || "—" }),
        el("td", {}, statusBadge(item.status), whereInUse(item)),
        el("td", { text: rangeText(item) }),
        el("td", {}, itemActions(item)))))));
  }

  // "In use (OT-1)" as on Figure 4.3: the theatre of the allocation running now.
  function whereInUse(item) {
    if (item.status !== "in_use") return null;
    const nowText = toInputDateTime(new Date());
    const running = allocations.find((allocation) => allocation.equipmentId === item.equipmentId
      && allocation.startTime.slice(0, 16) <= nowText && allocation.endTime.slice(0, 16) > nowText);
    return running ? ` (${theatreName(lookups, running.theatreId)})` : null;
  }

  function rangeText(item) {
    if (!rangeResult.has(item.equipmentId)) return "—";
    const result = rangeResult.get(item.equipmentId);
    return result.available ? "✔ Free" : `✖ ${result.reasons.join(", ")}`;
  }

  // OT-F-041: availability of every listed item for the chosen time range.
  async function checkRange() {
    try {
      const answers = await Promise.all(equipment.map((item) =>
        api("GET", `/equipment/${item.equipmentId}/availability`, { query: { start: from.value, end: to.value } })
          .then((result) => [item.equipmentId, result])));
      rangeResult = new Map(answers);
      drawTable();
    } catch (error) {
      notify("error", error.message);
    }
  }

  function itemActions(item) {
    const actions = [];
    if (can("manageEquipment")) {
      actions.push(smallButton("Edit", () => equipmentDialog(item, load)));
      if (item.status !== "in_use") {
        const next = item.status === "maintenance" ? "available" : "maintenance";
        actions.push(smallButton("Status", () => setStatus(item, next),
          { "aria-label": `Status: set ${item.name} to ${next}` })); // starts with the visible word
      }
    }
    if (can("allocate")) {
      actions.push(smallButton("Allocate", () => allocateDialog(item, load)));
      const current = allocations.filter((allocation) => allocation.equipmentId === item.equipmentId);
      if (current.length > 0) {
        actions.push(smallButton(`Release (${current.length})`, () => releaseDialog(item, current, load)));
      }
    }
    if (can("manageEquipment")) {
      actions.push(dangerButton("Retire", () => retireEquipment(item)));
    }
    return actions.length ? el("div", { class: "actions" }, actions) : "—";
  }

  // Available <-> maintenance (SAD 3.4). In use must be released first, so no button then.
  async function setStatus(item, next) {
    try {
      await api("PUT", `/equipment/${item.equipmentId}`, { body: { status: next } });
      notify("success", `${item.name} is now ${next === "maintenance" ? "under maintenance" : "available"}.`);
      load();
    } catch (error) {
      notify("error", `${item.name}: ${error.message}`);
    }
  }

  async function retireEquipment(item) {
    if (!window.confirm(`Retire ${item.name} (${assetTag(item.equipmentId)})? It can no longer be booked. Its history is kept.`)) return;
    try {
      await api("DELETE", `/equipment/${item.equipmentId}`);
      notify("success", `${item.name} retired.`);
      load();
    } catch (error) {
      notify("error", conflictText(`${item.name} not retired`, error));
    }
  }

  function conflictText(prefix, error) {
    if (error.status !== 409 || !lookups) return `${prefix}: ${error.message}`;
    return `${prefix}:\n${describeConflicts(error.conflicts, lookups).map((line) => `• ${line}`).join("\n")}`;
  }

  // Allocate one item to an upcoming surgery; the theatre is the surgery's own.
  async function allocateDialog(item, onDone) {
    const all = await api("GET", "/surgeries");
    const nowText = toInputDateTime(new Date());
    const upcoming = all.filter((surgery) => surgery.status === "scheduled" && surgery.end_time.slice(0, 16) > nowText)
      .sort((a, b) => a.start_time.localeCompare(b.start_time));
    const select = el("select", { id: "alloc-surgery" }, upcoming.map((surgery) =>
      el("option", { value: String(surgery.surgery_id) },
        `${formatDateTime(surgery.start_time)}–${formatTime(surgery.end_time)}, ${theatreName(lookups, surgery.theatre_id)}: ${surgery.patient_name}`)));
    const body = upcoming.length === 0
      ? el("p", { class: "hint", text: "There are no upcoming scheduled surgeries." })
      : el("div", { class: "field" }, el("label", { for: "alloc-surgery", text: "Surgery" }), select);
    openDialog(`Allocate ${item.name} (${assetTag(item.equipmentId)})`, body, async () => {
      const surgery = upcoming.find((entry) => entry.surgery_id === Number(select.value));
      if (!surgery) throw new Error("Choose a surgery.");
      try {
        await api("POST", "/allocations", {
          body: { surgeryId: surgery.surgery_id, theatreId: surgery.theatre_id, equipmentIds: [item.equipmentId] },
        });
      } catch (error) {
        // 409: all-or-nothing, nothing was allocated; the reasons name the resources.
        throw new Error(conflictText("Not allocated", error));
      }
      notify("success", `${item.name} allocated to ${surgery.patient_name}.`);
      onDone();
    });
  }

  await load();
}

// Release one of an item's current allocations (SAD 4.5: asks for confirmation).
function releaseDialog(item, current, onDone) {
  const list = el("ul", {}, current.map((allocation) => el("li", {},
    `${formatDateTime(allocation.startTime)}–${formatTime(allocation.endTime)} (surgery ${allocation.surgeryId}) `,
    el("button", {
      type: "button", class: "button button-secondary",
      onclick: async (event) => {
        if (!window.confirm(`Release ${item.name} from this surgery?`)) return;
        try {
          await api("POST", `/allocations/${allocation.allocationId}/release`);
          event.target.closest("li").replaceChildren(`✔ Released: ${formatDateTime(allocation.startTime)}`);
          notify("success", `${item.name} released.`);
          onDone();
        } catch (error) {
          notify("error", error.message);
        }
      },
    }, "Release"))));
  openDialog(`Release ${item.name}`, list, async () => {}, "Done");
}

// Add (item = null) or edit equipment. New items may start available or under maintenance.
function equipmentDialog(item, onDone) {
  const name = el("input", { id: "eq-name", maxlength: "100", value: item ? item.name : "" });
  const category = el("input", { id: "eq-category", maxlength: "100", value: item && item.category ? item.category : "" });
  const fields = [
    el("div", { class: "field" }, el("label", { for: "eq-name", text: "Name" }), name),
    el("div", { class: "field" }, el("label", { for: "eq-category", text: "Category (optional)" }), category),
  ];
  const status = el("select", { id: "eq-new-status" },
    el("option", { value: "available" }, "✔ Available"), el("option", { value: "maintenance" }, "✖ Maintenance"));
  if (!item) fields.push(el("div", { class: "field" }, el("label", { for: "eq-new-status", text: "Status" }), status));

  openDialog(item ? `Edit ${item.name}` : "Add equipment", el("div", {}, fields), async () => {
    const body = { name: name.value.trim(), category: category.value.trim() || null };
    if (item) {
      await api("PUT", `/equipment/${item.equipmentId}`, { body });
    } else {
      await api("POST", "/equipment", { body: { ...body, status: status.value } });
    }
    notify("success", `${body.name} saved.`);
    onDone();
  });
}

function theatreDialog(onDone) {
  const name = el("input", { id: "th-name", maxlength: "100" });
  openDialog("Add theatre", el("div", { class: "field" }, el("label", { for: "th-name", text: "Name" }), name), async () => {
    await api("POST", "/theatres", { body: { name: name.value.trim() } });
    notify("success", `Theatre ${name.value.trim()} added.`);
    onDone();
  });
}
