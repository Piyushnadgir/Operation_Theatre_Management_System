from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.models import RoleEnum
from app.schemas.shift import (
    AvailabilityResponse,
    ShiftResponse,
    ShiftsResponse,
    ShiftsUpdate,
)
from app.services.audit_service import log_action
from app.services.shift_service import ShiftService, ShiftValidationError
from app.services.staff_service import StaffService

# Same /staff prefix as the staff router: /staff/{id}/shifts and /staff/{id}/availability
router = APIRouter(prefix="/staff", tags=["Staff"])

_admin = require_roles(RoleEnum.admin)
_admin_or_scheduler = require_roles(RoleEnum.admin, RoleEnum.scheduler)


def _not_found(staff_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "NotFound", "message": f"Staff {staff_id} not found"},
    )


def _shifts_response(shifts) -> ShiftsResponse:
    return ShiftsResponse(shifts=[ShiftResponse.model_validate(s) for s in shifts])


@router.put("/{staff_id}/shifts", response_model=ShiftsResponse)
def set_shifts(
    staff_id: int,
    data: ShiftsUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(_admin),
):
    try:
        shifts = ShiftService(db).set_shifts(
            staff_id, [(s.start_time, s.end_time) for s in data.shifts]
        )
    except ShiftValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "InvalidShifts", "message": str(exc)},
        )
    if shifts is None:
        raise _not_found(staff_id)
    log_action(db, "staff.shifts_update", user_id=current_user.get("sub"),
               entity_type="staff", entity_id=staff_id)
    return _shifts_response(shifts)


@router.get("/{staff_id}/shifts", response_model=ShiftsResponse)
def get_shifts(
    staff_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(_admin_or_scheduler),
):
    if StaffService(db).get_staff(staff_id) is None:
        raise _not_found(staff_id)
    return _shifts_response(ShiftService(db).get_shifts(staff_id))


@router.get("/{staff_id}/availability", response_model=AvailabilityResponse)
def get_availability(
    staff_id: int,
    start_time: datetime = Query(...),
    end_time: datetime = Query(...),
    db: Session = Depends(get_db),
    current_user=Depends(_admin_or_scheduler),
):
    try:
        available = ShiftService(db).is_available(staff_id, start_time, end_time)
    except ShiftValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BadRange", "message": str(exc)},
        )
    if available is None:
        raise _not_found(staff_id)
    return {"available": available}
