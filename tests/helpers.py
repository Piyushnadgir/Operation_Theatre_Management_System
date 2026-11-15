"""Shared test helpers for the auth and staff modules."""
from datetime import datetime

from app.core.security import pwd_context
from app.models.models import (
    PriorityEnum,
    Staff,
    StaffTypeEnum,
    Surgery,
    SurgeryStaff,
    SurgeryStatusEnum,
    Theatre,
    TheatreStatusEnum,
)

# bcrypt is deliberately slow; use the minimum cost so the test suite stays fast.
pwd_context.update(bcrypt__rounds=4)

PASSWORD = "Passw0rd!x"


def dt(day: int, hour: int, minute: int = 0) -> datetime:
    """A naive datetime in November 2026."""
    return datetime(2026, 11, day, hour, minute)


def make_staff(db, name="Dr. Asha", staff_type=StaffTypeEnum.doctor, specialization="Cardiology", active=True):
    staff = Staff(name=name, staff_type=staff_type, specialization=specialization, is_active=active)
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return staff


def make_shift_for(db, staff, start, end):
    from app.services.shift_service import ShiftService

    return ShiftService(db).set_shifts(staff.staff_id, [(start, end)])


def make_surgery_with_staff(db, staff, start, end, status=SurgeryStatusEnum.scheduled):
    theatre = Theatre(name=f"OT-{staff.staff_id}-{start.hour}", status=TheatreStatusEnum.available)
    db.add(theatre)
    db.commit()
    surgery = Surgery(
        patient_name="Test Patient",
        theatre_id=theatre.theatre_id,
        start_time=start,
        end_time=end,
        priority=PriorityEnum.routine,
        status=status,
    )
    db.add(surgery)
    db.commit()
    db.add(SurgeryStaff(surgery_id=surgery.surgery_id, staff_id=staff.staff_id))
    db.commit()
    return surgery
