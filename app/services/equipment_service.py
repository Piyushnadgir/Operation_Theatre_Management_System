from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.models import (
    Allocation,
    AuditLog,
    Equipment,
    EquipmentStatusEnum,
    Surgery,
    SurgeryStatusEnum,
    Theatre,
    TheatreStatusEnum,
)
from app.services.conflict_detection import ConflictDetector

# SAD 3.4: the equipment status changes an admin may make by hand.
# in_use is only set and cleared by the allocation flow, so an admin can never choose it,
# and an in_use item must be released before it can go to maintenance.
EQUIPMENT_ADMIN_CHANGES = {
    EquipmentStatusEnum.available: {EquipmentStatusEnum.maintenance},
    EquipmentStatusEnum.maintenance: {EquipmentStatusEnum.available},
    EquipmentStatusEnum.in_use: set(),
}

# SAD 3.4: cleaning and maintenance are set by an admin; occupied follows the surgery.
THEATRE_ADMIN_STATUSES = {
    TheatreStatusEnum.available,
    TheatreStatusEnum.cleaning,
    TheatreStatusEnum.maintenance,
}


class ResourceNotFound(Exception):
    """A record does not exist (HTTP 404)."""


class InvalidRequest(Exception):
    """The request breaks a rule (HTTP 400)."""


class ResourceConflict(Exception):
    """A resource is unavailable (HTTP 409). Holds the same conflict dicts as ConflictDetector."""

    def __init__(self, conflicts: List[dict]):
        super().__init__("Resource conflict detected")
        self.conflicts = conflicts


def clean_time_range(start: datetime, end: datetime):
    """Check a time range and return it without timezone info.

    Surgeries are stored without an offset, so offsets are dropped here too. This also
    stops Python failing when one value has an offset and the other does not.
    """
    start = start.replace(tzinfo=None)
    end = end.replace(tzinfo=None)
    if end <= start:
        raise InvalidRequest("end must be after start")
    return start, end


class EquipmentService:
    def __init__(self, db: Session):
        self.db = db
        self.conflict_detector = ConflictDetector(db)

    # ---------- Equipment (OT-F-040) ----------

    def create_equipment(
        self,
        name: str,
        category: Optional[str] = None,
        status: EquipmentStatusEnum = EquipmentStatusEnum.available,
    ) -> Equipment:
        if status == EquipmentStatusEnum.in_use:
            raise InvalidRequest("New equipment cannot start as in_use")
        equipment = Equipment(name=name, category=category, status=status)
        self.db.add(equipment)
        self.db.commit()
        self.db.refresh(equipment)
        return equipment

    def list_equipment(
        self,
        status: Optional[EquipmentStatusEnum] = None,
        category: Optional[str] = None,
        include_retired: bool = False,
    ) -> List[Equipment]:
        query = self.db.query(Equipment)
        if status is not None:
            query = query.filter(Equipment.status == status)
        if category is not None:
            query = query.filter(Equipment.category == category)
        if not include_retired:
            query = query.filter(Equipment.is_active == True)
        return query.all()

    def update_equipment(
        self,
        equipment_id: int,
        name: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[EquipmentStatusEnum] = None,
    ) -> Equipment:
        equipment = self._get_equipment(equipment_id)
        if status is not None and status != equipment.status:
            if status not in EQUIPMENT_ADMIN_CHANGES[equipment.status]:
                raise InvalidRequest(
                    f"Equipment status cannot change from {equipment.status.value} to {status.value}"
                )
            equipment.status = status
        if name is not None:
            equipment.name = name
        if category is not None:
            equipment.category = category
        self.db.commit()
        self.db.refresh(equipment)
        return equipment

    def retire_equipment(self, equipment_id: int) -> Equipment:
        """Soft delete: the row stays for history and reports (OT-NF-004)."""
        equipment = self._get_equipment(equipment_id)
        # Overlapping "from now until forever" means any current or future allocation
        if self.conflict_detector.check_equipment_conflict([equipment_id], datetime.now(), datetime.max):
            raise ResourceConflict(
                [self._conflict("equipment", equipment_id, f"Equipment {equipment_id} has future allocations")]
            )
        equipment.is_active = False
        self.db.commit()
        return equipment

    # ---------- Theatres (OT-F-040) ----------

    def create_theatre(self, name: str, status: TheatreStatusEnum = TheatreStatusEnum.available) -> Theatre:
        self._check_theatre_status_allowed(status)
        self._check_theatre_name_free(name)
        theatre = Theatre(name=name, status=status)
        self.db.add(theatre)
        self.db.commit()
        self.db.refresh(theatre)
        return theatre

    def list_theatres(self, include_retired: bool = False) -> List[Theatre]:
        query = self.db.query(Theatre)
        if not include_retired:
            query = query.filter(Theatre.is_active == True)
        return query.all()

    def update_theatre(self, theatre_id: int, name: str) -> Theatre:
        theatre = self._get_theatre(theatre_id)
        if name != theatre.name:
            self._check_theatre_name_free(name)
            theatre.name = name
        self.db.commit()
        self.db.refresh(theatre)
        return theatre

    def update_theatre_status(self, theatre_id: int, status: TheatreStatusEnum) -> Theatre:
        theatre = self._get_theatre(theatre_id)
        self._check_theatre_status_allowed(status)
        if theatre.status == TheatreStatusEnum.occupied:
            raise InvalidRequest("Theatre is occupied; its status changes when the surgery ends")
        theatre.status = status
        self.db.commit()
        self.db.refresh(theatre)
        return theatre

    def retire_theatre(self, theatre_id: int) -> Theatre:
        """Soft delete, the same as retire_equipment."""
        theatre = self._get_theatre(theatre_id)
        if self._theatre_is_booked(theatre_id, datetime.now(), datetime.max):
            raise ResourceConflict(
                [self._conflict("theatre", theatre_id, f"Theatre {theatre_id} has future bookings")]
            )
        theatre.is_active = False
        self.db.commit()
        return theatre

    # ---------- Availability (OT-F-041) ----------

    def equipment_availability(self, equipment_id: int, start: datetime, end: datetime) -> dict:
        equipment = self._get_equipment(equipment_id)
        start, end = clean_time_range(start, end)
        reasons = self._equipment_problems(equipment, start, end)
        return {"available": not reasons, "status": equipment.status.value, "reasons": reasons}

    def theatre_availability(self, theatre_id: int, start: datetime, end: datetime) -> dict:
        theatre = self._get_theatre(theatre_id)
        start, end = clean_time_range(start, end)
        reasons = self._theatre_problems(theatre, start, end)
        return {"available": not reasons, "status": theatre.status.value, "reasons": reasons}

    # ---------- Allocation and release (OT-F-042) ----------

    def allocate(
        self, surgery_id: int, theatre_id: int, equipment_ids: List[int], user_id: Optional[int] = None
    ) -> List[Allocation]:
        """Allocate every item for the surgery's slot, or nothing at all (SAD 3.4)."""
        surgery = self.db.query(Surgery).filter(Surgery.surgery_id == surgery_id).first()
        if not surgery:
            raise ResourceNotFound(f"Surgery {surgery_id} not found")
        if surgery.status not in (SurgeryStatusEnum.scheduled, SurgeryStatusEnum.in_progress):
            raise InvalidRequest(f"Surgery {surgery_id} is {surgery.status.value}")
        theatre = self._get_theatre(theatre_id)
        if theatre_id != surgery.theatre_id:
            raise InvalidRequest(f"Surgery {surgery_id} is booked in theatre {surgery.theatre_id}, not {theatre_id}")
        items = [self._get_equipment(equipment_id) for equipment_id in equipment_ids]

        # Check everything before creating anything. The surgery's own theatre booking is not
        # a conflict, but its own allocations are, so an item cannot be allocated to it twice.
        start, end = surgery.start_time, surgery.end_time
        conflicts = [
            self._conflict("theatre", theatre_id, f"Theatre {theatre_id}: {problem}")
            for problem in self._theatre_problems(theatre, start, end, exclude_surgery_id=surgery_id)
        ]
        for equipment in items:
            for problem in self._equipment_problems(equipment, start, end):
                conflicts.append(
                    self._conflict("equipment", equipment.equipment_id, f"Equipment {equipment.equipment_id}: {problem}")
                )
        if conflicts:
            raise ResourceConflict(conflicts)

        allocations = [
            Allocation(
                surgery_id=surgery_id,
                equipment_id=equipment.equipment_id,
                theatre_id=theatre_id,
                start_time=start,
                end_time=end,
                released=False,
            )
            for equipment in items
        ]
        self.db.add_all(allocations)
        self.db.flush()  # gives each row its allocation_id for the audit log
        for allocation in allocations:
            self._audit(user_id, "allocate", allocation)
        self.sync_surgery_resources(surgery_id)
        self.db.commit()
        return allocations

    def release_allocation(self, allocation_id: int, user_id: Optional[int] = None) -> Allocation:
        allocation = self.db.query(Allocation).filter(Allocation.allocation_id == allocation_id).first()
        if not allocation:
            raise ResourceNotFound(f"Allocation {allocation_id} not found")
        # Releasing twice has no further effect (SAD 3.4)
        if not allocation.released:
            allocation.released = True
            self._audit(user_id, "release", allocation)
            self.sync_surgery_resources(allocation.surgery_id)
            self.db.commit()
        return allocation

    def sync_surgery_resources(self, surgery_id: int) -> None:
        """Make the stored status of a surgery's theatre and equipment match SAD 3.4.

        Call this after a surgery starts, ends or is cancelled. The caller commits.
        """
        self.db.flush()  # the session has autoflush off, so send pending changes before querying
        equipment_items = self.db.query(Equipment).join(Allocation).filter(Allocation.surgery_id == surgery_id)
        for equipment in equipment_items:
            self._sync_equipment_status(equipment)
        theatres = self.db.query(Theatre).join(Surgery).filter(Surgery.surgery_id == surgery_id)
        for theatre in theatres:
            self._sync_theatre_status(theatre)

    # ---------- Helpers ----------

    def _sync_equipment_status(self, equipment: Equipment) -> None:
        """in_use while an unreleased allocation's surgery is running, otherwise available."""
        if equipment.status == EquipmentStatusEnum.maintenance:
            return
        running = (
            self.db.query(Allocation)
            .join(Surgery)
            .filter(
                Allocation.equipment_id == equipment.equipment_id,
                Allocation.released == False,
                Surgery.status == SurgeryStatusEnum.in_progress,
            )
            .first()
        )
        equipment.status = EquipmentStatusEnum.in_use if running else EquipmentStatusEnum.available

    def _sync_theatre_status(self, theatre: Theatre) -> None:
        """occupied while a surgery is running. Cleaning and maintenance belong to the admin."""
        running = (
            self.db.query(Surgery)
            .filter(Surgery.theatre_id == theatre.theatre_id, Surgery.status == SurgeryStatusEnum.in_progress)
            .first()
        )
        if running and theatre.status == TheatreStatusEnum.available:
            theatre.status = TheatreStatusEnum.occupied
        elif not running and theatre.status == TheatreStatusEnum.occupied:
            theatre.status = TheatreStatusEnum.available

    def _equipment_problems(self, equipment: Equipment, start: datetime, end: datetime) -> List[str]:
        """Why this item cannot be used in the range. An empty list means it is free.

        in_use is not a problem by itself: it describes now, not the range asked about.
        If the item is busy in the range, its allocation is found by the overlap check.
        """
        problems = []
        if not equipment.is_active:
            problems.append("retired")
        if equipment.status == EquipmentStatusEnum.maintenance:
            problems.append("under maintenance")
        if self.conflict_detector.check_equipment_conflict([equipment.equipment_id], start, end):
            problems.append("already allocated in this time range")
        return problems

    def _theatre_problems(
        self, theatre: Theatre, start: datetime, end: datetime, exclude_surgery_id: Optional[int] = None
    ) -> List[str]:
        """Why this theatre cannot be used in the range. An empty list means it is free.

        occupied and cleaning are not problems by themselves, for the same reason as in_use.
        """
        problems = []
        if not theatre.is_active:
            problems.append("retired")
        if theatre.status == TheatreStatusEnum.maintenance:
            problems.append("under maintenance")
        if self._theatre_is_booked(theatre.theatre_id, start, end, exclude_surgery_id):
            problems.append("already booked in this time range")
        return problems

    def _theatre_is_booked(
        self, theatre_id: int, start: datetime, end: datetime, exclude_surgery_id: Optional[int] = None
    ) -> bool:
        """True if a live surgery or an unreleased allocation overlaps the range."""
        if self.conflict_detector.check_theatre_conflict(theatre_id, start, end, exclude_surgery_id):
            return True
        query = self.db.query(Allocation).filter(
            Allocation.theatre_id == theatre_id,
            Allocation.released == False,
            Allocation.start_time < end,
            Allocation.end_time > start,
        )
        if exclude_surgery_id is not None:
            query = query.filter(Allocation.surgery_id != exclude_surgery_id)
        return query.first() is not None

    def _get_equipment(self, equipment_id: int) -> Equipment:
        equipment = self.db.query(Equipment).filter(Equipment.equipment_id == equipment_id).first()
        if not equipment:
            raise ResourceNotFound(f"Equipment {equipment_id} not found")
        return equipment

    def _get_theatre(self, theatre_id: int) -> Theatre:
        theatre = self.db.query(Theatre).filter(Theatre.theatre_id == theatre_id).first()
        if not theatre:
            raise ResourceNotFound(f"Theatre {theatre_id} not found")
        return theatre

    def _check_theatre_status_allowed(self, status: TheatreStatusEnum) -> None:
        if status not in THEATRE_ADMIN_STATUSES:
            raise InvalidRequest(f"Theatre status {status.value} cannot be set by hand")

    def _check_theatre_name_free(self, name: str) -> None:
        existing = self.db.query(Theatre).filter(Theatre.name == name).first()
        if existing:
            raise ResourceConflict(
                [self._conflict("theatre", existing.theatre_id, f"Theatre name {name} is already used")]
            )

    def _conflict(self, resource_type: str, resource_id: int, message: str) -> dict:
        return {"resource_type": resource_type, "resource_id": resource_id, "message": message}

    def _audit(self, user_id: Optional[int], action: str, allocation: Allocation) -> None:
        """OT-SR-005: every allocation change is written to the audit log."""
        self.db.add(
            AuditLog(
                user_id=user_id,
                action=action,
                entity_type="allocation",
                entity_id=allocation.allocation_id,
                details=f"surgery {allocation.surgery_id}, equipment {allocation.equipment_id}",
            )
        )
