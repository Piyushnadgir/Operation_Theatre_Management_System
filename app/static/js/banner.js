// SAD 4.5: a prominent emergency banner that shows how many emergencies are active.

import { api } from "./api.js";

export async function refreshEmergencyBanner() {
  const count = document.getElementById("emergency-count");
  try {
    const queue = await api("GET", "/emergencies/queue");
    count.textContent = queue.length === 0
      ? "✔ No active emergencies"
      : `⚠ ${queue.length} active emergenc${queue.length === 1 ? "y" : "ies"}`;
    count.classList.toggle("active", queue.length > 0);
  } catch {
    count.textContent = "⚠ Emergency queue unavailable";
  }
}
