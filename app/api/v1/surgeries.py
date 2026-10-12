from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_roles
from app.models.models import RoleEnum
from app.schemas.surgery import ConflictResponse, SurgeryCreate, SurgeryResponse, SurgeryUpdate
from app.services.surgery_service import SurgeryService

router = APIRouter(prefix="/surgeries", tags=["Surgeries"])


@router.post("", response_model=SurgeryResponse, status_code=status.HTTP_201_CREATED)
def create_surgery(
    surgery_data: SurgeryCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(RoleEnum.scheduler, RoleEnum.admin)),
):
    service = SurgeryService(db)
    surgery, conflicts = service.create_surgery(
        patient_name=surgery_data.patient_name,
        theatre_id=surgery_data.theatre_id,
        start_time=surgery_data.start_time,
        end_time=surgery_data.end_time,
        doctor_ids=surgery_data.doctor_ids,
        nurse_ids=surgery_data.nurse_ids,
        equipment_ids=surgery_data.equipment_ids,
        priority=surgery_data.priority,
        created_by=current_user.get("sub"),
    )
    if surgery is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "Conflict", "message": "Resource conflict detected", "conflicts": conflicts},
        )
    return surgery


@router.put("/{surgery_id}", response_model=SurgeryResponse)
def reschedule_surgery(
    surgery_id: int,
    surgery_data: SurgeryUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(RoleEnum.scheduler, RoleEnum.admin)),
):
    service = SurgeryService(db)
    surgery, conflicts = service.reschedule_surgery(
        surgery_id=surgery_id,
        start_time=surgery_data.start_time,
        end_time=surgery_data.end_time,
        theatre_id=surgery_data.theatre_id,
        doctor_ids=surgery_data.doctor_ids,
        nurse_ids=surgery_data.nurse_ids,
        equipment_ids=surgery_data.equipment_ids,
    )
    if conflicts and surgery is None:
        # Check if not found
        if any(c.get("resource_type") == "surgery" and "not found" in c.get("message", "").lower() for c in conflicts):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=conflicts[0]["message"])
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "Conflict", "message": "Resource conflict detected", "conflicts": conflicts},
        )
    return surgery


@router.delete("/{surgery_id}")
def cancel_surgery(
    surgery_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(RoleEnum.scheduler, RoleEnum.admin)),
):
    service = SurgeryService(db)
    surgery = service.cancel_surgery(surgery_id)
    if not surgery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Surgery not found")
    return {"status": "cancelled"}


@router.get("")
def list_surgeries(
    date: Optional[date] = Query(None),
    theatre_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = SurgeryService(db)
    surgeries = service.get_surgeries(date=date, theatre_id=theatre_id)
    return surgeries
