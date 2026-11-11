# Utilization report notes (OTMS-22, OT-F-043)

Owner: Riyana K. Tests: TC-Rpt-01 and TC-Rpt-02 (and TC-Rpt-03 in OTMS-25).

## Endpoint

`GET /api/v1/reports/utilization?from=&to=[&theatreId=]`

| Item | Value |
|---|---|
| Access | admin and scheduler (read-only). doctor and nurse get 403, an invalid token gets 401 |
| `from`, `to` | ISO date or date-time, for example `2026-03-02` or `2026-03-02T08:00`. A date alone means midnight. The range is `[from, to)`: `to` is exclusive, so a whole November is `from=2026-11-01&to=2026-12-01` |
| `theatreId` | Optional. Limits the report to one theatre; equipment usage then counts only allocations in that theatre |
| 400 | `to` <= `from`, a range shorter than one minute, a badly formatted date, a missing `from`/`to`, a non-numeric `theatreId` |
| 404 | `theatreId` does not exist |

Response (camelCase, like the rest of the equipment module):

```json
{
  "start": "2026-03-02T08:00:00", "end": "2026-03-02T18:00:00", "rangeMinutes": 600,
  "theatres":  [{"theatreId": 1, "name": "OT-1", "bookedMinutes": 180, "availableMinutes": 600, "usagePercent": 30.0}],
  "equipment": [{"equipmentId": 1, "name": "Ventilator", "bookedMinutes": 180, "availableMinutes": 600, "usagePercent": 30.0}],
  "totals": {"theatres":  {"bookedMinutes": 180, "availableMinutes": 600, "usagePercent": 30.0},
             "equipment": {"bookedMinutes": 180, "availableMinutes": 600, "usagePercent": 30.0}}
}
```

## Definition

For each theatre and each equipment item:

- `availableMinutes` = whole minutes in `[from, to)`
- `bookedMinutes` = minutes of its bookings inside the range
- `usagePercent` = `bookedMinutes / availableMinutes x 100`, rounded half up to 2 decimals

Rules:

1. **Theatre bookings** are surgeries with status scheduled, in_progress or completed. Cancelled surgeries are excluded.
2. **Equipment bookings** are allocations whose surgery is not cancelled. Released allocations still count, because completed surgeries also release their equipment.
3. **Clipping.** A booking that crosses `from` or `to` counts only the part inside the range. A booking that only touches the range counts 0.
4. **No double counting.** Overlapping bookings of one item are merged before summing. This cannot happen through the API, but stays safe if bad data exists.
5. **Integer arithmetic.** Minutes are whole numbers (seconds are dropped, after merging), and the percentage uses `Decimal`, so the figures are exact and repeatable.
6. **Which items appear.** Every active theatre and equipment item appears, with 0% if unused. Retired items appear only if they have bookings in the range. With `theatreId`, that theatre always appears, even if retired.
7. **Totals** add up booked and available minutes over the listed rows: total % = sum(booked) / sum(available) x 100. With no rows, the total is 0%.

The denominator is the whole range. The SRS and SAD do not mention working hours, so none are used.

## Deviations and decisions

| # | Document says | Code does | Why |
|---|---|---|---|
| 1 | SAD 4.3: 200 {theatres[], equipment[]} | Adds `start`, `end`, `rangeMinutes` and `totals` | SAD 4.5 asks for "key figures", and TC-Rpt-03 needs totals |
| 2 | SAD 4.3 errors: 400 and 403 only | Also 404 for an unknown `theatreId`, and 401 for a bad token | A missing theatre is not a bad range. 401 comes from deps.py |
| 3 | Sprint task: `theatre_id` | Query name `theatreId` | Follows SAD 4.3 and the camelCase of the equipment module |
| 4 | Sprint task: snake_case fields | camelCase in JSON (`bookedMinutes`); snake_case inside Python | Same as the rest of the equipment module (SAD 4.3 style) |
| 5 | SRS 2.3: only Admin "views reports" | admin and scheduler | Sprint instruction |
| 6 | SAD 4.5: report "available for export" | No export endpoint | Not in SAD 4.3 or the Jira task; the JSON can be exported by the UI |

Limitation: an allocation released early (before its surgery ran) still counts, because the `allocation`
table has no release time. Only cancellation removes usage.

## Files

- `app/services/report_service.py`: the calculation (`booked_minutes`, `usage_percent`, `ReportService`)
- `app/schemas/report.py`: the response schema
- `app/api/v1/reports.py`: the endpoint
- `app/api/v1/__init__.py`: registers the router (shared file, one import and one line)
- `tests/test_report_service.py` and `tests/test_report_api.py`
