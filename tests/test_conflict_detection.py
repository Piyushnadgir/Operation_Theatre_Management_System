from datetime import datetime, timedelta

from app.models.models import Equipment, EquipmentStatusEnum, PriorityEnum, Staff, StaffTypeEnum, Surgery, SurgeryStaff, SurgeryStatusEnum, Theatre, TheatreStatusEnum
from app.services.conflict_detection import ConflictDetector


def test_theatre_conflict_detection(db_session):
    theatre = Theatre(name="OT-1", status=TheatreStatusEnum.available)
    db_session.add(theatre)
    db_session.commit()

    start = datetime(2026, 10, 28, 9, 0)
    end = datetime(2026, 10, 28, 11, 0)
    surgery = Surgery(
        patient_name="John Doe",
        theatre_id=theatre.theatre_id,
        start_time=start,
        end_time=end,
        priority=PriorityEnum.routine,
        status=SurgeryStatusEnum.scheduled,
    )
    db_session.add(surgery)
    db_session.commit()

    detector = ConflictDetector(db_session)
    has_conflict = detector.check_theatre_conflict(
        theatre.theatre_id, start + timedelta(hours=1), start + timedelta(hours=2)
    )
    assert has_conflict is True


def test_doctor_conflict_detection(db_session):
    doctor = Staff(name="Dr. Smith", staff_type=StaffTypeEnum.doctor, specialization="Cardio")
    db_session.add(doctor)
    db_session.commit()

    theatre = Theatre(name="OT-2", status=TheatreStatusEnum.available)
    db_session.add(theatre)
    db_session.commit()

    start = datetime(2026, 10, 28, 10, 0)
    end = datetime(2026, 10, 28, 12, 0)
    surgery = Surgery(
        patient_name="Jane Doe",
        theatre_id=theatre.theatre_id,
        start_time=start,
        end_time=end,
        priority=PriorityEnum.routine,
        status=SurgeryStatusEnum.scheduled,
    )
    db_session.add(surgery)
    db_session.commit()

    ss = SurgeryStaff(surgery_id=surgery.surgery_id, staff_id=doctor.staff_id)
    db_session.add(ss)
    db_session.commit()

    detector = ConflictDetector(db_session)
    conflicts = detector.check_doctor_conflict(
        [doctor.staff_id], start + timedelta(minutes=30), end + timedelta(minutes=30)
    )
    assert doctor.staff_id in conflicts


def test_equipment_conflict_detection(db_session):
    from app.models.models import Allocation

    theatre = Theatre(name="OT-3", status=TheatreStatusEnum.available)
    equipment = Equipment(name="Ventilator", category="Respiratory", status=EquipmentStatusEnum.in_use)
    db_session.add_all([theatre, equipment])
    db_session.commit()

    start = datetime(2026, 10, 28, 8, 0)
    end = datetime(2026, 10, 28, 10, 0)
    surgery = Surgery(
        patient_name="Bob",
        theatre_id=theatre.theatre_id,
        start_time=start,
        end_time=end,
        priority=PriorityEnum.routine,
        status=SurgeryStatusEnum.scheduled,
    )
    db_session.add(surgery)
    db_session.commit()

    alloc = Allocation(
        surgery_id=surgery.surgery_id,
        equipment_id=equipment.equipment_id,
        theatre_id=theatre.theatre_id,
        start_time=start,
        end_time=end,
        released=False,
    )
    db_session.add(alloc)
    db_session.commit()

    detector = ConflictDetector(db_session)
    conflicts = detector.check_equipment_conflict(
        [equipment.equipment_id], start, end - timedelta(minutes=30)
    )
    assert equipment.equipment_id in conflicts
