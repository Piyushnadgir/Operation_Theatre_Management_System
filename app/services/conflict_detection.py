from datetime import datetime
from typing import List, Tuple

from sqlalchemy.orm import Session

from app.models.models import Allocation, EquipmentStatusEnum, Shift, Staff, Surgery, SurgeryStaff, TheatreStatusEnum


class ConflictDetector:
    def __init__(self, db: Session):
        self.db = db

    def check_theatre_conflict(
        self, theatre_id: int, start_time: datetime, end_time: datetime, exclude_surgery_id: int = None
    ) -> bool:
        query = self.db.query(Surgery).filter(
            Surgery.theatre_id == theatre_id,
            Surgery.status.in_(["scheduled", "in_progress"]),
            Surgery.start_time < end_time,
            Surgery.end_time > start_time,
        )
        if exclude_surgery_id is not None:
            query = query.filter(Surgery.surgery_id != exclude_surgery_id)
        return query.first() is not None

    def check_doctor_conflict(
        self, doctor_ids: List[int], start_time: datetime, end_time: datetime, exclude_surgery_id: int = None
    ) -> List[int]:
        conflicts = []
        for doctor_id in doctor_ids:
            query = self.db.query(SurgeryStaff).join(Surgery).filter(
                SurgeryStaff.staff_id == doctor_id,
                Surgery.status.in_(["scheduled", "in_progress"]),
                Surgery.start_time < end_time,
                Surgery.end_time > start_time,
            )
            if exclude_surgery_id is not None:
                query = query.filter(Surgery.surgery_id != exclude_surgery_id)
            if query.first() is not None:
                conflicts.append(doctor_id)
        return conflicts

    def check_nurse_conflict(
        self, nurse_ids: List[int], start_time: datetime, end_time: datetime, exclude_surgery_id: int = None
    ) -> List[int]:
        conflicts = []
        for nurse_id in nurse_ids:
            query = self.db.query(SurgeryStaff).join(Surgery).filter(
                SurgeryStaff.staff_id == nurse_id,
                Surgery.status.in_(["scheduled", "in_progress"]),
                Surgery.start_time < end_time,
                Surgery.end_time > start_time,
            )
            if exclude_surgery_id is not None:
                query = query.filter(Surgery.surgery_id != exclude_surgery_id)
            if query.first() is not None:
                conflicts.append(nurse_id)
        return conflicts

    def check_equipment_conflict(
        self, equipment_ids: List[int], start_time: datetime, end_time: datetime, exclude_surgery_id: int = None
    ) -> List[int]:
        conflicts = []
        for equipment_id in equipment_ids:
            query = self.db.query(Allocation).filter(
                Allocation.equipment_id == equipment_id,
                Allocation.released == False,
                Allocation.start_time < end_time,
                Allocation.end_time > start_time,
            )
            if exclude_surgery_id is not None:
                query = query.filter(Allocation.surgery_id != exclude_surgery_id)
            if query.first() is not None:
                conflicts.append(equipment_id)
        return conflicts

    def detect_all_conflicts(
        self,
        theatre_id: int,
        start_time: datetime,
        end_time: datetime,
        doctor_ids: List[int] = None,
        nurse_ids: List[int] = None,
        equipment_ids: List[int] = None,
        exclude_surgery_id: int = None,
    ) -> Tuple[bool, List[dict]]:
        conflicts = []
        if self.check_theatre_conflict(theatre_id, start_time, end_time, exclude_surgery_id):
            conflicts.append(
                {"resource_type": "theatre", "resource_id": theatre_id, "message": f"Theatre {theatre_id} is already booked for the selected time slot"}
            )

        if doctor_ids:
            for doc_id in self.check_doctor_conflict(doctor_ids, start_time, end_time, exclude_surgery_id):
                conflicts.append(
                    {"resource_type": "doctor", "resource_id": doc_id, "message": f"Doctor {doc_id} is not available at the selected time"}
                )

        if nurse_ids:
            for nurse_id in self.check_nurse_conflict(nurse_ids, start_time, end_time, exclude_surgery_id):
                conflicts.append(
                    {"resource_type": "nurse", "resource_id": nurse_id, "message": f"Nurse {nurse_id} is not available at the selected time"}
                )

        if equipment_ids:
            for eq_id in self.check_equipment_conflict(equipment_ids, start_time, end_time, exclude_surgery_id):
                conflicts.append(
                    {"resource_type": "equipment", "resource_id": eq_id, "message": f"Equipment {eq_id} is already in use"}
                )

        return len(conflicts) > 0, conflicts
