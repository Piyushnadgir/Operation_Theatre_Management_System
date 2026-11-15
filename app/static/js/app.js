// Start-up, login, navigation by role, theme and the emergency banner.
// Each screen lives in its own file and exports a render(container) function.

import { api, ApiError, session, setSessionEndedHandler } from "./api.js";
import { el, hideMessage, notify, showMessage, whileBusy } from "./dom.js";
import { refreshEmergencyBanner } from "./banner.js";
import { renderBoard } from "./board.js";
import { renderDashboard } from "./dashboard.js";
import { renderEmergencies } from "./emergency.js";
import { can } from "./roles.js";
import { renderStaff } from "./staff.js";
import { renderSurgeries } from "./surgeries.js";

// The screens, in the order of the SAD Figure 4.3 navigation bar.
// "permission" names an entry in roles.js.
const SCREENS = [
  { id: "surgeries", label: "Surgeries", permission: "viewSurgeries", render: renderSurgeries },
  { id: "emergencies", label: "Emergencies", permission: "viewEmergencyQueue", render: renderEmergencies },
  { id: "staff", label: "Staff", permission: "manageStaff", render: renderStaff },
  { id: "equipment", label: "Equipment", permission: "viewEquipment", render: renderBoard },
  { id: "reports", label: "Reports", permission: "viewReports", render: renderDashboard },
];

const loginView = document.getElementById("login-view");
const view = document.getElementById("view");
const nav = document.getElementById("main-nav");

// ---------- login and logout ----------

function showLogin(message) {
  nav.hidden = true;
  document.getElementById("user-info").hidden = true;
  document.getElementById("logout-button").hidden = true;
  document.getElementById("emergency-banner").hidden = true;
  view.replaceChildren();
  hideMessage(document.getElementById("global-message"));
  loginView.hidden = false;
  if (message) showMessage(document.getElementById("login-error"), "error", message);
  document.getElementById("login-username").focus();
}

async function handleLogin(event) {
  event.preventDefault();
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("login-password").value;
  const errorBox = document.getElementById("login-error");
  if (!username || !password) {
    showMessage(errorBox, "error", "Enter your username and password.");
    return;
  }
  const button = event.target.querySelector("button[type=submit]");
  try {
    // The API answers 401 for a wrong password and 423 when the account is locked;
    // its message is shown as it is (OT-SR-004).
    const result = await whileBusy(button, "Signing in…", () =>
      api("POST", "/auth/login", { body: { username, password } }));
    session.save(result.token, result.role, username);
    document.getElementById("login-password").value = "";
    hideMessage(errorBox);
    startApp();
  } catch (error) {
    showMessage(errorBox, "error", error instanceof ApiError ? error.message : "Sign in failed.");
  }
}

function logout() {
  session.clear();
  window.location.hash = "";
  showLogin();
}

// ---------- after login ----------

function startApp() {
  loginView.hidden = true;
  const userInfo = document.getElementById("user-info");
  userInfo.textContent = `${session.username} (${session.role})`;
  userInfo.hidden = false;
  document.getElementById("logout-button").hidden = false;
  buildNav();
  showRoute();
}

// Only the screens this role may use appear in the menu (SAD 4.5: role-based dashboards).
function buildNav() {
  const links = SCREENS.filter((screen) => can(screen.permission)).map((screen) =>
    el("a", { href: `#${screen.id}`, "data-screen": screen.id, text: screen.label }));
  nav.replaceChildren(...links);
  nav.hidden = false;
  document.getElementById("emergency-banner").hidden = false;
  document.getElementById("emergency-button").hidden = !can("logEmergency");
}

// Draw the screen named in the URL hash (#surgeries, #equipment, ...).
async function showRoute() {
  if (!session.token) {
    showLogin();
    return;
  }
  const allowed = SCREENS.filter((screen) => can(screen.permission));
  const wanted = window.location.hash.slice(1);
  const screen = allowed.find((item) => item.id === wanted) || allowed[0];

  for (const link of nav.querySelectorAll("a")) {
    if (link.dataset.screen === screen.id) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  hideMessage(document.getElementById("global-message"));
  view.replaceChildren();
  try {
    await screen.render(view);
  } catch (error) {
    // Includes the server's 403 message if a role reaches something it may not use.
    if (session.token) notify("error", error.message || "Something went wrong.");
  }
  // Move focus to the screen title so keyboard users start at the top.
  const title = view.querySelector("h1");
  if (title) title.focus();
  refreshEmergencyBanner();
}

// ---------- high-contrast theme (SAD 4.5) ----------
// The choice is a display preference only, so localStorage is fine here.

function applyTheme(highContrast) {
  document.documentElement.dataset.theme = highContrast ? "contrast" : "default";
  const button = document.getElementById("theme-toggle");
  button.setAttribute("aria-pressed", String(highContrast));
}

function toggleTheme() {
  const highContrast = document.documentElement.dataset.theme !== "contrast";
  applyTheme(highContrast);
  try {
    localStorage.setItem("otms.theme", highContrast ? "contrast" : "default");
  } catch {
    // Storage can be blocked; the theme still changes for this visit.
  }
}

function loadTheme() {
  let saved = null;
  try {
    saved = localStorage.getItem("otms.theme");
  } catch {
    saved = null;
  }
  applyTheme(saved === "contrast");
}

// ---------- start ----------

loadTheme();
document.getElementById("theme-toggle").addEventListener("click", toggleTheme);
document.getElementById("login-form").addEventListener("submit", handleLogin);
document.getElementById("logout-button").addEventListener("click", logout);
window.addEventListener("hashchange", showRoute);
setSessionEndedHandler(() => showLogin("Your session has ended. Please sign in again."));

if (session.token) startApp();
else showLogin();
