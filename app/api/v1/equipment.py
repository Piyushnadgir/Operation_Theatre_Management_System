from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.errors import ResourceRoute
from app.core.database import get_db
from app.core.deps import get_current_user, require_roles
from app.models.models import EquipmentStatusEnum, RoleEnum
from app.schemas.equipment import AvailabilityResponse, EquipmentCreate, EquipmentResponse, EquipmentUpdate
from app.services.equipment_service import EquipmentService

router = APIRouter(prefix="/equipment", tags=["Equipment"], route_class=ResourceRoute)


@router.post("", response_model=EquipmentResponse, status_code=status.HTTP_201_CREATED)
def create_equipment(
    equipment_data: EquipmentCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(RoleEnum.admin)),
):
    return EquipmentService(db).create_equipment(
        name=equipment_data.name,
        category=equipment_data.category,
        status=equipment_data.status,
    )


@router.get("", response_model=List[EquipmentResponse])
def list_equipment(
    status: Optional[EquipmentStatusEnum] = Query(None),
    category: Optional[str] = Query(None),
    include_retired: bool = Query(False, alias="includeRetired"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return EquipmentService(db).list_equipment(status=status, category=category, include_retired=include_retired)


@router.put("/{equipment_id}", response_model=EquipmentResponse)
def update_equipment(
    equipment_id: int,
    equipment_data: EquipmentUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(RoleEnum.admin)),
):
    return EquipmentService(db).update_equipment(
        equipment_id,
        name=equipment_data.name,
        category=equipment_data.category,
        status=equipment_data.status,
    )


@router.delete("/{equipment_id}")
def retire_equipment(
    equipment_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles(RoleEnum.admin)),
):
    EquipmentService(db).retire_equipment(equipment_id)
    return {"status": "deactivated"}


@router.get("/{equipment_id}/availability", response_model=AvailabilityResponse)
def equipment_availability(
    equipment_id: int,
    start: datetime = Query(...),
    end: datetime = Query(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return EquipmentService(db).equipment_availability(equipment_id, start, end)
