"""Service tests for the utilization report (OT-F-043).

TC-Rpt-01: the report covers all theatres and equipment.
TC-Rpt-02: the report is filtered by date range (clipping, empty ranges, cancelled excluded).
"""
from datetime import datetime

import pytest

from app.models.models import Allocation, Equipment, Surgery, SurgeryStatusEnum, Theatre
from app.services.equipment_service import InvalidRequest, ResourceNotFound
from app.services.report_service import ReportService, booked_minutes, usage_percent

# A fixed 10-hour range: 600 minutes
FROM = datetime(2026, 3, 2, 8, 0)
TO = datetime(2026, 3, 2, 18, 0)


def at(hour, minute=0, day=2):
    return datetime(2026, 3, day, hour, minute)


def add(db, *rows):
    db.add_all(rows)
    db.commit()
    return rows


def surgery(db, theatre, start, end, status=SurgeryStatusEnum.completed):
    (row,) = add(db, Surgery(patient_name="P", theatre_id=theatre.theatre_id, start_time=start, end_time=end, status=status))
    return row


def allocate(db, surgery_row, equipment, start=None, end=None):
    add(
        db,
        Allocation(
            surgery_id=surgery_row.surgery_id,
            equipment_id=equipment.equipment_id,
            theatre_id=surgery_row.theatre_id,
            start_time=start or surgery_row.start_time,
            end_time=end or surgery_row.end_time,
            released=True,
        ),
    )


def by_name(rows):
    return {row["name"]: row for row in rows}


# ---------- helper functions ----------


def test_tc_rpt_02_usage_percent_rounds_half_up_to_two_decimals():
    assert usage_percent(1, 3) == 33.33
    assert usage_percent(2, 3) == 66.67
    assert usage_percent(1, 8) == 12.5
    assert usage_percent(1, 800) == 0.13  # 0.125 rounds up
    assert usage_percent(600, 600) == 100.0
    assert usage_percent(0, 600) == 0.0


def test_tc_rpt_02_booked_minutes_clips_and_does_not_double_count():
    bookings = [
        (at(7), at(9)),  # crosses the start: counts 8:00-9:00 = 60
        (at(10), at(11)),  # inside, overlaps the next one
        (at(10, 30), at(12)),  # merged with the one above: 10:00-12:00 = 120
        (at(17), at(20)),  # crosses the end: counts 17:00-18:00 = 60
        (at(19), at(21)),  # outside: 0
    ]
    assert booked_minutes(bookings, FROM, TO) == 240


def test_tc_rpt_02_booked_minutes_touching_bookings_add_up():
    assert booked_minutes([(at(9), at(10)), (at(10), at(11))], FROM, TO) == 120


def test_tc_rpt_02_booked_minutes_with_no_bookings():
    assert booked_minutes([], FROM, TO) == 0


# ---------- TC-Rpt-01: covers all theatres and equipment ----------


def test_tc_rpt_01_report_lists_every_theatre_and_equipment_item(db_session):
    ot1, ot2 = add(db_session, Theatre(name="OT-1"), Theatre(name="OT-2"))
    vent, monitor = add(db_session, Equipment(name="Ventilator"), Equipment(name="Monitor"))
    s = surgery(db_session, ot1, at(9), at(12))  # 180 minutes
    allocate(db_session, s, vent)

    report = ReportService(db_session).utilization(FROM, TO)

    assert report["range_minutes"] == 600
    assert report["theatres"] == [
        {"theatre_id": ot1.theatre_id, "name": "OT-1", "booked_minutes": 180, "available_minutes": 600, "usage_percent": 30.0},
        {"theatre_id": ot2.theatre_id, "name": "OT-2", "booked_minutes": 0, "available_minutes": 600, "usage_percent": 0.0},
    ]
    assert report["equipment"] == [
        {"equipment_id": vent.equipment_id, "name": "Ventilator", "booked_minutes": 180, "available_minutes": 600, "usage_percent": 30.0},
        {"equipment_id": monitor.equipment_id, "name": "Monitor", "booked_minutes": 0, "available_minutes": 600, "usage_percent": 0.0},
    ]
    assert report["totals"]["theatres"] == {"booked_minutes": 180, "available_minutes": 1200, "usage_percent": 15.0}
    assert report["totals"]["equipment"] == {"booked_minutes": 180, "available_minutes": 1200, "usage_percent": 15.0}


@pytest.mark.parametrize("status", [SurgeryStatusEnum.scheduled, SurgeryStatusEnum.in_progress, SurgeryStatusEnum.completed])
def test_tc_rpt_01_scheduled_running_and_completed_surgeries_count(db_session, status):
    (ot1,) = add(db_session, Theatre(name="OT-1"))
    (vent,) = add(db_session, Equipment(name="Ventilator"))
    allocate(db_session, surgery(db_session, ot1, at(9), at(10), status), vent)
    report = ReportService(db_session).utilization(FROM, TO)
    assert report["theatres"][0]["booked_minutes"] == 60
    assert report["equipment"][0]["booked_minutes"] == 60


def test_tc_rpt_01_retired_items_shown_only_with_bookings(db_session):
    used_ot, idle_ot = add(db_session, Theatre(name="Used", is_active=False), Theatre(name="Idle", is_active=False))
    used_eq, idle_eq = add(db_session, Equipment(name="Used", is_active=False), Equipment(name="Idle", is_active=False))
    allocate(db_session, surgery(db_session, used_ot, at(9), at(10)), used_eq)
    report = ReportService(db_session).utilization(FROM, TO)
    assert [row["name"] for row in report["theatres"]] == ["Used"]
    assert [row["name"] for row in report["equipment"]] == ["Used"]


def test_tc_rpt_01_empty_database(db_session):
    report = ReportService(db_session).utilization(FROM, TO)
    assert report["theatres"] == []
    assert report["equipment"] == []
    assert report["totals"]["theatres"] == {"booked_minutes": 0, "available_minutes": 0, "usage_percent": 0.0}


# ---------- TC-Rpt-02: date filtering ----------


def test_tc_rpt_02_bookings_crossing_the_edges_are_clipped(db_session):
    (ot1,) = add(db_session, Theatre(name="OT-1"))
    (vent,) = add(db_session, Equipment(name="Ventilator"))
    allocate(db_session, surgery(db_session, ot1, at(6), at(9)), vent)  # 60 inside
    allocate(db_session, surgery(db_session, ot1, at(17, 30), at(20)), vent)  # 30 inside
    report = ReportService(db_session).utilization(FROM, TO)
    assert report["theatres"][0]["booked_minutes"] == 90
    assert report["theatres"][0]["usage_percent"] == 15.0
    assert report["equipment"][0]["booked_minutes"] == 90


def test_tc_rpt_02_booking_covering_the_whole_range_is_100_percent(db_session):
    (ot1,) = add(db_session, Theatre(name="OT-1"))
    surgery(db_session, ot1, at(0), at(23))
    assert ReportService(db_session).utilization(FROM, TO)["theatres"][0]["usage_percent"] == 100.0


def test_tc_rpt_02_bookings_outside_or_touching_the_range_are_ignored(db_session):
    (ot1,) = add(db_session, Theatre(name="OT-1"))
    (vent,) = add(db_session, Equipment(name="Ventilator"))
    allocate(db_session, surgery(db_session, ot1, at(6), at(8)), vent)  # ends exactly at FROM
    allocate(db_session, surgery(db_session, ot1, at(18), at(19)), vent)  # starts exactly at TO
    allocate(db_session, surgery(db_session, ot1, at(9, day=3), at(10, day=3)), vent)  # next day
    report = ReportService(db_session).utilization(FROM, TO)
    assert report["theatres"][0]["booked_minutes"] == 0
    assert report["equipment"][0]["booked_minutes"] == 0


def test_tc_rpt_02_range_with_no_bookings(db_session):
    (ot1,) = add(db_session, Theatre(name="OT-1"))
    surgery(db_session, ot1, at(9), at(10))
    report = ReportService(db_session).utilization(at(8, day=10), at(18, day=10))
    assert report["theatres"][0]["booked_minutes"] == 0
    assert report["theatres"][0]["usage_percent"] == 0.0


def test_tc_rpt_02_same_data_different_ranges(db_session):
    (ot1,) = add(db_session, Theatre(name="OT-1"))
    surgery(db_session, ot1, at(9), at(11))
    service = ReportService(db_session)
    assert service.utilization(at(9), at(10))["theatres"][0]["usage_percent"] == 100.0
    assert service.utilization(at(10), at(14))["theatres"][0]["usage_percent"] == 25.0


def test_tc_rpt_02_cancelled_surgeries_and_their_allocations_are_excluded(db_session):
    (ot1,) = add(db_session, Theatre(name="OT-1"))
    (vent,) = add(db_session, Equipment(name="Ventilator"))
    allocate(db_session, surgery(db_session, ot1, at(9), at(11), SurgeryStatusEnum.cancelled), vent)
    report = ReportService(db_session).utilization(FROM, TO)
    assert report["theatres"][0]["booked_minutes"] == 0
    assert report["equipment"][0]["booked_minutes"] == 0


def test_tc_rpt_02_overlapping_bookings_are_counted_once(db_session):
    """Cannot happen through the API, but the report must still not count a minute twice."""
    (ot1,) = add(db_session, Theatre(name="OT-1"))
    (vent,) = add(db_session, Equipment(name="Ventilator"))
    allocate(db_session, surgery(db_session, ot1, at(9), at(11)), vent)
    allocate(db_session, surgery(db_session, ot1, at(10), at(12)), vent)
    report = ReportService(db_session).utilization(FROM, TO)
    assert report["theatres"][0]["booked_minutes"] == 180
    assert report["equipment"][0]["booked_minutes"] == 180


def test_tc_rpt_02_theatre_filter(db_session):
    ot1, ot2 = add(db_session, Theatre(name="OT-1"), Theatre(name="OT-2"))
    vent, monitor = add(db_session, Equipment(name="Ventilator"), Equipment(name="Monitor"))
    allocate(db_session, surgery(db_session, ot1, at(9), at(10)), vent)
    allocate(db_session, surgery(db_session, ot2, at(9), at(11)), monitor)
    report = ReportService(db_session).utilization(FROM, TO, theatre_id=ot2.theatre_id)
    assert [(r["name"], r["booked_minutes"]) for r in report["theatres"]] == [("OT-2", 120)]
    # Equipment usage counts only allocations in OT-2
    assert by_name(report["equipment"])["Monitor"]["booked_minutes"] == 120
    assert by_name(report["equipment"])["Ventilator"]["booked_minutes"] == 0


def test_tc_rpt_02_filter_on_a_retired_theatre_still_shows_it(db_session):
    (ot1,) = add(db_session, Theatre(name="OT-1", is_active=False))
    report = ReportService(db_session).utilization(FROM, TO, theatre_id=ot1.theatre_id)
    assert [row["name"] for row in report["theatres"]] == ["OT-1"]


@pytest.mark.parametrize("start, end", [(TO, FROM), (FROM, FROM), (FROM, datetime(2026, 3, 2, 8, 0, 30))])
def test_tc_rpt_02_bad_range_is_rejected(db_session, start, end):
    with pytest.raises(InvalidRequest):
        ReportService(db_session).utilization(start, end)


def test_tc_rpt_02_unknown_theatre_filter(db_session):
    with pytest.raises(ResourceNotFound):
        ReportService(db_session).utilization(FROM, TO, theatre_id=999)
