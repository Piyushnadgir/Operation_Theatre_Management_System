// API client: the one place that talks to the server.
// It adds the login token, turns JSON errors into readable messages and
// sends the user back to the login screen when the session has ended.

const TOKEN_KEY = "otms.token";
const ROLE_KEY = "otms.role";
const USER_KEY = "otms.username";

// The token lives in sessionStorage: it is gone when the tab closes, and it is
// never put in localStorage or in the URL (SAD 3.9).
export const session = {
  get token() { return sessionStorage.getItem(TOKEN_KEY); },
  get role() { return sessionStorage.getItem(ROLE_KEY); },
  get username() { return sessionStorage.getItem(USER_KEY); },

  save(token, role, username) {
    sessionStorage.setItem(TOKEN_KEY, token);
    sessionStorage.setItem(ROLE_KEY, role);
    sessionStorage.setItem(USER_KEY, username);
  },

  clear() {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(ROLE_KEY);
    sessionStorage.removeItem(USER_KEY);
  },
};

// An error from the server, with the HTTP status and, for 409, the conflict list.
export class ApiError extends Error {
  constructor(status, message, conflicts = []) {
    super(message);
    this.status = status;
    this.conflicts = conflicts;
  }
}

// app.js sets this so that a 401 anywhere shows the login screen again.
let onSessionEnded = () => {};
export function setSessionEndedHandler(handler) {
  onSessionEnded = handler;
}

// Call the API. Example: api("GET", "/equipment", { query: { status: "available" } })
export async function api(method, path, { body, query } = {}) {
  const url = new URL("/api/v1" + path, window.location.origin);
  for (const [name, value] of Object.entries(query || {})) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(name, value);
    }
  }

  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (session.token) headers.Authorization = "Bearer " + session.token;

  let response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check the connection and try again.");
  }

  const data = await response.json().catch(() => null);
  if (response.ok) return data;

  // 401 after login means the token expired or is invalid: end the session.
  if (response.status === 401 && path !== "/auth/login") {
    session.clear();
    onSessionEnded();
  }
  const detail = data ? data.detail : null;
  const conflicts = detail && Array.isArray(detail.conflicts) ? detail.conflicts : [];
  throw new ApiError(response.status, errorMessage(response.status, detail), conflicts);
}

// The API returns errors in a few shapes (SAD 4.4). Turn each into one sentence.
function errorMessage(status, detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI's own validation errors: [{loc: [...], msg: "..."}]
    return "Invalid input: " + detail.map((item) => `${item.loc.slice(-1)[0]} ${item.msg}`).join("; ");
  }
  if (detail && detail.message) {
    // Our ResourceRoute adds field details to 400 errors: [{field, message}]
    if (Array.isArray(detail.details) && detail.details.length > 0) {
      const fields = detail.details.map((item) => `${item.field.split(".").pop()}: ${item.message}`);
      return `${detail.message}. ${fields.join("; ")}`;
    }
    return detail.message;
  }
  if (status === 403) return "You do not have permission to do this.";
  return `The request failed (HTTP ${status}).`;
}
