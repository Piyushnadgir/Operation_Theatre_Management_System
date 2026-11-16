// What each role may do in the UI. This copies the server's RBAC rules
// (require_roles in app/api/v1/*.py) so the UI hides what a role cannot use.
// The server still checks every request (OT-SR-003); hiding is only for clarity.

import { session } from "./api.js";

const ALL = ["admin", "scheduler", "doctor", "nurse"];

export const PERMISSIONS = {
  viewSurgeries: ALL,                              // GET /surgeries
  manageSurgeries: ["admin", "scheduler"],         // POST, PUT, DELETE /surgeries
  logEmergency: ["admin", "doctor", "scheduler"],  // POST /emergencies
  viewEmergencyQueue: ALL,                         // GET /emergencies/queue
  manageStaff: ["admin"],                          // POST, PUT, DELETE /staff, PUT shifts
  listStaff: ["admin", "scheduler"],               // GET /staff, availability, shifts
  viewEquipment: ALL,                              // GET /equipment, /theatres, availability
  manageEquipment: ["admin"],                      // POST, PUT, DELETE /equipment and /theatres
  allocate: ["admin", "scheduler"],                // POST /allocations and release
  viewReports: ["admin", "scheduler"],             // GET /reports/utilization
};

export function can(action) {
  return PERMISSIONS[action].includes(session.role);
}
