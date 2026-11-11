# Equipment module notes (OTMS-19, OTMS-20, OTMS-21)

Owner: Riyana K. Covers OT-F-040, OT-F-041 and OT-F-042. Branch: `feature/equipment-tracking`.
All paths below are under `/api/v1`.

## 1. Endpoints implemented

| Method and path | Who | Success | Errors | Req |
|---|---|---|---|---|
| POST /equipment | admin | 201 equipment | 400, 403 | OT-F-040 |
| GET /equipment?status=&category=&includeRetired= | any logged-in user | 200 list | 400, 401 | OT-F-040 |
| PUT /equipment/{id} | admin | 200 equipment | 400, 403, 404 | OT-F-040 |
| DELETE /equipment/{id} (soft delete) | admin | 200 {status: deactivated} | 403, 404, 409 | OT-F-040 |
| GET /equipment/{id}/availability?start=&end= | any logged-in user | 200 {available, status, reasons} | 400, 404 | OT-F-041 |
| POST /theatres | admin | 201 theatre | 400, 403, 409 duplicate name | OT-F-040 |
| GET /theatres?includeRetired= | any logged-in user | 200 list | 401 | OT-F-040 |
| PUT /theatres/{id} (rename) | admin | 200 theatre | 400, 403, 404, 409 duplicate name | OT-F-040 |
| PATCH /theatres/{id}/status | admin | 200 theatre | 400, 403, 404 | OT-F-040 |
| DELETE /theatres/{id} (soft delete) | admin | 200 {status: deactivated} | 403, 404, 409 | OT-F-040 |
| GET /theatres/{id}/availability?start=&end= | any logged-in user | 200 {available, status, reasons} | 400, 404 | OT-F-041 |
| POST /allocations | scheduler, admin | 201 list of allocations | 400, 403, 404, 409 | OT-F-042 |
| POST /allocations/{id}/release | scheduler, admin | 200 {status: released} | 403, 404 | OT-F-042 |

## 2. Rules implemented

**Availability.** An item is unavailable if it is retired, under maintenance, or has an unreleased
allocation overlapping the range. A theatre is also unavailable if a scheduled or in-progress surgery
overlaps. The overlap rule is the ConflictDetector one: `existing.start < end AND existing.end > start`,
so touching boundaries are not a conflict.

**Equipment status (SAD 3.4).**

| From | To | Allowed? |
|---|---|---|
| available | maintenance | Yes, by admin |
| maintenance | available | Yes, by admin |
| available | in_use | Only when the surgery is in progress. An admin gets 400 |
| in_use | available | Only by release or cancellation. An admin gets 400 |
| in_use | maintenance | No, 400. The item must be released first |
| maintenance | in_use | No, 400. Not in the SAD table |

**Theatre status: how `occupied` and `cleaning` are handled.** The SRS lists three statuses, while the SAD
and `TheatreStatusEnum` have four. The code follows the SAD.

- `cleaning` and `maintenance` are set by an admin through PATCH, and `available` clears them.
- `occupied` is set by the system only, while a surgery is in progress. Asking for it through PATCH or
  POST gives 400, and an occupied theatre cannot be changed by hand.
- A surgery ending returns `occupied` to `available`. It does not move to `cleaning` automatically.
- Only `maintenance` blocks a time range. `occupied`, `cleaning` and `in_use` describe the present and
  have no end time, so they cannot say anything about next week. The response still returns `status`
  so that the UI can show them.

**Allocation.** All-or-nothing: every item is checked before any row is written. An item cannot be
allocated twice to the same surgery. Releasing twice changes nothing and writes no second audit entry.

## 3. Deviations from the SRS, SAD and Test Plan

| # | Document says | Code does | Why |
|---|---|---|---|
| 1 | SAD 3.6.1: table `resource_allocation` with `resource_type`, `state`, and exactly one of equipment_id and theatre_id | Existing `allocation` table: one row per equipment item, both ids set, and a `released` boolean | Sprint instruction: reuse the `Allocation` model. No reserved/active/released states; the surgery status plays that role |
| 2 | SAD 3.6.1: theatre allocation rows | The surgery row is the theatre booking; no separate theatre row. `theatreId` must equal the surgery's theatre (else 400) | `equipment_id` is NOT NULL, and one source of truth avoids two records disagreeing. Changing theatre stays on PUT /surgeries |
| 3 | SAD 4.3: POST /allocations returns 201 {allocationId} | Returns a list of allocations | There is one row per item, so several ids can result |
| 4 | SAD 4.3: `equipmentIds` may be read as optional | At least one id is required (else 400) | With deviation 2, a request with no equipment would have nothing to create |
| 5 | SAD 4.3: 409 {resources} | 409 {error, message, conflicts}, nested under FastAPI's `detail` | Sprint instruction: match the ConflictResponse shape in surgeries.py |
| 6 | SAD 4.4: {error, message, details} at the top level | Same fields, nested under `detail`; role errors from deps.py stay a plain string | Consistent with surgeries.py. A global change belongs in main.py |
| 7 | SAD 3.6.1: theatre has no `is_active` | `Theatre.is_active` added | SRS OT-F-040 and TC-Eq-01 require retiring theatres, and OT-NF-004 rules out deleting them |
| 8 | SAD 4.3 lists only GET /theatres and PATCH status | Also POST, PUT, DELETE and GET availability for theatres | SRS OT-F-040 and OT-F-041 require them. SAD 4.3 should be updated |
| 9 | SAD 4.3: {available: true/false} | Adds `status` and `reasons` | Sprint instruction allows extra fields; SAD 4.5 wants conflicts to name the cause |
| 10 | SAD 4.3: GET /equipment filters are status and category | Adds `includeRetired` (default false) | Retired records must stay retrievable (TC-OPS-01) |
| 11 | SAD 4.3: POST /allocations 404 is "surgery not found" | Also 404 for an unknown theatre or equipment id | A missing record is not the same as an unavailable one |
| 12 | SAD 3.4: statuses change on surgery start and end | Implemented in `sync_surgery_resources`, but **nothing starts or completes a surgery yet** (see section 6) | No endpoint for this exists in the code or in SAD 4.3 |
| 13 | SAD 3.6.1: overlap check and insert cannot race | Check and insert share one transaction but take no lock, so two simultaneous requests could both pass | Same as POST /surgeries. Needs a lock or exclusion constraint on PostgreSQL |
| 14 | SAD 4.4: audit entry for every create and change | Allocation create and release are audited (OT-SR-005). Equipment and theatre writes are not | OT-SR-005 names surgeries and allocations. Poorvi owns the audit log, so a shared helper is better than copying this |
| 15 | SAD 4.3: 401 for a missing token | No token gives 403; an invalid token gives 401 | `HTTPBearer` in deps.py behaves this way (Poorvi's file) |
| 16 | JSON naming: SAD uses camelCase | My endpoints use camelCase (snake_case is also accepted on input). /surgeries uses snake_case | My module follows the SAD. The team should pick one |
| 17 | Not specified | Time offsets are dropped, so times are treated as hospital clock time | SQLite stores surgeries without an offset. Revisit for PostgreSQL |

Allocation roles: the sprint task says equipment and theatre writes are admin-only, and does not name
roles for allocations. SRS 2.3 says the scheduler allocates resources, so `/allocations` allows scheduler and admin.

Assumptions: an admin can put an item or theatre into maintenance even if it has future bookings, because
something that breaks must be markable. The bookings stay in place and later allocations are rejected.
Retired records can still be edited through PUT. Deleting an already retired item returns 200.

## 4. Changes to shared or teammates' files

| File | Change | Why |
|---|---|---|
| app/services/conflict_detection.py (Pulkit) | New `check_equipment_status`, called from `detect_all_conflicts`. `check_equipment_conflict` is unchanged | Retired or maintenance equipment is a conflict on POST and PUT /surgeries |
| app/services/surgery_service.py (Pulkit) | One import, and one line in `cancel_surgery` | Resets in_use and occupied on cancellation (SAD 3.4) |
| app/models/models.py (shared) | `Theatre.is_active` | Deviation 7. **Any existing otms.db must be deleted**, because `create_all` does not add columns and there are no Alembic migrations yet |
| app/api/v1/__init__.py (shared) | Registers three routers | Required |

## 5. Test case to test name mapping

Parametrized tests count once below. Service tests are in `tests/test_equipment_service.py` and API tests
are in `tests/test_equipment_api.py`.

### TC-Eq-01: add, update and retire equipment and theatres (OT-F-040)

Service (21):

- `test_tc_eq_01_create_equipment`
- `test_tc_eq_01_new_equipment_cannot_start_in_use`
- `test_tc_eq_01_update_equipment_fields`
- `test_tc_eq_01_update_missing_equipment`
- `test_tc_eq_01_list_filters_by_status_and_category`
- `test_tc_eq_01_retire_is_soft_delete`
- `test_tc_eq_01_retire_blocked_by_future_allocation`
- `test_tc_eq_01_retire_allowed_with_past_or_released_allocation`
- `test_tc_eq_01_available_to_maintenance_and_back`
- `test_tc_eq_01_disallowed_status_change_rejected`
- `test_tc_eq_01_in_use_item_can_still_be_renamed`
- `test_tc_eq_01_create_and_rename_theatre`
- `test_tc_eq_01_theatre_name_must_be_unique`
- `test_tc_eq_01_admin_sets_cleaning_and_maintenance`
- `test_tc_eq_01_occupied_cannot_be_set_by_hand`
- `test_tc_eq_01_occupied_theatre_cannot_be_changed_by_hand`
- `test_tc_eq_01_retire_theatre_is_soft_delete`
- `test_tc_eq_01_retire_theatre_blocked_by_future_surgery`
- `test_tc_eq_01_detector_reports_maintenance_and_retired_equipment`
- `test_tc_eq_01_create_surgery_rejects_maintenance_equipment`
- `test_tc_eq_01_reschedule_surgery_rejects_maintenance_equipment`

API (26):

- `test_tc_eq_01_create_equipment`
- `test_tc_eq_01_category_is_optional`
- `test_tc_eq_01_create_invalid_input_returns_400`
- `test_tc_eq_01_malformed_json_returns_400`
- `test_tc_eq_01_injection_string_is_stored_harmlessly`
- `test_tc_eq_01_list_with_filters`
- `test_tc_eq_01_list_invalid_status_returns_400`
- `test_tc_eq_01_update_equipment`
- `test_tc_eq_01_update_invalid_input_returns_400`
- `test_tc_eq_01_update_missing_returns_404`
- `test_tc_eq_01_retire_equipment_keeps_the_record`
- `test_tc_eq_01_retire_with_future_allocation_returns_409`
- `test_tc_eq_01_retire_missing_returns_404`
- `test_tc_eq_01_create_list_and_rename_theatre`
- `test_tc_eq_01_duplicate_theatre_name_returns_409`
- `test_tc_eq_01_create_theatre_invalid_returns_400`
- `test_tc_eq_01_patch_theatre_status`
- `test_tc_eq_01_patch_invalid_theatre_status_returns_400`
- `test_tc_eq_01_theatre_writes_on_missing_return_404`
- `test_tc_eq_01_retire_theatre`
- `test_tc_eq_01_retire_theatre_with_future_surgery_returns_409`
- `test_tc_eq_01_writes_are_admin_only`
- `test_tc_eq_01_reads_need_a_valid_token`
- `test_tc_eq_01_post_surgery_with_maintenance_equipment_returns_409`
- `test_tc_eq_01_post_surgery_with_retired_equipment_returns_409`
- `test_tc_eq_01_equipment_can_be_booked_after_maintenance_clears`

### TC-Eq-02: availability for a time range is correct (OT-F-041)

Service (14):

- `test_tc_eq_02_free_equipment_is_available`
- `test_tc_eq_02_overlap_rule_and_touching_boundaries`
- `test_tc_eq_02_released_allocation_does_not_block`
- `test_tc_eq_02_maintenance_equipment_is_unavailable`
- `test_tc_eq_02_retired_equipment_is_unavailable`
- `test_tc_eq_02_in_use_status_alone_does_not_block_a_later_range`
- `test_tc_eq_02_live_surgery_blocks_theatre`
- `test_tc_eq_02_finished_surgery_does_not_block_theatre`
- `test_tc_eq_02_unreleased_allocation_blocks_theatre`
- `test_tc_eq_02_occupied_or_cleaning_alone_does_not_block_a_later_range`
- `test_tc_eq_02_maintenance_or_retired_theatre_is_unavailable`
- `test_tc_eq_02_end_must_be_after_start`
- `test_tc_eq_02_time_with_offset_is_compared_like_stored_surgeries`
- `test_tc_eq_02_missing_records`

API (6):

- `test_tc_eq_02_equipment_availability_any_role`
- `test_tc_eq_02_availability_follows_bookings`
- `test_tc_eq_02_availability_follows_status`
- `test_tc_eq_02_bad_range_returns_400`
- `test_tc_eq_02_mixed_timezone_range_does_not_crash`
- `test_tc_eq_02_missing_item_returns_404`

### TC-Eq-03: allocate and release resources for a surgery (OT-F-042)

Service (24):

- `test_tc_eq_03_allocate_shows_resources_as_allocated`
- `test_tc_eq_03_allocate_does_not_conflict_with_own_theatre_booking`
- `test_tc_eq_03_all_or_nothing_when_one_item_is_in_maintenance`
- `test_tc_eq_03_all_or_nothing_when_one_item_overlaps`
- `test_tc_eq_03_retired_item_is_rejected`
- `test_tc_eq_03_theatre_in_maintenance_is_rejected`
- `test_tc_eq_03_item_cannot_be_allocated_twice_to_one_surgery`
- `test_tc_eq_03_touching_surgeries_can_share_an_item`
- `test_tc_eq_03_theatre_must_match_the_surgery`
- `test_tc_eq_03_finished_surgery_cannot_be_allocated`
- `test_tc_eq_03_allocate_missing_records`
- `test_tc_eq_03_release_makes_item_available_again`
- `test_tc_eq_03_double_release_has_no_further_effect`
- `test_tc_eq_03_release_missing_allocation`
- `test_tc_eq_03_allocate_and_release_are_audited`
- `test_tc_eq_03_cancel_surgery_makes_resources_available_again`
- `test_tc_eq_03_cancel_surgery_with_unknown_equipment_id_still_works`
- `test_tc_eq_03_allocating_a_future_surgery_leaves_status_available`
- `test_tc_eq_03_surgery_start_sets_in_use_and_occupied`
- `test_tc_eq_03_allocating_a_running_surgery_sets_in_use`
- `test_tc_eq_03_release_returns_in_use_item_to_available`
- `test_tc_eq_03_cancelling_running_surgery_frees_equipment_and_theatre`
- `test_tc_eq_03_cancelling_a_later_surgery_keeps_item_in_use`
- `test_tc_eq_03_sync_leaves_admin_statuses_alone`

API (8):

- `test_tc_eq_03_allocate_then_release_end_to_end`
- `test_tc_eq_03_duplicate_ids_in_request_allocate_once`
- `test_tc_eq_03_conflict_returns_409_and_creates_nothing`
- `test_tc_eq_03_invalid_body_returns_400`
- `test_tc_eq_03_finished_surgery_returns_400`
- `test_tc_eq_03_missing_records_return_404`
- `test_tc_eq_03_doctors_and_nurses_cannot_allocate`
- `test_tc_eq_03_cancel_surgery_then_available_again`

## 6. Open items

Reproduced against the current code. None of these is fixed here, because each belongs to a teammate's module.

| Owner | Problem | Effect |
|---|---|---|
| Pulkit | Nothing sets a surgery to `in_progress` or `completed` | in_use and occupied never appear through the API, and "release on completion" is manual (POST /allocations/{id}/release). A start or complete action should set the status, release on completion, and call `EquipmentService(db).sync_surgery_resources(surgery_id)`, then commit |
| Pulkit | Rescheduling without `equipment_ids` leaves allocations on the old slot | **The equipment shows as free at the new time and can be double-booked** |
| Pulkit | ~~Rescheduling with `equipment_ids` hard-deletes allocation rows~~ | **Fixed in OTMS-24**: old rows are kept with `released` and `replaced` set (see docs/record_retention_notes.md) |
| Pulkit | POST /surgeries accepts a theatre under maintenance or retired | The status check was only requested for equipment. POST /allocations does check the theatre |
| Pulkit | POST /surgeries accepts end before start, and unknown theatre or equipment ids | Bad rows reach the tables I read. SQLite does not enforce the foreign keys |
| Pulkit | `cancel_surgery` can cancel a completed surgery | History is overwritten |
| Piyush | No CI workflow exists | "CI green" cannot be shown. Preemption should also call `sync_surgery_resources` |
| Poorvi | No token gives 403 rather than 401 (deviation 15) | Fix in deps.py |
| Team | `requirements.txt` pins do not install on Python 3.14 (pydantic-core fails to build) | Use Python 3.11, as the SAD says |

## 7. Test and coverage results

Environment: Python 3.11.16 with the pins from `requirements.txt`, plus pytest-cov 7.1.0. Not run on Python 3.14.

- Baseline before this work: 7 passed.
- Now: **168 passed, 0 failed** (7 existing, 161 new including parametrized cases: 86 TC-Eq-01, 38 TC-Eq-02, 37 TC-Eq-03).
- Whole project: 93% with branch coverage.

| File | Statements | Missed | Branches | Coverage |
|---|---|---|---|---|
| app/services/equipment_service.py | 207 | 0 | 80 | 100% |
| app/schemas/equipment.py | 49 | 0 | 0 | 100% |
| app/api/v1/equipment.py | 27 | 0 | 0 | 100% |
| app/api/v1/theatres.py | 30 | 0 | 0 | 100% |
| app/api/v1/allocations.py | 17 | 0 | 0 | 100% |
| app/api/v1/errors.py | 20 | 0 | 0 | 100% |

Two further checks were run once and are not part of the suite:

- 20 deliberate faults (for example `<` changed to `<=`, the release guard removed, role checks loosened)
  were introduced one at a time in a temporary copy. The tests caught all 20.
- The full flow in section 8 was run against a real uvicorn server with a temporary database.

To reproduce the results:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt pytest-cov
.venv/bin/pytest --cov=app --cov-branch --cov-report=term-missing --cov-report=html:docs/coverage_html
```

Coverage.py writes its own `.gitignore` inside `docs/coverage_html`, so the HTML report is not committed by default.

## 8. Demo flow

1. POST /equipment twice, one with `"status": "maintenance"`, and POST /theatres.
2. POST /surgeries with the maintenance item: 409 naming the item.
3. POST /surgeries with no equipment: 201.
4. POST /allocations with both items: 409, and nothing is created.
5. POST /allocations with the good item: 201.
6. GET /equipment/{id}/availability for the slot: `available: false`.
7. DELETE /equipment/{id}: 409, it has a future allocation.
8. POST /allocations/{id}/release, twice: 200 both times.
9. GET availability again: `available: true`.
10. DELETE /surgeries/{id}, then GET /theatres/{id}/availability: `available: true`.

There is no /auth/login yet, so create a demo token with `app.core.security.create_access_token`.
