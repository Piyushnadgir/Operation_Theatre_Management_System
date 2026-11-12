"""Emergency intake, priority queue, preemption, and notification service.

Covers OT-F-020 (OTMS-8), OT-F-021 (OTMS-9), OT-F-022 (OTMS-10),
OT-F-023 (OTMS-11), and supports OT-NF-001 (OTMS-12).
"""
import heapq
from datetime import datetime, timezone
from itertools import count
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.models.models import (
    Allocation,
    EmergencyCase,
    Notification,
    PriorityEnum,
    RoleEnum,
    Staff,
    Surgery,
    SurgeryStaff,
    SurgeryStatusEnum,
    Theatre,
    TheatreStatusEnum,
    User,
)
from app.schemas.emergency import EmergencyCreate, MovedSurgeryResponse
from app.services.audit_service import log_action

_PRIORITY_RANK: Dict[PriorityEnum, int] = {
    PriorityEnum.routine: 1,
    PriorityEnum.urgent: 2,
    PriorityEnum.critical: 3,
}


class EmergencyValidationError(ValueError):
    """Raised when emergency inputs fail OT-F-020 validation (HTTP 400)."""


class EmergencyConflictError(ValueError):
    """Raised when an emergency slot cannot be preempted or theatre is unavailable (HTTP 409)."""


class EmergencyNotFoundError(ValueError):
    """Raised when a requested emergency or notification record does not exist (HTTP 404)."""


def _to_utc_naive(dt: datetime) -> datetime:
    """Normalize datetimes to naive UTC to match SQLite storage."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def priority_weight(priority: PriorityEnum) -> int:
    return _PRIORITY_RANK[priority]


def times_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def find_next_free_slot(
    duration,
    earliest: datetime,
    busy_intervals: List[Tuple[datetime, datetime]],
) -> datetime:
    """Return earliest start >= earliest where duration fits without overlapping busy_intervals."""
    candidate = earliest
    for busy_start, busy_end in sorted(busy_intervals):
        if times_overlap(candidate, candidate + duration, busy_start, busy_end):
            if busy_end > candidate:
                candidate = busy_end
    return candidate


class EmergencyPriorityQueue:
    """Priority queue ordering critical before urgent, FIFO within the same priority (OT-F-021)."""

    def __init__(self) -> None:
        self._heap: list = []
        self._seq = count()

    def push(self, surgery: Surgery) -> None:
        heapq.heappush(self._heap, (-priority_weight(surgery.priority), next(self._seq), surgery))

    def pop(self) -> Surgery:
        if not self._heap:
            raise IndexError("Emergency queue is empty")
        return heapq.heappop(self._heap)[2]

    def peek(self) -> Optional[Surgery]:
        return self._heap[0][2] if self._heap else None

    def ordered(self) -> List[Surgery]:
        return [item[2] for item in sorted(self._heap)]

    def __len__(self) -> int:
        return len(self._heap)


class EmergencyService:
    """Coordinates emergency intake, preemption rescheduling, notifications, and queue retrieval."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def log_and_process_emergency(
        self,
        emergency_data: EmergencyCreate,
        logged_by_user_id: Optional[int] = None,
    ) -> Tuple[Surgery, EmergencyCase, List[MovedSurgeryResponse], int]:
        """Log an urgent/critical emergency, bump lower-priority clashes, and emit notifications."""
        patient_name = (emergency_data.patient_name or "").strip()
        if not patient_name:
            raise EmergencyValidationError("Patient name is required")

        if emergency_data.priority not in (PriorityEnum.urgent, PriorityEnum.critical):
            raise EmergencyValidationError("An emergency must have priority 'urgent' or 'critical'")

        start_time = _to_utc_naive(emergency_data.start_time)
        end_time = _to_utc_naive(emergency_data.end_time)
        if end_time <= start_time:
            raise EmergencyValidationError("End time must be after start time")

        theatre_id = emergency_data.theatre_id
        theatre = self.db.query(Theatre).filter(Theatre.theatre_id == theatre_id).first()
        if theatre is not None and (not theatre.is_active or theatre.status == TheatreStatusEnum.maintenance):
            raise EmergencyConflictError(
                f"Theatre {theatre_id} is unavailable (status={theatre.status.value}, active={theatre.is_active})"
            )

        active_statuses = [SurgeryStatusEnum.scheduled, SurgeryStatusEnum.in_progress]
        existing_in_theatre = (
            self.db.query(Surgery)
            .filter(
                Surgery.theatre_id == theatre_id,
                Surgery.status.in_(active_statuses),
                Surgery.end_time > start_time,
            )
            .order_by(Surgery.start_time, Surgery.surgery_id)
            .all()
        )

        clashes = [
            s
            for s in existing_in_theatre
            if times_overlap(start_time, end_time, _to_utc_naive(s.start_time), _to_utc_naive(s.end_time))
        ]

        emg_weight = priority_weight(emergency_data.priority)
        blockers = [s for s in clashes if priority_weight(s.priority) >= emg_weight]
        if blockers:
            blocker_ids = [b.surgery_id for b in blockers]
            raise EmergencyConflictError(
                f"Slot blocked by equal or higher priority surgery id(s): {blocker_ids}"
            )

        actor_id = int(logged_by_user_id) if logged_by_user_id is not None else None

        emg_surgery = Surgery(
            patient_name=patient_name,
            theatre_id=theatre_id,
            start_time=start_time,
            end_time=end_time,
            priority=emergency_data.priority,
            status=SurgeryStatusEnum.scheduled,
            created_by=actor_id,
        )
        self.db.add(emg_surgery)
        self.db.flush()

        assigned_staff_ids = set(emergency_data.doctor_ids + emergency_data.nurse_ids)
        for staff_id in assigned_staff_ids:
            self.db.add(SurgeryStaff(surgery_id=emg_surgery.surgery_id, staff_id=staff_id))

        for eq_id in set(emergency_data.equipment_ids):
            self.db.add(
                Allocation(
                    surgery_id=emg_surgery.surgery_id,
                    equipment_id=eq_id,
                    theatre_id=theatre_id,
                    start_time=start_time,
                    end_time=end_time,
                    released=False,
                    replaced=False,
                )
            )

        emg_case = EmergencyCase(surgery_id=emg_surgery.surgery_id, logged_by=actor_id)
        self.db.add(emg_case)
        self.db.flush()

        moved_surgeries: List[MovedSurgeryResponse] = []
        clashing_ids = {c.surgery_id for c in clashes}
        busy_intervals: List[Tuple[datetime, datetime]] = [
            (_to_utc_naive(s.start_time), _to_utc_naive(s.end_time))
            for s in existing_in_theatre
            if s.surgery_id not in clashing_ids
        ]
        busy_intervals.append((start_time, end_time))

        scheduler_user_ids = {
            row[0]
            for row in self.db.query(User.user_id).filter(User.role == RoleEnum.scheduler).all()
        }
        actor_exists = (
            actor_id is not None
            and self.db.query(User.user_id).filter(User.user_id == actor_id).first() is not None
        )

        notifications_created = 0

        for bumped in clashes:
            old_start = _to_utc_naive(bumped.start_time)
            old_end = _to_utc_naive(bumped.end_time)
            duration = old_end - old_start

            new_start = find_next_free_slot(duration, end_time, busy_intervals)
            new_end = new_start + duration
            bumped.start_time = new_start
            bumped.end_time = new_end
            busy_intervals.append((new_start, new_end))

            # Preserve allocation history (OT-NF-004) while moving equipment slots forward.
            active_allocs = (
                self.db.query(Allocation)
                .filter(
                    Allocation.surgery_id == bumped.surgery_id,
                    Allocation.released == False,
                    Allocation.replaced == False,
                )
                .all()
            )
            for old_alloc in active_allocs:
                old_alloc.released = True
                old_alloc.replaced = True
                self.db.add(
                    Allocation(
                        surgery_id=bumped.surgery_id,
                        equipment_id=old_alloc.equipment_id,
                        theatre_id=bumped.theatre_id,
                        start_time=new_start,
                        end_time=new_end,
                        released=False,
                        replaced=False,
                    )
                )

            moved_surgeries.append(
                MovedSurgeryResponse(
                    surgery_id=bumped.surgery_id,
                    patient_name=bumped.patient_name,
                    old_start_time=old_start,
                    old_end_time=old_end,
                    new_start_time=new_start,
                    new_end_time=new_end,
                    status=bumped.status,
                )
            )

            recipients = self._staff_user_ids_for_surgery(bumped.surgery_id) | scheduler_user_ids
            if not recipients and actor_exists and actor_id is not None:
                recipients.add(actor_id)

            move_msg = (
                f"Surgery {bumped.surgery_id} ({bumped.patient_name}) moved from "
                f"{old_start:%d %b %H:%M} to {new_start:%d %b %H:%M} due to emergency {emg_surgery.surgery_id}"
            )
            for uid in sorted(recipients):
                self.db.add(Notification(user_id=uid, surgery_id=bumped.surgery_id, message=move_msg))
                notifications_created += 1

            log_action(
                self.db,
                "surgery.preempt_reschedule",
                user_id=actor_id,
                entity_type="surgery",
                entity_id=bumped.surgery_id,
                details=f"moved {old_start.isoformat()} -> {new_start.isoformat()} by emergency {emg_surgery.surgery_id}",
                commit=False,
            )

        if assigned_staff_ids:
            emg_recipients = self._user_ids_for_staff_ids(assigned_staff_ids)
            emg_msg = (
                f"Emergency {emg_surgery.surgery_id} ({emg_surgery.patient_name}) assigned to "
                f"theatre {theatre_id} at {start_time:%d %b %H:%M}"
            )
            for uid in sorted(emg_recipients):
                self.db.add(Notification(user_id=uid, surgery_id=emg_surgery.surgery_id, message=emg_msg))
                notifications_created += 1

        log_action(
            self.db,
            "emergency.create",
            user_id=actor_id,
            entity_type="surgery",
            entity_id=emg_surgery.surgery_id,
            details=f"priority={emergency_data.priority.value}, bumped={len(moved_surgeries)}",
            commit=False,
        )

        self.db.commit()
        self.db.refresh(emg_surgery)
        self.db.refresh(emg_case)
        return emg_surgery, emg_case, moved_surgeries, notifications_created

    def get_priority_queue(self) -> List[Surgery]:
        """Return active emergency surgeries ordered by priority (critical > urgent > FIFO)."""
        rows = (
            self.db.query(Surgery)
            .join(EmergencyCase, EmergencyCase.surgery_id == Surgery.surgery_id)
            .filter(Surgery.status.in_([SurgeryStatusEnum.scheduled, SurgeryStatusEnum.in_progress]))
            .order_by(EmergencyCase.logged_at, EmergencyCase.emergency_id)
            .all()
        )
        queue = EmergencyPriorityQueue()
        for surgery in rows:
            queue.push(surgery)
        return queue.ordered()

    def get_notifications(self, user_id: int, unread_only: bool = False) -> List[Notification]:
        """Return notifications for a given user ordered newest first."""
        query = self.db.query(Notification).filter(Notification.user_id == user_id)
        if unread_only:
            query = query.filter(Notification.is_read == False)
        return query.order_by(Notification.notification_id.desc()).all()

    def mark_notification_read(self, notification_id: int, user_id: int) -> Notification:
        """Mark a user's notification as read."""
        notif = (
            self.db.query(Notification)
            .filter(Notification.notification_id == notification_id, Notification.user_id == user_id)
            .first()
        )
        if notif is None:
            raise EmergencyNotFoundError(f"Notification {notification_id} not found")
        notif.is_read = True
        self.db.commit()
        self.db.refresh(notif)
        return notif

    def _staff_user_ids_for_surgery(self, surgery_id: int) -> Set[int]:
        rows = (
            self.db.query(Staff.user_id)
            .join(SurgeryStaff, SurgeryStaff.staff_id == Staff.staff_id)
            .filter(SurgeryStaff.surgery_id == surgery_id, Staff.user_id.isnot(None))
            .all()
        )
        return {row[0] for row in rows if row[0] is not None}

    def _user_ids_for_staff_ids(self, staff_ids: Set[int]) -> Set[int]:
        if not staff_ids:
            return set()
        rows = (
            self.db.query(Staff.user_id)
            .filter(Staff.staff_id.in_(staff_ids), Staff.user_id.isnot(None))
            .all()
        )
        return {row[0] for row in rows if row[0] is not None}
