// Utilization Dashboard (SAD 4.5, Figure 4.4; OT-F-043).
// Date-range filter, four key figures, usage per theatre and per equipment item as
// CSS bars with the number written next to each bar, the top equipment by hours,
// and an export of the figures as a CSV file. No chart library.

import { api } from "./api.js";
import { el, notify, toInputDate } from "./dom.js";

export async function renderDashboard(container) {
  const today = new Date();
  const weekAgo = new Date(today.getTime() - 6 * 86400000);
  const from = el("input", { id: "rep-from", type: "date", value: toInputDate(weekAgo) });
  const to = el("input", { id: "rep-to", type: "date", value: toInputDate(today) });
  const exportButton = el("button", { type: "button", class: "button", disabled: true }, "Export report");
  const content = el("div", { "aria-live": "polite" });
  let report = null;

  container.append(
    el("div", { class: "title-row" },
      el("h1", { tabindex: "-1", text: "Utilization Dashboard" }),
      el("div", { class: "toolbar" },
        el("div", { class: "field" }, el("label", { for: "rep-from", text: "From" }), from),
        el("div", { class: "field" }, el("label", { for: "rep-to", text: "To (inclusive)" }), to),
        exportButton)),
    content);

  from.addEventListener("change", load);
  to.addEventListener("change", load);
  exportButton.addEventListener("click", () => exportCsv(report));

  async function load() {
    if (!from.value || !to.value || to.value < from.value) {
      content.replaceChildren(el("div", { class: "message message-error", text: "Choose a From date on or before the To date." }));
      exportButton.disabled = true;
      return;
    }
    content.replaceChildren(el("p", { class: "message message-loading", text: "Loading report…" }));
    // The API range is [from, to): add one day so the To date is included.
    const end = new Date(to.value + "T00:00");
    end.setDate(end.getDate() + 1);
    try {
      const [data, equipment] = await Promise.all([
        api("GET", "/reports/utilization", { query: { from: from.value, to: toInputDate(end) } }),
        api("GET", "/equipment"),
      ]);
      report = data;
      exportButton.disabled = false;
      draw(data, equipment);
    } catch (error) {
      content.replaceChildren(el("div", { class: "message message-error", text: error.message }));
      exportButton.disabled = true;
    }
  }

  function draw(data, equipment) {
    const inUse = equipment.filter((item) => item.status === "in_use").length;
    const topEquipment = [...data.equipment].sort((a, b) => b.bookedMinutes - a.bookedMinutes).slice(0, 5);
    // Layout: key figures, then the two charts one under the other (same bar grid, so the
    // same % gives the same bar length), then the top-equipment card in its own row.
    content.replaceChildren(
      el("div", { class: "tiles figures" },
        figure("Theatre utilization", `${data.totals.theatres.usagePercent} %`),
        figure("Equipment in use now", `${inUse} of ${equipment.length}`),
        figure("Surgeries in range", String(data.keyFigures.surgeries)),
        figure("Emergency cases", String(data.keyFigures.emergencyCases))),
      el("section", { "aria-labelledby": "by-theatre" },
        el("h2", { id: "by-theatre", text: "Utilization by theatre (booked hours / available hours)" }),
        bars(data.theatres)),
      el("section", { "aria-labelledby": "by-equipment" },
        el("h2", { id: "by-equipment", text: "Utilization by equipment item" }),
        bars(data.equipment)),
      el("section", { class: "card top-equipment", "aria-labelledby": "top-eq" },
        el("h2", { id: "top-eq", text: "Top equipment by usage" }),
        topEquipment.length === 0 || topEquipment[0].bookedMinutes === 0
          ? el("p", { class: "hint", text: "No equipment was used in this range." })
          : el("table", {}, el("tbody", {}, topEquipment.map((row) => el("tr", {},
            el("th", { scope: "row", text: row.name }),
            el("td", { class: "number", text: hours(row.bookedMinutes) })))))),
      el("p", { class: "hint", text: "Values are shown as text and bars; colour never carries meaning alone." }));
  }

  await load();
}

function figure(label, value) {
  return el("div", { class: "tile figure" },
    el("span", { class: "label", text: label }),
    el("span", { class: "value", text: value }));
}

function hours(minutes) {
  return `${Math.round(minutes / 6) / 10} h`;   // one decimal place
}

// One bar per row. The bar is decoration (aria-hidden); the percentage and hours are text.
function bars(rows) {
  if (rows.length === 0) return el("p", { class: "hint", text: "Nothing to show." });
  return el("div", {}, rows.map((row) => {
    const fill = el("div", { class: "bar-fill" });
    fill.style.width = `${Math.min(row.usagePercent, 100)}%`;
    return el("div", { class: "bar-row" },
      el("span", { text: row.name }),
      el("div", { class: "bar-track", "aria-hidden": "true" }, fill),
      el("span", { class: "bar-value", text: `${row.usagePercent} %` }),
      el("span", { class: "visually-hidden", text: `${hours(row.bookedMinutes)} of ${hours(row.availableMinutes)}` }));
  }));
}

// SAD 4.5: "the report available for export". The figures go into a CSV file
// built in the browser; nothing extra is sent to the server.
function exportCsv(report) {
  if (!report) return;
  // A name starting with = + - or @ could run as a formula in a spreadsheet, so it gets a ' first.
  const quote = (value) => {
    const text = /^[=+\-@]/.test(String(value)) ? `'${value}` : String(value);
    return `"${text.replace(/"/g, '""')}"`;
  };
  const lines = [["type", "id", "name", "booked_minutes", "available_minutes", "usage_percent"].join(",")];
  for (const row of report.theatres) {
    lines.push(["theatre", row.theatreId, quote(row.name), row.bookedMinutes, row.availableMinutes, row.usagePercent].join(","));
  }
  for (const row of report.equipment) {
    lines.push(["equipment", row.equipmentId, quote(row.name), row.bookedMinutes, row.availableMinutes, row.usagePercent].join(","));
  }
  const file = new Blob([lines.join("\n") + "\n"], { type: "text/csv" });
  const link = el("a", { href: URL.createObjectURL(file), download: `utilization_${report.start.slice(0, 10)}_${report.end.slice(0, 10)}.csv` });
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
  notify("success", "Report exported as a CSV file.");
}
