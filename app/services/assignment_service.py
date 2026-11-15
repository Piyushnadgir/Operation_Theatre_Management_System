"""Rules for assigning staff to a surgery (OT-F-033).

A doctor or nurse may be assigned only if the person exists, is active, is on shift
for the whole surgery and (for doctors, when a specialization is required) is
suitably specialized. Double-booking is handled by ConflictDetector.

Usage from the scheduling code::

    issues = AssignmentService(db).validate_assignments(
        doctor_ids, nurse_ids, start_time, end_time, required_specialization)
    if issues:
        return None, issues     # same dict format as ConflictDetector
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.models import StaffTypeEnum
from app.services.shift_service import ShiftService
from app.services.staff_service import StaffService


class AssignmentService:
    def __init__(self, db: Session):
        self.staff_service = StaffService(db)
        self.shift_service = ShiftService(db)

    def validate_assignment(
        self,
        staff_id: int,
        start_time: datetime,
        end_time: datetime,
        expected_type: Optional[StaffTypeEnum] = None,
        required_specialization: Optional[str] = None,
    ) -> Optional[str]:
        """Return the reason the person can't be assigned, or None if they can."""
        staff = self.staff_service.get_staff(staff_id)
        if staff is None:
            return f"Staff member {staff_id} does not exist"
        if not staff.is_active:
            return f"{staff.name} is deactivated and cannot be assigned"
        if expected_type is not None and staff.staff_type != expected_type:
            return f"{staff.name} is a {staff.staff_type.value}, not a {expected_type.value}"
        if not self.shift_service.is_on_shift(staff_id, start_time, end_time):
            return f"{staff.name} is not on shift for the whole surgery time"
        if staff.staff_type == StaffTypeEnum.doctor and required_specialization:
            have = (staff.specialization or "").strip().lower()
            if have != required_specialization.strip().lower():
                return f"{staff.name} is not specialized in {required_specialization.strip()}"
        return None

    def validate_assignments(
        self,
        doctor_ids: Optional[List[int]],
        nurse_ids: Optional[List[int]],
        start_time: datetime,
        end_time: datetime,
        required_specialization: Optional[str] = None,
    ) -> List[dict]:
        issues = []
        for staff_id in dict.fromkeys(doctor_ids or []):
            reason = self.validate_assignment(
                staff_id, start_time, end_time, StaffTypeEnum.doctor, required_specialization
            )
            if reason:
                issues.append({"resource_type": "doctor", "resource_id": staff_id, "message": reason})
        for staff_id in dict.fromkeys(nurse_ids or []):
            reason = self.validate_assignment(staff_id, start_time, end_time, StaffTypeEnum.nurse)
            if reason:
                issues.append({"resource_type": "nurse", "resource_id": staff_id, "message": reason})
        return issues
