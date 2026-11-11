"""Doctor and nurse records (OT-F-030)."""
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import Staff, StaffTypeEnum

_UNSET = object()


class StaffService:
    def __init__(self, db: Session):
        self.db = db

    def create_staff(
        self,
        name: str,
        staff_type,
        specialization: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Staff:
        staff = Staff(
            name=name,
            staff_type=StaffTypeEnum(staff_type),
            specialization=specialization,
            user_id=user_id,
            is_active=True,
        )
        self.db.add(staff)
        self.db.commit()
        self.db.refresh(staff)
        return staff

    def get_staff(self, staff_id: int) -> Optional[Staff]:
        return self.db.query(Staff).filter(Staff.staff_id == staff_id).first()

    def list_staff(
        self,
        staff_type=None,
        specialization: Optional[str] = None,
        include_inactive: bool = False,
    ) -> List[Staff]:
        query = self.db.query(Staff)
        if not include_inactive:
            query = query.filter(Staff.is_active.is_(True))
        if staff_type is not None:
            query = query.filter(Staff.staff_type == StaffTypeEnum(staff_type))
        if specialization:
            query = query.filter(
                func.lower(Staff.specialization) == specialization.strip().lower()
            )
        return query.order_by(Staff.staff_id).all()

    def update_staff(self, staff_id: int, name=_UNSET, specialization=_UNSET) -> Optional[Staff]:
        staff = self.get_staff(staff_id)
        if staff is None:
            return None
        if name is not _UNSET:
            staff.name = name
        if specialization is not _UNSET:
            staff.specialization = specialization
        self.db.commit()
        self.db.refresh(staff)
        return staff

    def deactivate_staff(self, staff_id: int) -> Optional[Staff]:
        """Staff are deactivated, never deleted, so history stays available."""
        staff = self.get_staff(staff_id)
        if staff is None:
            return None
        staff.is_active = False
        self.db.commit()
        self.db.refresh(staff)
        return staff
