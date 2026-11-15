"""Shifts and availability (OT-F-031)."""
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.models.models import Shift, Staff, Surgery, SurgeryStaff, SurgeryStatusEnum


class ShiftValidationError(ValueError):
    pass


def to_naive_utc(dt: datetime) -> datetime:
    """The database holds naive UTC datetimes; convert aware inputs to match."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _check_range(start: datetime, end: datetime) -> Tuple[datetime, datetime]:
    start, end = to_naive_utc(start), to_naive_utc(end)
    if end <= start:
        raise ShiftValidationError("End time must be after start time")
    return start, end


class ShiftService:
    def __init__(self, db: Session):
        self.db = db

    def _staff(self, staff_id: int) -> Optional[Staff]:
        return self.db.query(Staff).filter(Staff.staff_id == staff_id).first()

    def get_shifts(self, staff_id: int) -> List[Shift]:
        return (
            self.db.query(Shift)
            .filter(Shift.staff_id == staff_id)
            .order_by(Shift.start_time)
            .all()
        )

    def set_shifts(
        self, staff_id: int, shifts: Sequence[Tuple[datetime, datetime]]
    ) -> Optional[List[Shift]]:
        """Replace all shifts of a person. Returns None if the person does not exist.
        Raises ShiftValidationError for bad or overlapping shifts."""
        if self._staff(staff_id) is None:
            return None

        ranges = sorted(_check_range(start, end) for start, end in shifts)
        for previous, current in zip(ranges, ranges[1:]):
            if current[0] < previous[1]:
                raise ShiftValidationError("Shifts of one person must not overlap")

        # Expunge cached Shift objects before bulk delete so SQLite id reuse cannot leave stale state.
        for old_shift in self.db.query(Shift).filter(Shift.staff_id == staff_id).all():
            self.db.expunge(old_shift)
        self.db.query(Shift).filter(Shift.staff_id == staff_id).delete(synchronize_session=False)
        self.db.flush()
        new_shifts = [Shift(staff_id=staff_id, start_time=s, end_time=e) for s, e in ranges]
        self.db.add_all(new_shifts)
        self.db.commit()
        for shift in new_shifts:
            self.db.refresh(shift)
        return new_shifts

    def is_on_shift(self, staff_id: int, start: datetime, end: datetime) -> bool:
        """True if one shift covers the whole time range."""
        start, end = _check_range(start, end)
        return (
            self.db.query(Shift)
            .filter(
                Shift.staff_id == staff_id,
                Shift.start_time <= start,
                Shift.end_time >= end,
            )
            .first()
            is not None
        )

    def is_available(self, staff_id: int, start: datetime, end: datetime) -> Optional[bool]:
        """Active, on shift for the whole range and not in another surgery.
        Returns None if the person does not exist."""
        staff = self._staff(staff_id)
        if staff is None:
            return None
        start, end = _check_range(start, end)
        if not staff.is_active:
            return False
        if not self.is_on_shift(staff_id, start, end):
            return False
        busy = (
            self.db.query(SurgeryStaff)
            .join(Surgery, Surgery.surgery_id == SurgeryStaff.surgery_id)
            .filter(
                SurgeryStaff.staff_id == staff_id,
                Surgery.status.in_([SurgeryStatusEnum.scheduled, SurgeryStatusEnum.in_progress]),
                Surgery.start_time < end,
                Surgery.end_time > start,
            )
            .first()
        )
        return busy is None
