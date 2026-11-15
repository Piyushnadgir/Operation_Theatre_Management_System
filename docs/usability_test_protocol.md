# Usability test protocol (OTMS-23, OT-NF-003, TC-UX-01)

Requirement (SRS OT-NF-003): a trained scheduler shall be able to schedule a surgery in at most
**2 minutes** and **8 interactions** without help.
Acceptance: a usability test with **5 users** meets the target. SAD 4.5 repeats the 8-interaction target.

## What is automated and what is not

| Part of the target | How it is checked | Status |
|---|---|---|
| The API needs at most 8 requests to schedule a surgery | `tests/test_usability_scheduling.py` (automated proxy) | Passes: 5 requests, plus 1 for a staff list once `/staff` exists, so 6 |
| The server responds far faster than 2 minutes | Same tests: the whole flow must take under 12 s | Passes (well under 1 s) |
| A conflict names the resource, so the user can recover quickly | Same tests: the 409 says which theatre is taken | Passes |
| **A person finishes in ≤ 2 minutes** | **Manual test below only** | Not run |
| **A person needs ≤ 8 interactions (clicks, selections, field entries)** | **Manual test below only** | Not run |
| **"Without help" and "trained"** | **Manual test below only** | Not run |

The automated tests are a proxy. API requests are not user interactions: one screen can make several
requests, and one request can need several clicks. Only the manual test can show that OT-NF-003 is met.

**Prerequisite:** there is no frontend in the repository yet. The manual test can only run once the
scheduling screen (Web UI) exists. A team decision is needed on whether it runs before the demo.

## Participants

- 5 people acting as schedulers, none of them the developer of the scheduling screen.
- "Trained" means each person gets the same 5-minute walk-through of the scheduling screen beforehand,
  using a different patient, theatre and time from the test task. They may not practise the test task itself.

## Setup

1. A test database seeded with: theatres OT-1 to OT-3, a few equipment items including "Ventilator",
   at least one doctor ("Dr. Rao") and one nurse ("Nurse Mary"), and a few existing surgeries.
   OT-1 is already booked at the test time, so the user meets one conflict. No real patient data.
2. The participant is logged in as a scheduler, on the start screen (calendar or dashboard).
3. One observer with a stopwatch and this sheet. Optionally record the screen to recount afterwards.

## Task (read this to the participant word for word)

> "Please schedule a surgery for patient **Test Patient** on **[date] from 09:00 to 11:00**, in any free theatre,
> with **Dr. Rao** and **Nurse Mary**, and book a **Ventilator**. Tell me when you think you are done."

## What to measure

- **Time:** from the end of the task wording to the moment the "surgery scheduled" confirmation appears.
- **Interactions:** count 1 for each click or tap, each selection from a list or date picker, and each text
  field completed (typing within one field counts as 1, however many keys). Scrolling and reading do not count.
- **Errors:** any wrong action the user has to undo, and any conflict message seen.
- **Help:** any question answered or hint given by the observer. One hint means "without help" failed.

## Success criteria

Each participant **passes** only if all of these hold:

1. The surgery is saved correctly (right patient, time, staff and equipment, in a free theatre).
2. Time ≤ 2:00 (minutes:seconds).
3. Interactions ≤ 8.
4. No help was given.

**Pass/fail rule for TC-UX-01:** the test passes only if **all 5 participants pass**. If anyone fails, log a
GitHub issue describing where time or interactions were lost, fix the screen, and repeat with 5 new participants.
(This is the strict reading of "a usability test with 5 users meets the target". If the team prefers a
looser rule, for example 4 of 5, agree it before testing and record it here.)

## Results (fill in by hand; do not estimate)

Date of test: ____________  Build or commit tested: ____________  Observer: ____________

| User | Role or background | Time (mm:ss) | Interactions | Errors | Help given? (Y/N) | Saved correctly? (Y/N) | Pass? (Y/N) | Notes |
|---|---|---|---|---|---|---|---|---|
| U1 |  |  |  |  |  |  |  |  |
| U2 |  |  |  |  |  |  |  |  |
| U3 |  |  |  |  |  |  |  |  |
| U4 |  |  |  |  |  |  |  |  |
| U5 |  |  |  |  |  |  |  |  |

Summary: ___ of 5 passed. Longest time: ______. Most interactions: ______.

**TC-UX-01 result:** PASS / FAIL (circle one). Signed: ____________

## Automated proxy tests

| Test | Flow (requests) |
|---|---|
| `test_tc_ux_01_proxy_schedule_surgery_within_8_requests` | list theatres, theatre availability, list available equipment, equipment availability, create surgery = 5 (+1 staff list later) |
| `test_tc_ux_01_proxy_recovering_from_a_conflict_stays_within_8_requests` | list theatres, list equipment, create (409 names the theatre), availability of another theatre, create = 5 (+1 staff list later) |

Gap found: `main` has no `/staff` endpoint, so a UI cannot list doctors and nurses yet. It is on Poorvi's
unmerged branch, and the proxy counts it as one extra request.
