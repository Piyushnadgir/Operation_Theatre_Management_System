"""Unit & service tests for Emergency module: OT-F-020..023 (OTMS-8..11)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models.models import (
    Allocation,
    AuditLog,
    EmergencyCase,
    Equipment,
    Notification,
    PriorityEnum,
    RoleEnum,
    Staff,
    StaffTypeEnum,
    Surgery,
    SurgeryStaff,
    SurgeryStatusEnum,
    Theatre,
    TheatreStatusEnum,
    User,
)
from app.schemas.emergency import EmergencyCreate
from app.services.emergency_service import (
    EmergencyConflictError,
    EmergencyNotFoundError,
    EmergencyPriorityQueue,
    EmergencyService,
    EmergencyValidationError,
    find_next_free_slot,
    times_overlap,
)
from app.services.surgery_service import SurgeryService


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 15, hour, minute)


# ---------- OTMS-8 / OT-F-020: Emergency Intake ----------


def test_tc_emg_01_logs_critical_and_urgent_emergencies(db_session):
    theatre = Theatre(name="OT-1", status=TheatreStatusEnum.available)
    db_session.add(theatre)
    db_session.commit()

    service = EmergencyService(db_session)
    surgery, case, bumped, notifs = service.log_and_process_emergency(
        EmergencyCreate(
            patient_name="  Ravi Kumar  ",
            theatre_id=theatre.theatre_id,
            start_time=at(9),
            end_time=at(11),
            priority=PriorityEnum.critical,
        )
    )
    assert surgery.patient_name == "Ravi Kumar"
    assert surgery.priority == PriorityEnum.critical
    assert surgery.status == SurgeryStatusEnum.scheduled
    assert case.surgery_id == surgery.surgery_id
    assert bumped == []
    assert notifs == 0
    assert db_session.query(EmergencyCase).count() == 1
    assert db_session.query(AuditLog).filter(AuditLog.action == "emergency.create").count() == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"priority": PriorityEnum.routine},
        {"patient_name": "   "},
        {"start_time": at(11), "end_time": at(9)},
        {"start_time": at(10), "end_time": at(10)},
    ],
)
def test_tc_emg_01_rejects_invalid_emergency_inputs(db_session, kwargs):
    base = {
        "patient_name": "Ravi",
        "theatre_id": 1,
        "start_time": at(9),
        "end_time": at(11),
        "priority": PriorityEnum.critical,
    }
    base.update(kwargs)
    with pytest.raises(EmergencyValidationError):
        EmergencyService(db_session).log_and_process_emergency(EmergencyCreate(**base))


def test_rejects_maintenance_or_retired_theatre(db_session):
    maint = Theatre(name="OT-Maint", status=TheatreStatusEnum.maintenance)
    retired = Theatre(name="OT-Ret", status=TheatreStatusEnum.available, is_active=False)
    db_session.add_all([maint, retired])
    db_session.commit()

    service = EmergencyService(db_session)
    for t_id in (maint.theatre_id, retired.theatre_id):
        with pytest.raises(EmergencyConflictError):
            service.log_and_process_emergency(
                EmergencyCreate(
                    patient_name="Ravi",
                    theatre_id=t_id,
                    start_time=at(9),
                    end_time=at(11),
                    priority=PriorityEnum.urgent,
                )
            )


def test_accepts_timezone_aware_inputs(db_session):
    start_tz = at(9).replace(tzinfo=timezone.utc)
    end_tz = at(10).replace(tzinfo=timezone.utc)
    surgery, _, _, _ = EmergencyService(db_session).log_and_process_emergency(
        EmergencyCreate(
            patient_name="TZ Patient",
            theatre_id=1,
            start_time=start_tz,
            end_time=end_tz,
            priority=PriorityEnum.urgent,
        )
    )
    assert surgery.start_time == at(9)
    assert surgery.end_time == at(10)


# ---------- OTMS-9 / OT-F-021: Emergency Priority Queue ----------


def test_tc_emg_02_priority_queue_unit_order():
    q = EmergencyPriorityQueue()
    assert q.peek() is None and len(q) == 0
    with pytest.raises(IndexError):
        q.pop()

    u1 = Surgery(surgery_id=1, patient_name="U1", theatre_id=1, start_time=at(9), end_time=at(10), priority=PriorityEnum.urgent)
    c1 = Surgery(surgery_id=2, patient_name="C1", theatre_id=1, start_time=at(9), end_time=at(10), priority=PriorityEnum.critical)
    u2 = Surgery(surgery_id=3, patient_name="U2", theatre_id=1, start_time=at(9), end_time=at(10), priority=PriorityEnum.urgent)
    c2 = Surgery(surgery_id=4, patient_name="C2", theatre_id=1, start_time=at(9), end_time=at(10), priority=PriorityEnum.critical)

    for s in (u1, c1, u2, c2):
        q.push(s)

    assert len(q) == 4
    assert q.peek().surgery_id == 2
    assert [s.surgery_id for s in q.ordered()] == [2, 4, 1, 3]
    assert [q.pop().surgery_id for _ in range(4)] == [2, 4, 1, 3]


def test_tc_emg_02_service_queue_returns_critical_before_urgent_fifo(db_session):
    service = EmergencyService(db_session)
    service.log_and_process_emergency(
        EmergencyCreate(patient_name="Urgent-1", theatre_id=1, start_time=at(9), end_time=at(10), priority=PriorityEnum.urgent)
    )
    service.log_and_process_emergency(
        EmergencyCreate(patient_name="Critical-1", theatre_id=2, start_time=at(9), end_time=at(10), priority=PriorityEnum.critical)
    )
    service.log_and_process_emergency(
        EmergencyCreate(patient_name="Urgent-2", theatre_id=3, start_time=at(9), end_time=at(10), priority=PriorityEnum.urgent)
    )
    service.log_and_process_emergency(
        EmergencyCreate(patient_name="Critical-2", theatre_id=4, start_time=at(9), end_time=at(10), priority=PriorityEnum.critical)
    )

    ordered_names = [s.patient_name for s in service.get_priority_queue()]
    assert ordered_names == ["Critical-1", "Critical-2", "Urgent-1", "Urgent-2"]


# ---------- OTMS-10 / OT-F-022: Slot Preemption & Rescheduling ----------


def test_overlaps_and_find_next_free_slot_helpers():
    assert times_overlap(at(9), at(11), at(10), at(12))
    assert not times_overlap(at(9), at(10), at(10), at(11))
    assert find_next_free_slot(timedelta(hours=1), at(9), []) == at(9)


def test_tc_emg_03_bumps_routine_and_skips_later_booked_slots(db_session):
    theatre = Theatre(name="OT-1", status=TheatreStatusEnum.available)
    other_theatre = Theatre(name="OT-2", status=TheatreStatusEnum.available)
    vent = Equipment(name="Ventilator")
    db_session.add_all([theatre, other_theatre, vent])
    db_session.commit()

    sched = SurgeryService(db_session)
    r1, _ = sched.create_surgery("Asha", theatre.theatre_id, at(9), at(11), equipment_ids=[vent.equipment_id])
    r2, _ = sched.create_surgery("Vikram", theatre.theatre_id, at(11), at(13))
    other, _ = sched.create_surgery("OtherOT", other_theatre.theatre_id, at(9), at(11))

    emg, _, moved, _ = EmergencyService(db_session).log_and_process_emergency(
        EmergencyCreate(
            patient_name="Emergency-1",
            theatre_id=theatre.theatre_id,
            start_time=at(9),
            end_time=at(10),
            priority=PriorityEnum.critical,
        )
    )

    assert len(moved) == 1
    assert moved[0].surgery_id == r1.surgery_id
    assert moved[0].old_start_time == at(9)
    assert moved[0].new_start_time == at(13)  # 10-12 clashes with Vikram (11-13)
    assert moved[0].new_end_time == at(15)

    db_session.refresh(r1)
    db_session.refresh(r2)
    db_session.refresh(other)
    assert r1.start_time == at(13) and r1.end_time == at(15)
    assert r2.start_time == at(11)  # untouched
    assert other.start_time == at(9)  # other theatre untouched
    assert emg.start_time == at(9)

    # OT-NF-004: allocation history preserved (old row replaced=True, new row active)
    allocs = db_session.query(Allocation).filter(Allocation.surgery_id == r1.surgery_id).order_by(Allocation.allocation_id).all()
    assert [(a.start_time, a.released, a.replaced) for a in allocs] == [
        (at(9), True, True),
        (at(13), False, False),
    ]


def test_tc_emg_04_cannot_bump_equal_or_higher_priority(db_session):
    theatre = Theatre(name="OT-1", status=TheatreStatusEnum.available)
    db_session.add(theatre)
    db_session.commit()

    service = EmergencyService(db_session)
    service.log_and_process_emergency(
        EmergencyCreate(
            patient_name="Critical-First",
            theatre_id=theatre.theatre_id,
            start_time=at(9),
            end_time=at(11),
            priority=PriorityEnum.critical,
        )
    )

    with pytest.raises(EmergencyConflictError, match="blocked by equal or higher priority"):
        service.log_and_process_emergency(
            EmergencyCreate(
                patient_name="Urgent-Second",
                theatre_id=theatre.theatre_id,
                start_time=at(10),
                end_time=at(12),
                priority=PriorityEnum.urgent,
            )
        )

    # Queue should still contain only the successfully placed emergency
    assert [s.patient_name for s in service.get_priority_queue()] == ["Critical-First"]


# ---------- OTMS-11 / OT-F-023: Notifications ----------


def test_tc_emg_05_notifications_created_for_affected_staff_and_schedulers(db_session):
    u_doc = User(username="doc1", password_hash="hash", role=RoleEnum.doctor)
    u_nurse = User(username="nurse1", password_hash="hash", role=RoleEnum.nurse)
    u_sched = User(username="sched1", password_hash="hash", role=RoleEnum.scheduler)
    u_emg_doc = User(username="emgdoc", password_hash="hash", role=RoleEnum.doctor)
    db_session.add_all([u_doc, u_nurse, u_sched, u_emg_doc])
    db_session.flush()

    s_doc = Staff(user_id=u_doc.user_id, name="Dr. Rao", staff_type=StaffTypeEnum.doctor)
    s_nurse = Staff(user_id=u_nurse.user_id, name="Nurse Mary", staff_type=StaffTypeEnum.nurse)
    s_emg_doc = Staff(user_id=u_emg_doc.user_id, name="Dr. Emergency", staff_type=StaffTypeEnum.doctor)
    theatre = Theatre(name="OT-1", status=TheatreStatusEnum.available)
    db_session.add_all([s_doc, s_nurse, s_emg_doc, theatre])
    db_session.commit()

    routine, _ = SurgeryService(db_session).create_surgery(
        "Asha",
        theatre.theatre_id,
        at(9),
        at(11),
        doctor_ids=[s_doc.staff_id],
        nurse_ids=[s_nurse.staff_id],
    )

    emg, _, _, notif_count = EmergencyService(db_session).log_and_process_emergency(
        EmergencyCreate(
            patient_name="Ravi",
            theatre_id=theatre.theatre_id,
            start_time=at(9),
            end_time=at(10),
            priority=PriorityEnum.critical,
            doctor_ids=[s_emg_doc.staff_id],
        ),
        logged_by_user_id=u_sched.user_id,
    )

    assert notif_count == 4  # routine doctor, routine nurse, scheduler, emergency doctor
    all_notifs = db_session.query(Notification).all()
    assert len(all_notifs) == 4

    for uid in (u_doc.user_id, u_nurse.user_id, u_sched.user_id):
        notes = EmergencyService(db_session).get_notifications(uid, unread_only=True)
        assert len(notes) == 1
        assert str(routine.surgery_id) in notes[0].message
        assert "09:00" in notes[0].message and "10:00" in notes[0].message

    emg_notes = EmergencyService(db_session).get_notifications(u_emg_doc.user_id)
    assert len(emg_notes) == 1
    assert str(emg.surgery_id) in emg_notes[0].message

    marked = EmergencyService(db_session).mark_notification_read(emg_notes[0].notification_id, u_emg_doc.user_id)
    assert marked.is_read is True
    assert EmergencyService(db_session).get_notifications(u_emg_doc.user_id, unread_only=True) == []

    with pytest.raises(EmergencyNotFoundError):
        EmergencyService(db_session).mark_notification_read(emg_notes[0].notification_id, u_doc.user_id)
