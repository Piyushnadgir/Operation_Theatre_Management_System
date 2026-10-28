from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.models import (
    Allocation,
    Equipment,
    EquipmentStatusEnum,
    PriorityEnum,
    Staff,
    Surgery,
    SurgeryStaff,
    SurgeryStatusEnum,
)
from app.services.conflict_detection import ConflictDetector


class SurgeryService:
    def __init__(self, db: Session):
        self.db = db
        self.conflict_detector = ConflictDetector(db)

    def create_surgery(
        self,
        patient_name: str,
        theatre_id: int,
        start_time: datetime,
        end_time: datetime,
        doctor_ids: List[int] = None,
        nurse_ids: List[int] = None,
        equipment_ids: List[int] = None,
        priority: PriorityEnum = PriorityEnum.routine,
        created_by: int = None,
    ):
        doctor_ids = doctor_ids or []
        nurse_ids = nurse_ids or []
        equipment_ids = equipment_ids or []

        has_conflict, conflicts = self.conflict_detector.detect_all_conflicts(
            theatre_id=theatre_id,
            start_time=start_time,
            end_time=end_time,
            doctor_ids=doctor_ids,
            nurse_ids=nurse_ids,
            equipment_ids=equipment_ids,
        )
        if has_conflict:
            return None, conflicts

        surgery = Surgery(
            patient_name=patient_name,
            theatre_id=theatre_id,
            start_time=start_time,
            end_time=end_time,
            priority=priority,
            status=SurgeryStatusEnum.scheduled,
            created_by=created_by,
        )
        self.db.add(surgery)
        self.db.flush()

        for staff_id in set(doctor_ids + nurse_ids):
            ss = SurgeryStaff(surgery_id=surgery.surgery_id, staff_id=staff_id)
            self.db.add(ss)

        for eq_id in equipment_ids:
            alloc = Allocation(
                surgery_id=surgery.surgery_id,
                equipment_id=eq_id,
                theatre_id=theatre_id,
                start_time=start_time,
                end_time=end_time,
                released=False,
            )
            self.db.add(alloc)

        self.db.commit()
        self.db.refresh(surgery)
        return surgery, None

    def reschedule_surgery(
        self,
        surgery_id: int,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        theatre_id: Optional[int] = None,
        doctor_ids: Optional[List[int]] = None,
        nurse_ids: Optional[List[int]] = None,
        equipment_ids: Optional[List[int]] = None,
    ):
        surgery = self.db.query(Surgery).filter(Surgery.surgery_id == surgery_id).first()
        if not surgery:
            return None, [{"resource_type": "surgery", "resource_id": surgery_id, "message": "Surgery not found"}]

        new_start = start_time or surgery.start_time
        new_end = end_time or surgery.end_time
        new_theatre = theatre_id or surgery.theatre_id

        # Get current assigned staff
        current_staff = [ss.staff_id for ss in surgery.surgery_staff]
        new_doctors = doctor_ids if doctor_ids is not None else current_staff
        new_nurses = nurse_ids if nurse_ids is not None else []
        new_equipment = equipment_ids if equipment_ids is not None else []

        has_conflict, conflicts = self.conflict_detector.detect_all_conflicts(
            theatre_id=new_theatre,
            start_time=new_start,
            end_time=new_end,
            doctor_ids=new_doctors,
            nurse_ids=new_nurses,
            equipment_ids=new_equipment,
            exclude_surgery_id=surgery_id,
        )
        if has_conflict:
            return None, conflicts

        # Update surgery
        surgery.start_time = new_start
        surgery.end_time = new_end
        surgery.theatre_id = new_theatre

        # Update staff assignments
        if doctor_ids is not None or nurse_ids is not None:
            self.db.query(SurgeryStaff).filter(SurgeryStaff.surgery_id == surgery_id).delete()
            for staff_id in set((doctor_ids or []) + (nurse_ids or [])):
                ss = SurgeryStaff(surgery_id=surgery_id, staff_id=staff_id)
                self.db.add(ss)

        # Update allocations
        if equipment_ids is not None:
            self.db.query(Allocation).filter(Allocation.surgery_id == surgery_id).delete()
            for eq_id in equipment_ids:
                alloc = Allocation(
                    surgery_id=surgery_id,
                    equipment_id=eq_id,
                    theatre_id=new_theatre,
                    start_time=new_start,
                    end_time=new_end,
                    released=False,
                )
                self.db.add(alloc)

        self.db.commit()
        self.db.refresh(surgery)
        return surgery, None

    def cancel_surgery(self, surgery_id: int):
        surgery = self.db.query(Surgery).filter(Surgery.surgery_id == surgery_id).first()
        if not surgery:
            return None

        surgery.status = SurgeryStatusEnum.cancelled
        # Release allocations
        self.db.query(Allocation).filter(Allocation.surgery_id == surgery_id).update({"released": True})
        self.db.commit()
        self.db.refresh(surgery)
        return surgery

    def get_surgeries(self, date=None, theatre_id=None):
        query = self.db.query(Surgery)
        if theatre_id:
            query = query.filter(Surgery.theatre_id == theatre_id)
        if date:
            from datetime import date as date_type

            if isinstance(date, str):
                date = datetime.strptime(date, "%Y-%m-%d").date()
            query = query.filter(
                Surgery.start_time >= datetime.combine(date, datetime.min.time()),
                Surgery.start_time < datetime.combine(date, datetime.max.time()),
            )
        return query.all()
