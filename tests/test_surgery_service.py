from datetime import datetime, timedelta

from app.models.models import Equipment, EquipmentStatusEnum, Staff, StaffTypeEnum, Theatre, TheatreStatusEnum
from app.services.surgery_service import SurgeryService


def test_create_surgery_success(db_session):
    theatre = Theatre(name="OT-1", status=TheatreStatusEnum.available)
    doctor = Staff(name="Dr. Alice", staff_type=StaffTypeEnum.doctor)
    nurse = Staff(name="Nurse Bob", staff_type=StaffTypeEnum.nurse)
    equipment = Equipment(name="Monitor", status=EquipmentStatusEnum.available)
    db_session.add_all([theatre, doctor, nurse, equipment])
    db_session.commit()

    service = SurgeryService(db_session)
    start = datetime(2026, 10, 29, 9, 0)
    end = datetime(2026, 10, 29, 11, 0)
    surgery, conflicts = service.create_surgery(
        patient_name="Test Patient",
        theatre_id=theatre.theatre_id,
        start_time=start,
        end_time=end,
        doctor_ids=[doctor.staff_id],
        nurse_ids=[nurse.staff_id],
        equipment_ids=[equipment.equipment_id],
    )
    assert surgery is not None
    assert conflicts is None
    assert surgery.status.value == "scheduled"


def test_create_surgery_conflict_rejected(db_session):
    theatre = Theatre(name="OT-1", status=TheatreStatusEnum.available)
    db_session.add(theatre)
    db_session.commit()

    service = SurgeryService(db_session)
    start = datetime(2026, 10, 29, 9, 0)
    end = datetime(2026, 10, 29, 11, 0)
    surgery1, _ = service.create_surgery(
        patient_name="Patient 1",
        theatre_id=theatre.theatre_id,
        start_time=start,
        end_time=end,
    )
    assert surgery1 is not None

    surgery2, conflicts = service.create_surgery(
        patient_name="Patient 2",
        theatre_id=theatre.theatre_id,
        start_time=start + timedelta(hours=1),
        end_time=end + timedelta(hours=1),
    )
    assert surgery2 is None
    assert conflicts is not None
    assert len(conflicts) > 0


def test_reschedule_surgery(db_session):
    theatre = Theatre(name="OT-1", status=TheatreStatusEnum.available)
    theatre2 = Theatre(name="OT-2", status=TheatreStatusEnum.available)
    db_session.add_all([theatre, theatre2])
    db_session.commit()

    service = SurgeryService(db_session)
    start = datetime(2026, 10, 29, 9, 0)
    end = datetime(2026, 10, 29, 11, 0)
    surgery, _ = service.create_surgery(
        patient_name="Patient 1",
        theatre_id=theatre.theatre_id,
        start_time=start,
        end_time=end,
    )

    new_start = datetime(2026, 10, 30, 9, 0)
    new_end = datetime(2026, 10, 30, 11, 0)
    rescheduled, conflicts = service.reschedule_surgery(
        surgery.surgery_id, start_time=new_start, end_time=new_end, theatre_id=theatre2.theatre_id
    )
    assert rescheduled is not None
    assert conflicts is None
    assert rescheduled.theatre_id == theatre2.theatre_id


def test_cancel_surgery_releases_resources(db_session):
    theatre = Theatre(name="OT-1", status=TheatreStatusEnum.available)
    db_session.add(theatre)
    db_session.commit()

    service = SurgeryService(db_session)
    start = datetime(2026, 10, 29, 9, 0)
    end = datetime(2026, 10, 29, 11, 0)
    surgery, _ = service.create_surgery(
        patient_name="Patient 1",
        theatre_id=theatre.theatre_id,
        start_time=start,
        end_time=end,
    )

    cancelled = service.cancel_surgery(surgery.surgery_id)
    assert cancelled.status.value == "cancelled"
