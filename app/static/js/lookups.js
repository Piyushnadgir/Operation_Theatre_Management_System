// Names for ids. The API reports conflicts by id ("Theatre 3 is already booked"),
// but SAD 4.5 asks for conflict messages that name the resource ("OT-1 is already booked").

import { api } from "./api.js";
import { assetTag } from "./dom.js";
import { can } from "./roles.js";

// Load theatres, equipment and (if this role may) staff once per screen.
export async function loadLookups() {
  const [theatres, equipment, staff] = await Promise.all([
    api("GET", "/theatres", { query: { includeRetired: true } }),
    api("GET", "/equipment", { query: { includeRetired: true } }),
    can("listStaff") ? api("GET", "/staff", { query: { include_inactive: true } }) : Promise.resolve([]),
  ]);
  return { theatres, equipment, staff };
}

export function theatreName(lookups, id) {
  const theatre = lookups.theatres.find((item) => item.theatreId === id);
  return theatre ? theatre.name : `Theatre ${id}`;
}

export function equipmentName(lookups, id) {
  const item = lookups.equipment.find((entry) => entry.equipmentId === id);
  return item ? `${item.name} (${assetTag(id)})` : assetTag(id);
}

export function staffName(lookups, id) {
  const person = lookups.staff.find((entry) => entry.staff_id === id);
  return person ? person.name : `Staff ${id}`;
}

function nameFor(lookups, type, id) {
  if (type === "theatre") return `Theatre ${theatreName(lookups, id)}`;
  if (type === "equipment") return equipmentName(lookups, id);
  if (type === "doctor" || type === "nurse") return staffName(lookups, id);
  return `${type} ${id}`;
}

// One line per conflict, naming the resource. The API message starts with
// "<Type> <id>" or "<Type> <id>:", which is replaced by the name.
export function describeConflicts(conflicts, lookups) {
  return conflicts.map((conflict) => {
    const rest = conflict.message.replace(/^\w+ \d+:?\s*/, "");
    const name = nameFor(lookups, conflict.resource_type, conflict.resource_id);
    return /^(is|are|has)\b/.test(rest) ? `${name} ${rest}` : `${name}: ${rest}`;
  });
}
