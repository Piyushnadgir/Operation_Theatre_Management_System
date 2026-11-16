# Web UI notes

The browser-based Web UI described in SAD 3.3, 3.4 and 4.5. It is plain HTML, CSS and JavaScript in
`app/static/`, served by the same FastAPI app at `/ui`. There is no build step, no framework and no CDN,
so it runs offline.

## How to run it

```bash
conda activate otms
pip install -r requirements.txt pytest-cov

# Create one login per role (there is no public sign-up). Pick your own password, at least 8 characters.
export OTMS_SEED_PASSWORD='choose-a-password'
python -m app.utils.seed --username admin --role admin
python -m app.utils.seed --username scheduler --role scheduler

uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/ (it redirects to `/ui/`). The API docs are still at http://127.0.0.1:8000/docs.

**Demo data:** sign in as `admin`, then:

1. On **Equipment**, use "+ Add theatre" and "+ Add equipment".
2. On **Staff**, add doctors and nurses. Fill in the optional username and password to give a doctor or
   nurse their own login: this links their staff record, so they see "My upcoming surgeries" and their
   notifications. A login made only with `seed.py` is not linked to a staff record.
3. Still on Staff, use **Shifts** to give each doctor and nurse a shift. Staff who are not on shift
   cannot be ticked on the schedule form (OT-F-033).

**HTTPS (OT-SR-001):** `ENFORCE_HTTPS` defaults to off, so the UI works on plain `http://127.0.0.1` during
development. For deployment, set `ENFORCE_HTTPS=true` and run with TLS, for example
`uvicorn app.main:app --ssl-keyfile key.pem --ssl-certfile cert.pem`. The UI is served by the same app,
so it gets the same protection. This setting was not changed.

## Screens and the documents

| Screen (menu) | Roles | What it does | Requirements / design |
|---|---|---|---|
| Sign in | everyone | `POST /auth/login`; shows the API's invalid-credentials and lockout messages; Log out button | OT-F-032, OT-SR-004 |
| Menu | by role | Only the screens a role may use are listed. A refused request shows the server's 403 message | SAD 4.5 role-based dashboards, OT-SR-003 |
| Surgeries | scheduler, admin | Schedule form; calendar day view with one column per theatre; Reschedule (dialog) and Cancel (with confirmation) | OT-F-010 to 013, SAD 4.2 Sequence Diagram 1, SAD 4.5 |
| Surgeries | doctor, nurse | "My upcoming surgeries", plus a read-only day view | SAD 4.5 |
| Surgeries | everyone | "My notifications", with Mark as read | OT-F-023 |
| Emergencies | admin, doctor, scheduler | One-screen intake form; the result lists the surgeries that were moved | OT-F-020, 022, SAD 4.2 Sequence Diagram 2, SAD 4.5 |
| Emergencies | everyone | Priority queue: critical first, then first come first served | OT-F-021 |
| Emergency banner | everyone | Count of active emergencies on every screen, plus a "Log emergency" button where allowed | SAD 4.5 |
| Staff | admin | Add (optionally with a login), edit, deactivate (with confirmation), shifts, availability for a range | OT-F-030, OT-F-031 |
| Equipment | everyone (actions by role) | Equipment & Theatre Board: theatre tiles, inventory with asset tag, search, status filter, availability for a range; Edit, Status and Retire (admin); Allocate and Release (admin, scheduler) | OT-F-040 to 042, SAD 3.4 status rules, SAD Figure 4.3 |
| Reports | admin, scheduler | Utilization Dashboard: date range, 4 key figures, bars per theatre and per item with the % as text, top equipment by hours, Export report (CSV) | OT-F-043, SAD Figure 4.4 |

Accessibility (SAD 4.5):
- 18px base font, a label on every input, visible focus outline, and a skip link.
- Every status shows an icon and words; colour only adds to them.
- High-contrast theme button; the choice is remembered in `localStorage`. It is only a display preference.
- Errors take keyboard focus, and dialogs close with Esc.

Security (SAD 3.9, OT-SR-006):
- **No HTML from data.** API data never goes into the page as HTML: `el()` in `js/dom.js` puts all text in
  with `textContent`. `tests/test_ui_static.py` fails if any JS file uses `innerHTML`, `outerHTML`,
  `insertAdjacentHTML`, `document.write`, `eval` or `new Function` with non-constant data.
- **Token handling.** The token is kept in `sessionStorage` only, never in `localStorage` or the URL. It is
  cleared on Log out and on any 401.
- **No external code.** A Content-Security-Policy allows only this server's own files: no inline scripts
  and no CDN. There are no secrets in the JavaScript.
- **CSV export.** A name starting with `=`, `+`, `-` or `@` gets a leading `'`, so it cannot run as a
  spreadsheet formula.

## Backend additions made for the UI

All are additive and tested. Each closes a gap between the SAD's UI and the API:

| Addition | Why | Tests |
|---|---|---|
| `app/main.py`: `/ui` static mount and `/` redirect | Serve the UI from the same app | `tests/test_ui_static.py` |
| `GET /me/surgeries` (`app/api/v1/me.py`, `app/services/my_surgeries.py`) | SAD 4.5: doctors and nurses see their own upcoming surgeries | `tests/test_ui_backend_additions.py` |
| Optional `user_id` in `POST /staff` and in staff responses (`app/schemas/staff.py`, `app/api/v1/staff.py`) | Links a doctor or nurse to their login. 400 if the user does not exist | `tests/test_ui_backend_additions.py` |
| `GET /allocations?surgeryId=&equipmentId=&includeReleased=` | Release needs the allocation id. Reschedule sends the surgery's equipment again so it moves with the surgery | `tests/test_ui_backend_additions.py` |
| `keyFigures` (surgeries, emergency cases) in `GET /reports/utilization` | The key figures in SAD Figure 4.4 | `tests/test_report_service.py`, `tests/test_report_api.py` |

## TC-UX-01: scheduling flow, counted step by step

The interaction rules match `docs/usability_test_protocol.md`: each click or tap, each selection, each
completed text field and each checkbox counts as 1. The scheduler signs in and lands on Surgeries, with the
schedule form at the top.

| # | Interaction | Notes |
|---|---|---|
| — | Duration 2 h, priority Routine | Defaults; 0 interactions unless they need changing |
| — | Theatre | The first free theatre for the slot is chosen automatically; busy ones are shown and cannot be chosen |
| 1 | Type the patient name | |
| 2 | Set the start date and time | One `datetime-local` field. Default is tomorrow 09:00 |
| 3 | Tick the doctor | Off-shift doctors are shown with the reason and cannot be ticked |
| 4 | Tick the nurse | |
| 5 | Tick the equipment | Only items free for the slot are offered |
| 6 | Press "Schedule surgery" | |

**Typical total: 6 interactions.** It rises to 7 if the scheduler picks a different theatre, and to 8 if
they also change the duration or priority. If the API returns 409, the message names each busy resource and
every entry is kept. Fixing it costs 1 to 2 interactions (untick or change one choice, then Save), but that
takes the total over 8, so the conflict path is a known risk to watch in the user test.

This was also checked in the browser: a scheduler booked a surgery in exactly 6 interactions, using the
keyboard for the last two. That is a scripted proxy. **The SRS target (≤ 2 minutes and ≤ 8 interactions
without help, for a trained scheduler) can only be confirmed by the 5-user test below.** The full
protocol is in `docs/usability_test_protocol.md`.

### Results (fill in by hand; do not estimate)

Date: ____________  Build or commit: ____________  Observer: ____________

| User | Time (mm:ss) | Interactions | Errors | Help given? (Y/N) | Saved correctly? (Y/N) | Pass? (Y/N) | Notes |
|---|---|---|---|---|---|---|---|
| U1 |  |  |  |  |  |  |  |
| U2 |  |  |  |  |  |  |  |
| U3 |  |  |  |  |  |  |  |
| U4 |  |  |  |  |  |  |  |
| U5 |  |  |  |  |  |  |  |

TC-UX-01 passes only if all 5 users pass (≤ 2:00, ≤ 8 interactions, no help, saved correctly).

## What was checked, and what was not

**Automated (in the test suite):** `tests/test_ui_static.py` and `tests/test_ui_backend_additions.py`,
plus the key-figure tests.

**Run once in a real browser:** Chrome for Testing driven by Playwright against a real uvicorn server, a
temporary database and data created through the API. These scripts are not part of the repository.
- Stage A, 31 checks:
  - **Sign-in:** invalid-credentials and lockout messages; the menu for each role; log out.
  - **Session:** the token stays out of `localStorage` and the URL; an invalid token returns to sign-in.
  - **Display and keyboard:** the high-contrast theme persists; the skip link works.
- Stage B, 30 checks:
  - **Scheduling:** 6-interaction booking; theatre picked automatically; maintenance item not offered;
    off-shift doctor disabled.
  - **Conflict:** 409 names Dr. Rao and Nurse Mary, entries kept, resubmit succeeds.
  - **Unsafe input:** a patient name containing `<img onerror>` is shown as text and does not run.
  - **Reschedule and cancel:** reschedule moves the equipment allocation; cancel asks for confirmation.
  - **Emergency:** it moves a surgery, and the queue, banner and notifications update; a blocked emergency
    shows the 409 reason.
  - **Roles:** doctor and nurse views; a faked role in `sessionStorage` still gets the server's 403.
- Stage C, 29 checks:
  - **Staff:** add with a login, then log in as that user; duplicate username; edit; overlapping shifts;
    availability; deactivate.
  - **Board:** tile status, add, search, maintenance; retire blocked by a future booking (item named);
    allocate and release; refusal for a theatre under maintenance.
  - **Dashboard:** figures and bars equal the API exactly; CSV export with the formula guard; high
    contrast inside a dialog.

**Not checked:**
- **"In use (OT-1)" on the board and "Equipment in use now" above 0.** Both need a surgery in progress, and
  no endpoint or screen can start a surgery.
- **Screen-reader use** with VoiceOver or NVDA. Not tested.
- **Colour contrast with a measuring tool.** Contrast values were chosen by calculation, not measured.
- **Browsers other than Chromium.** Not tested.
- **Phone-sized screens.** The layout is responsive, but this was not tested.

**Known limits:**
- **Doctors' emergency form has no staff lists.** `GET /staff` is for admins and schedulers only.
- **Staff can only be linked to a login when the staff record is created.**
- **A failed staff save can leave an unused login.** If creating the login works but saving the staff
  record then fails, the login stays and the error is shown.
