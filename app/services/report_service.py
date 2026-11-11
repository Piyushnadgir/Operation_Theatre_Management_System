from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.models import Allocation, Equipment, Surgery, SurgeryStatusEnum, Theatre
from app.services.equipment_service import InvalidRequest, ResourceNotFound, clean_time_range

# Surgeries that really use their theatre. Cancelled ones do not count.
COUNTED_SURGERY_STATUSES = (
    SurgeryStatusEnum.scheduled,
    SurgeryStatusEnum.in_progress,
    SurgeryStatusEnum.completed,
)

Interval = Tuple[datetime, datetime]


def whole_minutes(start: datetime, end: datetime) -> int:
    """Minutes from start to end. Leftover seconds are dropped."""
    return int((end - start).total_seconds()) // 60


def usage_percent(booked_minutes: int, available_minutes: int) -> float:
    """booked / available x 100, rounded half up to 2 decimals.

    Decimal is used so that, for example, 1/8 gives 12.50 and not a float rounding surprise.
    """
    percent = Decimal(booked_minutes * 100) / Decimal(available_minutes)
    return float(percent.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def booked_minutes(bookings: List[Interval], start: datetime, end: datetime) -> int:
    """Minutes covered by the bookings inside [start, end).

    Each booking is first clipped to the range. Overlapping bookings are then merged,
    so a minute that is booked twice is counted once.
    """
    clipped = sorted((max(s, start), min(e, end)) for s, e in bookings)
    clipped = [(s, e) for s, e in clipped if s < e]  # drop bookings that lie outside the range

    total = 0
    current_start, current_end = None, None
    for s, e in clipped:
        if current_end is not None and s < current_end:
            current_end = max(current_end, e)  # overlaps the current block: extend it
        else:
            if current_end is not None:
                total += whole_minutes(current_start, current_end)
            current_start, current_end = s, e
    if current_end is not None:
        total += whole_minutes(current_start, current_end)
    return total


class ReportService:
    """Utilization report (OT-F-043), computed from the stored surgery and allocation rows.

    Definition, for each theatre and equipment item:
        available_minutes = whole minutes in the range [from, to)
        booked_minutes    = minutes of its bookings inside the range (clipped at the edges,
                            overlaps counted once)
        usage_percent     = booked_minutes / available_minutes x 100, rounded to 2 decimals
    Theatre bookings are surgeries that are scheduled, in progress or completed.
    Equipment bookings are allocations whose surgery is not cancelled and that were not
    replaced by a reschedule.
    """

    def __init__(self, db: Session):
        self.db = db

    def utilization(self, start: datetime, end: datetime, theatre_id: Optional[int] = None) -> dict:
        start, end = clean_time_range(start, end)
        range_minutes = whole_minutes(start, end)
        if range_minutes == 0:
            raise InvalidRequest("The range must be at least one minute long")
        if theatre_id is not None and self.db.get(Theatre, theatre_id) is None:
            raise ResourceNotFound(f"Theatre {theatre_id} not found")

        theatre_bookings = self._theatre_bookings(start, end, theatre_id)
        equipment_bookings = self._equipment_bookings(start, end, theatre_id)

        theatres = [
            self._row("theatre_id", theatre.theatre_id, theatre.name, theatre_bookings, start, end, range_minutes)
            for theatre in self._theatres_to_show(theatre_id, theatre_bookings)
        ]
        equipment = [
            self._row("equipment_id", item.equipment_id, item.name, equipment_bookings, start, end, range_minutes)
            for item in self._equipment_to_show(equipment_bookings)
        ]
        return {
            "start": start,
            "end": end,
            "range_minutes": range_minutes,
            "theatres": theatres,
            "equipment": equipment,
            "totals": {"theatres": self._total(theatres), "equipment": self._total(equipment)},
        }

    def _theatre_bookings(self, start, end, theatre_id) -> Dict[int, List[Interval]]:
        query = self.db.query(Surgery).filter(
            Surgery.status.in_(COUNTED_SURGERY_STATUSES),
            Surgery.start_time < end,
            Surgery.end_time > start,
        )
        if theatre_id is not None:
            query = query.filter(Surgery.theatre_id == theatre_id)
        bookings: Dict[int, List[Interval]] = {}
        for surgery in query:
            bookings.setdefault(surgery.theatre_id, []).append((surgery.start_time, surgery.end_time))
        return bookings

    def _equipment_bookings(self, start, end, theatre_id) -> Dict[int, List[Interval]]:
        query = (
            self.db.query(Allocation)
            .join(Surgery)
            .filter(
                Surgery.status != SurgeryStatusEnum.cancelled,
                Allocation.replaced == False,
                Allocation.start_time < end,
                Allocation.end_time > start,
            )
        )
        if theatre_id is not None:
            query = query.filter(Allocation.theatre_id == theatre_id)
        bookings: Dict[int, List[Interval]] = {}
        for allocation in query:
            bookings.setdefault(allocation.equipment_id, []).append((allocation.start_time, allocation.end_time))
        return bookings

    def _theatres_to_show(self, theatre_id, bookings) -> List[Theatre]:
        """The requested theatre, or every active theatre plus retired ones with bookings."""
        query = self.db.query(Theatre)
        if theatre_id is not None:
            query = query.filter(Theatre.theatre_id == theatre_id)
        else:
            query = query.filter(or_(Theatre.is_active == True, Theatre.theatre_id.in_(list(bookings))))
        return query.order_by(Theatre.theatre_id).all()

    def _equipment_to_show(self, bookings) -> List[Equipment]:
        """Every active item, plus retired items only if they have bookings in the range."""
        return (
            self.db.query(Equipment)
            .filter(or_(Equipment.is_active == True, Equipment.equipment_id.in_(list(bookings))))
            .order_by(Equipment.equipment_id)
            .all()
        )

    def _row(self, id_field, item_id, name, bookings, start, end, range_minutes) -> dict:
        booked = booked_minutes(bookings.get(item_id, []), start, end)
        return {
            id_field: item_id,
            "name": name,
            "booked_minutes": booked,
            "available_minutes": range_minutes,
            "usage_percent": usage_percent(booked, range_minutes),
        }

    def _total(self, rows: List[dict]) -> dict:
        booked = sum(row["booked_minutes"] for row in rows)
        available = sum(row["available_minutes"] for row in rows)
        return {
            "booked_minutes": booked,
            "available_minutes": available,
            "usage_percent": usage_percent(booked, available) if available else 0.0,
        }
