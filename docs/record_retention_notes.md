# Record retention notes (OTMS-24, OT-NF-004)

Requirement: surgery, allocation and audit records are retained for at least 5 years.
Acceptance (TC-OPS-01): records older than 1 year remain retrievable, and nothing deletes them automatically before 5 years.

## How the requirement is met

| Record | How it is kept |
|---|---|
| Surgery | Never deleted. Cancelling sets `status = cancelled` (DELETE /surgeries/{id} is a cancel, not a delete) |
| Allocation | Never deleted. Release and cancel set `released = True`. Since OTMS-24, rescheduling also keeps the old rows (see below) |
| Audit log | Rows are only ever added; no code updates or deletes them |
| Equipment and theatres | Retiring sets `is_active = False`, so old allocations and reports still find them |

There is no purge job, scheduler or background task in the application. Rows stay until someone deletes them on purpose, outside the application.

## How it is tested (`tests/test_record_retention.py`, TC-OPS-01)

| Test | What it proves |
|---|---|
| `test_tc_ops_01_old_records_retrievable_through_service_layer` | Surgery, allocation and audit rows dated 2 and 6 years ago are read back through `SurgeryService`, the session and `ReportService` |
| `test_tc_ops_01_old_surgeries_retrievable_through_api` | `GET /api/v1/surgeries?date=` returns the old surgeries |
| `test_tc_ops_01_report_for_an_old_range_through_api` | The utilization report for an old range still shows the old usage |
| `test_tc_ops_01_normal_operations_never_remove_old_records` | Create, allocate, release, reschedule, cancel and retire leave every old row in place |
| `test_tc_ops_01_no_code_deletes_surgery_allocation_or_audit_rows` | Scans `app/` and fails on `session.delete(...)`, `query(Surgery/Allocation/AuditLog)...delete()` or raw `DELETE FROM`/`TRUNCATE`/`DROP TABLE` |
| `test_tc_ops_01_no_scheduler_or_background_job` | Fails if `app/` imports a scheduler (APScheduler, Celery, `schedule`, `rq`, `sched`) or uses `BackgroundTasks`, `on_event`, `lifespan`, `create_task` or `Timer` |
| `test_tc_ops_01_scan_really_detects_deletes` | Checks the scan itself on a sample file, so an empty result means something |
| `test_tc_ops_01_reschedule_keeps_old_allocation_rows` and 3 more | Rescheduling keeps every version of the allocation, frees the old slot, and the report does not double count |

## Fix made in OTMS-24 (approved by Riyana; Pulkit's file)

Before: `SurgeryService.reschedule_surgery` deleted all of a surgery's allocation rows when `equipment_ids` was given.
The code scan found this.

After:
- `app/models/models.py`: new column `Allocation.replaced` (Boolean, default False).
- `app/services/surgery_service.py`: the old rows get `released = True, replaced = True` instead of being deleted; new rows are added as before.
- `app/services/report_service.py`: the utilization report ignores replaced rows.

Why a new column: releasing alone was not enough. The report counts released rows, because completed surgeries
also release their equipment. With release only, a 2-hour surgery moved within one day showed 240 equipment minutes instead of 120.
`replaced` plays the role of the `cancelled` state in the SAD's `resource_allocation` table (SAD 3.6.1).

**Existing databases:** there are no Alembic migrations, and `create_all` does not add columns. Delete any old `otms.db` so it is recreated.

## Manual or out of scope

- **Backups.** The database file must be backed up by whoever runs the server (for example, copy `otms.db` daily, or use PostgreSQL backups in deployment). Not automated here.
- **Deleting records after 5 years.** The requirement sets a minimum. Any deletion after 5 years is a hospital policy decision and is not built.
- **Audit log API.** `main` has no endpoint to read the audit log yet (Poorvi's auth/audit branch is not merged), so audit rows are checked through the database session only.
- **Database administrators.** Nothing stops someone deleting rows directly in the database. That is controlled by server access, not the application.
- **Staff assignments.** `reschedule_surgery` still deletes and recreates `surgery_staff` rows. OT-NF-004 does not list staff assignments, so this is left as is and reported to Pulkit.
- **Not fixed:** rescheduling without `equipment_ids` still leaves the allocations on the old slot (reported in docs/equipment_module_notes.md).

## Deviation from the SAD

SAD 3.6.1 gives allocations a `state` (reserved, active, released, cancelled). The code keeps the existing `released` boolean
and adds a `replaced` boolean instead of moving to a state column, which would need changes across the team's code.
