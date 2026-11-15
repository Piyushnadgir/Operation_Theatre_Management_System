from datetime import datetime
from typing import List

from sqlalchemy.orm import Session

from app.models.models import Staff, Surgery, SurgeryStaff, SurgeryStatusEnum


def upcoming_surgeries_for_user(db: Session, user_id: int, now: datetime) -> List[Surgery]:
    """Surgeries not yet finished that the user's staff record is assigned to (SAD 4.5).

    A doctor or nurse is linked to a login through staff.user_id. Users with no staff
    record (admins, schedulers) get an empty list.
    """
    return (
        db.query(Surgery)
        .join(SurgeryStaff, SurgeryStaff.surgery_id == Surgery.surgery_id)
        .join(Staff, Staff.staff_id == SurgeryStaff.staff_id)
        .filter(
            Staff.user_id == user_id,
            Surgery.status.in_([SurgeryStatusEnum.scheduled, SurgeryStatusEnum.in_progress]),
            Surgery.end_time > now,
        )
        .order_by(Surgery.start_time)
        .distinct()
        .all()
    )
