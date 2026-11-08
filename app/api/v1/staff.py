from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.models import RoleEnum, StaffTypeEnum
from app.schemas.staff import (
    AssignmentCheckRequest,
    AssignmentCheckResponse,
    StaffCreate,
    StaffResponse,
    StaffUpdate,
)
from app.services.assignment_service import AssignmentService
from app.services.audit_service import log_action
from app.services.staff_service import StaffService

router = APIRouter(prefix="/staff", tags=["Staff"])

_admin = require_roles(RoleEnum.admin)
_admin_or_scheduler = require_roles(RoleEnum.admin, RoleEnum.scheduler)


def _not_found(staff_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "NotFound", "message": f"Staff {staff_id} not found"},
    )


@router.post("", response_model=StaffResponse, status_code=status.HTTP_201_CREATED)
def create_staff(
    data: StaffCreate,
    db: Session = Depends(get_db),
    current_user=Depends(_admin),
):
    staff = StaffService(db).create_staff(
        name=data.name, staff_type=data.staff_type, specialization=data.specialization
    )
    log_action(db, "staff.create", user_id=current_user.get("sub"),
               entity_type="staff", entity_id=staff.staff_id)
    return staff


@router.get("", response_model=List[StaffResponse])
def list_staff(
    staff_type: Optional[StaffTypeEnum] = Query(None),
    specialization: Optional[str] = Query(None, max_length=100),
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
    current_user=Depends(_admin_or_scheduler),
):
    return StaffService(db).list_staff(
        staff_type=staff_type, specialization=specialization, include_inactive=include_inactive
    )


@router.post("/validate-assignment", response_model=AssignmentCheckResponse)
def validate_assignment(
    data: AssignmentCheckRequest,
    db: Session = Depends(get_db),
    current_user=Depends(_admin_or_scheduler),
):
    """Pre-check OT-F-033: can these doctors and nurses be assigned for this time?"""
    issues = AssignmentService(db).validate_assignments(
        data.doctor_ids,
        data.nurse_ids,
        data.start_time,
        data.end_time,
        data.required_specialization,
    )
    return {"valid": not issues, "conflicts": issues}


@router.put("/{staff_id}", response_model=StaffResponse)
def update_staff(
    staff_id: int,
    data: StaffUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(_admin),
):
    staff = StaffService(db).update_staff(staff_id, **data.model_dump(exclude_unset=True))
    if staff is None:
        raise _not_found(staff_id)
    log_action(db, "staff.update", user_id=current_user.get("sub"),
               entity_type="staff", entity_id=staff_id)
    return staff


@router.delete("/{staff_id}")
def deactivate_staff(
    staff_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(_admin),
):
    staff = StaffService(db).deactivate_staff(staff_id)
    if staff is None:
        raise _not_found(staff_id)
    log_action(db, "staff.deactivate", user_id=current_user.get("sub"),
               entity_type="staff", entity_id=staff_id)
    return {"status": "deactivated"}
